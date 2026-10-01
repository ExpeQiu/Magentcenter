"""任务 CRUD 与 SSE 事件流 API。"""

import json
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse

from app.core import workspaces as workspace_service
from app.core.live_tasks import collect_live_tasks
from app.models.schemas import (
    CreateTaskRequest,
    TaskInfo,
    TaskListResponse,
    UpdateTaskRequest,
)

logger = logging.getLogger(__name__)

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
    node_id: str | None = None,
    remote_only: bool = False,
    include_live: bool = Query(
        True,
        description="合并 OpenClaw/Hermes 近 15 分钟 Session 为执行中任务",
    ),
) -> TaskListResponse:
    tm = request.app.state.task_manager
    wid = None
    if workspace_id:
        wid = await workspace_service.resolve_workspace_id(workspace_id)
        if not wid:
            raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")
    items, total = await tm.list_tasks(
        page,
        page_size,
        status,
        agent_id,
        project_id,
        wid,
        scheduled,
        node_id,
        remote_only,
    )

    # 项目筛选下不掺 live session；scheduled/gantt 同理
    want_live = (
        include_live
        and not project_id
        and not scheduled
        and (not status or status in ("running", "all"))
    )
    if want_live:
        try:
            monitor = request.app.state.monitor
            sessions, _ = await monitor.get_sessions(limit=80)
            known = {t.session_id for t in items if t.session_id}
            # 再取一页无过滤的 running，避免漏掉已绑定 session 的本地任务
            running_items, _ = await tm.list_tasks(
                1, 100, "running", agent_id, None, None, False
            )
            known |= {t.session_id for t in running_items if t.session_id}
            live = collect_live_tasks(
                sessions,
                known_session_ids=known,
                agent_id=agent_id,
                status=status or "running",
            )
            if live:
                # live 置顶，便于看板「执行中」看见
                items = live + items
                total += len(live)
                logger.info(
                    "tasks list merged live=%d local_page=%d status=%s workspace=%s",
                    len(live),
                    len(items) - len(live),
                    status or "all",
                    wid or "all",
                )
        except Exception:
            logger.exception("tasks list include_live failed")

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


# 独立 router 用于 /api/live-tasks（前端调用，结构与 /api/tasks 一致但只含 live sessions）
live_tasks_router = APIRouter(prefix="/api", tags=["live-tasks"])


@live_tasks_router.get("/live-tasks", response_model=TaskListResponse)
async def list_live_tasks(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query("running"),
    agent_id: str | None = None,
    workspace_id: str | None = None,
) -> TaskListResponse:
    """仅返回从 OpenClaw/Hermes 活跃 session 映射出的实时任务。"""
    monitor = request.app.state.monitor
    sessions, _ = await monitor.get_sessions(limit=200)
    live = collect_live_tasks(
        sessions,
        known_session_ids=set(),
        agent_id=agent_id,
        status=status or "running",
    )
    total = len(live)
    start = (page - 1) * page_size
    end = start + page_size
    items = live[start:end]
    return TaskListResponse(items=items, total=total, page=page, page_size=page_size)
