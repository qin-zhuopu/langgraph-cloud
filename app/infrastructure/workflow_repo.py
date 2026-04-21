"""SQLite workflow repository implementation for version management.

This module provides workflow configuration version management using SQLite.
"""
import json
from typing import Any, Optional

import aiosqlite

from app.domain.interfaces import IWorkflowRepo
from app.infrastructure.database import Database


class SQLiteWorkflowRepo(IWorkflowRepo):
    """SQLite implementation of IWorkflowRepo for workflow version management.

    This repository manages workflow configurations with version tracking,
    allowing retrieval of active versions and specific version configurations.
    """

    def __init__(self, db: Database) -> None:
        """Initialize the SQLiteWorkflowRepo.

        Args:
            db: The Database instance to use for connections.
        """
        self._db = db

    async def get_active(self, workflow_name: str) -> Optional[dict[str, Any]]:
        """Get the active version of a workflow.

        Args:
            workflow_name: The workflow name/identifier.

        Returns:
            The workflow config dict or None if not found.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            cursor = await conn.execute(
                """
                SELECT version, workflow_name, config, active
                FROM workflow_versions
                WHERE workflow_name = ? AND active = 1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (workflow_name,),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

            return {
                "version": row[0],
                "workflow_name": row[1],
                "config": json.loads(row[2]) if row[2] else {},
                "active": row[3] == 1,
            }

    async def get_by_version(
        self, workflow_name: str, version: str
    ) -> Optional[dict[str, Any]]:
        """Get a specific version of a workflow.

        Args:
            workflow_name: The workflow name/identifier.
            version: The version string (e.g., 'v1').

        Returns:
            The workflow config dict or None if not found.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            cursor = await conn.execute(
                """
                SELECT version, workflow_name, config, active
                FROM workflow_versions
                WHERE workflow_name = ? AND version = ?
                """,
                (workflow_name, version),
            )
            row = await cursor.fetchone()

            if row is None:
                return None

            return {
                "version": row[0],
                "workflow_name": row[1],
                "config": json.loads(row[2]) if row[2] else {},
                "active": row[3] == 1,
            }

    async def save_version(
        self,
        version: str,
        workflow_name: str,
        config: dict[str, Any],
        active: bool = True,
    ) -> None:
        """Save a workflow version.

        Uses INSERT OR REPLACE to handle both new versions and updates
        to existing versions. When active=True, all other versions of the
        same workflow are deactivated.

        Args:
            version: The version string.
            workflow_name: The workflow name/identifier.
            config: The workflow configuration dict.
            active: Whether this should be the active version.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            # If setting this version as active, deactivate all other versions
            if active:
                await conn.execute(
                    """
                    UPDATE workflow_versions
                    SET active = 0
                    WHERE workflow_name = ?
                    """,
                    (workflow_name,),
                )

            await conn.execute(
                """
                INSERT OR REPLACE INTO workflow_versions (version, workflow_name, config, active)
                VALUES (?, ?, ?, ?)
                """,
                (version, workflow_name, json.dumps(config), 1 if active else 0),
            )
            await conn.commit()

    async def list_orchestrations(
        self, page: int = 1, page_size: int = 20
    ) -> dict[str, Any]:
        """List orchestration summaries with pagination.

        Returns active workflow versions grouped by workflow_name.

        Args:
            page: Page number (1-indexed).
            page_size: Number of items per page.

        Returns:
            Dict with keys: total, page, page_size, items.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            # Count total active orchestrations
            cursor = await conn.execute(
                "SELECT COUNT(DISTINCT workflow_name) FROM workflow_versions WHERE active = 1"
            )
            row = await cursor.fetchone()
            total = row[0] if row else 0

            # Fetch paginated results
            offset = (page - 1) * page_size
            cursor = await conn.execute(
                """
                SELECT version, workflow_name, config, created_at
                FROM workflow_versions
                WHERE active = 1
                ORDER BY workflow_name ASC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
            rows = await cursor.fetchall()

            items = []
            for version, workflow_name, config_json, created_at in rows:
                config = json.loads(config_json) if config_json else {}
                items.append({
                    "type": workflow_name,
                    "latest_version": version,
                    "description": config.get("description", config.get("display_name", "")),
                    "created_at": created_at,
                    "updated_at": created_at,
                })

            return {
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": items,
            }
