"""Workflow executor for running LangGraph workflows with interrupt handling.

This module provides the WorkflowExecutor class that manages workflow execution,
including handling interrupts (human-in-the-loop scenarios) and publishing events
to the message bus.
"""
import json
import uuid
from typing import Any, Dict, List, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph
from langgraph.pregel import Pregel

from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage


class WorkflowExecutor:
    """Executes LangGraph workflows with interrupt handling.

    This class handles:
    - Running workflows from initial state or from checkpoints
    - Detecting and handling interrupts (nodes waiting for human input)
    - Publishing interrupt events to the message bus
    - Resuming workflows from interrupt state with user input

    The executor integrates with the message bus to notify clients when
    a workflow reaches an interrupt point and requires user input.
    """

    def __init__(self, message_bus: IMessageBus) -> None:
        """Initialize the WorkflowExecutor.

        Args:
            message_bus: The message bus for publishing workflow events.
        """
        self._message_bus = message_bus

    async def execute(
        self,
        graph: StateGraph,
        thread_id: str,
        user_id: str,
        task_id: str,
        task_type: str,
        initial_data: Dict[str, Any],
    ) -> str:
        """Execute a workflow from initial state.

        Runs the workflow until completion or until an interrupt is encountered.
        If an interrupt occurs, publishes an event to the message bus and returns
        the interrupt status.

        Args:
            graph: The LangGraph StateGraph to execute.
            thread_id: Unique identifier for the workflow execution thread.
            user_id: The user ID who initiated the workflow.
            task_id: The task ID associated with this execution.
            task_type: The type/name of the task (workflow name).
            initial_data: Initial state data for the workflow.

        Returns:
            str: The final status of the workflow execution.
                - "completed": Workflow finished successfully
                - "interrupted": Workflow is waiting for user input
        """
        # Compile the graph if needed
        if not isinstance(graph, Pregel):
            compiled_graph = graph.compile()
        else:
            compiled_graph = graph

        # Configure the runnable with thread_id
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id,
            }
        )

        try:
            # Stream the workflow execution
            async for chunk in compiled_graph.astream(
                initial_data,
                config,
                stream_mode="updates",
            ):
                # Check if we've hit an interrupt
                if self._detect_interrupt(chunk):
                    # Find the node that caused the interrupt
                    node_id = self._extract_node_id(chunk)
                    await self._handle_interrupt(
                        task_id=task_id,
                        task_type=task_type,
                        node_id=node_id,
                        user_id=user_id,
                        chunk=chunk,
                    )
                    return "interrupted"

            return "completed"

        except Exception as e:
            # Handle execution errors
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
            return "error"

    async def resume(
        self,
        graph: StateGraph,
        thread_id: str,
        task_id: str,
        user_id: str,
        task_type: str,
        node_id: str,
        user_input: Dict[str, Any],
    ) -> str:
        """Resume a workflow from an interrupt state with user input.

        Continues workflow execution from the last checkpoint after applying
        the user's input to the workflow state.

        Args:
            graph: The LangGraph StateGraph to resume.
            thread_id: The workflow execution thread ID.
            task_id: The task ID associated with this execution.
            user_id: The user ID providing the input.
            task_type: The type/name of the task (workflow name).
            node_id: The node ID where the interrupt occurred.
            user_input: The user's input data to resume with.

        Returns:
            str: The final status of the workflow after resuming.
                - "completed": Workflow finished successfully
                - "interrupted": Workflow hit another interrupt
                - "error": An error occurred during execution
        """
        # Compile the graph if needed
        if not isinstance(graph, Pregel):
            compiled_graph = graph.compile()
        else:
            compiled_graph = graph

        # Configure with thread_id to resume from checkpoint
        config = RunnableConfig(
            configurable={
                "thread_id": thread_id,
            }
        )

        try:
            # Resume execution with user input
            async for chunk in compiled_graph.astream(
                user_input,
                config,
                stream_mode="updates",
            ):
                # Check if we've hit another interrupt
                if self._detect_interrupt(chunk):
                    new_node_id = self._extract_node_id(chunk)
                    await self._handle_interrupt(
                        task_id=task_id,
                        task_type=task_type,
                        node_id=new_node_id,
                        user_id=user_id,
                        chunk=chunk,
                    )
                    return "interrupted"

            return "completed"

        except Exception as e:
            # Handle execution errors
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
            return "error"

    async def _handle_interrupt(
        self,
        task_id: str,
        task_type: str,
        node_id: str,
        user_id: str,
        chunk: Dict[str, Any],
    ) -> None:
        """Handle a workflow interrupt by publishing to the message bus.

        Creates an EventMessage with details about the interrupt and publishes
        it to the user's message queue for WebSocket delivery or polling.

        Args:
            task_id: The task ID associated with the workflow.
            task_type: The type/name of the task (workflow name).
            node_id: The node ID where the interrupt occurred.
            user_id: The user ID to notify.
            chunk: The execution chunk containing interrupt details.
        """
        # Extract interrupt details from the chunk
        display_data = self._extract_display_data(chunk, node_id)
        required_params = self._extract_required_params(chunk, node_id)

        # Create and publish the interrupt event
        event = EventMessage(
            event_id=str(uuid.uuid4()),
            task_id=task_id,
            task_type=task_type,
            status="interrupted",
            node_id=node_id,
            required_params=required_params,
            display_data=display_data,
        )

        await self._message_bus.publish(user_id, event)

    def _detect_interrupt(self, chunk: Dict[str, Any]) -> bool:
        """Detect if the execution chunk indicates an interrupt.

        Args:
            chunk: The execution chunk to analyze.

        Returns:
            bool: True if the chunk indicates an interrupt, False otherwise.
        """
        # Check for interrupt signals in the chunk
        if isinstance(chunk, dict):
            for node_name, node_data in chunk.items():
                if isinstance(node_data, dict):
                    # Check for interrupt markers
                    if "__interrupt__" in node_data or "__interrupt" in str(node_data):
                        return True
                    # Check for status indicating waiting for input
                    if node_data.get("status") == "waiting_for_input":
                        return True
        return False

    def _extract_node_id(self, chunk: Dict[str, Any]) -> str:
        """Extract the node ID from an interrupt chunk.

        Args:
            chunk: The execution chunk containing interrupt information.

        Returns:
            str: The node ID where the interrupt occurred.
        """
        if isinstance(chunk, dict):
            # The first key in the chunk dict is typically the node name
            for node_name in chunk.keys():
                return str(node_name)
        return ""

    def _extract_display_data(self, chunk: Dict[str, Any], node_id: str) -> Dict[str, Any]:
        """Extract display data from an interrupt chunk.

        Args:
            chunk: The execution chunk containing interrupt information.
            node_id: The node ID where the interrupt occurred.

        Returns:
            dict: Display data for the interrupt UI.
        """
        display_data: Dict[str, Any] = {}

        if isinstance(chunk, dict) and node_id in chunk:
            node_data = chunk[node_id]
            if isinstance(node_data, dict):
                # Extract relevant fields for display
                for key, value in node_data.items():
                    if not key.startswith("__") and key != "status":
                        # Convert non-serializable types to strings
                        try:
                            json.dumps(value)
                            display_data[key] = value
                        except (TypeError, ValueError):
                            display_data[key] = str(value)

        return display_data

    def _extract_required_params(self, chunk: Dict[str, Any], node_id: str) -> List[str]:
        """Extract required parameters from an interrupt chunk.

        Args:
            chunk: The execution chunk containing interrupt information.
            node_id: The node ID where the interrupt occurred.

        Returns:
            list: List of required parameter names for user input.
        """
        required_params: List[str] = []

        if isinstance(chunk, dict) and node_id in chunk:
            node_data = chunk[node_id]
            if isinstance(node_data, dict):
                # Look for explicit required params
                if "required_params" in node_data:
                    params = node_data["required_params"]
                    if isinstance(params, list):
                        required_params.extend(str(p) for p in params)

                # If no explicit params, look for common patterns
                if not required_params:
                    for key in node_data.keys():
                        if key.startswith("required_") or key.endswith("_required"):
                            param_name = key.replace("required_", "").replace("_required", "")
                            required_params.append(param_name)

        return required_params
