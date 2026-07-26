"""Hermes Kanban API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.core.hermes_kanban import (
    HermesKanban,
    KanbanBoard,
    KanbanTask,
    SwarmGraph,
)
from app.models.schemas import CreateTaskRequest, TaskInfo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


class CreateKanbanRequest(BaseModel):
    title: str
    body: str = ""
    assignee: str = "default"
    priority: int = 0
    triage: bool = False


class RunKanbanRequest(BaseModel):
    prompt: str = ""
    agent_id: str = ""
    timeout: int | None = None


class CreateSwarmRequest(BaseModel):
    goal: str
    workers: list[str]
    verifier: str = "default"
    synthesizer: str = "default"
    priority: int = 0
    created_by: str = "default"


def _kb(request: Request) -> HermesKanban:
    settings = request.app.state.settings
    return HermesKanban(settings)


@router.get("/boards", response_model=list[KanbanBoard])
async def list_boards(request: Request):
    return await _kb(request).list_boards()


@router.get("/tasks", response_model=list[KanbanTask])
async def list_tasks(
    request: Request,
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    archived: bool = False,
):
    return await _kb(request).list_tasks(
        status=status, assignee=assignee, archived=archived
    )


@router.post("/tasks", response_model=KanbanTask, status_code=201)
async def create_task(req: CreateKanbanRequest, request: Request):
    try:
        task = await _kb(request).create_task(
            req.title,
            body=req.body,
            assignee=req.assignee,
            priority=req.priority,
            triage=req.triage,
        )
        logger.info("api kanban create id=%s title=%s", task.id, task.title)
        return task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/tasks/{task_id}", response_model=KanbanTask)
async def get_task(task_id: str, request: Request):
    task = await _kb(request).get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"kanban task not found: {task_id}")
    return task


@router.post("/swarm", response_model=SwarmGraph, status_code=201)
async def create_swarm(req: CreateSwarmRequest, request: Request):
    try:
        graph = await _kb(request).create_swarm(
            req.goal,
            workers=req.workers,
            verifier=req.verifier,
            synthesizer=req.synthesizer,
            priority=req.priority,
            created_by=req.created_by,
        )
        logger.info(
            "api kanban swarm root=%s workers=%d",
            graph.root_id,
            len(graph.worker_ids),
        )
        return graph
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/swarm/{root_id}", response_model=SwarmGraph)
async def get_swarm(root_id: str, request: Request):
    graph = await _kb(request).get_swarm(root_id)
    if not graph:
        raise HTTPException(status_code=404, detail=f"swarm not found: {root_id}")
    return graph


@router.post("/tasks/{task_id}/run", response_model=TaskInfo, status_code=201)
async def run_kanban_as_agentcenter_task(
    task_id: str,
    request: Request,
    body: RunKanbanRequest | None = None,
) -> TaskInfo:
    """将 Kanban 任务映射为 Hermes runtime 的 AgentCenter 任务。"""
    kb = _kb(request)
    task = await kb.get_task(task_id)
    if not task and request.app.state.settings.ai_mock_mode:
        # mock list 内查找
        tasks = await kb.list_tasks()
        task = next((t for t in tasks if t.id == task_id), None)
    if not task:
        raise HTTPException(status_code=404, detail=f"kanban task not found: {task_id}")

    req_body = body or RunKanbanRequest()
    agent_id = req_body.agent_id or task.assignee or "default"
    prompt = req_body.prompt or (
        f"[Hermes Kanban {task.id}] {task.title}\n\n{task.body}".strip()
    )
    tm = request.app.state.task_manager
    try:
        ac_task = await tm.create_task(
            CreateTaskRequest(
                agent_id=agent_id,
                runtime="hermes",
                prompt=prompt,
                system_prompt=f"[AgentCenter kanban-run kanban_id={task.id}]",
                timeout=req_body.timeout,
            )
        )
        logger.info(
            "kanban run mapped kanban_id=%s ac_task=%s agent=%s",
            task.id,
            ac_task.id,
            agent_id,
        )
        return ac_task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
