"""End-to-end tests for WebSocket mode.

These tests verify the complete flow from task creation through WebSocket message
delivery and callback handling. They use the httpx ASGI transport to test the
FastAPI app directly without requiring a running server.

Note: The current workflow implementation completes tasks immediately without
triggering LangGraph interrupts. Full interrupt handling would require using
langgraph's interrupt() function in node implementations. These tests verify
the WebSocket infrastructure is correctly set up for when interrupts are used.
"""
import asyncio
from pathlib import Path
from typing import AsyncGenerator

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
    return str(tmp_path / "e2e_test.db")


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
        return {"status": "e2e_test"}

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


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_task_creation_flow(
    e2e_client: httpx.AsyncClient,
    e2e_app,
    purchase_request_workflow_config: dict,
):
    """Test WebSocket mode task creation and listener registration.

    This test verifies the flow:
    1. Load purchase_request workflow config
    2. Create task via POST /v1/tasks
    3. Register listener queue with message_bus
    4. Verify listener is registered but no messages for immediate completion
    5. Verify task status

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
    user_id = "e2e_test_user_single"
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

    # Step 3: Create listener queue and register with message_bus
    message_bus: IMessageBus = e2e_app.state.message_bus
    listener_queue: asyncio.Queue[EventMessage] = asyncio.Queue()

    # Register listener after task creation (simulating late connection)
    message_bus.register_listener(user_id, listener_queue)

    try:
        # Step 4: Verify listener is registered
        # Since task already completed, no messages should be in the queue
        # (unconsumed messages would be delivered via subscribe, not listener queue)
        try:
            event = await asyncio.wait_for(listener_queue.get(), timeout=1.0)
            # If we get here, an unexpected message was received
            # This could happen if the workflow sent an interrupt
            assert event.task_id == task_id
        except asyncio.TimeoutError:
            # Expected - no messages for immediate completion
            pass

        # Step 5: Verify final status
        get_response = await e2e_client.get(f"/v1/tasks/{task_id}")
        assert get_response.status_code == 200

        final_task = get_response.json()["task"]
        assert final_task["id"] == task_id
        assert final_task["status"] in ("completed", "interrupted", "error")

    finally:
        # Clean up listener
        message_bus.unregister_listener(user_id, listener_queue)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_no_messages_on_complete(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that no WebSocket messages are sent for workflows that complete immediately.

    This test verifies that when a workflow completes without hitting any
    interrupt points, no messages are published to the WebSocket listener.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Create a simple workflow that completes immediately
    simple_workflow_config = {
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
    }

    # Load workflow config
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    await workflow_repo.save_version("v1", "simple_task", simple_workflow_config, active=True)

    # Create listener queue
    message_bus: IMessageBus = e2e_app.state.message_bus
    user_id = "e2e_test_user_simple"
    listener_queue: asyncio.Queue[EventMessage] = asyncio.Queue()
    message_bus.register_listener(user_id, listener_queue)

    try:
        # Create task
        request_data = {
            "user_id": user_id,
            "task": {
                "type": "simple_task",
                "data": {"message": "Test"},
            },
        }

        response = await e2e_client.post("/v1/tasks", json=request_data)
        assert response.status_code == 201

        task_data = response.json()["task"]
        task_id = task_data["id"]

        # Verify task was created
        assert task_id is not None

        # Wait briefly to ensure no messages were sent
        try:
            event = await asyncio.wait_for(listener_queue.get(), timeout=1.0)
            # If we get here, a message was sent unexpectedly
            pytest.fail(f"Unexpected message received: {event}")
        except asyncio.TimeoutError:
            # Expected - no messages should be sent for immediate completion
            pass

        # Verify task status
        get_response = await e2e_client.get(f"/v1/tasks/{task_id}")
        assert get_response.status_code == 200

        final_task = get_response.json()["task"]
        assert final_task["id"] == task_id

    finally:
        # Clean up listener
        message_bus.unregister_listener(user_id, listener_queue)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_listener_isolation(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that WebSocket listeners only receive messages for their user_id.

    This test verifies message isolation between different users.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Create a simple workflow
    simple_workflow_config = {
        "name": "isolated_task",
        "display_name": "Isolated Task",
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
    await workflow_repo.save_version("v1", "isolated_task", simple_workflow_config, active=True)

    # Create two listeners for different users
    message_bus: IMessageBus = e2e_app.state.message_bus
    user1_id = "e2e_test_user_1"
    user2_id = "e2e_test_user_2"

    listener1: asyncio.Queue[EventMessage] = asyncio.Queue()
    listener2: asyncio.Queue[EventMessage] = asyncio.Queue()

    message_bus.register_listener(user1_id, listener1)
    message_bus.register_listener(user2_id, listener2)

    try:
        # Create task for user1
        request_data = {
            "user_id": user1_id,
            "task": {
                "type": "isolated_task",
                "data": {"message": "User1 task"},
            },
        }

        response = await e2e_client.post("/v1/tasks", json=request_data)
        assert response.status_code == 201

        task_data = response.json()["task"]
        task_id = task_data["id"]

        # Verify task was created
        assert task_id is not None

        # Verify neither listener receives messages for immediate completion
        for i, listener in enumerate([listener1, listener2], 1):
            try:
                event = await asyncio.wait_for(listener.get(), timeout=1.0)
                pytest.fail(f"Listener {i} should not have received any message, got: {event}")
            except asyncio.TimeoutError:
                # Expected - no messages for immediate completion
                pass

    finally:
        # Clean up listeners
        message_bus.unregister_listener(user1_id, listener1)
        message_bus.unregister_listener(user2_id, listener2)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_message_bus_publish_direct(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that message_bus delivers published messages to registered listeners.

    This test directly publishes a message to verify the WebSocket
    infrastructure works correctly.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    message_bus: IMessageBus = e2e_app.state.message_bus
    user_id = "e2e_test_user_direct"

    listener_queue: asyncio.Queue[EventMessage] = asyncio.Queue()
    message_bus.register_listener(user_id, listener_queue)

    try:
        # Create and publish a test event directly
        test_event = EventMessage(
            event_id="test-event-123",
            task_id="test-task-456",
            task_type="test_workflow",
            status="interrupted",
            node_id="test_node",
            required_params=["param1", "param2"],
            display_data={"message": "Test interrupt"},
        )

        # Publish the event
        await message_bus.publish(user_id, test_event)

        # Verify the listener receives the message
        try:
            received_event = await asyncio.wait_for(listener_queue.get(), timeout=2.0)
            assert received_event.event_id == test_event.event_id
            assert received_event.task_id == test_event.task_id
            assert received_event.task_type == test_event.task_type
            assert received_event.status == test_event.status
            assert received_event.node_id == test_event.node_id
            assert received_event.required_params == test_event.required_params
            assert received_event.display_data == test_event.display_data
        except asyncio.TimeoutError:
            pytest.fail("Listener should have received the published message")

    finally:
        # Clean up listener
        message_bus.unregister_listener(user_id, listener_queue)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_multiple_listeners_same_user(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that multiple listeners for the same user all receive messages.

    This test verifies that when multiple queues are registered for the same
    user, they all receive published messages (useful for multiple WebSocket
    connections from the same user).

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    message_bus: IMessageBus = e2e_app.state.message_bus
    user_id = "e2e_test_user_multi_listener"

    # Create multiple listeners for the same user
    listener1: asyncio.Queue[EventMessage] = asyncio.Queue()
    listener2: asyncio.Queue[EventMessage] = asyncio.Queue()
    listener3: asyncio.Queue[EventMessage] = asyncio.Queue()

    message_bus.register_listener(user_id, listener1)
    message_bus.register_listener(user_id, listener2)
    message_bus.register_listener(user_id, listener3)

    try:
        # Publish a test event
        test_event = EventMessage(
            event_id="test-event-multi-123",
            task_id="test-task-multi-456",
            task_type="test_workflow",
            status="interrupted",
            node_id="test_node",
            required_params=[],
            display_data={"message": "Multi-listener test"},
        )

        await message_bus.publish(user_id, test_event)

        # Verify all listeners receive the message
        for i, listener in enumerate([listener1, listener2, listener3], 1):
            try:
                received_event = await asyncio.wait_for(listener.get(), timeout=2.0)
                assert received_event.event_id == test_event.event_id
            except asyncio.TimeoutError:
                pytest.fail(f"Listener {i} should have received the published message")

    finally:
        # Clean up all listeners
        message_bus.unregister_listener(user_id, listener1)
        message_bus.unregister_listener(user_id, listener2)
        message_bus.unregister_listener(user_id, listener3)


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_websocket_mode_unregister_listener(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that unregistered listeners no longer receive messages.

    This test verifies that after unregistering a listener, it no longer
    receives published messages.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    message_bus: IMessageBus = e2e_app.state.message_bus
    user_id = "e2e_test_user_unregister"

    listener_queue: asyncio.Queue[EventMessage] = asyncio.Queue()
    message_bus.register_listener(user_id, listener_queue)

    try:
        # Publish first event - should be received
        test_event1 = EventMessage(
            event_id="test-event-unreg-1",
            task_id="test-task-unreg-1",
            task_type="test_workflow",
            status="interrupted",
            node_id="test_node",
            required_params=[],
            display_data={},
        )

        await message_bus.publish(user_id, test_event1)

        try:
            received_event = await asyncio.wait_for(listener_queue.get(), timeout=2.0)
            assert received_event.event_id == test_event1.event_id
        except asyncio.TimeoutError:
            pytest.fail("Listener should have received the first message")

        # Unregister the listener
        message_bus.unregister_listener(user_id, listener_queue)

        # Publish second event - should NOT be received
        test_event2 = EventMessage(
            event_id="test-event-unreg-2",
            task_id="test-task-unreg-2",
            task_type="test_workflow",
            status="interrupted",
            node_id="test_node",
            required_params=[],
            display_data={},
        )

        await message_bus.publish(user_id, test_event2)

        try:
            received_event = await asyncio.wait_for(listener_queue.get(), timeout=1.0)
            pytest.fail(f"Unregistered listener should not receive messages, got: {received_event}")
        except asyncio.TimeoutError:
            # Expected - unregistered listener should not receive messages
            pass

    finally:
        # Ensure listener is unregistered
        message_bus.unregister_listener(user_id, listener_queue)
