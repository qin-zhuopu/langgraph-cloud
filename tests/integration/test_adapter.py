"""Integration tests for the client adapter routes.

Uses ASGI transport (no port binding). Tests the adapter's protocol
translation between JerehPilot client format and our core engine.
"""
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
from httpx import ASGITransport

from app.api.deps import set_task_service, set_workflow_repo
from app.api.routes import router
from app.api.adapter import adapter_router
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
    return str(tmp_path / "test_adapter.db")


@pytest.fixture
async def test_app(db_path: str):
    """Create a fully initialized FastAPI app with adapter routes."""
    from fastapi import FastAPI

    test_app = FastAPI()
    test_app.include_router(router)
    test_app.include_router(adapter_router)

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

    # Load inquiry workflow config
    inquiry_config = WorkflowBuilder.load_config("inquiry")
    await workflow_repo.save_version("v1", "inquiry", inquiry_config, active=True)

    test_app.state.task_service = task_service
    test_app.state.workflow_repo = workflow_repo

    return test_app


@pytest.fixture
async def client(test_app) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Create task via adapter
# ---------------------------------------------------------------------------


class TestAdapterCreate:
    """Tests for POST /financial/audit."""

    @pytest.mark.asyncio
    async def test_create_returns_thread_id(self, client: httpx.AsyncClient):
        """Create task returns thread_id."""
        response = await client.post(
            "/financial/audit",
            data={"session_id": "sess_001", "workflow_type": "inquiry"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "thread_id" in body
        assert body["thread_id"]

    @pytest.mark.asyncio
    async def test_create_unknown_workflow_returns_404(self, client: httpx.AsyncClient):
        """Create with unknown workflow type returns 404."""
        response = await client.post(
            "/financial/audit",
            data={"session_id": "sess_001", "workflow_type": "nonexistent"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Decide via adapter
# ---------------------------------------------------------------------------


class TestAdapterDecide:
    """Tests for POST /financial/audit/decide."""

    @pytest.mark.asyncio
    async def test_decide_add_in_maps_to_first_transition(self, client: httpx.AsyncClient):
        """'add in' decision maps to first transition (new_round)."""
        # Create task
        create_resp = await client.post(
            "/financial/audit",
            data={"session_id": "sess_002", "workflow_type": "inquiry"},
        )
        thread_id = create_resp.json()["thread_id"]

        # Get pending callback info via status
        status_resp = await client.get(f"/financial/audit/status?thread_id={thread_id}")
        assert status_resp.json()["status"] == "awaiting_human_review"

        # Get event_id from core API
        task_resp = await client.get(f"/v1/tasks/{thread_id}")
        pending = task_resp.json()["task"]["pending_callback"]
        event_id = pending["event_id"]

        # Decide "add in" → should map to new_round (first transition)
        decide_resp = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": event_id,
                "thread_id": thread_id,
                "decision": "add in",
                "new_deadline": "2026-06-01T18:00:00",
                "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN"],
            },
        )
        assert decide_resp.status_code == 200
        body = decide_resp.json()
        assert body["success"] is True
        # After new_round, should still be awaiting
        assert body["next_status"] == "awaiting_human_review"

    @pytest.mark.asyncio
    async def test_decide_reject_maps_to_last_transition(self, client: httpx.AsyncClient):
        """'reject' decision maps to last transition (award)."""
        # Create task
        create_resp = await client.post(
            "/financial/audit",
            data={"session_id": "sess_003", "workflow_type": "inquiry"},
        )
        thread_id = create_resp.json()["thread_id"]

        # Get event_id
        task_resp = await client.get(f"/v1/tasks/{thread_id}")
        event_id = task_resp.json()["task"]["pending_callback"]["event_id"]

        # Decide "reject" → should map to award (last transition)
        decide_resp = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": event_id,
                "thread_id": thread_id,
                "decision": "reject",
                "winners": [
                    {"material_code": "MAT_001", "supplier_code": "SUP_001", "awarded_price": 100.0},
                ],
            },
        )
        assert decide_resp.status_code == 200
        body = decide_resp.json()
        assert body["success"] is True
        assert body["next_status"] == "completed"

    @pytest.mark.asyncio
    async def test_decide_missing_thread_id_returns_400(self, client: httpx.AsyncClient):
        """Missing thread_id returns 400."""
        response = await client.post(
            "/financial/audit/decide",
            json={"event_id": "evt_001", "decision": "add in"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_decide_nonexistent_task_returns_404(self, client: httpx.AsyncClient):
        """Decide on nonexistent task returns 404."""
        response = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": "evt_001",
                "thread_id": "nonexistent",
                "decision": "add in",
            },
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Status via adapter
# ---------------------------------------------------------------------------


class TestAdapterStatus:
    """Tests for GET /financial/audit/status."""

    @pytest.mark.asyncio
    async def test_status_returns_awaiting_after_create(self, client: httpx.AsyncClient):
        """Status returns awaiting_human_review after task creation."""
        create_resp = await client.post(
            "/financial/audit",
            data={"session_id": "sess_004", "workflow_type": "inquiry"},
        )
        thread_id = create_resp.json()["thread_id"]

        status_resp = await client.get(f"/financial/audit/status?thread_id={thread_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "awaiting_human_review"
        assert status_resp.json()["thread_id"] == thread_id

    @pytest.mark.asyncio
    async def test_status_nonexistent_returns_404(self, client: httpx.AsyncClient):
        """Status for nonexistent task returns 404."""
        response = await client.get("/financial/audit/status?thread_id=nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Full happy path via adapter (no Kafka)
# ---------------------------------------------------------------------------


class TestAdapterHappyPath:
    """Full happy path through adapter: create → new_round → award → completed."""

    @pytest.mark.asyncio
    async def test_full_flow(self, client: httpx.AsyncClient):
        """Complete inquiry flow through adapter routes."""
        # 1. Create
        create_resp = await client.post(
            "/financial/audit",
            data={"session_id": "sess_hp", "workflow_type": "inquiry"},
        )
        assert create_resp.status_code == 200
        thread_id = create_resp.json()["thread_id"]

        # 2. Verify awaiting
        status_resp = await client.get(f"/financial/audit/status?thread_id={thread_id}")
        assert status_resp.json()["status"] == "awaiting_human_review"

        # 3. Get event_id for first callback
        task_resp = await client.get(f"/v1/tasks/{thread_id}")
        event_id_1 = task_resp.json()["task"]["pending_callback"]["event_id"]

        # 4. Decide new_round ("add in")
        decide_resp = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": event_id_1,
                "thread_id": thread_id,
                "decision": "add in",
                "new_deadline": "2026-06-01T18:00:00",
                "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN"],
            },
        )
        assert decide_resp.json()["next_status"] == "awaiting_human_review"

        # 5. Get new event_id
        task_resp = await client.get(f"/v1/tasks/{thread_id}")
        event_id_2 = task_resp.json()["task"]["pending_callback"]["event_id"]
        assert event_id_2 != event_id_1

        # 6. Decide award ("reject" maps to last transition)
        decide_resp = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": event_id_2,
                "thread_id": thread_id,
                "decision": "reject",
                "winners": [
                    {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                ],
            },
        )
        assert decide_resp.json()["next_status"] == "completed"

        # 7. Verify completed
        status_resp = await client.get(f"/financial/audit/status?thread_id={thread_id}")
        assert status_resp.json()["status"] == "completed"
