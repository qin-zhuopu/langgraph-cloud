"""Unit tests for SQLiteEventStore."""
import pytest
import aiosqlite
from app.domain.interfaces import IEventStore
from app.infrastructure.database import Database


class TestSQLiteEventStore:
    """Tests for SQLiteEventStore implementation."""

    def test_implements_interface(self, event_store):
        """Verify SQLiteEventStore implements IEventStore interface."""
        assert isinstance(event_store, IEventStore)

    @pytest.mark.asyncio
    async def test_mark_consumed_first_time(self, event_store, db):
        """Test marking an event as consumed for the first time."""
        # Arrange
        event_id = "event-123"

        # Act
        result = await event_store.mark_consumed(event_id)

        # Assert
        assert result is True, "First time marking should return True"

    @pytest.mark.asyncio
    async def test_mark_consumed_duplicate(self, event_store, db):
        """Test marking an event as consumed when already consumed."""
        # Arrange - mark as consumed first time
        event_id = "event-456"
        await event_store.mark_consumed(event_id)

        # Act - try to mark again
        result = await event_store.mark_consumed(event_id)

        # Assert
        assert result is False, "Duplicate marking should return False (replay protection)"

    @pytest.mark.asyncio
    async def test_is_consumed(self, event_store, db):
        """Test checking if an event is consumed."""
        # Arrange
        event_id = "event-789"

        # Act & Assert - not consumed initially
        assert await event_store.is_consumed(event_id) is False

        # Mark as consumed
        await event_store.mark_consumed(event_id)

        # Act & Assert - now consumed
        assert await event_store.is_consumed(event_id) is True

    @pytest.mark.asyncio
    async def test_mark_consumed_inserts_row(self, event_store, db):
        """Test that mark_consumed inserts a row in the events table."""
        # Arrange
        event_id = "event-insert-test"

        # Act
        await event_store.mark_consumed(event_id)

        # Assert - verify row was inserted
        async with aiosqlite.connect(db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT consumed FROM events WHERE event_id = ?",
                (event_id,)
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == 1  # consumed flag should be 1

    @pytest.mark.asyncio
    async def test_is_consumed_nonexistent_event(self, event_store):
        """Test checking consumption for non-existent event."""
        # Act
        result = await event_store.is_consumed("nonexistent-event")

        # Assert
        assert result is False
