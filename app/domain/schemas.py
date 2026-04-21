"""Domain Pydantic schemas for DTOs."""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field
from uuid import UUID


# ---------------------------------------------------------------------------
# Task schemas
# ---------------------------------------------------------------------------

class TaskData(BaseModel):
    """Task data payload containing type and business data."""

    type: str = Field(..., description="任务类型，对应工作流名称")
    data: dict = Field(default_factory=dict, description="业务数据")


class TaskCreate(BaseModel):
    """Request schema for creating a new task."""

    user_id: str = Field(..., description="用户 ID")
    task: TaskData = Field(..., description="任务数据")


class PendingCallback(BaseModel):
    """Pending callback context for an interrupted task."""

    event_id: str = Field(..., description="中断事件 ID")
    node_id: str = Field(..., description="中断节点 ID")


class CurrentOwner(BaseModel):
    """Current owner / assignee of a task."""

    type: str = Field(..., description="负责人类型: human | agent | program")
    id: str = Field(..., description="负责人标识")
    name: str = Field(..., description="负责人名称")


class Task(BaseModel):
    """Task entity schema."""

    id: str
    user_id: str
    type: str
    orchestration_version: str = Field(
        "v1",
        validation_alias="workflow_version",
        description="编排版本号",
    )
    status: str
    pending_callback: Optional[PendingCallback] = None
    current_owner: Optional[CurrentOwner] = None
    data: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Event schemas
# ---------------------------------------------------------------------------

class EventMessage(BaseModel):
    """Event message schema for workflow events."""

    event_id: str
    task_id: str
    task_type: str
    status: str
    node_id: str
    required_params: list[str] = Field(default_factory=list)
    display_data: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Callback schemas
# ---------------------------------------------------------------------------

class CallbackRequest(BaseModel):
    """Request schema for user callback/input."""

    event_id: str
    node_id: str
    action: str = Field(..., description="用户选择的分支标识")
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


# ---------------------------------------------------------------------------
# Orchestration schemas
# ---------------------------------------------------------------------------

class TransitionSchema(BaseModel):
    """Transition definition within an interrupt node."""

    action: str = Field(..., description="分支标识")
    label: str = Field(..., description="分支显示名称")
    target_node: str = Field(..., description="目标节点 ID")
    form_schema: dict = Field(..., description="JSON Schema for user_input validation")


class NodeSchema(BaseModel):
    """Node definition within an orchestration."""

    id: str
    type: str = Field(..., description="action | interrupt | terminal")
    description: str = ""
    transitions: Optional[list[TransitionSchema]] = None


class OrchestrationDetail(BaseModel):
    """Full orchestration definition for a specific version."""

    type: str
    version: str
    description: str = ""
    nodes: list[NodeSchema]


class OrchestrationSummary(BaseModel):
    """Lightweight orchestration summary for list responses."""

    type: str
    latest_version: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class OrchestrationListResponse(BaseModel):
    """Paginated orchestration list response."""

    total: int
    page: int
    page_size: int
    items: list[OrchestrationSummary]
