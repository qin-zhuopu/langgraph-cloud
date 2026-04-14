"""Unit tests for SQLiteTaskRepository."""
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from app.domain.interfaces import ITaskRepository
from app.domain.schemas import Task
from app.infrastructure.database import Database


class TestSQLiteTaskRepository:
    """Tests for SQLiteTaskRepository implementation."""

    def test_implements_interface(self, task_repo):
        """Verify SQLiteTaskRepository implements ITaskRepository interface."""
        assert isinstance(task_repo, ITaskRepository)

    @pytest.mark.asyncio
    async def test_create_task(self, task_repo, db):
        """Test creating a new task returns a task ID (UUID)."""
        # Arrange
        user_id = "user123"
        task_type = "test_workflow"
        workflow_version = "v1"
        data = {"key": "value"}

        # Act
        task_id = await task_repo.create(user_id, task_type, workflow_version, data)

        # Assert
        assert task_id is not None
        assert isinstance(task_id, str)
        assert len(task_id) > 0

        # Verify task was actually created in database
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
            assert row is not None
            assert row[1] == user_id  # user_id
            assert row[2] == task_type  # type
            assert row[3] == workflow_version  # workflow_version
            assert row[5] == json.dumps(data)  # data

    @pytest.mark.asyncio
    async def test_get_task(self, task_repo, db):
        """Test getting a task by ID returns the task."""
        # Arrange - create a task directly in database
        task_id = "test-task-id-123"
        user_id = "user456"
        task_type = "workflow_a"
        workflow_version = "v2"
        status = "pending"
        data = {"foo": "bar"}

        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            await conn.execute(
                """
                INSERT INTO tasks (id, user_id, type, workflow_version, status, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (task_id, user_id, task_type, workflow_version, status, json.dumps(data)),
            )
            await conn.commit()

        # Act
        result = await task_repo.get(task_id)

        # Assert
        assert result is not None
        assert result["id"] == task_id
        assert result["user_id"] == user_id
        assert result["type"] == task_type
        assert result["workflow_version"] == workflow_version
        assert result["status"] == status
        assert result["data"] == data
        assert "created_at" in result
        assert "updated_at" in result

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, task_repo):
        """Test getting a non-existent task returns None."""
        # Act
        result = await task_repo.get("nonexistent-task-id")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_update_task_status(self, task_repo, db):
        """Test updating task status."""
        # Arrange - create a task
        task_id = "task-to-update"
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            await conn.execute(
                """
                INSERT INTO tasks (id, user_id, type, workflow_version, status, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (task_id, "user789", "workflow_b", "v1", "pending", "{}"),
            )
            await conn.commit()

        # Act
        success = await task_repo.update_status(task_id, "processing")

        # Assert
        assert success is True

        # Verify status was updated
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,))
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "processing"

    @pytest.mark.asyncio
    async def test_update_task_status_with_data(self, task_repo, db):
        """Test updating task status with additional data."""
        # Arrange - create a task with initial data
        task_id = "task-with-data"
        initial_data = {"step1": "complete"}
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            await conn.execute(
                """
                INSERT INTO tasks (id, user_id, type, workflow_version, status, data, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (task_id, "user101", "workflow_c", "v1", "pending", json.dumps(initial_data)),
            )
            await conn.commit()

        # Act
        new_data = {"step2": "complete", "result": 42}
        success = await task_repo.update_status(task_id, "complete", new_data)

        # Assert
        assert success is True

        # Verify status and data were updated
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT status, data FROM tasks WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "complete"
            # Data should be merged
            updated_data = json.loads(row[1])
            assert updated_data["step1"] == "complete"
            assert updated_data["step2"] == "complete"
            assert updated_data["result"] == 42

    @pytest.mark.asyncio
    async def test_update_task_status_nonexistent_task(self, task_repo):
        """Test updating status of non-existent task returns False."""
        # Act
        success = await task_repo.update_status("nonexistent-task", "complete")

        # Assert
        assert success is False

    @pytest.mark.asyncio
    async def test_create_generates_unique_ids(self, task_repo):
        """Test that creating multiple tasks generates unique IDs."""
        # Act
        task_id1 = await task_repo.create("user1", "workflow", "v1", {})
        task_id2 = await task_repo.create("user2", "workflow", "v1", {})

        # Assert
        assert task_id1 != task_id2
