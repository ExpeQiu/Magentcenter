"""任务生命周期管理。"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select

from app.config import Settings
from app.core import projects as project_service
from app.core import workspaces as workspace_service
from app.core.agent_registry import AgentRegistry
from app.core.runtime_event import RuntimeEvent
from app.models.db import TaskEventRecord, TaskRecord, get_session_factory
from app.models.runtime import agent_lock_key, normalize_runtime
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

    def _record_to_info(self, rec: TaskRecord) -> TaskInfo:
        usage = None
        if rec.usage_json:
            try:
                usage = TokenUsage(**json.loads(rec.usage_json))
            except (json.JSONDecodeError, TypeError):
                pass
        runtime = getattr(rec, "runtime", None) or "openclaw"
        return TaskInfo(
            id=rec.id,
            workspace_id=rec.workspace_id or "",
            project_id=rec.project_id or "",
            agent_id=rec.agent_id,
            runtime=runtime,  # type: ignore[arg-type]
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
            node_id=getattr(rec, "node_id", "") or "",
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

    def _resolve_runtime(self, req: CreateTaskRequest) -> str:
        raw = req.runtime or self.settings.default_runtime
        rt = normalize_runtime(raw, self.settings.default_runtime)
        if not self.settings.is_runtime_enabled(rt):
            raise ValueError(f"runtime not enabled: {rt}")
        return rt

    async def create_task(self, req: CreateTaskRequest) -> TaskInfo:
        runtime = self._resolve_runtime(req)
        target = (req.node_id or "").strip()
        remote_node = ""
        stamped_node = ""
        if target and target.lower() != "local":
            from app.core.fleet import FleetError, plan_dispatch

            try:
                plan = await plan_dispatch(
                    target, runtime, req.agent_id, workspace_id=req.workspace_id or ""
                )
            except FleetError as e:
                raise ValueError(str(e)) from e
            stamped_node = plan["node_id"]
            if plan["local"]:
                agent = await self.registry.get_agent(req.agent_id, runtime=runtime)
                if not agent:
                    raise ValueError(f"agent not found: {runtime}/{req.agent_id}")
            else:
                remote_node = plan["node_id"]
        else:
            agent = await self.registry.get_agent(req.agent_id, runtime=runtime)
            if not agent:
                raise ValueError(f"agent not found: {runtime}/{req.agent_id}")

        # 固化 runtime，供 dispatch 使用
        req = req.model_copy(update={"runtime": runtime})  # type: ignore[arg-type]

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

        system_prompt = req.system_prompt or ""
        want_inject = (
            self.settings.knowledge_inject_enabled
            if req.inject_knowledge is None
            else bool(req.inject_knowledge)
        )
        if want_inject and (req.prompt or "").strip():
            try:
                from app.core.knowledge import build_task_inject_context
                from app.core.wiki_layers import is_high_stakes

                for_ops = req.agent_id in ("ops-agent", "ops") or "cron-repair" in system_prompt
                high_stakes = for_ops or is_high_stakes(req.prompt) or is_high_stakes(system_prompt)
                # 跨 runtime 共享机构记忆：注入检索不按 runtime 收窄
                block, hits = await build_task_inject_context(
                    req.prompt,
                    workspace_id=workspace_id,
                    runtime=None,
                    top_k=max(1, int(self.settings.knowledge_inject_top_k or 3)),
                    for_ops=high_stakes,
                )
                if block:
                    system_prompt = (
                        f"{block}\n\n{system_prompt}".strip()
                        if system_prompt
                        else block
                    )
                    logger.info(
                        "knowledge injected task=%s hits=%d layers=%s",
                        task_id,
                        len(hits),
                        [h.layer for h in hits],
                    )
                if high_stakes and not hits and not req.skip_knowledge_gate:
                    note = "已跳过门禁：高风险任务未召回到依据。"
                    system_prompt = f"{note}\n\n{system_prompt}".strip()
                    logger.warning("knowledge gate skipped task=%s agent=%s", task_id, req.agent_id)
                    gate_note = note
                else:
                    gate_note = ""
            except Exception as e:
                logger.warning("knowledge inject failed agent=%s: %s", req.agent_id, e)
                gate_note = ""
        else:
            gate_note = ""

        if self.settings.skill_mine_enabled and (req.prompt or "").strip():
            try:
                from app.core.skill_mine import build_skill_inject_block

                skill_block = await build_skill_inject_block(
                    req.prompt,
                    runtime=runtime,
                    top_k=max(1, int(self.settings.skill_inject_top_k or 2)),
                    openclaw_dir=self.settings.skills_dir or None,
                    hermes_dir=self.settings.hermes_skills_dir or None,
                )
                if skill_block:
                    system_prompt = (
                        f"{skill_block}\n\n{system_prompt}".strip()
                        if system_prompt
                        else skill_block
                    )
                    logger.info("skill injected task=%s", task_id)
            except Exception as e:
                logger.warning("skill inject failed task=%s: %s", task_id, e)

        # 固化注入后的 system_prompt 与解析后的 workspace，供 dispatch / 蒸馏使用
        req = req.model_copy(
            update={"system_prompt": system_prompt, "workspace_id": workspace_id}
        )  # type: ignore[arg-type]

        factory = get_session_factory()
        async with factory() as session:
            rec = TaskRecord(
                id=task_id,
                workspace_id=workspace_id,
                project_id=project_id,
                agent_id=req.agent_id,
                runtime=runtime,
                prompt=req.prompt,
                system_prompt=system_prompt,
                status="queued",
                session_id=req.resume_session_id or "",
                start_date=req.start_date or "",
                due_date=req.due_date or "",
                node_id=stamped_node,
            )
            session.add(rec)
            await session.commit()
            await session.refresh(rec)
            info = self._record_to_info(rec)

        logger.info(
            "task created id=%s runtime=%s agent=%s project=%s workspace=%s inject=%s gate=%s",
            task_id,
            runtime,
            req.agent_id,
            project_id or "-",
            workspace_id or "-",
            want_inject,
            bool(gate_note),
        )
        if gate_note:
            await self._emit(
                task_id,
                TaskEvent(type="status", status="queued", content=gate_note),
            )
        if project_id:
            await project_service.update_task_count(project_id, 1)
        if remote_node:
            await self._emit(
                task_id,
                TaskEvent(
                    type="status",
                    status="queued",
                    content=f"queued for node {remote_node}",
                ),
            )
            logger.info(
                "task queued remote id=%s node=%s runtime=%s agent=%s",
                task_id,
                remote_node,
                runtime,
                req.agent_id,
            )
            from app.core.chain import append_chain

            await append_chain(
                kind="dispatch",
                task_id=task_id,
                actor_id="coordinator",
                target_id=remote_node,
                status="queued",
                summary=req.prompt,
                detail={"runtime": runtime, "agent_id": req.agent_id},
            )
            try:
                from app.core.fleet import notify_connector

                await notify_connector(
                    remote_node,
                    {
                        "id": task_id,
                        "agent_id": req.agent_id,
                        "runtime": runtime,
                        "prompt": req.prompt,
                        "system_prompt": system_prompt,
                        "session_id": req.resume_session_id or "",
                    },
                )
            except Exception as e:
                logger.warning("fleet notify failed task=%s node=%s: %s", task_id, remote_node, e)
            return info
        from app.core.chain import append_chain

        await append_chain(
            kind="dispatch",
            task_id=task_id,
            actor_id="coordinator",
            target_id=stamped_node or "local",
            status="queued",
            summary=req.prompt,
            detail={"runtime": runtime, "agent_id": req.agent_id},
        )
        asyncio.create_task(self._dispatch(task_id, req))
        return info

    async def _dispatch(self, task_id: str, req: CreateTaskRequest) -> None:
        runtime = req.runtime or self.settings.default_runtime
        lock_key = agent_lock_key(runtime, req.agent_id)
        async with self._semaphore:
            if self.settings.agent_serial_execution:
                async with self._agent_locks[lock_key]:
                    await self._run_task(task_id, req)
            else:
                await self._run_task(task_id, req)

    async def _run_task(self, task_id: str, req: CreateTaskRequest) -> None:
        self._cancel_flags[task_id] = False
        await self._update_task(task_id, status="running")
        await self._emit(task_id, TaskEvent(type="status", status="running"))

        runtime = req.runtime or self.settings.default_runtime
        if runtime == "hermes":
            timeout = req.timeout or self.settings.hermes_default_timeout
        else:
            timeout = req.timeout or self.settings.openclaw_default_timeout
        session_id = req.resume_session_id or f"agentcenter-{uuid.uuid4().hex[:12]}"
        output_parts: list[str] = []
        tools_used: list[str] = []
        final_status = "failed"
        final_error = ""
        usage: TokenUsage | None = None
        duration_ms = 0

        try:
            executor = self.registry.get_executor(runtime)
            event_iter = executor.execute(
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
                elif event.type == "tool_use" and event.tool:
                    if event.tool not in tools_used:
                        tools_used.append(event.tool)
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
            logger.exception("task %s failed runtime=%s", task_id, runtime)
            final_status = "failed"
            final_error = str(e)
            await self._emit(task_id, TaskEvent(type="error", content=final_error))

        output_text = "".join(output_parts)
        await self._update_task(
            task_id,
            status=final_status,
            output=output_text,
            error=final_error,
            session_id=session_id,
            usage_json=json.dumps(usage.model_dump()) if usage else "",
            duration_ms=duration_ms,
        )
        await self._emit(
            task_id,
            TaskEvent(type="result", content=final_status, status=final_status),
        )
        try:
            from app.core.knowledge import distill_from_task

            await distill_from_task(
                task_id=task_id,
                prompt=req.prompt or "",
                output=output_text,
                agent_id=req.agent_id or "",
                runtime=runtime,
                session_id=session_id,
                status=final_status,
                workspace_id=req.workspace_id or "",
                error=final_error,
            )
        except Exception as e:
            logger.warning("knowledge distill failed task=%s: %s", task_id, e)
        if self.settings.skill_mine_enabled and final_status in ("completed", "failed", "timeout"):
            try:
                from app.core.skill_mine import capture_task, record_skill_outcomes

                await capture_task(
                    task_id=task_id,
                    prompt=req.prompt or "",
                    output=output_text,
                    error=final_error,
                    agent_id=req.agent_id or "",
                    runtime=runtime,
                    session_id=session_id,
                    status=final_status,
                    workspace_id=req.workspace_id or "",
                    tools_used=tools_used,
                    duration_ms=duration_ms,
                    skills_dir=self.settings.skills_dir or None,
                    hermes_skills_dir=self.settings.hermes_skills_dir or None,
                )
                await record_skill_outcomes(
                    req.system_prompt or "",
                    success=final_status == "completed",
                    runtime=runtime,
                )
            except Exception as e:
                logger.warning("skill capture failed task=%s: %s", task_id, e)
        logger.info(
            "task finished id=%s runtime=%s status=%s",
            task_id,
            runtime,
            final_status,
        )
        from app.core.chain import append_chain

        await append_chain(
            kind="finish",
            task_id=task_id,
            actor_id="coordinator",
            target_id="local",
            status=final_status,
            summary=output_text or final_error,
            detail={"runtime": runtime, "agent_id": req.agent_id, "duration_ms": duration_ms},
        )

    def _normalize_event(self, raw: RuntimeEvent) -> TaskEvent:
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
        node_id: str | None = None,
        remote_only: bool = False,
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
                # 工作区任务 + 无归属的活动任务（避免 running 被 workspace 过滤藏掉）
                unscoped_active = and_(
                    or_(
                        TaskRecord.workspace_id == "",
                        TaskRecord.workspace_id.is_(None),
                    ),
                    TaskRecord.status.in_(("queued", "running")),
                )
                ws_cond = or_(
                    TaskRecord.workspace_id == workspace_id,
                    unscoped_active,
                )
                q = q.where(ws_cond)
                count_q = count_q.where(ws_cond)
            if scheduled:
                scheduled_cond = or_(
                    TaskRecord.start_date != "",
                    TaskRecord.due_date != "",
                )
                q = q.where(scheduled_cond)
                count_q = count_q.where(scheduled_cond)
            if node_id:
                q = q.where(TaskRecord.node_id == node_id)
                count_q = count_q.where(TaskRecord.node_id == node_id)
            if remote_only:
                remote_cond = TaskRecord.node_id != ""
                q = q.where(remote_cond)
                count_q = count_q.where(remote_cond)
            total = (await session.execute(count_q)).scalar() or 0
            q = (
                q.order_by(TaskRecord.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(q)).scalars().all()
            return [self._record_to_info(r) for r in rows], total

    async def get_agent_stats(self) -> list[dict]:
        factory = get_session_factory()
        async with factory() as session:
            total_q = (
                select(
                    TaskRecord.agent_id,
                    func.count().label("task_count"),
                    func.max(TaskRecord.updated_at).label("last_active_at"),
                )
                .group_by(TaskRecord.agent_id)
            )
            rows = (await session.execute(total_q)).all()
            stats_map = {
                r.agent_id: {
                    "agent_id": r.agent_id,
                    "task_count": int(r.task_count),
                    "running_count": 0,
                    "last_active_at": r.last_active_at,
                }
                for r in rows
            }
            running_q = (
                select(TaskRecord.agent_id, func.count())
                .where(TaskRecord.status == "running")
                .group_by(TaskRecord.agent_id)
            )
            for agent_id, cnt in (await session.execute(running_q)).all():
                if agent_id in stats_map:
                    stats_map[agent_id]["running_count"] = int(cnt)
                else:
                    stats_map[agent_id] = {
                        "agent_id": agent_id,
                        "task_count": 0,
                        "running_count": int(cnt),
                        "last_active_at": None,
                    }
            return list(stats_map.values())

    async def cancel_task(self, task_id: str) -> TaskInfo | None:
        task = await self.get_task(task_id)
        if not task:
            return None
        if task.status == "queued" and (task.node_id or ""):
            await self._update_task(task_id, status="cancelled", error="cancelled before claim")
            await self._emit(
                task_id,
                TaskEvent(type="status", status="cancelled", content="cancelled"),
            )
            logger.info("remote task cancelled before claim id=%s node=%s", task_id, task.node_id)
            return await self.get_task(task_id)
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
            runtime=task.runtime,
            workspace_id=task.workspace_id or "",
            project_id=task.project_id or "",
            start_date=task.start_date or "",
            due_date=task.due_date or "",
            resume_session_id=task.session_id or None,
            node_id=task.node_id or "",
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
