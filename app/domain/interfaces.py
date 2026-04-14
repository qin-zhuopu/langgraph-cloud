"""Domain interface definitions for repositories and services.

These abstract base classes define the contracts that concrete implementations
must follow, enabling dependency inversion and testability.
"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any, Optional

from app.domain.schemas import EventMessage


class ITaskRepository(ABC):
    """Repository interface for Task persistence operations."""

    @abstractmethod
    async def create(
        self,
        user_id: str,
        task_type: str,
        workflow_version: str,
        data: dict[str, Any],
    ) -> str:
        """Create a new task.

        Args:
            user_id: The user identifier.
            task_type: The type/name of task (corresponds to workflow name).
            workflow_version: The version of workflow to use.
            data: Business data for the task.

        Returns:
            The created task ID.
        """
        ...

    @abstractmethod
    async def get(self, task_id: str) -> Optional[dict[str, Any]]:
        """Get a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            The task data dict or None if not found.
        """
        ...

    @abstractmethod
    async def update_status(
        self,
        task_id: str,
        status: str,
        data: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Update task status.

        Args:
            task_id: The task identifier.
            status: The new status value.
            data: Optional additional data to merge.

        Returns:
            True if update succeeded, False otherwise.
        """
        ...


class IMessageBus(ABC):
    """Message bus interface for async event pub/sub.

    Supports user-scoped event streaming for workflow notifications.
    """

    @abstractmethod
    async def publish(self, user_id: str, message: EventMessage) -> None:
        """Publish a message to a user's queue.

        Args:
            user_id: The user identifier.
            message: The event message to publish.
        """
        ...

    @abstractmethod
    async def subscribe(self, user_id: str) -> AsyncIterator[EventMessage]:
        """Subscribe to a user's message stream.

        Args:
            user_id: The user identifier.

        Yields:
            EventMessage objects as they arrive.
        """
        ...

    @abstractmethod
    def register_listener(self, user_id: str, queue: Any) -> None:
        """Register a queue listener for a user.

        Args:
            user_id: The user identifier.
            queue: The queue object to register.
        """
        ...

    @abstractmethod
    def unregister_listener(self, user_id: str, queue: Any) -> None:
        """Unregister a queue listener for a user.

        Args:
            user_id: The user identifier.
            queue: The queue object to unregister.
        """
        ...


class IEventStore(ABC):
    """Event store interface for tracking consumed events."""

    @abstractmethod
    async def mark_consumed(self, event_id: str) -> bool:
        """Mark an event as consumed.

        Args:
            event_id: The event identifier.

        Returns:
            True if marked successfully, False otherwise.
        """
        ...

    @abstractmethod
    async def is_consumed(self, event_id: str) -> bool:
        """Check if an event has been consumed.

        Args:
            event_id: The event identifier.

        Returns:
            True if consumed, False otherwise.
        """
        ...


class IWorkflowRepo(ABC):
    """Repository interface for workflow configuration management."""

    @abstractmethod
    async def get_active(self, workflow_name: str) -> Optional[dict[str, Any]]:
        """Get the active version of a workflow.

        Args:
            workflow_name: The workflow name/identifier.

        Returns:
            The workflow config dict or None if not found.
        """
        ...

    @abstractmethod
    async def get_by_version(
        self, workflow_name: str, version: str
    ) -> Optional[dict[str, Any]]:
        """Get a specific version of a workflow.

        Args:
            workflow_name: The workflow name/identifier.
            version: The version string (e.g., 'v1').

        Returns:
            The workflow config dict or None if not found.
        """
        ...

    @abstractmethod
    async def save_version(
        self,
        version: str,
        workflow_name: str,
        config: dict[str, Any],
        active: bool = True,
    ) -> None:
        """Save a workflow version.

        Args:
            version: The version string.
            workflow_name: The workflow name/identifier.
            config: The workflow configuration dict.
            active: Whether this should be the active version.
        """
        ...
