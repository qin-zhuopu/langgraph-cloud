"""Integration tests for FastAPI API endpoints."""
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import set_task_service, set_workflow_repo
from app.api.routes import router
from app.infrastructure.database import Database
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.service.task_service import TaskService
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor


@pytest.fixture
async def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.db")


@pytest.fixture
async def test_app(db_path: str):
    """Create a fully initialized FastAPI app for testing."""
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(router)

    @test_app.get("/")
    async def root():
        return {"status": "test"}

    database = Database(db_path)
    conn = await database.connect()
    await database.init_tables(conn)
    await conn.close()

    task_repo = SQLiteTaskRepository(database)
    message_bus = SQLiteMessageBus(database)
    event_store = SQLiteEventStore(database)
    workflow_repo = SQLiteWorkflowRepo(database)

    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor,
    )

    set_task_service(task_service)
    set_workflow_repo(workflow_repo)

    test_app.state.database = database
    test_app.state.task_service = task_service
    test_app.state.message_bus = message_bus
    test_app.state.workflow_repo = workflow_repo
    test_app.state.task_repo = task_repo
    test_app.state.event_store = event_store

    return test_app


@pytest.fixture
async def client(test_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


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


# ---------------------------------------------------------------------------
# Task endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_endpoint(client: httpx.AsyncClient):
    """POST /v1/tasks returns 404 when workflow doesn't exist."""
    request_data = {
        "user_id": "test_user_123",
        "task": {"type": "nonexistent_workflow", "data": {"message": "Hello"}},
    }
    response = await client.post("/v1/tasks", json=request_data)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_task_with_workflow(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """POST /v1/tasks creates a task and returns correct structure."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    request_data = {
        "user_id": "test_user_456",
        "task": {"type": "purchase_request", "data": {"amount": 1000}},
    }
    response = await client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task = response.json()["task"]
    assert "id" in task
    assert task["user_id"] == "test_user_456"
    assert task["type"] == "purchase_request"
    assert task["status"] in ("pending", "completed", "error", "awaiting_manager_audit")


@pytest.mark.asyncio
async def test_get_nonexistent_task(client: httpx.AsyncClient):
    """GET /v1/tasks/{id} returns 404 for non-existent task."""
    response = await client.get("/v1/tasks/nonexistent_task_id")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_task_endpoint(client: httpx.AsyncClient, test_app):
    """GET /v1/tasks/{id} returns task details."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "simple_task", {
        "name": "simple_task",
        "display_name": "Simple Task",
        "nodes": [
            {"id": "start", "type": "action", "display_name": "Start", "target_node": "end"},
            {"id": "end", "type": "terminal", "display_name": "End", "status": "completed"},
        ],
    }, active=True)

    create_response = await client.post("/v1/tasks", json={
        "user_id": "test_user_789",
        "task": {"type": "simple_task", "data": {"message": "Test"}},
    })
    assert create_response.status_code == 201
    task_id = create_response.json()["task"]["id"]

    get_response = await client.get(f"/v1/tasks/{task_id}")
    assert get_response.status_code == 200
    retrieved_task = get_response.json()["task"]
    assert retrieved_task["id"] == task_id
    assert retrieved_task["user_id"] == "test_user_789"


@pytest.mark.asyncio
async def test_get_task_with_pending_callback(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """GET /v1/tasks/{id} returns pending_callback when interrupted."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    response = await client.post("/v1/tasks", json={
        "user_id": "test_user",
        "task": {"type": "purchase_request", "data": {"amount": 1000}},
    })
    assert response.status_code == 201
    task = response.json()["task"]
    assert task["status"] == "awaiting_manager_audit"
    assert task["pending_callback"] is not None
    assert "event_id" in task["pending_callback"]
    assert task["pending_callback"]["node_id"] == "manager_audit"


@pytest.mark.asyncio
async def test_callback_endpoint(client: httpx.AsyncClient):
    """POST /v1/tasks/{id}/callback returns 404 for non-existent task."""
    callback_data = {
        "event_id": "test-event-123",
        "node_id": "manager_audit",
        "action": "approve",
        "user_input": {"is_approved": True, "audit_opinion": "OK", "approver": "mgr"},
    }
    response = await client.post("/v1/tasks/nonexistent_task_id/callback", json=callback_data)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_root_endpoint(client: httpx.AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "test"


@pytest.mark.asyncio
async def test_health_endpoint(client: httpx.AsyncClient):
    response = await client.get("/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Orchestration endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_orchestrations(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """GET /v1/orchestrations returns paginated list."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    response = await client.get("/v1/orchestrations")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert data["page"] == 1
    assert len(data["items"]) >= 1
    item = next(i for i in data["items"] if i["type"] == "purchase_request")
    assert item["latest_version"] == "v1"


@pytest.mark.asyncio
async def test_get_orchestration_version(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """GET /v1/orchestrations/{type}/versions/{version} returns full definition."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    response = await client.get("/v1/orchestrations/purchase_request/versions/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "purchase_request"
    assert data["version"] == "v1"
    assert len(data["nodes"]) == 4

    # Verify interrupt node has transitions
    manager_node = next(n for n in data["nodes"] if n["id"] == "manager_audit")
    assert manager_node["transitions"] is not None
    assert len(manager_node["transitions"]) == 2
    assert manager_node["transitions"][0]["action"] == "approve"
    assert "form_schema" in manager_node["transitions"][0]


@pytest.mark.asyncio
async def test_get_orchestration_node(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """GET /v1/orchestrations/{type}/versions/{version}/nodes/{node_id} returns single node."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    response = await client.get("/v1/orchestrations/purchase_request/versions/v1/nodes/manager_audit")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "manager_audit"
    assert data["type"] == "interrupt"
    assert len(data["transitions"]) == 2


@pytest.mark.asyncio
async def test_get_orchestration_node_not_found(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """GET /v1/orchestrations/.../nodes/{node_id} returns 404 for unknown node."""
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    response = await client.get("/v1/orchestrations/purchase_request/versions/v1/nodes/nonexistent")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_orchestration_version_not_found(client: httpx.AsyncClient):
    """GET /v1/orchestrations/{type}/versions/{version} returns 404 for unknown."""
    response = await client.get("/v1/orchestrations/nonexistent/versions/v1")
    assert response.status_code == 404
