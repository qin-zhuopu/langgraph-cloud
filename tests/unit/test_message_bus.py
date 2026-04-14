"""Unit tests for SQLiteMessageBus."""
import asyncio
import pytest
import aiosqlite

from app.domain.interfaces import IMessageBus
from app.domain.schemas import EventMessage
from app.infrastructure.database import Database


class TestSQLiteMessageBus:
    """Tests for SQLiteMessageBus implementation."""

    def test_implements_interface(self, message_bus):
        """Verify SQLiteMessageBus implements IMessageBus interface."""
        assert isinstance(message_bus, IMessageBus)

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, message_bus, db):
        """Test publishing a message and subscribing to receive it."""
        # Arrange
        user_id = "user-123"
        message = EventMessage(
            event_id="event-1",
            task_id="task-1",
            task_type="test_workflow",
            status="pending",
            node_id="node-1"
        )

        # Act - publish the message
        await message_bus.publish(user_id, message)

        # Act - subscribe and receive the message
        messages = []
        async for msg in message_bus.subscribe(user_id):
            messages.append(msg)
            # Break after receiving one message for this test
            break

        # Assert
        assert len(messages) == 1
        received_msg = messages[0]
        assert received_msg.event_id == "event-1"
        assert received_msg.task_id == "task-1"
        assert received_msg.task_type == "test_workflow"
        assert received_msg.status == "pending"
        assert received_msg.node_id == "node-1"

    @pytest.mark.asyncio
    async def test_register_listener(self, message_bus, db):
        """Test registering an in-memory queue listener for a user."""
        # Arrange
        user_id = "user-listener"
        queue = asyncio.Queue()

        # Act - register the listener
        message_bus.register_listener(user_id, queue)

        # Publish a message
        message = EventMessage(
            event_id="event-listener-1",
            task_id="task-listener-1",
            task_type="listener_workflow",
            status="waiting",
            node_id="node-listener"
        )
        await message_bus.publish(user_id, message)

        # Assert - message should be in the queue
        received_msg = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received_msg.event_id == "event-listener-1"

    @pytest.mark.asyncio
    async def test_unregister_listener(self, message_bus, db):
        """Test unregistering an in-memory queue listener for a user."""
        # Arrange
        user_id = "user-unregister"
        queue = asyncio.Queue()
        message_bus.register_listener(user_id, queue)

        # Act - unregister the listener
        message_bus.unregister_listener(user_id, queue)

        # Publish a message after unregistering
        message = EventMessage(
            event_id="event-unregister-1",
            task_id="task-unregister-1",
            task_type="unregister_workflow",
            status="waiting",
            node_id="node-unregister"
        )
        await message_bus.publish(user_id, message)

        # Assert - queue should be empty (message not pushed)
        assert queue.empty()

    @pytest.mark.asyncio
    async def test_multiple_users_isolation(self, message_bus, db):
        """Test that messages for different users are isolated."""
        # Arrange
        user1_id = "user-isolation-1"
        user2_id = "user-isolation-2"

        user1_queue = asyncio.Queue()
        user2_queue = asyncio.Queue()

        message_bus.register_listener(user1_id, user1_queue)
        message_bus.register_listener(user2_id, user2_queue)

        # Act - publish messages for each user
        user1_message = EventMessage(
            event_id="event-iso-1",
            task_id="task-iso-1",
            task_type="workflow1",
            status="pending",
            node_id="node-1"
        )
        user2_message = EventMessage(
            event_id="event-iso-2",
            task_id="task-iso-2",
            task_type="workflow2",
            status="pending",
            node_id="node-2"
        )

        await message_bus.publish(user1_id, user1_message)
        await message_bus.publish(user2_id, user2_message)

        # Assert - each user should only receive their own message
        user1_received = await asyncio.wait_for(user1_queue.get(), timeout=1.0)
        user2_received = await asyncio.wait_for(user2_queue.get(), timeout=1.0)

        assert user1_received.event_id == "event-iso-1"
        assert user2_received.event_id == "event-iso-2"

        # Verify queues are now empty (no cross-contamination)
        assert user1_queue.empty()
        assert user2_queue.empty()

    @pytest.mark.asyncio
    async def test_subscribe_reads_unconsumed_messages(self, message_bus, db):
        """Test that subscribe reads unconsumed messages first."""
        # Arrange
        user_id = "user-unconsumed"

        # Publish multiple messages before subscribing
        message1 = EventMessage(
            event_id="event-unconsumed-1",
            task_id="task-unconsumed-1",
            task_type="workflow1",
            status="pending",
            node_id="node-1"
        )
        message2 = EventMessage(
            event_id="event-unconsumed-2",
            task_id="task-unconsumed-2",
            task_type="workflow2",
            status="pending",
            node_id="node-2"
        )

        await message_bus.publish(user_id, message1)
        await message_bus.publish(user_id, message2)

        # Act - subscribe and read all unconsumed messages
        messages = []
        message_count = 0
        async for msg in message_bus.subscribe(user_id):
            messages.append(msg)
            message_count += 1
            if message_count >= 2:
                break

        # Assert - should receive both unconsumed messages
        assert len(messages) == 2
        assert messages[0].event_id == "event-unconsumed-1"
        assert messages[1].event_id == "event-unconsumed-2"

    @pytest.mark.asyncio
    async def test_multiple_listeners_same_user(self, message_bus, db):
        """Test that multiple listeners for the same user all receive messages."""
        # Arrange
        user_id = "user-multi-listener"
        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()

        message_bus.register_listener(user_id, queue1)
        message_bus.register_listener(user_id, queue2)

        # Act - publish a message
        message = EventMessage(
            event_id="event-multi-1",
            task_id="task-multi-1",
            task_type="multi_workflow",
            status="pending",
            node_id="node-1"
        )
        await message_bus.publish(user_id, message)

        # Assert - both queues should receive the message
        msg1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
        msg2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

        assert msg1.event_id == "event-multi-1"
        assert msg2.event_id == "event-multi-1"
