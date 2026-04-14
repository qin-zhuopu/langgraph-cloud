"""TaskService for orchestrating task creation and workflow execution.

This module provides the TaskService class that acts as the business orchestration
layer, coordinating between repositories, message bus, event store, and the
workflow engine.
"""
import uuid
from typing import Any, Dict, Optional

from app.domain.interfaces import IEventStore, IMessageBus, ITaskRepository, IWorkflowRepo
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor


class TaskService:
    """Service for orchestrating task lifecycle and workflow execution.

    This service coordinates:
    - Task creation and persistence
    - Workflow configuration loading
    - Graph building and execution
    - Callback handling for user input during workflow interrupts

    Attributes:
        task_repo: Repository for task persistence.
        message_bus: Message bus for publishing workflow events.
        event_store: Event store for tracking consumed events (replay protection).
        workflow_repo: Repository for workflow configuration.
        builder: WorkflowBuilder for constructing LangGraph graphs.
        executor: WorkflowExecutor for running workflows.
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
        """Initialize the TaskService with its dependencies.

        Args:
            task_repo: Repository for task persistence operations.
            message_bus: Message bus for publishing workflow events.
            event_store: Event store for replay protection.
            workflow_repo: Repository for workflow configuration.
            builder: WorkflowBuilder for constructing graphs.
            executor: WorkflowExecutor for running workflows.
        """
        self._task_repo = task_repo
        self._message_bus = message_bus
        self._event_store = event_store
        self._workflow_repo = workflow_repo
        self._builder = builder
        self._executor = executor

    async def create_task(self, user_id: str, task_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new task and start its workflow execution.

        This method:
        1. Creates a task record in the repository
        2. Loads the workflow configuration for the task type
        3. Builds the LangGraph graph
        4. Executes the graph with the provided data

        Args:
            user_id: The user ID who is creating the task.
            task_type: The type of task (corresponds to workflow name).
            data: Business data for the task.

        Returns:
            dict: The created task record with keys:
                - id: Task ID
                - user_id: User ID
                - type: Task type
                - workflow_version: Workflow version used
                - status: Task status
                - data: Task data
                - created_at: Creation timestamp
                - updated_at: Last update timestamp

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
        thread_id = task_id  # Use task_id as thread_id for checkpointing
        status = await self._executor.execute(
            graph=graph,
            thread_id=thread_id,
            user_id=user_id,
            task_id=task_id,
            task_type=task_type,
            initial_data=data,
        )

        # Update task status
        await self._task_repo.update_status(task_id, status)

        # Return updated task
        updated_task = await self._task_repo.get(task_id)
        return updated_task if updated_task is not None else task

    async def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            The task record dict or None if not found. Keys:
                - id: Task ID
                - user_id: User ID
                - type: Task type
                - workflow_version: Workflow version used
                - status: Task status
                - data: Task data
                - created_at: Creation timestamp
                - updated_at: Last update timestamp
        """
        return await self._task_repo.get(task_id)

    async def callback(
        self,
        task_id: str,
        event_id: str,
        node_id: str,
        user_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle user callback for a workflow interrupt.

        This method:
        1. Validates the event hasn't been consumed (replay protection)
        2. Marks the event as consumed
        3. Resumes the workflow with user input
        4. Updates task status

        Args:
            task_id: The task ID associated with the callback.
            event_id: The event ID for replay protection.
            node_id: The node ID where the interrupt occurred.
            user_input: The user's input data to resume the workflow.

        Returns:
            dict: The updated task record.

        Raises:
            ValueError: If the event has already been consumed.
            RuntimeError: If the task is not found.
        """
        # Check if event has already been consumed (replay protection)
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

        # Build the graph
        graph = self._builder.build(workflow_config, workflow_version)

        # Resume workflow execution
        thread_id = task_id  # Use task_id as thread_id
        user_id = task["user_id"]

        status = await self._executor.resume(
            graph=graph,
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            node_id=node_id,
            user_input=user_input,
        )

        # Update task status with user input data merged
        await self._task_repo.update_status(task_id, status, data=user_input)

        # Return updated task
        updated_task = await self._task_repo.get(task_id)
        if updated_task is None:
            raise RuntimeError(f"Failed to retrieve task after callback: {task_id}")

        return updated_task
