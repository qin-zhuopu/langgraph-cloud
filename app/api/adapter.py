"""Client adapter routes for JerehPilot compatibility.

This module provides routes that match the JerehPilot client's expected
API contract, translating between the client's protocol and our core
workflow engine.

Routes:
    POST /financial/audit         — Create a task (multipart file upload)
    POST /financial/audit/decide  — Submit a human decision (callback)
    GET  /financial/audit/status  — Query task status
"""
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form, Query, status

from app.api.deps import TaskServiceDep, WorkflowRepoDep
from app.infrastructure.kafka_producer import map_status_to_client

adapter_router = APIRouter(prefix="/financial/audit", tags=["adapter"])

# Default workflow type for the adapter — can be overridden per-request
DEFAULT_WORKFLOW_TYPE = "inquiry"


@adapter_router.post("")
async def create_task(
    request: Request,
    task_service: TaskServiceDep,
    files: list[UploadFile] = File(default=[]),
    session_id: str = Form(default=""),
    workflow_type: str = Form(default=DEFAULT_WORKFLOW_TYPE),
) -> dict:
    """Create a task via file upload (JerehPilot compatible).

    Accepts multipart/form-data with files, creates a workflow task,
    and returns ``{thread_id}`` matching the client's expectation.
    """
    try:
        # Build file metadata for task data
        file_infos = []
        for f in files:
            content = await f.read()
            file_infos.append({
                "filename": f.filename,
                "content_type": f.content_type,
                "size": len(content),
            })

        task_data: dict[str, Any] = {
            "files": file_infos,
            "session_id": session_id,
        }

        task = await task_service.create_task(
            user_id=session_id or "anonymous",
            task_type=workflow_type,
            data=task_data,
        )

        return {
            "thread_id": task["id"],
            "message": "Task created, waiting for Kafka notification",
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create task: {e}",
        )


@adapter_router.post("/decide")
async def decide(
    request: Request,
    task_service: TaskServiceDep,
) -> dict:
    """Submit a human decision (JerehPilot compatible).

    Accepts ``{event_id, thread_id, decision}`` and maps to the core
    callback interface.

    Decision mapping:
        - "add in" / "y" / "yes" → action from first transition (approve/new_round/award)
        - "reject" → action from second transition (reject)
    """
    body = await request.json()
    event_id = body.get("event_id", "")
    thread_id = body.get("thread_id", "")
    decision = body.get("decision", "")

    if not event_id or not thread_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="event_id and thread_id are required",
        )

    # Get the task to find its workflow type and pending node
    task = await task_service.get_task(thread_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {thread_id}",
        )

    pending = task.get("pending_callback")
    if not pending:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Task has no pending callback",
        )

    node_id = pending["node_id"]

    # Map decision to action by looking up the workflow config
    action, user_input = await _map_decision_to_action(
        task_service, task, node_id, decision, body,
    )

    try:
        result = await task_service.callback(
            task_id=thread_id,
            event_id=event_id,
            node_id=node_id,
            action=action,
            user_input=user_input,
        )

        return {
            "success": True,
            "next_status": map_status_to_client(result["status"]),
        }

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@adapter_router.get("/status")
async def get_status(
    thread_id: str = Query(...),
    task_service: TaskServiceDep = None,
) -> dict:
    """Query task status (JerehPilot compatible)."""
    task = await task_service.get_task(thread_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {thread_id}",
        )

    return {
        "thread_id": task["id"],
        "status": map_status_to_client(task["status"]),
        "data": task.get("data", {}),
    }


async def _map_decision_to_action(
    task_service: TaskServiceDep,
    task: dict,
    node_id: str,
    decision: str,
    body: dict,
) -> tuple[str, dict]:
    """Map a client decision string to a workflow action + user_input.

    For simple approve/reject workflows, maps:
        - "add in" / "y" / "yes" → first transition's action
        - anything else → second transition's action (or "reject")

    The user_input is passed through from the request body, minus the
    control fields (event_id, thread_id, decision).
    """
    from app.workflow.builder import WorkflowBuilder

    # Get workflow config to look up node transitions
    task_type = task["type"]
    workflow_version = task["workflow_version"]

    workflow_repo = task_service._workflow_repo
    workflow_result = await workflow_repo.get_by_version(task_type, workflow_version)

    if workflow_result is None:
        return decision, {}

    workflow_config = workflow_result["config"]
    node_cfg = WorkflowBuilder.get_node_config(workflow_config, node_id)

    if node_cfg is None:
        return decision, {}

    transitions = node_cfg.get("transitions", [])
    if not transitions:
        return decision, {}

    # Build user_input from body (exclude control fields)
    user_input = {k: v for k, v in body.items() if k not in ("event_id", "thread_id", "decision")}

    # Map decision to action
    approve_values = {"add in", "y", "yes", "approve"}
    if decision.lower().strip() in approve_values:
        action = transitions[0]["action"]
    else:
        action = transitions[-1]["action"] if len(transitions) > 1 else transitions[0]["action"]

    return action, user_input
