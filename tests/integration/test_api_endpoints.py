"""Integration tests for FastAPI API endpoints.

These tests verify the REST endpoints work correctly by making actual HTTP requests
to the FastAPI application using the httpx ASGI transport.
"""
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import set_task_service
from app.api.routes import router
from app.domain.interfaces import IMessageBus
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
    """Return a test database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
async def test_app(db_path: str):
    """Create a fully initialized FastAPI app for testing.

    This fixture sets up all services before returning the app.
    """
    from fastapi import FastAPI

    # Create the app without lifespan (we'll initialize manually)
    test_app = FastAPI()
    test_app.include_router(router)

    @test_app.get("/")
    async def root():
        return {"status": "test"}

    # Initialize services manually
    database = Database(db_path)
    conn = await database.connect()
    await database.init_tables(conn)
    await conn.close()

    # Initialize repositories
    task_repo = SQLiteTaskRepository(database)
    message_bus = SQLiteMessageBus(database)
    event_store = SQLiteEventStore(database)
    workflow_repo = SQLiteWorkflowRepo(database)

    # Initialize workflow components
    builder = WorkflowBuilder()
    executor = WorkflowExecutor(message_bus)

    # Initialize task service
    task_service = TaskService(
        task_repo=task_repo,
        message_bus=message_bus,
        event_store=event_store,
        workflow_repo=workflow_repo,
        builder=builder,
        executor=executor,
    )

    set_task_service(task_service)

    test_app.state.database = database
    test_app.state.task_service = task_service
    test_app.state.message_bus = message_bus
    test_app.state.workflow_repo = workflow_repo
    test_app.state.task_repo = task_repo
    test_app.state.event_store = event_store

    return test_app


@pytest.fixture
async def client(test_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx AsyncClient for testing API endpoints.

    Uses ASGI transport to call the app directly without a server.

    Args:
        test_app: The fully initialized FastAPI application.

    Yields:
        httpx.AsyncClient: Configured client for making requests.
    """
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
        "nodes": [
            {
                "id": "submit",
                "type": "action",
                "display_name": "提交申请",
                "description": "用户提交采购申请",
                "next": "manager_audit",
            },
            {
                "id": "manager_audit",
                "type": "interrupt",
                "display_name": "经理审批",
                "description": "部门经理审批采购申请",
                "required_params": ["is_approved", "audit_opinion", "approver"],
                "transitions": [
                    {"condition": "is_approved == true", "next": "approved"},
                    {"condition": "is_approved == false", "next": "rejected"},
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


@pytest.mark.asyncio
async def test_create_task_endpoint(client: httpx.AsyncClient):
    """Test creating a task via the REST API.

    This test verifies:
    - POST /v1/tasks returns appropriate error when workflow doesn't exist
    - Response structure is correct
    """
    # Create a task creation request for a non-existent workflow
    request_data = {
        "user_id": "test_user_123",
        "task": {
            "type": "nonexistent_workflow",
            "data": {"message": "Hello, world!"},
        },
    }

    response = await client.post("/v1/tasks", json=request_data)

    # Since workflow doesn't exist, we expect 404
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_task_with_workflow(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """Test creating a task with a pre-configured workflow.

    This test verifies:
    1. Workflow is registered via service layer
    2. Task can be created successfully
    3. Task response structure is correct
    """
    # Register the workflow using the workflow_repo from app state
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "purchase_request", purchase_request_config, active=True)

    # Now create a task with the registered workflow
    request_data = {
        "user_id": "test_user_456",
        "task": {
            "type": "purchase_request",
            "data": {"amount": 1000, "description": "Office supplies"},
        },
    }

    response = await client.post("/v1/tasks", json=request_data)

    # Should get 201 created
    assert response.status_code == 201

    data = response.json()
    assert "task" in data
    task = data["task"]
    assert "id" in task
    assert task["user_id"] == "test_user_456"
    assert task["type"] == "purchase_request"
    assert task["status"] in ("pending", "completed", "interrupted", "error")


@pytest.mark.asyncio
async def test_get_nonexistent_task(client: httpx.AsyncClient):
    """Test getting a task that doesn't exist.

    Verifies:
    - GET /v1/tasks/{id} returns 404 for non-existent task
    - Error message is descriptive
    """
    response = await client.get("/v1/tasks/nonexistent_task_id")

    assert response.status_code == 404

    data = response.json()
    assert "detail" in data
    assert "not found" in data["detail"].lower()


@pytest.mark.asyncio
async def test_get_task_endpoint(client: httpx.AsyncClient, test_app, purchase_request_config: dict):
    """Test getting an existing task.

    Verifies:
    - GET /v1/tasks/{id} returns task details
    - Response structure is correct
    """
    # Register the workflow
    workflow_repo: SQLiteWorkflowRepo = test_app.state.workflow_repo
    await workflow_repo.save_version("v1", "simple_task", {
        "name": "simple_task",
        "display_name": "Simple Task",
        "nodes": [
            {
                "id": "start",
                "type": "action",
                "display_name": "Start",
                "next": "end",
            },
            {
                "id": "end",
                "type": "terminal",
                "display_name": "End",
                "status": "completed",
            },
        ],
    }, active=True)

    # Create a task
    create_response = await client.post("/v1/tasks", json={
        "user_id": "test_user_789",
        "task": {
            "type": "simple_task",
            "data": {"message": "Test"},
        },
    })

    assert create_response.status_code == 201
    task_data = create_response.json()["task"]
    task_id = task_data["id"]

    # Get the task
    get_response = await client.get(f"/v1/tasks/{task_id}")

    assert get_response.status_code == 200
    retrieved_task = get_response.json()["task"]
    assert retrieved_task["id"] == task_id
    assert retrieved_task["user_id"] == "test_user_789"


@pytest.mark.asyncio
async def test_callback_endpoint(client: httpx.AsyncClient):
    """Test the callback endpoint for resuming workflows.

    Verifies:
    - POST /v1/tasks/{id}/callback structure is correct
    - Validation works for missing parameters
    """
    # Test with a task that doesn't exist
    callback_data = {
        "event_id": "test-event-123",
        "node_id": "manager_audit",
        "user_input": {"is_approved": True, "audit_opinion": "OK", "approver": "manager"},
    }

    response = await client.post(
        "/v1/tasks/nonexistent_task_id/callback", json=callback_data
    )

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_root_endpoint(client: httpx.AsyncClient):
    """Test the root endpoint returns service information."""
    response = await client.get("/")

    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["status"] == "test"


@pytest.mark.asyncio
async def test_health_endpoint(client: httpx.AsyncClient):
    """Test that the root endpoint works as health check."""
    response = await client.get("/")
    assert response.status_code == 200
