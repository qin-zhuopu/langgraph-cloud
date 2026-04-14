"""FastAPI dependency injection for the application.

This module provides dependency functions that can be used in FastAPI routes
to access application services like TaskService.
"""
from typing import Annotated, Optional

from fastapi import Depends

from app.service.task_service import TaskService

# Global reference to the TaskService instance
# This will be set during application startup
_task_service: Optional[TaskService] = None


def get_task_service() -> TaskService:
    """Dependency function to get the TaskService instance.

    Returns:
        TaskService: The application's TaskService instance.

    Raises:
        RuntimeError: If the service has not been initialized.
    """
    if _task_service is None:
        raise RuntimeError(
            "TaskService not initialized. "
            "Ensure the application startup event has run."
        )
    return _task_service


def set_task_service(service: TaskService) -> None:
    """Set the global TaskService instance.

    This is called during application startup to initialize the service
    before any requests are handled.

    Args:
        service: The TaskService instance to use for the application.
    """
    global _task_service
    _task_service = service


# Type alias for dependency injection
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
