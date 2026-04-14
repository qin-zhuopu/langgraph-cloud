"""Domain Pydantic schemas for DTOs."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from uuid import UUID


class TaskData(BaseModel):
    """Task data payload containing type and business data."""

    type: str = Field(..., description="任务类型，对应工作流名称")
    data: dict = Field(default_factory=dict, description="业务数据")


class TaskCreate(BaseModel):
    """Request schema for creating a new task."""

    user_id: str = Field(..., description="用户 ID")
    task: TaskData = Field(..., description="任务数据")


class Task(BaseModel):
    """Task entity schema."""

    id: str
    user_id: str
    type: str
    workflow_version: str = "v1"
    status: str
    data: dict
    created_at: datetime
    updated_at: datetime


class EventMessage(BaseModel):
    """Event message schema for workflow events."""

    event_id: str
    task_id: str
    task_type: str
    status: str
    node_id: str
    required_params: list[str] = Field(default_factory=list)
    display_data: dict = Field(default_factory=dict)


class CallbackRequest(BaseModel):
    """Request schema for user callback/input."""

    event_id: str
    node_id: str
    user_input: dict = Field(..., description="用户输入")


class TaskResponse(BaseModel):
    """Response schema containing a task."""

    task: Task


class CallbackResponse(BaseModel):
    """Response schema for callback operations."""

    success: bool
    next_status: str


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: dict = Field(..., description="{code, message, details}")
