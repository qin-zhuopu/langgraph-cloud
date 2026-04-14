"""FastAPI routes for REST and WebSocket endpoints.

This module defines the API router with REST endpoints for task management
and a WebSocket endpoint for real-time event streaming.
"""
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from app.api.deps import TaskServiceDep, set_task_service
from app.domain.schemas import (
    CallbackRequest,
    CallbackResponse,
    ErrorResponse,
    Task,
    TaskCreate,
    TaskResponse,
)
from app.domain.schemas import EventMessage

router = APIRouter()


@router.post("/v1/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: TaskCreate,
    task_service: TaskServiceDep,
) -> TaskResponse:
    """Create a new task and start its workflow execution.

    Args:
        request: The task creation request containing user_id and task data.
        task_service: The TaskService dependency.

    Returns:
        TaskResponse: The created task with its ID and status.

    Raises:
        HTTPException: If workflow not found (404) or other error occurs (500).
    """
    try:
        task_dict = await task_service.create_task(
            user_id=request.user_id,
            task_type=request.task.type,
            data=request.task.data,
        )
        # Convert dict to Task schema
        task = Task(**task_dict)
        return TaskResponse(task=task)
    except ValueError as e:
        # Workflow not found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        # Other errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {e}",
        )


@router.get("/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    task_service: TaskServiceDep,
) -> TaskResponse:
    """Get a task by ID.

    Args:
        task_id: The task identifier.
        task_service: The TaskService dependency.

    Returns:
        TaskResponse: The task details.

    Raises:
        HTTPException: If task not found (404).
    """
    task_dict = await task_service.get_task(task_id)
    if task_dict is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )
    task = Task(**task_dict)
    return TaskResponse(task=task)


@router.post("/v1/tasks/{task_id}/callback", response_model=CallbackResponse)
async def callback_task(
    task_id: str,
    request: CallbackRequest,
    task_service: TaskServiceDep,
) -> CallbackResponse:
    """Handle user callback to resume a workflow from an interrupt.

    Args:
        task_id: The task ID associated with the callback.
        request: The callback request containing event_id, node_id, and user_input.
        task_service: The TaskService dependency.

    Returns:
        CallbackResponse: The result of the callback operation.

    Raises:
        HTTPException: If task not found (404), event already consumed (400), or other error (500).
    """
    try:
        task_dict = await task_service.callback(
            task_id=task_id,
            event_id=request.event_id,
            node_id=request.node_id,
            user_input=request.user_input,
        )
        return CallbackResponse(success=True, next_status=task_dict["status"])
    except ValueError as e:
        # Event already consumed or other value error
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        # Task not found
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        # Other errors
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Callback failed: {e}",
        )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time workflow event streaming.

    Clients connect with a user_id query parameter to receive events
    for that user's tasks. The endpoint:
    1. Accepts the connection
    2. Registers a listener for the user
    3. Pushes EventMessage objects as JSON
    4. Cleans up on disconnect

    Query parameters:
        user_id: The user ID to subscribe to events for.

    Connection format:
        Messages are JSON objects matching EventMessage schema.
    """
    # Get user_id from query params
    user_id = websocket.query_params.get("user_id")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Accept the connection
    await websocket.accept()

    # Import here to avoid circular dependency
    from app.api.main import get_app_state

    app_state = get_app_state()
    message_bus = app_state.message_bus

    # Create a queue for this connection
    import asyncio
    queue: asyncio.Queue[EventMessage] = asyncio.Queue()

    try:
        # Register listener
        message_bus.register_listener(user_id, queue)

        # Listen for messages and send to client
        while True:
            try:
                # Wait for message with timeout to allow checking connection health
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                # Send as JSON
                await websocket.send_json(event.model_dump())
            except asyncio.TimeoutError:
                # Send heartbeat periodically
                try:
                    # Use ping with empty bytes
                    await websocket.ping()
                except Exception:
                    break
            except WebSocketDisconnect:
                break

    except Exception as e:
        # Log error (in production, use proper logging)
        pass

    finally:
        # Clean up: unregister listener
        message_bus.unregister_listener(user_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass
