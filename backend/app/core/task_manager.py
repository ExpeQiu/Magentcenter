"""任务生命周期管理。"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select

from app.config import Settings
from app.core import projects as project_service
from app.core import workspaces as workspace_service
from app.core.agent_registry import AgentRegistry
from app.core.mock_adapter import MockAdapter, MockEvent
from app.core.openclaw_adapter import OpenClawAdapter, OpenClawEvent
from app.models.db import TaskEventRecord, TaskRecord, get_session_factory
from app.models.schemas import CreateTaskRequest, TaskEvent, TaskInfo, TokenUsage, UpdateTaskRequest

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self, settings: Settings, registry: AgentRegistry):
        self.settings = settings
        self.registry = registry
        self._running: dict[str, asyncio.Task] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._event_queues: dict[str, asyncio.Queue[TaskEvent]] = defaultdict(asyncio.Queue)
        self._agent_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_tasks)
        self._executor = (
            MockAdapter() if settings.ai_mock_mode else OpenClawAdapter(settings)
        )

    def _record_to_info(self, rec: TaskRecord) -> TaskInfo:
        usage = None
        if rec.usage_json:
            try:
                usage = TokenUsage(**json.loads(rec.usage_json))
            except (json.JSONDecodeError, TypeError):
                pass
        return TaskInfo(
            id=rec.id,
            workspace_id=rec.workspace_id or "",
            project_id=rec.project_id or "",
            agent_id=rec.agent_id,
            prompt=rec.prompt,
            system_prompt=rec.system_prompt or "",
            status=rec.status,
            session_id=rec.session_id or "",
            output=rec.output or "",
            error=rec.error or "",
            usage=usage,
            duration_ms=rec.duration_ms or 0,
            start_date=rec.start_date or "",
            due_date=rec.due_date or "",
            created_at=rec.created_at,
            updated_at=rec.updated_at,
        )

    async def _update_task(self, task_id: str, **fields: Any) -> None:
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(TaskRecord, task_id)
            if not rec:
                return
            for k, v in fields.items():
                setattr(rec, k, v)
            rec.updated_at = datetime.utcnow()
            await session.commit()

    async def _save_event(self, task_id: str, event: TaskEvent) -> None:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                TaskEventRecord(
                    task_id=task_id,
                    event_type=event.type,
                    content=event.content,
                    tool=event.tool,
                    call_id=event.call_id,
                    event_json=json.dumps(
                        event.model_dump(mode="json", exclude_none=True), ensure_ascii=False
                    ),
                )
            )
            await session.commit()

    async def _emit(self, task_id: str, event: TaskEvent) -> None:
        await self._save_event(task_id, event)
        q = self._event_queues[task_id]
        await q.put(event)

    async def create_task(self, req: CreateTaskRequest) -> TaskInfo:
        agent = await self.registry.get_agent(req.agent_id)
        if not agent:
            raise ValueError(f"agent not found: {req.agent_id}")

        task_id = str(uuid.uuid4())
        project_id = req.project_id or ""
        workspace_id = req.workspace_id or ""

        if project_id:
            project = await project_service.get_project(project_id)
            if not project:
                raise ValueError(f"project not found: {project_id}")
            if not workspace_id:
                workspace_id = project.workspace_id

        if workspace_id:
            ws = await workspace_service.get_workspace(workspace_id)
            if not ws:
                resolved = await workspace_service.resolve_workspace_id(workspace_id)
                if not resolved:
                    raise ValueError(f"workspace not found: {workspace_id}")
                workspace_id = resolved

        factory = get_session_factory()
        async with factory() as session:
            rec = TaskRecord(
                id=task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                agent_id=req.agent_id,
                prompt=req.prompt,
                system_prompt=req.system_prompt or "",
                status="queued",
                session_id=req.resume_session_id or "",
                start_date=req.start_date or "",
                due_date=req.due_date or "",
            )
            session.add(rec)
            await session.commit()
            await session.refresh(rec)
            info = self._record_to_info(rec)

        logger.info(
            "task created id=%s agent=%s project=%s workspace=%s",
            task_id,
            req.agent_id,
            project_id or "-",
            workspace_id or "-",
        )
        if project_id:
            await project_service.update_task_count(project_id, 1)
        asyncio.create_task(self._dispatch(task_id, req))
        return info

    async def _dispatch(self, task_id: str, req: CreateTaskRequest) -> None:
        async with self._semaphore:
            if self.settings.agent_serial_execution:
                async with self._agent_locks[req.agent_id]:
                    await self._run_task(task_id, req)
            else:
                await self._run_task(task_id, req)

    async def _run_task(self, task_id: str, req: CreateTaskRequest) -> None:
        self._cancel_flags[task_id] = False
        await self._update_task(task_id, status="running")
        await self._emit(task_id, TaskEvent(type="status", status="running"))

        timeout = req.timeout or self.settings.openclaw_default_timeout
        session_id = req.resume_session_id or f"agentcenter-{uuid.uuid4().hex[:12]}"
        output_parts: list[str] = []
        final_status = "failed"
        final_error = ""
        usage: TokenUsage | None = None
        duration_ms = 0

        try:
            if self.settings.ai_mock_mode:
                event_iter = self._executor.execute(
                    req.agent_id,
                    req.prompt,
                    req.system_prompt,
                    session_id,
                    timeout,
                )
            else:
                event_iter = self._executor.execute(
                    req.agent_id,
                    req.prompt,
                    req.system_prompt,
                    session_id,
                    timeout,
                )

            async for raw_event in event_iter:
                if self._cancel_flags.get(task_id):
                    final_status = "cancelled"
                    final_error = "execution cancelled"
                    await self._emit(
                        task_id, TaskEvent(type="error", content=final_error)
                    )
                    break

                event = self._normalize_event(raw_event)
                await self._emit(task_id, event)

                if event.type == "text":
                    output_parts.append(event.content)
                elif event.type == "error":
                    final_error = event.content
                    final_status = "failed"
                elif event.type == "result":
                    if event.content in ("completed", "timeout", "failed", "cancelled"):
                        final_status = event.content
                    else:
                        final_status = "completed" if event.content else "failed"

            if final_status == "running":
                final_status = "completed"

        except Exception as e:
            logger.exception("task %s failed", task_id)
            final_status = "failed"
            final_error = str(e)
            await self._emit(task_id, TaskEvent(type="error", content=final_error))

        await self._update_task(
            task_id,
            status=final_status,
            output="".join(output_parts),
            error=final_error,
            session_id=session_id,
            usage_json=json.dumps(usage.model_dump()) if usage else "",
            duration_ms=duration_ms,
        )
        await self._emit(
            task_id,
            TaskEvent(type="result", content=final_status, status=final_status),
        )
        logger.info("task finished id=%s status=%s", task_id, final_status)

    def _normalize_event(self, raw: OpenClawEvent | MockEvent) -> TaskEvent:
        return TaskEvent(
            type=raw.type,
            content=getattr(raw, "content", "") or getattr(raw, "output", ""),
            tool=getattr(raw, "tool", ""),
            call_id=getattr(raw, "call_id", ""),
            input=getattr(raw, "input", None),
            output=getattr(raw, "output", ""),
            status=getattr(raw, "status", ""),
        )

    async def get_task(self, task_id: str) -> TaskInfo | None:
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(TaskRecord, task_id)
            return self._record_to_info(rec) if rec else None

    async def list_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
        scheduled: bool = False,
    ) -> tuple[list[TaskInfo], int]:
        factory = get_session_factory()
        async with factory() as session:
            q = select(TaskRecord)
            count_q = select(func.count()).select_from(TaskRecord)
            if status:
                q = q.where(TaskRecord.status == status)
                count_q = count_q.where(TaskRecord.status == status)
            if agent_id:
                q = q.where(TaskRecord.agent_id == agent_id)
                count_q = count_q.where(TaskRecord.agent_id == agent_id)
            if project_id:
                q = q.where(TaskRecord.project_id == project_id)
                count_q = count_q.where(TaskRecord.project_id == project_id)
            if workspace_id:
                q = q.where(TaskRecord.workspace_id == workspace_id)
                count_q = count_q.where(TaskRecord.workspace_id == workspace_id)
            if scheduled:
                scheduled_cond = or_(
                    TaskRecord.start_date != "",
                    TaskRecord.due_date != "",
                )
                q = q.where(scheduled_cond)
                count_q = count_q.where(scheduled_cond)
            total = (await session.execute(count_q)).scalar() or 0
            q = (
                q.order_by(TaskRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(q)).scalars().all()
            return [self._record_to_info(r) for r in rows], total

    async def cancel_task(self, task_id: str) -> TaskInfo | None:
        task = await self.get_task(task_id)
        if not task:
            return None
        if task.status != "running":
            raise ValueError(f"task {task_id} is not running (status={task.status})")
        self._cancel_flags[task_id] = True
        logger.info("task cancel requested id=%s", task_id)
        return task

    async def retry_task(self, task_id: str) -> TaskInfo:
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")
        if task.status not in ("failed", "cancelled", "timeout"):
            raise ValueError(f"task {task_id} cannot be retried (status={task.status})")

        req = CreateTaskRequest(
            agent_id=task.agent_id,
            prompt=task.prompt,
            system_prompt=task.system_prompt,
            workspace_id=task.workspace_id or "",
            project_id=task.project_id or "",
            start_date=task.start_date or "",
            due_date=task.due_date or "",
            resume_session_id=task.session_id or None,
        )
        return await self.create_task(req)

    async def update_task(self, task_id: str, req: UpdateTaskRequest) -> TaskInfo:
        task = await self.get_task(task_id)
        if not task:
            raise ValueError(f"task not found: {task_id}")
        fields: dict[str, Any] = {}
        if req.start_date is not None:
            fields["start_date"] = req.start_date
        if req.due_date is not None:
            fields["due_date"] = req.due_date
        if req.project_id is not None:
            if req.project_id:
                project = await project_service.get_project(req.project_id)
                if not project:
                    raise ValueError(f"project not found: {req.project_id}")
            fields["project_id"] = req.project_id
        if fields:
            await self._update_task(task_id, **fields)
        updated = await self.get_task(task_id)
        if not updated:
            raise ValueError(f"task not found: {task_id}")
        return updated

    async def get_events(self, task_id: str, after_id: int = 0) -> list[TaskEvent]:
        factory = get_session_factory()
        async with factory() as session:
            q = (
                select(TaskEventRecord)
                .where(TaskEventRecord.task_id == task_id)
                .where(TaskEventRecord.id > after_id)
                .order_by(TaskEventRecord.id)
            )
            rows = (await session.execute(q)).scalars().all()
            events = []
            for r in rows:
                events.append(
                    TaskEvent(
                        type=r.event_type,
                        content=r.content or "",
                        tool=r.tool or "",
                        call_id=r.call_id or "",
                        timestamp=r.created_at,
                    )
                )
            return events

    def subscribe(self, task_id: str) -> asyncio.Queue[TaskEvent]:
        return self._event_queues[task_id]

    async def stream_events(self, task_id: str):
        """SSE 生成器：先回放历史，再实时推送。"""
        history = await self.get_events(task_id)
        last_id = 0
        for ev in history:
            yield ev
        factory = get_session_factory()
        async with factory() as session:
            q = select(func.max(TaskEventRecord.id)).where(
                TaskEventRecord.task_id == task_id
            )
            last_id = (await session.execute(q)).scalar() or 0

        queue = self.subscribe(task_id)
        task = await self.get_task(task_id)
        if task and task.status in ("completed", "failed", "cancelled", "timeout"):
            return

        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=30)
                yield ev
                if ev.type == "result":
                    break
            except asyncio.TimeoutError:
                task = await self.get_task(task_id)
                if task and task.status in (
                    "completed",
                    "failed",
                    "cancelled",
                    "timeout",
                ):
                    break
                yield TaskEvent(type="heartbeat", content="ping")
