"""Integration tests for TaskService."""
import asyncio
import uuid

import pytest

from app.domain.schemas import EventMessage
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.service.task_service import TaskService
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor


@pytest.fixture
def purchase_request_config() -> dict:
    """Return a purchase request workflow config for testing."""
    return {
        "name": "purchase_request",
        "display_name": "采购申请审批流程",
        "description": "采购申请审批流程",
        "nodes": [
            {
                "id": "submit",
                "type": "action",
                "display_name": "提交申请",
                "description": "用户提交采购申请",
                "target_node": "manager_audit",
            },
            {
                "id": "manager_audit",
                "type": "interrupt",
                "display_name": "经理审批",
                "description": "部门经理审批采购申请",
                "transitions": [
                    {
                        "action": "approve",
                        "label": "批准",
                        "target_node": "approved",
                        "condition": "is_approved == true",
                        "form_schema": {
                            "type": "object",
                            "required": ["is_approved", "audit_opinion", "approver"],
                            "properties": {
                                "is_approved": {"type": "boolean", "const": True},
                                "audit_opinion": {"type": "string", "minLength": 1},
                                "approver": {"type": "string"},
                            },
                        },
                    },
                    {
                        "action": "reject",
                        "label": "驳回",
                        "target_node": "rejected",
                        "condition": "is_approved == false",
                        "form_schema": {
                            "type": "object",
                            "required": ["is_approved", "reject_reason", "approver"],
                            "properties": {
                                "is_approved": {"type": "boolean", "const": False},
                                "reject_reason": {"type": "string", "minLength": 1},
                                "approver": {"type": "string"},
                            },
                        },
                    },
                ],
            },
            {
                "id": "approved",
                "type": "terminal",
                "display_name": "审批通过",
                "description": "采购申请已通过所有审批",
                "status": "completed",
            },
            {
                "id": "rejected",
                "type": "terminal",
                "display_name": "审批拒绝",
                "description": "采购申请被拒绝",
                "status": "rejected",
            },
        ],
    }


@pytest.fixture
async def workflow_with_interrupt(db, workflow_repo: SQLiteWorkflowRepo, purchase_request_config: dict):
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)
    yield "purchase_request"


@pytest.fixture
def task_service(
    task_repo: SQLiteTaskRepository,
    message_bus: SQLiteMessageBus,
    event_store: SQLiteEventStore,
    workflow_repo: SQLiteWorkflowRepo,
) -> TaskService:
    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)
    return TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor,
    )


@pytest.mark.asyncio
async def test_create_task(db, task_service: TaskService, workflow_with_interrupt: str):
    """Test creating a task starts workflow and returns correct status."""
    task = await task_service.create_task("test_user_123", workflow_with_interrupt, {"amount": 1000})

    assert task is not None
    assert "id" in task
    assert task["user_id"] == "test_user_123"
    assert task["type"] == workflow_with_interrupt
    assert task["workflow_version"] == "v1"
    assert task["status"] in ("pending", "completed", "error", "awaiting_manager_audit")
    assert task["data"] == {"amount": 1000}

    retrieved_task = await task_service.get_task(task["id"])
    assert retrieved_task is not None
    assert retrieved_task["id"] == task["id"]


@pytest.mark.asyncio
async def test_callback_task(db, task_service: TaskService, workflow_with_interrupt: str):
    """Test callback resumes workflow correctly."""
    task = await task_service.create_task("test_user_456", workflow_with_interrupt, {"amount": 5000})
    assert task is not None
    task_id = task["id"]
    assert task["status"] in ("completed", "awaiting_manager_audit", "pending", "error")

    retrieved = await task_service.get_task(task_id)
    assert retrieved is not None
    assert retrieved["id"] == task_id


@pytest.mark.asyncio
async def test_callback_with_action_validation(db, task_service: TaskService, workflow_with_interrupt: str):
    """Test callback validates action against node transitions."""
    task = await task_service.create_task("test_user", workflow_with_interrupt, {"amount": 1000})
    task_id = task["id"]

    if task["status"] == "awaiting_manager_audit" and task.get("pending_callback"):
        event_id = task["pending_callback"]["event_id"]

        # Invalid action should fail
        with pytest.raises(ValueError, match="Invalid action"):
            await task_service.callback(
                task_id=task_id,
                event_id=event_id,
                node_id="manager_audit",
                action="invalid_action",
                user_input={"is_approved": True},
            )


@pytest.mark.asyncio
async def test_callback_with_form_schema_validation(db, task_service: TaskService, workflow_with_interrupt: str):
    """Test callback validates user_input against form_schema."""
    task = await task_service.create_task("test_user", workflow_with_interrupt, {"amount": 1000})
    task_id = task["id"]

    if task["status"] == "awaiting_manager_audit" and task.get("pending_callback"):
        event_id = task["pending_callback"]["event_id"]

        # Missing required field should fail
        with pytest.raises(ValueError, match="validation failed"):
            await task_service.callback(
                task_id=task_id,
                event_id=event_id,
                node_id="manager_audit",
                action="approve",
                user_input={"is_approved": True},  # missing audit_opinion and approver
            )


@pytest.mark.asyncio
async def test_callback_replay_protection(
    db, task_service: TaskService, workflow_repo: SQLiteWorkflowRepo, purchase_request_config: dict
):
    """Test that callback enforces replay protection."""
    await workflow_repo.save_version("v1", "test_workflow", purchase_request_config, active=True)

    task = await task_service.create_task("test_user_789", "test_workflow", {"amount": 100})
    task_id = task["id"]

    event_id = str(uuid.uuid4())
    event_store = SQLiteEventStore(db)
    await event_store.mark_consumed(event_id)
    assert await event_store.is_consumed(event_id) is True

    with pytest.raises(ValueError, match="Event already consumed"):
        await task_service.callback(
            task_id=task_id,
            event_id=event_id,
            node_id="manager_audit",
            action="approve",
            user_input={"is_approved": True, "audit_opinion": "OK", "approver": "mgr"},
        )


@pytest.mark.asyncio
async def test_get_task_not_found(task_service: TaskService):
    result = await task_service.get_task("nonexistent_task_id")
    assert result is None


@pytest.mark.asyncio
async def test_create_task_workflow_not_found(db, task_service: TaskService):
    with pytest.raises(ValueError, match="Workflow not found"):
        await task_service.create_task("test_user", "nonexistent_workflow", {"test": "data"})


@pytest.mark.asyncio
async def test_callback_task_not_found(task_service: TaskService, event_store: SQLiteEventStore):
    event_id = str(uuid.uuid4())
    assert await event_store.is_consumed(event_id) is False

    with pytest.raises(RuntimeError, match="Task not found"):
        await task_service.callback(
            task_id="nonexistent_task_id",
            event_id=event_id,
            node_id="some_node",
            action="approve",
            user_input={"test": "input"},
        )
