"""FastAPI dependency injection for the application.

This module provides dependency functions that can be used in FastAPI routes
to access application services like TaskService and WorkflowRepo.
"""
from typing import Annotated, Optional

from fastapi import Depends

from app.domain.interfaces import IWorkflowRepo
from app.service.task_service import TaskService

# ---------------------------------------------------------------------------
# TaskService
# ---------------------------------------------------------------------------

_task_service: Optional[TaskService] = None


def get_task_service() -> TaskService:
    """Dependency function to get the TaskService instance."""
    if _task_service is None:
        raise RuntimeError(
            "TaskService not initialized. "
            "Ensure the application startup event has run."
        )
    return _task_service


def set_task_service(service: TaskService) -> None:
    """Set the global TaskService instance (called during startup)."""
    global _task_service
    _task_service = service


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


# ---------------------------------------------------------------------------
# WorkflowRepo
# ---------------------------------------------------------------------------

_workflow_repo: Optional[IWorkflowRepo] = None


def get_workflow_repo() -> IWorkflowRepo:
    """Dependency function to get the IWorkflowRepo instance."""
    if _workflow_repo is None:
        raise RuntimeError(
            "WorkflowRepo not initialized. "
            "Ensure the application startup event has run."
        )
    return _workflow_repo


def set_workflow_repo(repo: IWorkflowRepo) -> None:
    """Set the global WorkflowRepo instance (called during startup)."""
    global _workflow_repo
    _workflow_repo = repo


WorkflowRepoDep = Annotated[IWorkflowRepo, Depends(get_workflow_repo)]
