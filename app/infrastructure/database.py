"""SQLite database connection and table initialization.

This module provides the Database class for managing SQLite connections
and initializing the required tables for the application.
"""
import aiosqlite
from typing import Optional


class Database:
    """Database connection and table management for SQLite.

    This class handles database connections, table initialization,
    and utility operations like clearing all tables.
    """

    def __init__(self, db_path: str) -> None:
        """Initialize the Database with a file path.

        Args:
            db_path: The file path to the SQLite database.
        """
        self.db_path = db_path

    async def connect(self) -> aiosqlite.Connection:
        """Create and return a new database connection.

        Returns:
            An aiosqlite connection object.
        """
        return await aiosqlite.connect(self.db_path)

    async def init_tables(self, conn: aiosqlite.Connection) -> None:
        """Initialize all required database tables and indexes.

        Creates the following tables:
        - tasks: Stores task entities with status and workflow info
        - events: Stores workflow events for pub/sub messaging
        - checkpoints: Stores LangGraph checkpoint state
        - workflow_versions: Stores workflow configuration by version

        Also creates indexes for common query patterns.

        Args:
            conn: The database connection to use.
        """
        # Tasks table - stores task entities
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                type TEXT NOT NULL,
                workflow_version TEXT NOT NULL DEFAULT 'v1',
                status TEXT NOT NULL,
                data TEXT NOT NULL DEFAULT '{}',
                pending_event_id TEXT,
                pending_node_id TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Events table - stores workflow events for pub/sub
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                consumed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )

        # Checkpoints table - stores LangGraph checkpoint state
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_id TEXT NOT NULL,
                state TEXT NOT NULL,
                metadata TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (thread_id, checkpoint_id)
            )
            """
        )

        # Workflow versions table - stores workflow configurations
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workflow_versions (
                version TEXT NOT NULL,
                workflow_name TEXT NOT NULL,
                config TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (version, workflow_name)
            )
            """
        )

        # Create indexes for common query patterns
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_user_id
            ON tasks(user_id)
            """
        )

        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_user_consumed
            ON events(user_id, consumed)
            """
        )

        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_checkpoints_thread_id
            ON checkpoints(thread_id)
            """
        )

    async def clear_all(self, conn: aiosqlite.Connection) -> None:
        """Clear all data from all tables.

        This is primarily useful for testing purposes.

        Args:
            conn: The database connection to use.
        """
        await conn.execute("DELETE FROM tasks")
        await conn.execute("DELETE FROM events")
        await conn.execute("DELETE FROM checkpoints")
        await conn.execute("DELETE FROM workflow_versions")
