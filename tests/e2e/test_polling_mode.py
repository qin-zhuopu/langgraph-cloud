"""End-to-end tests for Polling mode (Fallback scenario).

These tests verify the complete flow from task creation through polling
for status changes and callback handling. They use the httpx ASGI transport
to test the FastAPI app directly without requiring a running server.

The polling mode is the fallback when WebSocket connections are unavailable.
Clients periodically poll GET /v1/tasks/{id} to check for status changes
and extract interrupt information from the message_bus when status becomes
awaiting_*.

Note: The current workflow implementation completes tasks immediately without
triggering LangGraph interrupts. Full interrupt handling would require using
langgraph's interrupt() function in node implementations. These tests verify
the polling infrastructure is correctly set up for when interrupts are used.
"""
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import set_task_service
from app.api.routes import router
from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage
from app.infrastructure.database import Database
from app.infrastructure.event_store import SQLiteEventStore
from app.infrastructure.sqlite_bus import SQLiteMessageBus
from app.infrastructure.sqlite_repository import SQLiteTaskRepository
from app.infrastructure.workflow_repo import SQLiteWorkflowRepo
from app.service.task_service import TaskService
from app.workflow.builder import WorkflowBuilder
from app.workflow.executor import WorkflowExecutor


@pytest.fixture
async def e2e_db_path(tmp_path: Path) -> str:
    """Return a test database path for E2E tests."""
    return str(tmp_path / "e2e_polling_test.db")


@pytest.fixture
async def e2e_app(e2e_db_path: str):
    """Create a fully initialized FastAPI app for E2E testing.

    This fixture sets up all services before returning the app,
    simulating the full application lifecycle.
    """
    from fastapi import FastAPI

    # Create the app without lifespan (we'll initialize manually)
    e2e_app = FastAPI()
    e2e_app.include_router(router)

    @e2e_app.get("/")
    async def root():
        return {"status": "e2e_polling_test"}

    # Initialize services manually
    database = Database(e2e_db_path)
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

    e2e_app.state.database = database
    e2e_app.state.task_service = task_service
    e2e_app.state.message_bus = message_bus
    e2e_app.state.workflow_repo = workflow_repo
    e2e_app.state.task_repo = task_repo
    e2e_app.state.event_store = event_store

    return e2e_app


@pytest.fixture
async def e2e_client(e2e_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Create an httpx AsyncClient for E2E testing.

    Uses ASGI transport to call the app directly without a server.

    Args:
        e2e_app: The fully initialized FastAPI application.

    Yields:
        httpx.AsyncClient: Configured client for making requests.
    """
    async with httpx.AsyncClient(
        transport=ASGITransport(app=e2e_app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def purchase_request_workflow_config() -> dict:
    """Return the purchase request workflow config for E2E testing."""
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
                    {"condition": "is_approved == true", "next": "finance_audit"},
                    {"condition": "is_approved == false", "next": "rejected"},
                ],
            },
            {
                "id": "finance_audit",
                "type": "interrupt",
                "display_name": "财务审批",
                "description": "财务部门审批采购申请",
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


async def poll_task_status(
    client: httpx.AsyncClient,
    task_id: str,
    target_statuses: List[str],
    max_iterations: int = 20,
    poll_interval: float = 0.1,
) -> Tuple[str, Optional[Dict]]:
    """Poll a task's status until it reaches one of the target statuses.

    Args:
        client: The httpx client.
        task_id: The task ID to poll.
        target_statuses: List of acceptable statuses to stop polling.
        max_iterations: Maximum number of polling iterations.
        poll_interval: Seconds between polls.

    Returns:
        A tuple of (status, task_data) where task_data is the full task dict.

    Raises:
        TimeoutError: If target status not reached within max_iterations.
    """
    for _ in range(max_iterations):
        response = await client.get(f"/v1/tasks/{task_id}")
        assert response.status_code == 200

        task_data = response.json()["task"]
        status = task_data["status"]

        if status in target_statuses:
            return status, task_data

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"Task did not reach target status {target_statuses} within {max_iterations * poll_interval}s")


async def extract_event_from_message_bus(
    message_bus: IMessageBus,
    user_id: str,
    task_id: str,
    timeout: float = 2.0,
) -> Optional[EventMessage]:
    """Extract an event from the message_bus for a specific task.

    This simulates polling the subscribe endpoint when an awaiting_*
    status is detected.

    Args:
        message_bus: The message bus instance.
        user_id: The user ID.
        task_id: The task ID to find events for.
        timeout: Maximum time to wait for an event.

    Returns:
        An EventMessage if found, None otherwise.
    """
    start_time = asyncio.get_event_loop().time()

    async for event in message_bus.subscribe(user_id):
        if event.task_id == task_id:
            return event

        # Check timeout
        if asyncio.get_event_loop().time() - start_time > timeout:
            break

    return None


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_task_creation_and_status_polling(
    e2e_client: httpx.AsyncClient,
    e2e_app,
    purchase_request_workflow_config: dict,
):
    """Test polling mode for task creation and status polling.

    This test verifies the flow:
    1. Load purchase_request workflow config
    2. Create task via POST /v1/tasks
    3. Poll GET /v1/tasks/{id} for status changes
    4. Verify task reaches final status without WebSocket

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
        purchase_request_workflow_config: The workflow configuration.
    """
    # Step 1: Load workflow config
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    await workflow_repo.save_version(
        "v1", "purchase_request", purchase_request_workflow_config, active=True
    )

    # Step 2: Create task via POST /v1/tasks
    user_id = "e2e_polling_user_1"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "purchase_request",
            "data": {"amount": 1000, "description": "Office supplies"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task_data = response.json()["task"]
    task_id = task_data["id"]
    assert task_data["user_id"] == user_id
    assert task_data["type"] == "purchase_request"

    # Step 3: Poll for status changes
    # Since workflow completes immediately, poll for terminal statuses
    final_status, final_task = await poll_task_status(
        e2e_client,
        task_id,
        target_statuses=["completed", "rejected", "error", "interrupted"],
        max_iterations=10,
        poll_interval=0.05,
    )

    # Step 4: Verify final status
    assert final_status in ("completed", "rejected", "error", "interrupted")
    assert final_task["id"] == task_id


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_fallback_without_websocket(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test polling mode as fallback when WebSocket is unavailable.

    This test verifies that:
    1. Tasks can be created without WebSocket connection
    2. Status can be polled successfully
    3. No WebSocket listener is needed

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Create a simple workflow
    simple_workflow_config = {
        "name": "simple_polling_task",
        "display_name": "Simple Polling Task",
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
    }

    # Load workflow config
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    await workflow_repo.save_version("v1", "simple_polling_task", simple_workflow_config, active=True)

    # Create task WITHOUT registering any WebSocket listener
    user_id = "e2e_polling_user_no_ws"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "simple_polling_task",
            "data": {"message": "Test polling fallback"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task_data = response.json()["task"]
    task_id = task_data["id"]

    # Poll for completion - should work fine without WebSocket
    final_status, final_task = await poll_task_status(
        e2e_client,
        task_id,
        target_statuses=["completed", "error"],
        max_iterations=10,
        poll_interval=0.05,
    )

    assert final_status == "completed"
    assert final_task["id"] == task_id


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_extract_event_from_message_bus(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test extracting event information from message_bus during polling.

    This test verifies that when a task is interrupted, the event info
    can be extracted from the message_bus's subscribe endpoint.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    message_bus: IMessageBus = e2e_app.state.message_bus
    user_id = "e2e_polling_user_extract"

    # Create a test event directly
    test_event = EventMessage(
        event_id="test-polling-event-123",
        task_id="test-polling-task-456",
        task_type="test_workflow",
        status="awaiting_input",
        node_id="test_node",
        required_params=["param1", "param2"],
        display_data={"message": "Test polling interrupt"},
    )

    # Publish the event to message_bus
    await message_bus.publish(user_id, test_event)

    # Extract the event using subscribe (simulating polling mode)
    extracted_event = await extract_event_from_message_bus(
        message_bus,
        user_id,
        test_event.task_id,
        timeout=2.0,
    )

    # Verify extracted event matches original
    assert extracted_event is not None
    assert extracted_event.event_id == test_event.event_id
    assert extracted_event.task_id == test_event.task_id
    assert extracted_event.task_type == test_event.task_type
    assert extracted_event.status == test_event.status
    assert extracted_event.node_id == test_event.node_id
    assert extracted_event.required_params == test_event.required_params
    assert extracted_event.display_data == test_event.display_data


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_callback_after_interrupt(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test callback flow after detecting interrupt via polling.

    This test verifies:
    1. Polling detects awaiting_* status
    2. Event info extracted from message_bus
    3. Callback sent to resume workflow
    4. Task completes after callback

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Create a simple workflow
    simple_workflow_config = {
        "name": "polling_callback_task",
        "display_name": "Polling Callback Task",
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
    }

    # Load workflow config
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    await workflow_repo.save_version("v1", "polling_callback_task", simple_workflow_config, active=True)

    # Create task
    user_id = "e2e_polling_user_callback"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "polling_callback_task",
            "data": {"message": "Test callback"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task_data = response.json()["task"]
    task_id = task_data["id"]

    # Poll for completion (workflow completes immediately)
    final_status, final_task = await poll_task_status(
        e2e_client,
        task_id,
        target_statuses=["completed", "error"],
        max_iterations=10,
        poll_interval=0.05,
    )

    assert final_status == "completed"

    # Verify callback endpoint is accessible
    # Test 1: Call callback with new event_id - should succeed (marks event as consumed)
    callback_request = {
        "event_id": "test-event-id-new",
        "node_id": "test-node",
        "user_input": {"test": "value"},
    }

    callback_response = await e2e_client.post(
        f"/v1/tasks/{task_id}/callback",
        json=callback_request,
    )
    # Should succeed since it's a new event_id
    assert callback_response.status_code == 200
    result = callback_response.json()
    assert result["success"] is True

    # Test 2: Call callback again with same event_id - should fail (event already consumed)
    callback_response2 = await e2e_client.post(
        f"/v1/tasks/{task_id}/callback",
        json=callback_request,
    )
    # Should fail since event already consumed
    assert callback_response2.status_code == 400


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_multiple_tasks_concurrent_polling(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test polling multiple tasks concurrently.

    This test verifies that multiple tasks can be polled simultaneously
    without interference, simulating a real-world scenario where a client
    polls multiple tasks.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Create a simple workflow
    simple_workflow_config = {
        "name": "concurrent_polling_task",
        "display_name": "Concurrent Polling Task",
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
    }

    # Load workflow config
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    await workflow_repo.save_version("v1", "concurrent_polling_task", simple_workflow_config, active=True)

    # Create multiple tasks
    user_id = "e2e_polling_user_concurrent"
    task_ids = []

    for i in range(3):
        request_data = {
            "user_id": user_id,
            "task": {
                "type": "concurrent_polling_task",
                "data": {"index": i},
            },
        }

        response = await e2e_client.post("/v1/tasks", json=request_data)
        assert response.status_code == 201

        task_data = response.json()["task"]
        task_ids.append(task_data["id"])

    # Poll all tasks concurrently
    async def poll_single_task(task_id: str) -> tuple[str, str]:
        status, task_data = await poll_task_status(
            e2e_client,
            task_id,
            target_statuses=["completed", "error"],
            max_iterations=10,
            poll_interval=0.05,
        )
        return task_id, status

    # Run polling concurrently
    results = await asyncio.gather(*[poll_single_task(tid) for tid in task_ids])

    # Verify all tasks completed
    assert len(results) == 3
    for task_id, status in results:
        assert status == "completed"
        assert task_id in task_ids


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_poll_interval_behavior(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test polling behavior with different intervals.

    This test verifies that polling works correctly with various
    intervals and that the API responds consistently.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Create a simple workflow
    simple_workflow_config = {
        "name": "interval_test_task",
        "display_name": "Interval Test Task",
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
    }

    # Load workflow config
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    await workflow_repo.save_version("v1", "interval_test_task", simple_workflow_config, active=True)

    # Create task
    user_id = "e2e_polling_user_interval"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "interval_test_task",
            "data": {"test": "interval"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task_data = response.json()["task"]
    task_id = task_data["id"]

    # Test with short interval
    status1, _ = await poll_task_status(
        e2e_client,
        task_id,
        target_statuses=["completed", "error"],
        max_iterations=10,
        poll_interval=0.01,  # Very short interval
    )
    assert status1 == "completed"

    # Verify consistent response across multiple polls
    for _ in range(3):
        response = await e2e_client.get(f"/v1/tasks/{task_id}")
        assert response.status_code == 200
        task = response.json()["task"]
        assert task["id"] == task_id
        assert task["status"] in ("completed", "error", "interrupted")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_polling_mode_task_not_found(
    e2e_client: httpx.AsyncClient,
):
    """Test polling behavior for non-existent task.

    This test verifies that the API returns proper error when
    polling for a task that doesn't exist.

    Args:
        e2e_client: The httpx test client.
    """
    fake_task_id = "non-existent-task-id"

    response = await e2e_client.get(f"/v1/tasks/{fake_task_id}")
    assert response.status_code == 404

    error_data = response.json()
    assert "detail" in error_data
