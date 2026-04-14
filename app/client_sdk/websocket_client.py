"""WebSocket client for real-time event streaming.

This module provides a WebSocket client that connects to the LangGraph Cloud
service's WebSocket endpoint to receive real-time workflow events.
"""
import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Optional, Union

import websockets
from websockets.asyncio.client import ClientConnection

from app.domain.schemas import EventMessage

logger = logging.getLogger(__name__)


MessageHandler = Union[
    Callable[[EventMessage], Awaitable[None]],
    Callable[[EventMessage], None],
]


class WebSocketClient:
    """Async WebSocket client for real-time event streaming.

    This client connects to the LangGraph Cloud WebSocket endpoint and
    receives real-time events for a specific user. It supports automatic
    reconnection with exponential backoff.

    Example:
        ```python
        async with WebSocketClient("ws://localhost:8000/ws", "user_123") as client:
            @client.on_message
            async def handle_event(event: EventMessage):
                print(f"Received: {event}")

            await client.connect()
            # Keep connection alive...
        ```
    """

    def __init__(
        self,
        server_url: str,
        user_id: str,
        reconnect_delay: float = 1.0,
        max_reconnect_delay: float = 60.0,
    ) -> None:
        """Initialize the WebSocket client.

        Args:
            server_url: WebSocket server URL (e.g., "ws://localhost:8000/ws")
            user_id: User ID to subscribe events for
            reconnect_delay: Initial reconnection delay in seconds (default: 1.0)
            max_reconnect_delay: Maximum reconnection delay in seconds (default: 60.0)
        """
        self.server_url = server_url
        self.user_id = user_id
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_delay = max_reconnect_delay

        # Connection state
        self._connection: Optional[ClientConnection] = None
        self._is_connected = False
        self._should_stop = False

        # Message handling
        self._message_handlers: "list[MessageHandler]" = []

        # Background tasks
        self._listen_task: Optional[asyncio.Task[None]] = None
        self._reconnect_task: Optional[asyncio.Task[None]] = None

    def on_message(self, handler: MessageHandler) -> MessageHandler:
        """Register a callback for incoming messages.

        The handler will be called for each EventMessage received from the server.
        Can be used as a decorator.

        Args:
            handler: Async or sync function that takes an EventMessage

        Returns:
            The handler function (for decorator use)

        Example:
            ```python
            @client.on_message
            async def my_handler(event: EventMessage):
                print(f"Event: {event.status}")
            ```
        """
        self._message_handlers.append(handler)
        return handler

    async def connect(self) -> None:
        """Connect to the WebSocket server.

        This method starts the connection and begins listening for messages.
        It will automatically reconnect if the connection is lost, with
        exponential backoff up to max_reconnect_delay.

        Raises:
            RuntimeError: If already connected
        """
        if self._is_connected:
            raise RuntimeError("Client is already connected")

        self._should_stop = False
        await self._connect_with_backoff()

    async def _connect_with_backoff(self) -> None:
        """Connect to WebSocket with exponential backoff retry.

        This method handles the reconnection logic with increasing delays
        between attempts.
        """
        delay = self.reconnect_delay

        while not self._should_stop:
            try:
                # Construct WebSocket URL with user_id query parameter
                url = f"{self.server_url}?user_id={self.user_id}"

                logger.info(f"Connecting to WebSocket: {url}")

                # Connect to server
                self._connection = await websockets.connect(url)
                self._is_connected = True
                logger.info("WebSocket connected successfully")

                # Reset delay on successful connection
                delay = self.reconnect_delay

                # Start listening for messages
                self._listen_task = asyncio.create_task(self._listen())
                await self._listen_task

            except asyncio.CancelledError:
                logger.info("Connection task cancelled")
                break

            except Exception as e:
                self._is_connected = False
                logger.warning(f"WebSocket connection failed: {e}")

                if self._should_stop:
                    break

                # Exponential backoff with jitter
                current_delay = min(delay, self.max_reconnect_delay)
                logger.info(f"Reconnecting in {current_delay:.1f} seconds...")

                await asyncio.sleep(current_delay)

                # Increase delay for next attempt (exponential backoff)
                delay = min(delay * 2, self.max_reconnect_delay)

        self._is_connected = False

    async def _listen(self) -> None:
        """Listen for incoming messages from the WebSocket server.

        This method runs in a background task and continuously receives
        messages, parsing them as EventMessage objects and calling
        registered handlers.
        """
        if self._connection is None:
            return

        try:
            async for message in self._connection:
                try:
                    # Parse JSON message
                    data = json.loads(message)
                    event = EventMessage(**data)

                    # Call all registered handlers
                    for handler in self._message_handlers:
                        result = handler(event)
                        if asyncio.iscoroutine(result):
                            await result

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {e}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in listen loop: {e}")

    async def disconnect(self) -> None:
        """Disconnect from the WebSocket server.

        This method gracefully closes the connection and stops
        the background listener task.
        """
        self._should_stop = True

        # Cancel listen task
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # Close connection
        if self._connection:
            await self._connection.close()
            self._connection = None

        self._is_connected = False
        logger.info("WebSocket disconnected")

    async def __aenter__(self) -> "WebSocketClient":
        """Async context manager entry.

        Returns:
            The connected WebSocketClient instance
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Any,
    ) -> None:
        """Async context manager exit.

        Ensures the connection is properly closed.
        """
        await self.disconnect()

    @property
    def is_connected(self) -> bool:
        """Check if the client is currently connected.

        Returns:
            True if connected, False otherwise
        """
        return self._is_connected
