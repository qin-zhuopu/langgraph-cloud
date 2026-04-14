"""Integration tests for WebSocket client.

These tests verify the WebSocket client functionality for real-time
event streaming from the LangGraph Cloud service.

Note: Full E2E tests for WebSocket mode are in tests/e2e/test_websocket_mode.py
"""
import pytest

from app.client_sdk.websocket_client import WebSocketClient


@pytest.mark.integration
class TestWebSocketClient:
    """Test WebSocket client initialization and configuration."""

    def test_init_with_defaults(self) -> None:
        """Test WebSocketClient initialization with default parameters."""
        client = WebSocketClient("ws://localhost:8000/ws", "user_123")

        assert client.server_url == "ws://localhost:8000/ws"
        assert client.user_id == "user_123"
        assert client.reconnect_delay == 1.0
        assert client.max_reconnect_delay == 60.0
        assert not client.is_connected

    def test_init_with_custom_delays(self) -> None:
        """Test WebSocketClient initialization with custom reconnection delays."""
        client = WebSocketClient(
            server_url="ws://example.com/ws",
            user_id="user_456",
            reconnect_delay=2.5,
            max_reconnect_delay=120.0,
        )

        assert client.server_url == "ws://example.com/ws"
        assert client.user_id == "user_456"
        assert client.reconnect_delay == 2.5
        assert client.max_reconnect_delay == 120.0

    def test_on_message_decorator(self) -> None:
        """Test registering message handlers via decorator."""
        client = WebSocketClient("ws://localhost:8000/ws", "user_123")
        received_messages: list[object] = []

        @client.on_message
        async def handler(event: object) -> None:
            received_messages.append(event)

        assert len(client._message_handlers) == 1
        assert client._message_handlers[0] is handler

    def test_on_message_method(self) -> None:
        """Test registering message handlers via method call."""
        client = WebSocketClient("ws://localhost:8000/ws", "user_123")

        async def handler(event: object) -> None:
            pass

        client.on_message(handler)

        assert len(client._message_handlers) == 1
        assert client._message_handlers[0] is handler

    def test_multiple_message_handlers(self) -> None:
        """Test registering multiple message handlers."""
        client = WebSocketClient("ws://localhost:8000/ws", "user_123")

        @client.on_message
        async def handler1(event: object) -> None:
            pass

        @client.on_message
        async def handler2(event: object) -> None:
            pass

        async def handler3(event: object) -> None:
            pass

        client.on_message(handler3)

        assert len(client._message_handlers) == 3

    def test_is_connected_property(self) -> None:
        """Test the is_connected property reflects connection state."""
        client = WebSocketClient("ws://localhost:8000/ws", "user_123")

        # Initially not connected
        assert not client.is_connected


@pytest.mark.integration
class TestWebSocketClientE2E:
    """Placeholder for E2E WebSocket tests.

    Full E2E tests are implemented in tests/e2e/test_websocket_mode.py
    and require a running server to test actual WebSocket communication.
    """

    @pytest.mark.asyncio
    async def test_placeholder_for_e2e(self) -> None:
        """Placeholder test for E2E WebSocket functionality.

        Real E2E tests verify:
        - Connection establishment with server
        - Message reception and handler invocation
        - Reconnection after connection loss
        - Context manager usage
        """
        # This is a stub - real E2E tests are in tests/e2e/
        assert True
