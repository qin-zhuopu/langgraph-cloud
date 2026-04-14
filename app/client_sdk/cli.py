"""LangGraph Cloud CLI client with dual-mode support.

This module provides an interactive CLI client for LangGraph Cloud that supports
both WebSocket real-time mode and HTTP polling mode for receiving workflow events.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

import httpx
from websockets.asyncio.client import ClientConnection

from app.client_sdk.websocket_client import WebSocketClient
from app.domain.schemas import CallbackRequest, EventMessage, TaskCreate, TaskData

logger = logging.getLogger(__name__)


class LangGraphClient:
    """Client for interacting with LangGraph Cloud service.

    This client provides both real-time WebSocket mode and HTTP polling mode
    for receiving workflow events. It supports task creation, status queries,
    and user callbacks for workflow interrupts.

    Example:
        ```python
        client = LangGraphClient(
            api_url="http://localhost:8000",
            ws_url="ws://localhost:8000/ws",
            user_id="user_123"
        )
        await client.run_websocket_mode()
        ```
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        ws_url: str = "ws://localhost:8000/ws",
        user_id: str = "cli_user",
    ) -> None:
        """Initialize the LangGraph client.

        Args:
            api_url: Base URL for HTTP API endpoints.
            ws_url: WebSocket server URL for real-time events.
            user_id: User ID for task ownership and event subscription.
        """
        self.api_url = api_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")
        self.user_id = user_id

        # HTTP client
        self._http_client: Optional[httpx.AsyncClient] = None

        # WebSocket client
        self._ws_client: Optional[WebSocketClient] = None

        # Event storage for both modes
        self._pending_events: dict[str, EventMessage] = {}
        self._task_cache: dict[str, dict] = {}

        # Mode flag
        self._mode: str = "idle"  # idle, websocket, polling

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client.

        Returns:
            Async HTTP client instance.
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Close all connections and cleanup resources."""
        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
        self._mode = "idle"

    async def create_task(self, task_type: str, data: dict) -> dict:
        """Create a new task via HTTP API.

        Args:
            task_type: Type of task (corresponds to workflow name).
            data: Business data for the task.

        Returns:
            Dictionary containing task details with id and status.
        """
        client = await self._get_http_client()
        request = TaskCreate(user_id=self.user_id, task=TaskData(type=task_type, data=data))
        response = await client.post(
            f"{self.api_url}/v1/tasks",
            json=request.model_dump(),
        )
        response.raise_for_status()
        result = response.json()
        task = result["task"]
        # Cache task data
        self._task_cache[task["id"]] = task
        return task

    async def get_task(self, task_id: str) -> Optional[dict]:
        """Get task status from server.

        Args:
            task_id: The task identifier.

        Returns:
            Task dictionary or None if not found.
        """
        client = await self._get_http_client()
        try:
            response = await client.get(f"{self.api_url}/v1/tasks/{task_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
            result = response.json()
            task = result["task"]
            # Update cache
            self._task_cache[task_id] = task
            return task
        except httpx.HTTPStatusError:
            return None

    async def callback(
        self,
        task_id: str,
        event_id: str,
        node_id: str,
        user_input: dict,
    ) -> dict:
        """Resume workflow execution by providing user input.

        Args:
            task_id: The task ID associated with the callback.
            event_id: The event ID requiring input.
            node_id: The node ID that is waiting for input.
            user_input: User input data for the workflow.

        Returns:
            Dictionary with success status and next workflow status.
        """
        client = await self._get_http_client()
        request = CallbackRequest(
            event_id=event_id,
            node_id=node_id,
            user_input=user_input,
        )
        response = await client.post(
            f"{self.api_url}/v1/tasks/{task_id}/callback",
            json=request.model_dump(),
        )
        response.raise_for_status()
        return response.json()

    def on_event(self, event: EventMessage) -> None:
        """Handle incoming events from WebSocket or polling.

        This method is called when a new event is received. It stores
        the event in the pending events dictionary for later processing.

        Args:
            event: The event message received from the server.
        """
        self._pending_events[event.event_id] = event
        logger.info(
            f"Event received: task={event.task_id}, "
            f"status={event.status}, node={event.node_id}"
        )
        # Also update task cache
        self._task_cache[event.task_id] = {
            "id": event.task_id,
            "type": event.task_type,
            "status": event.status,
        }

    async def run_websocket_mode(self) -> None:
        """Start WebSocket mode for real-time event streaming.

        This method connects to the WebSocket server and registers
        the on_event handler to receive real-time workflow updates.
        """
        if self._mode != "idle":
            raise RuntimeError(f"Client already in {self._mode} mode")

        self._mode = "websocket"
        self._ws_client = WebSocketClient(self.ws_url, self.user_id)
        self._ws_client.on_message(self.on_event)
        await self._ws_client.connect()

    async def run_polling_mode(self, interval: float = 2.0) -> None:
        """Start polling mode for periodic status checks.

        Args:
            interval: Polling interval in seconds (default: 2.0).
        """
        if self._mode != "idle":
            raise RuntimeError(f"Client already in {self._mode} mode")

        self._mode = "polling"

        async def poller() -> None:
            while self._mode == "polling":
                # Check all known tasks
                for task_id in list(self._task_cache.keys()):
                    task = await self.get_task(task_id)
                    if task:
                        # Create synthetic event for status changes
                        event = EventMessage(
                            event_id=f"poll_{task_id}_{datetime.now().isoformat()}",
                            task_id=task_id,
                            task_type=task.get("type", "unknown"),
                            status=task.get("status", "unknown"),
                            node_id=task.get("status", "unknown"),
                            required_params=[],
                            display_data={},
                        )
                        self.on_event(event)
                await asyncio.sleep(interval)

        asyncio.create_task(poller())

    def get_pending_events(self) -> list[EventMessage]:
        """Get all pending events that haven't been processed.

        Returns:
            List of pending event messages.
        """
        return list(self._pending_events.values())

    def clear_pending_events(self) -> None:
        """Clear all pending events."""
        self._pending_events.clear()

    def get_tasks(self) -> list[dict]:
        """Get all cached tasks.

        Returns:
            List of cached task dictionaries.
        """
        return list(self._task_cache.values())


class InteractiveCLI:
    """Interactive CLI for LangGraph Cloud client.

    This provides a menu-driven interface for:
    - Creating purchase request tasks
    - Viewing task status
    - Handling pending approvals
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8000",
        ws_url: str = "ws://localhost:8000/ws",
        user_id: str = "cli_user",
        use_websocket: bool = True,
    ) -> None:
        """Initialize the interactive CLI.

        Args:
            api_url: Base URL for HTTP API endpoints.
            ws_url: WebSocket server URL.
            user_id: User ID for task operations.
            use_websocket: If True, use WebSocket mode; otherwise use polling.
        """
        self.client = LangGraphClient(api_url, ws_url, user_id)
        self.use_websocket = use_websocket
        self._running = False

    async def start(self) -> None:
        """Start the interactive CLI."""
        self._running = True

        # Start the appropriate mode
        if self.use_websocket:
            print("启动 WebSocket 实时模式...")
            await self.client.run_websocket_mode()
        else:
            print("启动 HTTP 轮询模式...")
            await self.client.run_polling_mode()

        # Enter interactive loop
        await self.interactive_loop()

    async def stop(self) -> None:
        """Stop the CLI and cleanup resources."""
        self._running = False
        await self.client.close()

    async def interactive_loop(self) -> None:
        """Main menu-driven interface loop."""
        while self._running:
            self._print_menu()
            choice = await self._get_input("请选择操作 (1-4): ").strip()

            if choice == "1":
                await self._create_purchase_request()
            elif choice == "2":
                await self._view_task_status()
            elif choice == "3":
                await self._handle_pending_approvals()
            elif choice == "4":
                print("退出程序...")
                break
            else:
                print("无效选择，请重试。")

            # Pause before showing menu again
            if choice != "4":
                await self._pause()

        await self.stop()

    def _print_menu(self) -> None:
        """Print the main menu."""
        print("\n" + "=" * 50)
        print("LangGraph Cloud 采购审批系统 CLI")
        print("=" * 50)
        print("1. 创建采购申请任务")
        print("2. 查看任务状态")
        print("3. 处理待审批任务")
        print("4. 退出")
        print("=" * 50)

    async def _get_input(self, prompt: str) -> str:
        """Get user input asynchronously.

        Args:
            prompt: The prompt to display.

        Returns:
            User input string.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, input, prompt)

    async def _create_purchase_request(self) -> None:
        """Create a new purchase request task."""
        print("\n--- 创建采购申请 ---")

        try:
            item_name = await self._get_input("物品名称: ")
            quantity = await self._get_input("数量: ")
            amount = await self._get_input("金额: ")
            requester = await self._get_input("申请人: ")

            task_data = {
                "item_name": item_name,
                "quantity": quantity,
                "amount": amount,
                "requester": requester,
            }

            print("\n创建任务中...")
            task = await self.client.create_task("purchase_approval", task_data)

            print(f"\n任务创建成功!")
            print(f"  任务ID: {task['id']}")
            print(f"  状态: {task['status']}")

        except Exception as e:
            print(f"\n创建任务失败: {e}")

    async def _view_task_status(self) -> None:
        """View status of all tasks."""
        print("\n--- 任务状态 ---")

        tasks = self.client.get_tasks()

        if not tasks:
            print("暂无任务记录")
            return

        for task in tasks:
            print(f"\n任务ID: {task.get('id', 'N/A')}")
            print(f"  类型: {task.get('type', 'N/A')}")
            print(f"  状态: {task.get('status', 'N/A')}")

    async def _handle_pending_approvals(self) -> None:
        """Handle pending approval tasks."""
        print("\n--- 处理待审批任务 ---")

        events = self.client.get_pending_events()

        # Filter for events that require user input
        pending = [e for e in events if e.required_params]

        if not pending:
            print("暂无待审批任务")
            return

        for event in pending:
            print(f"\n任务ID: {event.task_id}")
            print(f"  节点: {event.node_id}")
            print(f"  需要参数: {', '.join(event.required_params)}")
            print(f"  显示数据: {event.display_data}")

            try:
                approve = await self._get_input("是否批准? (y/n): ").strip().lower()

                user_input = {
                    "approved": approve == "y",
                    "approver": self.client.user_id,
                    "timestamp": datetime.now().isoformat(),
                }

                # Add display data to input for context
                user_input.update(event.display_data)

                result = await self.client.callback(
                    task_id=event.task_id,
                    event_id=event.event_id,
                    node_id=event.node_id,
                    user_input=user_input,
                )

                print(f"\n回调结果: {'成功' if result.get('success') else '失败'}")
                if result.get("next_status"):
                    print(f"  下一状态: {result['next_status']}")

                # Remove processed event
                if event.event_id in self.client._pending_events:
                    del self.client._pending_events[event.event_id]

            except Exception as e:
                print(f"\n处理失败: {e}")

    async def _pause(self) -> None:
        """Pause before continuing."""
        await self._get_input("\n按 Enter 继续...")


async def main() -> None:
    """Main entry point for the CLI application."""
    import sys

    # Simple argument parsing
    use_websocket = "--poll" not in sys.argv
    user_id = "cli_user"

    # Parse user_id from args if provided
    for arg in sys.argv[1:]:
        if arg.startswith("--user="):
            user_id = arg.split("=", 1)[1]

    cli = InteractiveCLI(
        api_url="http://localhost:8000",
        ws_url="ws://localhost:8000/ws",
        user_id=user_id,
        use_websocket=use_websocket,
    )

    try:
        await cli.start()
    except KeyboardInterrupt:
        print("\n\n用户中断，正在退出...")
        await cli.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(main())
