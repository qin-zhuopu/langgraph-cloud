"""Unit tests for Database connection and table initialization."""
import pytest
import aiosqlite
from pathlib import Path

from app.infrastructure.database import Database


class TestDatabaseInit:
    """Tests for Database initialization."""

    def test_database_init_with_path(self, tmp_path):
        """Test Database initialization with a path."""
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        assert db.db_path == db_path


class TestDatabaseConnect:
    """Tests for Database connection."""

    @pytest.mark.asyncio
    async def test_connect_returns_connection(self, db):
        """Test that connect returns an aiosqlite connection."""
        conn = await db.connect()
        assert isinstance(conn, aiosqlite.Connection)
        await conn.close()

    @pytest.mark.asyncio
    async def test_connect_creates_db_file(self, db, db_path):
        """Test that connect creates the database file."""
        await db.connect()
        assert Path(db_path).exists()


class TestDatabaseInitTables:
    """Tests for table initialization."""

    @pytest.mark.asyncio
    async def test_init_tables_creates_tasks_table(self, db):
        """Test that init_tables creates the tasks table."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            # Check table exists
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
            )
            result = await cursor.fetchone()
            assert result is not None

    @pytest.mark.asyncio
    async def test_init_tables_creates_events_table(self, db):
        """Test that init_tables creates the events table."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            )
            result = await cursor.fetchone()
            assert result is not None

    @pytest.mark.asyncio
    async def test_init_tables_creates_checkpoints_table(self, db):
        """Test that init_tables creates the checkpoints table."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='checkpoints'"
            )
            result = await cursor.fetchone()
            assert result is not None

    @pytest.mark.asyncio
    async def test_init_tables_creates_workflow_versions_table(self, db):
        """Test that init_tables creates the workflow_versions table."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_versions'"
            )
            result = await cursor.fetchone()
            assert result is not None

    @pytest.mark.asyncio
    async def test_tasks_table_schema(self, db):
        """Test that tasks table has correct schema."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute("PRAGMA table_info(tasks)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            expected_columns = [
                "id",
                "user_id",
                "type",
                "workflow_version",
                "status",
                "data",
                "created_at",
                "updated_at",
            ]
            for expected in expected_columns:
                assert expected in column_names

    @pytest.mark.asyncio
    async def test_events_table_schema(self, db):
        """Test that events table has correct schema."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute("PRAGMA table_info(events)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            expected_columns = [
                "id",
                "event_id",
                "user_id",
                "task_id",
                "payload",
                "consumed",
                "created_at",
            ]
            for expected in expected_columns:
                assert expected in column_names

    @pytest.mark.asyncio
    async def test_checkpoints_table_schema(self, db):
        """Test that checkpoints table has correct schema."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute("PRAGMA table_info(checkpoints)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            expected_columns = [
                "thread_id",
                "checkpoint_id",
                "state",
                "created_at",
            ]
            for expected in expected_columns:
                assert expected in column_names

    @pytest.mark.asyncio
    async def test_workflow_versions_table_schema(self, db):
        """Test that workflow_versions table has correct schema."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute("PRAGMA table_info(workflow_versions)")
            columns = await cursor.fetchall()
            column_names = [col[1] for col in columns]
            expected_columns = [
                "version",
                "workflow_name",
                "config",
                "active",
                "created_at",
            ]
            for expected in expected_columns:
                assert expected in column_names

    @pytest.mark.asyncio
    async def test_tasks_table_has_user_id_index(self, db):
        """Test that tasks table has index on user_id."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tasks_user_id'"
            )
            result = await cursor.fetchone()
            assert result is not None

    @pytest.mark.asyncio
    async def test_events_table_has_user_id_consumed_index(self, db):
        """Test that events table has index on user_id and consumed."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_events_user_consumed'"
            )
            result = await cursor.fetchone()
            assert result is not None

    @pytest.mark.asyncio
    async def test_checkpoints_table_has_thread_id_index(self, db):
        """Test that checkpoints table has index on thread_id."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_checkpoints_thread_id'"
            )
            result = await cursor.fetchone()
            assert result is not None


class TestDatabaseClearAll:
    """Tests for clearing all tables."""

    @pytest.mark.asyncio
    async def test_clear_all_removes_all_data(self, db):
        """Test that clear_all removes all data from tables."""
        async with aiosqlite.connect(db.db_path) as conn:
            await db.init_tables(conn)
            # Insert test data
            await conn.execute(
                "INSERT INTO tasks (id, user_id, type, status, data, created_at, updated_at) "
                "VALUES ('task1', 'user1', 'test', 'pending', '{}', datetime('now'), datetime('now'))"
            )
            await conn.execute(
                "INSERT INTO events (event_id, user_id, task_id, payload, consumed, created_at) "
                "VALUES ('event1', 'user1', 'task1', '{}', 0, datetime('now'))"
            )
            await conn.commit()

            # Verify data exists
            cursor = await conn.execute("SELECT COUNT(*) FROM tasks")
            assert (await cursor.fetchone())[0] == 1

            # Clear all
            await db.clear_all(conn)

            # Verify all tables are empty
            cursor = await conn.execute("SELECT COUNT(*) FROM tasks")
            assert (await cursor.fetchone())[0] == 0
            cursor = await conn.execute("SELECT COUNT(*) FROM events")
            assert (await cursor.fetchone())[0] == 0
