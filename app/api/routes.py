"""FastAPI routes for REST and WebSocket endpoints.

This module defines the API router with REST endpoints for task management,
orchestration metadata queries, and a WebSocket endpoint for real-time
event streaming.
"""
import asyncio
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from app.api.deps import TaskServiceDep, WorkflowRepoDep
from app.domain.schemas import (
    CallbackRequest,
    CallbackResponse,
    EventMessage,
    NodeSchema,
    OrchestrationDetail,
    OrchestrationListResponse,
    Task,
    TaskCreate,
    TaskResponse,
    TransitionSchema,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Task endpoints
# ---------------------------------------------------------------------------


@router.post("/v1/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    request: TaskCreate,
    task_service: TaskServiceDep,
) -> TaskResponse:
    """Create a new task and start its workflow execution."""
    try:
        task_dict = await task_service.create_task(
            user_id=request.user_id,
            task_type=request.task.type,
            data=request.task.data,
        )
        task = Task(**task_dict)
        return TaskResponse(task=task)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {e}",
        )


@router.get("/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    task_service: TaskServiceDep,
) -> TaskResponse:
    """Get a task by ID, including pending_callback when interrupted."""
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

    Validates action against node transitions and user_input against form_schema.
    """
    try:
        task_dict = await task_service.callback(
            task_id=task_id,
            event_id=request.event_id,
            node_id=request.node_id,
            action=request.action,
            user_input=request.user_input,
        )
        return CallbackResponse(success=True, next_status=task_dict["status"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Callback failed: {e}",
        )


# ---------------------------------------------------------------------------
# Orchestration endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/orchestrations", response_model=OrchestrationListResponse)
async def list_orchestrations(
    workflow_repo: WorkflowRepoDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> OrchestrationListResponse:
    """List available orchestration definitions with pagination."""
    result = await workflow_repo.list_orchestrations(page=page, page_size=page_size)
    return OrchestrationListResponse(**result)


@router.get("/v1/orchestrations/{orch_type}/versions/{version}", response_model=OrchestrationDetail)
async def get_orchestration_version(
    orch_type: str,
    version: str,
    workflow_repo: WorkflowRepoDep,
) -> OrchestrationDetail:
    """Get the full orchestration definition for a specific version."""
    workflow_result = await workflow_repo.get_by_version(orch_type, version)
    if workflow_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Orchestration not found: {orch_type} version {version}",
        )
    return _config_to_orchestration_detail(workflow_result)


@router.get("/v1/orchestrations/{orch_type}/versions/{version}/nodes/{node_id}", response_model=NodeSchema)
async def get_orchestration_node(
    orch_type: str,
    version: str,
    node_id: str,
    workflow_repo: WorkflowRepoDep,
) -> NodeSchema:
    """Get a single node definition from an orchestration version."""
    workflow_result = await workflow_repo.get_by_version(orch_type, version)
    if workflow_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Orchestration not found: {orch_type} version {version}",
        )

    config = workflow_result["config"]
    for node in config.get("nodes", []):
        if node["id"] == node_id:
            return _node_dict_to_schema(node)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Node not found: {node_id}",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_to_orchestration_detail(workflow_result: dict) -> OrchestrationDetail:
    """Convert a workflow_repo result dict to an OrchestrationDetail schema."""
    config = workflow_result["config"]
    nodes = [_node_dict_to_schema(n) for n in config.get("nodes", [])]
    return OrchestrationDetail(
        type=config.get("name", workflow_result.get("workflow_name", "")),
        version=workflow_result["version"],
        description=config.get("description", config.get("display_name", "")),
        nodes=nodes,
    )


def _node_dict_to_schema(node: dict) -> NodeSchema:
    """Convert a raw node config dict to a NodeSchema."""
    transitions = None
    if node.get("type") == "interrupt" and "transitions" in node:
        transitions = [
            TransitionSchema(
                action=t["action"],
                label=t["label"],
                target_node=t["target_node"],
                form_schema=t.get("form_schema", {}),
            )
            for t in node["transitions"]
        ]
    return NodeSchema(
        id=node["id"],
        type=node["type"],
        description=node.get("description", ""),
        transitions=transitions,
    )


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time workflow event streaming."""
    user_id = websocket.query_params.get("user_id")
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    from app.api.main import get_app_state

    app_state = get_app_state()
    message_bus = app_state.message_bus

    queue: asyncio.Queue[EventMessage] = asyncio.Queue()

    try:
        message_bus.register_listener(user_id, queue)

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                await websocket.send_json(event.model_dump())
            except asyncio.TimeoutError:
                try:
                    await websocket.ping()
                except Exception:
                    break
            except WebSocketDisconnect:
                break

    except Exception:
        pass

    finally:
        message_bus.unregister_listener(user_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass
