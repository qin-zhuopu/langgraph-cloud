"""SQLite repository implementations for domain interfaces.

This module provides concrete implementations of the repository interfaces
using SQLite as the backing store.
"""
import json
import uuid
from typing import Any, Optional

import aiosqlite

from app.domain.interfaces import ITaskRepository
from app.infrastructure.database import Database


class SQLiteTaskRepository(ITaskRepository):
    """SQLite implementation of ITaskRepository.

    This repository manages task persistence using the tasks table.
    """

    def __init__(self, db: Database) -> None:
        """Initialize the repository with a Database instance.

        Args:
            db: The Database instance to use for connections.
        """
        self._db = db

    async def create(
        self,
        user_id: str,
        task_type: str,
        workflow_version: str,
        data: dict[str, Any],
    ) -> str:
        """Create a new task.

        Args:
            user_id: The user identifier.
            task_type: The type/name of task (corresponds to workflow name).
            workflow_version: The version of workflow to use.
            data: Business data for the task.

        Returns:
            The created task ID (UUID string).
        """
        task_id = str(uuid.uuid4())

        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)
            await conn.execute(
                """
                INSERT INTO tasks (id, user_id, type, workflow_version, status, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, user_id, task_type, workflow_version, "pending", json.dumps(data)),
            )
            await conn.commit()

        return task_id

    async def get(self, task_id: str) -> Optional[dict[str, Any]]:
        """Get a task by ID.

        Args:
            task_id: The task identifier.

        Returns:
            The task data dict or None if not found.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)
            cursor = await conn.execute(
                """
                SELECT id, user_id, type, workflow_version, status, data,
                       pending_event_id, pending_node_id,
                       created_at, updated_at
                FROM tasks WHERE id = ?
                """,
                (task_id,),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

            result: dict[str, Any] = {
                "id": row[0],
                "user_id": row[1],
                "type": row[2],
                "workflow_version": row[3],
                "status": row[4],
                "data": json.loads(row[5]) if row[5] else {},
                "created_at": row[8],
                "updated_at": row[9],
            }

            # Build pending_callback if both fields are present
            if row[6] and row[7]:
                result["pending_callback"] = {
                    "event_id": row[6],
                    "node_id": row[7],
                }
            else:
                result["pending_callback"] = None

            return result

    async def update_status(
        self,
        task_id: str,
        status: str,
        data: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Update task status.

        Uses BEGIN IMMEDIATE to handle concurrent updates safely.

        Args:
            task_id: The task identifier.
            status: The new status value.
            data: Optional additional data to merge.

        Returns:
            True if update succeeded, False otherwise.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            # BEGIN IMMEDIATE acquires a reserved lock immediately
            # to prevent concurrent write conflicts
            await conn.execute("BEGIN IMMEDIATE")

            try:
                # Check if task exists
                cursor = await conn.execute(
                    "SELECT data FROM tasks WHERE id = ?", (task_id,)
                )
                row = await cursor.fetchone()

                if row is None:
                    await conn.rollback()
                    return False

                # Merge data if provided
                if data is not None:
                    existing_data = json.loads(row[0]) if row[0] else {}
                    merged_data = {**existing_data, **data}
                    data_json = json.dumps(merged_data)

                    await conn.execute(
                        """
                        UPDATE tasks
                        SET status = ?, data = ?, updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (status, data_json, task_id),
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE tasks
                        SET status = ?, updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (status, task_id),
                    )

                await conn.commit()
                return True

            except Exception:
                await conn.rollback()
                raise

    async def update_pending_callback(
        self,
        task_id: str,
        event_id: str,
        node_id: str,
    ) -> bool:
        """Set the pending callback fields on a task.

        Args:
            task_id: The task identifier.
            event_id: The interrupt event ID.
            node_id: The interrupt node ID.

        Returns:
            True if update succeeded, False otherwise.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)
            cursor = await conn.execute(
                """
                UPDATE tasks
                SET pending_event_id = ?, pending_node_id = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (event_id, node_id, task_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def clear_pending_callback(self, task_id: str) -> bool:
        """Clear the pending callback fields on a task.

        Args:
            task_id: The task identifier.

        Returns:
            True if update succeeded, False otherwise.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)
            cursor = await conn.execute(
                """
                UPDATE tasks
                SET pending_event_id = NULL, pending_node_id = NULL, updated_at = datetime('now')
                WHERE id = ?
                """,
                (task_id,),
            )
            await conn.commit()
            return cursor.rowcount > 0
