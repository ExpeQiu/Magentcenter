"""任务 CRUD 与 SSE 事件流 API。"""

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.core import workspaces as workspace_service
from app.models.schemas import (
    CreateTaskRequest,
    TaskInfo,
    TaskListResponse,
    UpdateTaskRequest,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.post("", response_model=TaskInfo, status_code=201)
async def create_task(req: CreateTaskRequest, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    try:
        return await tm.create_task(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    agent_id: str | None = None,
    project_id: str | None = None,
    workspace_id: str | None = None,
    scheduled: bool = False,
) -> TaskListResponse:
    tm = request.app.state.task_manager
    wid = None
    if workspace_id:
        wid = await workspace_service.resolve_workspace_id(workspace_id)
        if not wid:
            raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")
    items, total = await tm.list_tasks(
        page, page_size, status, agent_id, project_id, wid, scheduled
    )
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskInfo)
async def get_task(task_id: str, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    task = await tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return task


@router.patch("/{task_id}", response_model=TaskInfo)
async def update_task(
    task_id: str, req: UpdateTaskRequest, request: Request
) -> TaskInfo:
    tm = request.app.state.task_manager
    try:
        return await tm.update_task(task_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{task_id}/stream")
async def stream_task_events(task_id: str, request: Request):
    tm = request.app.state.task_manager
    task = await tm.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    async def event_generator():
        async for ev in tm.stream_events(task_id):
            if ev.type == "heartbeat":
                yield {"event": "heartbeat", "data": "ping"}
            else:
                payload = ev.model_dump(mode="json")
                if isinstance(payload.get("timestamp"), datetime):
                    payload["timestamp"] = payload["timestamp"].isoformat()
                yield {"event": ev.type, "data": json.dumps(payload, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


@router.post("/{task_id}/cancel", response_model=TaskInfo)
async def cancel_task(task_id: str, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    try:
        task = await tm.cancel_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not task:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")
    return task


@router.post("/{task_id}/retry", response_model=TaskInfo, status_code=201)
async def retry_task(task_id: str, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    try:
        return await tm.retry_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
