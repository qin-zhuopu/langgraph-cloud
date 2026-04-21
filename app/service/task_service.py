"""TaskService for orchestrating task creation and workflow execution.

This module provides the TaskService class that acts as the business orchestration
layer, coordinating between repositories, message bus, event store, and the
workflow engine.
"""
import uuid
from typing import Any, Dict, Optional

import jsonschema

from app.domain.interfaces import IEventStore, IMessageBus, ITaskRepository, IWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import ExecutionResult, WorkflowExecutor


class TaskService:
    """Service for orchestrating task lifecycle and workflow execution.

    This service coordinates:
    - Task creation and persistence
    - Workflow configuration loading
    - Graph building and execution
    - Callback handling with action + form_schema validation
    """

    def __init__(
        self,
        task_repo: ITaskRepository,
        message_bus: IMessageBus,
        event_store: IEventStore,
        workflow_repo: IWorkflowRepo,
        builder: WorkflowBuilder,
        executor: WorkflowExecutor,
    ) -> None:
        self._task_repo = task_repo
        self._message_bus = message_bus
        self._event_store = event_store
        self._workflow_repo = workflow_repo
        self._builder = builder
        self._executor = executor

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_task(self, user_id: str, task_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new task and start its workflow execution.

        Args:
            user_id: The user ID who is creating the task.
            task_type: The type of task (corresponds to workflow name).
            data: Business data for the task.

        Returns:
            dict: The created task record.

        Raises:
            ValueError: If workflow configuration is not found.
        """
        # Get active workflow configuration
        workflow_result = await self._workflow_repo.get_active(task_type)
        if workflow_result is None:
            raise ValueError(f"Workflow not found: {task_type}")

        workflow_config = workflow_result["config"]
        workflow_version = workflow_result["version"]

        # Create task record
        task_id = await self._task_repo.create(
            user_id=user_id,
            task_type=task_type,
            workflow_version=workflow_version,
            data=data,
        )

        # Get the created task
        task = await self._task_repo.get(task_id)
        if task is None:
            raise RuntimeError("Failed to retrieve created task")

        # Build the graph
        graph = self._builder.build(workflow_config, workflow_version)

        # Execute the workflow
        result: ExecutionResult = await self._executor.execute(
            graph=graph,
            thread_id=task_id,
            user_id=user_id,
            task_id=task_id,
            task_type=task_type,
            initial_data=data,
            workflow_config=workflow_config,
        )

        # Derive business-semantic status
        status = self._derive_status(result, workflow_config)

        # Update task status
        await self._task_repo.update_status(task_id, status)

        # Update pending_callback if interrupted
        if result.status == "interrupted" and result.event_id and result.node_id:
            await self._task_repo.update_pending_callback(
                task_id, result.event_id, result.node_id
            )

        # Return updated task
        updated_task = await self._task_repo.get(task_id)
        return updated_task if updated_task is not None else task

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            The task record dict or None if not found.
        """
        return await self._task_repo.get(task_id)

    # ------------------------------------------------------------------
    # Callback
    # ------------------------------------------------------------------

    async def callback(
        self,
        task_id: str,
        event_id: str,
        node_id: str,
        action: str,
        user_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle user callback for a workflow interrupt.

        Validates:
        1. event_id not already consumed (replay protection)
        2. action is a valid transition for the node
        3. user_input passes the transition's form_schema

        Args:
            task_id: The task ID associated with the callback.
            event_id: The event ID for replay protection.
            node_id: The node ID where the interrupt occurred.
            action: The user-selected transition action.
            user_input: The user's input data to resume the workflow.

        Returns:
            dict: The updated task record.

        Raises:
            ValueError: If validation fails (event consumed, invalid action, schema mismatch).
            RuntimeError: If the task is not found.
        """
        # 1. Replay protection
        if await self._event_store.is_consumed(event_id):
            raise ValueError(f"Event already consumed: {event_id}")

        # Mark event as consumed
        await self._event_store.mark_consumed(event_id)

        # Get task
        task = await self._task_repo.get(task_id)
        if task is None:
            raise RuntimeError(f"Task not found: {task_id}")

        # Get workflow configuration
        task_type = task["type"]
        workflow_version = task["workflow_version"]

        workflow_result = await self._workflow_repo.get_by_version(
            task_type, workflow_version
        )
        if workflow_result is None:
            raise ValueError(f"Workflow not found: {task_type} version {workflow_version}")

        workflow_config = workflow_result["config"]

        # 2. Validate action against node transitions
        node_cfg = WorkflowBuilder.get_node_config(workflow_config, node_id)
        if node_cfg is None:
            raise ValueError(f"Node not found in orchestration: {node_id}")

        transitions = node_cfg.get("transitions", [])
        matched_transition = None
        for t in transitions:
            if t.get("action") == action:
                matched_transition = t
                break

        if matched_transition is None:
            valid_actions = [t.get("action") for t in transitions]
            raise ValueError(
                f"Invalid action '{action}' for node '{node_id}'. "
                f"Valid actions: {valid_actions}"
            )

        # 3. Validate user_input against form_schema
        form_schema = matched_transition.get("form_schema")
        if form_schema:
            try:
                jsonschema.validate(instance=user_input, schema=form_schema)
            except jsonschema.ValidationError as e:
                raise ValueError(f"user_input validation failed: {e.message}")

        # Clear pending callback before resuming
        await self._task_repo.clear_pending_callback(task_id)

        # Build the graph
        graph = self._builder.build(workflow_config, workflow_version)

        # Merge action into user_input so the condition routing function
        # can evaluate expressions like `action == "award"` against the state.
        resume_data = {**user_input, "action": action}

        # Resume workflow execution
        user_id = task["user_id"]

        result: ExecutionResult = await self._executor.resume(
            graph=graph,
            thread_id=task_id,
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            node_id=node_id,
            user_input=resume_data,
            workflow_config=workflow_config,
        )

        # Derive business-semantic status
        status = self._derive_status(result, workflow_config)

        # Update task status with user input data merged
        await self._task_repo.update_status(task_id, status, data=user_input)

        # Update pending_callback if interrupted again
        if result.status == "interrupted" and result.event_id and result.node_id:
            await self._task_repo.update_pending_callback(
                task_id, result.event_id, result.node_id
            )

        # Return updated task
        updated_task = await self._task_repo.get(task_id)
        if updated_task is None:
            raise RuntimeError(f"Failed to retrieve task after callback: {task_id}")

        return updated_task

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _derive_status(result: ExecutionResult, workflow_config: Optional[Dict[str, Any]]) -> str:
        """Derive a business-semantic status string from an ExecutionResult.

        For interrupted workflows, generates ``awaiting_{node_id}``.
        For completed workflows, returns ``completed``.
        For errors, returns ``error``.

        Args:
            result: The execution result.
            workflow_config: The workflow configuration (for future terminal status lookup).

        Returns:
            A business-semantic status string.
        """
        if result.status == "interrupted" and result.node_id:
            return f"awaiting_{result.node_id}"
        return result.status
