"""SQLite event store implementation for tracking consumed events.

This module provides replay protection by tracking which events have been consumed.
"""
import aiosqlite

from app.domain.interfaces import IEventStore
from app.infrastructure.database import Database


class SQLiteEventStore(IEventStore):
    """SQLite implementation of IEventStore for replay protection.

    This class tracks consumed events in the events table to prevent duplicate
    processing of the same event (replay protection).
    """

    def __init__(self, db: Database) -> None:
        """Initialize the SQLiteEventStore.

        Args:
            db: The Database instance to use for connections.
        """
        self._db = db

    async def mark_consumed(self, event_id: str) -> bool:
        """Mark an event as consumed.

        This method uses BEGIN IMMEDIATE for concurrency safety, which acquires
        a reserved lock on the database immediately, preventing write-write conflicts.

        Args:
            event_id: The event identifier.

        Returns:
            True if marked successfully (first time), False if already consumed.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            # Use BEGIN IMMEDIATE for concurrency safety
            await conn.execute("BEGIN IMMEDIATE")

            try:
                # Check if event already exists and is consumed
                cursor = await conn.execute(
                    "SELECT consumed FROM events WHERE event_id = ?",
                    (event_id,)
                )
                row = await cursor.fetchone()

                if row is not None:
                    # Event exists, check if already consumed
                    if row[0] == 1:
                        await conn.rollback()
                        return False
                    # Event exists but not consumed, update it
                    await conn.execute(
                        "UPDATE events SET consumed = 1 WHERE event_id = ?",
                        (event_id,)
                    )
                else:
                    # Event doesn't exist, insert it as consumed
                    await conn.execute(
                        """
                        INSERT INTO events (event_id, user_id, task_id, payload, consumed)
                        VALUES (?, '', '', '{}', 1)
                        """,
                        (event_id,)
                    )

                await conn.commit()
                return True
            except aiosqlite.IntegrityError:
                # Handle race condition: another transaction inserted the event
                await conn.rollback()
                return False

    async def is_consumed(self, event_id: str) -> bool:
        """Check if an event has been consumed.

        Args:
            event_id: The event identifier.

        Returns:
            True if consumed, False otherwise.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            cursor = await conn.execute(
                "SELECT consumed FROM events WHERE event_id = ?",
                (event_id,)
            )
            row = await cursor.fetchone()

            if row is None:
                return False

            return row[0] == 1
