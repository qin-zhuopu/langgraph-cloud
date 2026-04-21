"""Workflow executor for running LangGraph workflows with interrupt handling.

This module provides the WorkflowExecutor class that manages workflow execution,
including handling interrupts (human-in-the-loop scenarios) and publishing events
to the message bus.
"""
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from langgraph.pregel import Pregel

from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage
from app.workflow.builder import WorkflowBuilder
from app.workflow.checkpointer import SQLiteSaver

# Optional Kafka producer — imported at runtime to avoid hard dependency
try:
    from app.infrastructure.kafka_producer import KafkaEventProducer
except ImportError:
    KafkaEventProducer = None  # type: ignore


@dataclass
class ExecutionResult:
    """Structured result from workflow execution.

    Attributes:
        status: Final status string (interrupted, completed, error).
        node_id: The node ID where an interrupt occurred (None if completed).
        event_id: The event ID generated for the interrupt (None if completed).
    """
    status: str
    node_id: Optional[str] = None
    event_id: Optional[str] = None


class WorkflowExecutor:
    """Executes LangGraph workflows with interrupt handling.

    This class handles:
    - Compiling graphs with interrupt_before for interrupt-type nodes
    - Running workflows from initial state with a checkpointer
    - Detecting LangGraph interrupt states via get_state()
    - Publishing interrupt events to the message bus
    - Resuming workflows from interrupt state with user input
    """

    def __init__(self, message_bus: IMessageBus, checkpointer: Optional[SQLiteSaver] = None,
                 kafka_producer: Optional[Any] = None, kafka_topic: str = "") -> None:
        """Initialize the WorkflowExecutor.

        Args:
            message_bus: The message bus for publishing workflow events.
            checkpointer: Optional SQLiteSaver for state persistence.
            kafka_producer: Optional KafkaEventProducer for Kafka publishing.
            kafka_topic: Kafka topic name (used only if kafka_producer is set).
        """
        self._message_bus = message_bus
        self._checkpointer = checkpointer
        self._kafka_producer = kafka_producer
        self._kafka_topic = kafka_topic

    def _get_checkpointer(self):
        """Return the configured checkpointer, falling back to MemorySaver."""
        if self._checkpointer is not None:
            return self._checkpointer
        from langgraph.checkpoint.memory import MemorySaver
        if not hasattr(self, "_memory_saver"):
            self._memory_saver = MemorySaver()
        return self._memory_saver

    async def execute(
        self,
        graph: StateGraph,
        thread_id: str,
        user_id: str,
        task_id: str,
        task_type: str,
        initial_data: Dict[str, Any],
        workflow_config: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a workflow from initial state.

        Args:
            graph: The LangGraph StateGraph to execute.
            thread_id: Unique identifier for the workflow execution thread.
            user_id: The user ID who initiated the workflow.
            task_id: The task ID associated with this execution.
            task_type: The type/name of the task (workflow name).
            initial_data: Initial state data for the workflow.
            workflow_config: The raw workflow YAML config dict.

        Returns:
            ExecutionResult with status, node_id, and event_id.
        """
        # Determine interrupt nodes from config
        interrupt_node_ids: List[str] = []
        if workflow_config is not None:
            interrupt_node_ids = WorkflowBuilder.get_interrupt_node_ids(workflow_config)

        # Compile with checkpointer and interrupt_before
        compiled = graph.compile(
            checkpointer=self._get_checkpointer(),
            interrupt_before=interrupt_node_ids if interrupt_node_ids else None,
        )

        config = RunnableConfig(configurable={"thread_id": thread_id})

        try:
            # Run the graph – it will stop before any interrupt node
            async for _chunk in compiled.astream(initial_data, config, stream_mode="updates"):
                pass  # consume the stream

            # After the stream ends, check if the graph is paused at an interrupt
            state = await compiled.aget_state(config)
            if state.next:
                # The graph stopped before one of the interrupt nodes
                node_id = state.next[0]
                event_id = str(uuid.uuid4())
                await self._handle_interrupt(
                    task_id=task_id,
                    task_type=task_type,
                    node_id=node_id,
                    user_id=user_id,
                    event_id=event_id,
                    workflow_config=workflow_config,
                    state_values=state.values,
                )
                return ExecutionResult(status="interrupted", node_id=node_id, event_id=event_id)

            # Workflow completed — publish completed event to Kafka
            await self._publish_completed(task_id, task_type, user_id)
            return ExecutionResult(status="completed")

        except Exception as e:
            error_event = EventMessage(
                event_id=str(uuid.uuid4()),
                task_id=task_id,
                task_type=task_type,
                status="error",
                node_id="",
                required_params=[],
                display_data={"error": str(e)},
            )
            await self._message_bus.publish(user_id, error_event)
            await self._publish_to_kafka(error_event)
            return ExecutionResult(status="error")

    async def resume(
        self,
        graph: StateGraph,
        thread_id: str,
        task_id: str,
        user_id: str,
        task_type: str,
        node_id: str,
        user_input: Dict[str, Any],
        workflow_config: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Resume a workflow from an interrupt state with user input.

        Args:
            graph: The LangGraph StateGraph to resume.
            thread_id: The workflow execution thread ID.
            task_id: The task ID associated with this execution.
            user_id: The user ID providing the input.
            task_type: The type/name of the task (workflow name).
            node_id: The node ID where the interrupt occurred.
            user_input: The user's input data to resume with.
            workflow_config: The raw workflow YAML config dict.

        Returns:
            ExecutionResult with status, node_id, and event_id.
        """
        interrupt_node_ids: List[str] = []
        if workflow_config is not None:
            interrupt_node_ids = WorkflowBuilder.get_interrupt_node_ids(workflow_config)

        compiled = graph.compile(
            checkpointer=self._get_checkpointer(),
            interrupt_before=interrupt_node_ids if interrupt_node_ids else None,
        )

        config = RunnableConfig(configurable={"thread_id": thread_id})

        try:
            # Update the state with user input so the interrupt node sees it
            await compiled.aupdate_state(config, user_input)

            # Resume execution (pass None to continue from checkpoint)
            async for _chunk in compiled.astream(None, config, stream_mode="updates"):
                pass

            # Check if we hit another interrupt
            state = await compiled.aget_state(config)
            if state.next:
                new_node_id = state.next[0]
                new_event_id = str(uuid.uuid4())
                await self._handle_interrupt(
                    task_id=task_id,
                    task_type=task_type,
                    node_id=new_node_id,
                    user_id=user_id,
                    event_id=new_event_id,
                    workflow_config=workflow_config,
                    state_values=state.values,
                )
                return ExecutionResult(status="interrupted", node_id=new_node_id, event_id=new_event_id)

            # Workflow completed — publish completed event to Kafka
            await self._publish_completed(task_id, task_type, user_id)
            return ExecutionResult(status="completed")

        except Exception as e:
            error_event = EventMessage(
                event_id=str(uuid.uuid4()),
                task_id=task_id,
                task_type=task_type,
                status="error",
                node_id=node_id,
                required_params=[],
                display_data={"error": str(e)},
            )
            await self._message_bus.publish(user_id, error_event)
            await self._publish_to_kafka(error_event)
            return ExecutionResult(status="error")

    async def _handle_interrupt(
        self,
        task_id: str,
        task_type: str,
        node_id: str,
        user_id: str,
        event_id: str,
        workflow_config: Optional[Dict[str, Any]],
        state_values: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Handle a workflow interrupt by publishing to the message bus.

        Args:
            task_id: The task ID associated with the workflow.
            task_type: The type/name of the task (workflow name).
            node_id: The node ID where the interrupt occurred.
            user_id: The user ID to notify.
            event_id: The event ID for this interrupt.
            workflow_config: The raw workflow config for extracting metadata.
            state_values: Current workflow state values.
        """
        required_params: List[str] = []
        display_data: Dict[str, Any] = {}

        # Extract metadata from the workflow config
        if workflow_config is not None:
            node_cfg = WorkflowBuilder.get_node_config(workflow_config, node_id)
            if node_cfg:
                display_data["display_name"] = node_cfg.get("display_name", node_id)
                display_data["description"] = node_cfg.get("description", "")
                # Collect required params from all transitions' form_schemas
                for transition in node_cfg.get("transitions", []):
                    form_schema = transition.get("form_schema", {})
                    for param in form_schema.get("required", []):
                        if param not in required_params:
                            required_params.append(param)

        # Include current state values in display_data for context
        if state_values:
            for k, v in state_values.items():
                if k not in display_data and not k.startswith("_"):
                    try:
                        json.dumps(v)
                        display_data[k] = v
                    except (TypeError, ValueError):
                        display_data[k] = str(v)

        event = EventMessage(
            event_id=event_id,
            task_id=task_id,
            task_type=task_type,
            status="interrupted",
            node_id=node_id,
            required_params=required_params,
            display_data=display_data,
        )

        await self._message_bus.publish(user_id, event)
        await self._publish_to_kafka(event)

    async def _publish_to_kafka(self, event: EventMessage) -> None:
        """Publish an event to Kafka if a producer is configured."""
        if self._kafka_producer and self._kafka_topic:
            try:
                await self._kafka_producer.send(self._kafka_topic, event)
            except Exception:
                pass  # Kafka failure should not break the workflow

    async def _publish_completed(self, task_id: str, task_type: str, user_id: str) -> None:
        """Publish a completed event to Kafka."""
        event = EventMessage(
            event_id=str(uuid.uuid4()),
            task_id=task_id,
            task_type=task_type,
            status="completed",
            node_id="",
            required_params=[],
            display_data={},
        )
        await self._publish_to_kafka(event)
