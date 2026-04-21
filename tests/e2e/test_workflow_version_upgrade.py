"""End-to-end tests for workflow version upgrade and isolation.

These tests verify that:
1. Tasks created with a specific workflow version continue using that version
2. Workflow version upgrades don't affect existing tasks
3. New tasks use the latest active version
4. Each task maintains its workflow_version snapshot at creation time

The test simulates a workflow upgrade scenario:
1. Load v1 config (purchase_request) and save to workflow_repo
2. Create task A (should use v1)
3. Directly insert v2 config to workflow_repo (simulates upgrade, adds CTO audit node)
4. Create task B (should use v2)
5. Verify task A still uses v1, task B uses v2
"""
import asyncio
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import set_task_service
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
async def e2e_db_path(tmp_path: Path) -> str:
    """Return a test database path for E2E tests."""
    return str(tmp_path / "e2e_version_upgrade_test.db")


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
        return {"status": "e2e_version_upgrade_test"}

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
def purchase_request_workflow_v1() -> dict:
    """Return the v1 purchase request workflow config.

    V1 has 3 nodes:
    - submit: action node
    - manager_audit: interrupt node for approval
    - approved: terminal node (status=completed)
    - rejected: terminal node (status=rejected)
    """
    return {
        "name": "purchase_request",
        "display_name": "采购申请审批流程",
        "version": "v1",
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
                "required_params": ["is_approved", "audit_opinion", "approver"],
                "transitions": [
                    {"condition": "is_approved == true", "target_node": "approved"},
                    {"condition": "is_approved == false", "target_node": "rejected"},
                ],
            },
            {
                "id": "approved",
                "type": "terminal",
                "display_name": "审批通过",
                "description": "采购申请已通过审批",
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
def purchase_request_workflow_v2() -> dict:
    """Return the v2 purchase request workflow config.

    V2 adds a CTO audit step after manager approval:
    - submit: action node
    - manager_audit: interrupt node for manager approval
    - cto_audit: NEW interrupt node for CTO approval (added in v2)
    - approved: terminal node (status=completed)
    - rejected: terminal node (status=rejected)
    """
    return {
        "name": "purchase_request",
        "display_name": "采购申请审批流程",
        "version": "v2",
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
                "required_params": ["is_approved", "audit_opinion", "approver"],
                "transitions": [
                    {"condition": "is_approved == true", "target_node": "cto_audit"},
                    {"condition": "is_approved == false", "target_node": "rejected"},
                ],
            },
            {
                "id": "cto_audit",
                "type": "interrupt",
                "display_name": "CTO审批",
                "description": "CTO审批大额采购申请",
                "required_params": ["is_approved", "audit_opinion", "approver"],
                "transitions": [
                    {"condition": "is_approved == true", "target_node": "approved"},
                    {"condition": "is_approved == false", "target_node": "rejected"},
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
    target_statuses: list,
    max_iterations: int = 20,
    poll_interval: float = 0.1,
) -> tuple:
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

    raise TimeoutError(
        f"Task did not reach target status {target_statuses} "
        f"within {max_iterations * poll_interval}s"
    )


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_version_isolation_on_upgrade(
    e2e_client: httpx.AsyncClient,
    e2e_app,
    purchase_request_workflow_v1: dict,
    purchase_request_workflow_v2: dict,
):
    """Test that tasks maintain their workflow version after upgrade.

    This test simulates a workflow upgrade scenario:
    1. Load v1 config and save to workflow_repo as active
    2. Create task A (should use v1)
    3. Insert v2 config to workflow_repo as active (simulates upgrade)
    4. Create task B (should use v2)
    5. Verify task A still has workflow_version=v1
    6. Verify task B has workflow_version=v2

    This confirms that:
    - Tasks snapshot the workflow_version at creation time
    - New tasks use get_active() to get latest version
    - Old tasks are not affected by workflow upgrades

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
        purchase_request_workflow_v1: V1 workflow config.
        purchase_request_workflow_v2: V2 workflow config.
    """
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    task_repo = e2e_app.state.task_repo

    # Step 1: Load v1 config and save as active
    await workflow_repo.save_version(
        version="v1",
        workflow_name="purchase_request",
        config=purchase_request_workflow_v1,
        active=True,
    )

    # Verify v1 is active
    v1_workflow = await workflow_repo.get_active("purchase_request")
    assert v1_workflow is not None
    assert v1_workflow["version"] == "v1"

    # Step 2: Create task A (should use v1)
    user_id = "e2e_version_upgrade_user"
    request_data_a = {
        "user_id": user_id,
        "task": {
            "type": "purchase_request",
            "data": {"amount": 5000, "description": "Office equipment"},
        },
    }

    response_a = await e2e_client.post("/v1/tasks", json=request_data_a)
    assert response_a.status_code == 201

    task_a_data = response_a.json()["task"]
    task_a_id = task_a_data["id"]

    # Verify task A was created with v1
    assert task_a_data["type"] == "purchase_request"
    assert task_a_data["orchestration_version"] == "v1"

    # Step 3: Insert v2 config as active (simulating upgrade)
    await workflow_repo.save_version(
        version="v2",
        workflow_name="purchase_request",
        config=purchase_request_workflow_v2,
        active=True,
    )

    # Verify v2 is now active
    v2_workflow = await workflow_repo.get_active("purchase_request")
    assert v2_workflow is not None
    assert v2_workflow["version"] == "v2"

    # Step 4: Create task B (should use v2)
    request_data_b = {
        "user_id": user_id,
        "task": {
            "type": "purchase_request",
            "data": {"amount": 10000, "description": "Server upgrade"},
        },
    }

    response_b = await e2e_client.post("/v1/tasks", json=request_data_b)
    assert response_b.status_code == 201

    task_b_data = response_b.json()["task"]
    task_b_id = task_b_data["id"]

    # Verify task B was created with v2
    assert task_b_data["type"] == "purchase_request"
    assert task_b_data["orchestration_version"] == "v2"

    # Step 5: Verify task A still has v1 when queried
    task_a_from_db = await task_repo.get(task_a_id)
    assert task_a_from_db is not None
    assert task_a_from_db["workflow_version"] == "v1"

    # Step 6: Verify task B has v2 when queried
    task_b_from_db = await task_repo.get(task_b_id)
    assert task_b_from_db is not None
    assert task_b_from_db["workflow_version"] == "v2"

    # Additional verification: Get v1 and v2 configs directly
    v1_config = await workflow_repo.get_by_version("purchase_request", "v1")
    assert v1_config is not None
    assert v1_config["version"] == "v1"
    # Count nodes in v1
    assert len(v1_config["config"]["nodes"]) == 4  # submit, manager_audit, approved, rejected

    v2_config = await workflow_repo.get_by_version("purchase_request", "v2")
    assert v2_config is not None
    assert v2_config["version"] == "v2"
    # Count nodes in v2 (should have cto_audit added)
    assert len(v2_config["config"]["nodes"]) == 5  # submit, manager_audit, cto_audit, approved, rejected

    # Verify v2 has the CTO audit node
    v2_node_ids = [node["id"] for node in v2_config["config"]["nodes"]]
    assert "cto_audit" in v2_node_ids
    # Verify v1 does NOT have the CTO audit node
    v1_node_ids = [node["id"] for node in v1_config["config"]["nodes"]]
    assert "cto_audit" not in v1_node_ids


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_version_multiple_coexisting_versions(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that multiple workflow versions can coexist in the system.

    This test verifies:
    1. Multiple versions of the same workflow can be stored
    2. Each version is independently retrievable
    3. The active flag correctly identifies the current version

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo

    # Create v1 workflow
    v1_config = {
        "name": "multi_version_test",
        "display_name": "Multi Version Test",
        "nodes": [
            {
                "id": "start",
                "type": "action",
                "display_name": "Start",
                "target_node": "end",
            },
            {
                "id": "end",
                "type": "terminal",
                "display_name": "End",
                "status": "completed",
            },
        ],
    }

    await workflow_repo.save_version(
        version="v1",
        workflow_name="multi_version_test",
        config=v1_config,
        active=True,
    )

    # Create v2 workflow (adds a middle node)
    v2_config = {
        "name": "multi_version_test",
        "display_name": "Multi Version Test",
        "nodes": [
            {
                "id": "start",
                "type": "action",
                "display_name": "Start",
                "target_node": "middle",
            },
            {
                "id": "middle",
                "type": "action",
                "display_name": "Middle Node (added in v2)",
                "target_node": "end",
            },
            {
                "id": "end",
                "type": "terminal",
                "display_name": "End",
                "status": "completed",
            },
        ],
    }

    await workflow_repo.save_version(
        version="v2",
        workflow_name="multi_version_test",
        config=v2_config,
        active=True,
    )

    # Verify both versions exist
    retrieved_v1 = await workflow_repo.get_by_version("multi_version_test", "v1")
    assert retrieved_v1 is not None
    assert retrieved_v1["version"] == "v1"
    assert len(retrieved_v1["config"]["nodes"]) == 2

    retrieved_v2 = await workflow_repo.get_by_version("multi_version_test", "v2")
    assert retrieved_v2 is not None
    assert retrieved_v2["version"] == "v2"
    assert len(retrieved_v2["config"]["nodes"]) == 3

    # Verify v2 is the active version
    active_version = await workflow_repo.get_active("multi_version_test")
    assert active_version is not None
    assert active_version["version"] == "v2"

    # Create a task - should use v2
    user_id = "e2e_multi_version_user"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "multi_version_test",
            "data": {"test": "data"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task_data = response.json()["task"]
    assert task_data["orchestration_version"] == "v2"

    # Make v1 active again
    await workflow_repo.save_version(
        version="v1",
        workflow_name="multi_version_test",
        config=v1_config,
        active=True,
    )

    # Verify v1 is now active
    active_version = await workflow_repo.get_active("multi_version_test")
    assert active_version is not None
    assert active_version["version"] == "v1"

    # Create another task - should use v1 now
    request_data_2 = {
        "user_id": user_id,
        "task": {
            "type": "multi_version_test",
            "data": {"test": "data2"},
        },
    }

    response_2 = await e2e_client.post("/v1/tasks", json=request_data_2)
    assert response_2.status_code == 201

    task_data_2 = response_2.json()["task"]
    assert task_data_2["orchestration_version"] == "v1"


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_version_task_persistence(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test that a task's workflow_version persists across status updates.

    This test verifies that when a task's status is updated, the
    workflow_version field remains unchanged.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    workflow_repo: SQLiteWorkflowRepo = e2e_app.state.workflow_repo
    task_repo = e2e_app.state.task_repo

    # Create a simple workflow
    workflow_config = {
        "name": "version_persistence_test",
        "display_name": "Version Persistence Test",
        "nodes": [
            {
                "id": "start",
                "type": "action",
                "display_name": "Start",
                "target_node": "end",
            },
            {
                "id": "end",
                "type": "terminal",
                "display_name": "End",
                "status": "completed",
            },
        ],
    }

    await workflow_repo.save_version(
        version="v1",
        workflow_name="version_persistence_test",
        config=workflow_config,
        active=True,
    )

    # Create task
    user_id = "e2e_persistence_user"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "version_persistence_test",
            "data": {"test": "persistence"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)
    assert response.status_code == 201

    task_data = response.json()["task"]
    task_id = task_data["id"]
    original_version = task_data["orchestration_version"]

    assert original_version == "v1"

    # Wait for task to complete
    final_status, final_task = await poll_task_status(
        e2e_client,
        task_id,
        target_statuses=["completed", "error"],
        max_iterations=10,
        poll_interval=0.05,
    )

    # Verify workflow_version is still v1 after completion
    assert final_task["orchestration_version"] == "v1"

    # Also verify by querying the task directly from repo
    task_from_db = await task_repo.get(task_id)
    assert task_from_db is not None
    assert task_from_db["workflow_version"] == "v1"
    assert task_from_db["status"] in ("completed", "error")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_workflow_version_nonexistent_workflow(
    e2e_client: httpx.AsyncClient,
    e2e_app,
):
    """Test behavior when creating a task for a non-existent workflow.

    This test verifies that the API handles the case where a task
    is requested for a workflow type that doesn't exist in the repo.

    Args:
        e2e_client: The httpx test client.
        e2e_app: The FastAPI application with state.
    """
    # Try to create a task for a workflow that doesn't exist
    user_id = "e2e_nonexistent_user"
    request_data = {
        "user_id": user_id,
        "task": {
            "type": "nonexistent_workflow",
            "data": {"test": "data"},
        },
    }

    response = await e2e_client.post("/v1/tasks", json=request_data)

    # The API should return an error when workflow is not found
    # (This will be handled by the task service)
    assert response.status_code in (400, 404)
    error_data = response.json()
    assert "detail" in error_data
    assert "not found" in error_data["detail"].lower() or "workflow" in error_data["detail"].lower()
