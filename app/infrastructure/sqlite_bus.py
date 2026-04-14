"""SQLite message bus implementation for pub/sub messaging.

This module provides SQLite-based persistent pub/sub messaging for workflow events.
"""
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import aiosqlite

from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage
from app.infrastructure.database import Database


class SQLiteMessageBus(IMessageBus):
    """SQLite implementation of IMessageBus for event pub/sub.

    This class provides:
    - Persistent message storage in SQLite
    - In-memory queue listeners for WebSocket connections
    - Async iterator-based subscription for reading messages
    - User-scoped message isolation
    """

    def __init__(self, db: Database) -> None:
        """Initialize the SQLiteMessageBus.

        Args:
            db: The Database instance to use for connections.
        """
        self._db = db
        # Map user_id -> list of queues for in-memory listeners
        self._listeners: dict[str, list[asyncio.Queue[EventMessage]]] = {}
        # Async events for signaling new messages per user
        self._new_message_events: dict[str, asyncio.Event] = {}

    async def publish(self, user_id: str, message: EventMessage) -> None:
        """Publish a message to a user's queue.

        Persists the message to the database and pushes to any registered
        in-memory listeners for real-time WebSocket delivery.

        Args:
            user_id: The user identifier.
            message: The event message to publish.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)

            # Insert message into events table (not consumed yet)
            payload = message.model_dump_json()
            await conn.execute(
                """
                INSERT INTO events (event_id, user_id, task_id, payload, consumed)
                VALUES (?, ?, ?, ?, 0)
                """,
                (message.event_id, user_id, message.task_id, payload)
            )
            await conn.commit()

        # Push to in-memory listeners for real-time delivery
        if user_id in self._listeners:
            for queue in self._listeners[user_id]:
                await queue.put(message)

        # Signal that a new message is available
        if user_id in self._new_message_events:
            self._new_message_events[user_id].set()

    async def subscribe(self, user_id: str) -> AsyncIterator[EventMessage]:
        """Subscribe to a user's message stream.

        First yields all unconsumed messages for the user, then waits for
        new messages to be published.

        Args:
            user_id: The user identifier.

        Yields:
            EventMessage objects as they arrive.
        """
        # Create an event for signaling new messages
        if user_id not in self._new_message_events:
            self._new_message_events[user_id] = asyncio.Event()

        event = self._new_message_events[user_id]

        while True:
            # First, read all unconsumed messages from the database
            async with aiosqlite.connect(self._db.db_path) as conn:
                await self._db.init_tables(conn)

                cursor = await conn.execute(
                    """
                    SELECT event_id, payload FROM events
                    WHERE user_id = ? AND consumed = 0
                    ORDER BY id ASC
                    """,
                    (user_id,)
                )
                rows = await cursor.fetchall()

            # Yield unconsumed messages
            for event_id, payload in rows:
                try:
                    message = EventMessage.model_validate_json(payload)
                    # Mark as consumed
                    await self._mark_consumed(user_id, event_id)
                    yield message
                except Exception:
                    # Skip invalid messages
                    await self._mark_consumed(user_id, event_id)
                    continue

            # Wait for new messages to be published
            event.clear()
            await event.wait()

    async def _mark_consumed(self, user_id: str, event_id: str) -> None:
        """Mark a message as consumed for a user.

        Args:
            user_id: The user identifier.
            event_id: The event identifier.
        """
        async with aiosqlite.connect(self._db.db_path) as conn:
            await self._db.init_tables(conn)
            await conn.execute(
                """
                UPDATE events SET consumed = 1
                WHERE user_id = ? AND event_id = ?
                """,
                (user_id, event_id)
            )
            await conn.commit()

    def register_listener(self, user_id: str, queue: Any) -> None:
        """Register a queue listener for a user.

        Registers an in-memory queue to receive messages in real-time,
        typically for WebSocket connections.

        Args:
            user_id: The user identifier.
            queue: The queue object to register.
        """
        if user_id not in self._listeners:
            self._listeners[user_id] = []
        self._listeners[user_id].append(queue)

    def unregister_listener(self, user_id: str, queue: Any) -> None:
        """Unregister a queue listener for a user.

        Args:
            user_id: The user identifier.
            queue: The queue object to unregister.
        """
        if user_id in self._listeners:
            try:
                self._listeners[user_id].remove(queue)
            except ValueError:
                # Queue not in list, ignore
                pass
