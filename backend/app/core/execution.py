"""执行记录：接收去重、句柄、取消和启动恢复。

进程内异步任务在重启后无法核验，进入 unknown，不重新启动。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.autonomy_state import reduce_outcome
from app.core.identity import load_or_create_identity
from app.models.db import ExecutionRecord, TaskRecord, get_session_factory

logger = logging.getLogger(__name__)

_LIVE = {"accepted", "starting", "running"}


def _now() -> datetime:
    return datetime.utcnow()


async def open_local(task_id: str, runtime: str, agent_id: str, attempt: int = 1) -> str:
    ident = load_or_create_identity()
    execution_id = str(uuid.uuid4())
    key = f"local:{task_id}:{attempt}"
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(select(ExecutionRecord).where(ExecutionRecord.dedupe_key == key))
        ).scalar_one_or_none()
        if existing:
            logger.info(
                "execution reused center_id=%s task_id=%s execution_id=%s attempt=%s",
                ident.center_id,
                task_id,
                existing.id,
                attempt,
            )
            return existing.id
        session.add(
            ExecutionRecord(
                id=execution_id,
                task_id=task_id,
                owner_center_id=ident.center_id,
                attempt=attempt,
                dedupe_key=key,
                status="accepted",
                runtime=runtime,
                agent_id=agent_id,
                node_id=ident.node_id,
            )
        )
        await session.commit()
    logger.info(
        "execution accepted center_id=%s task_id=%s execution_id=%s attempt=%s",
        ident.center_id,
        task_id,
        execution_id,
        attempt,
    )
    return execution_id


async def accept_remote(task_id: str, node_id: str, attempt: int = 1, delegation_id: str = "") -> bool:
    """同一 delegation/attempt 或同一 v1 任务只接收一次。返回 False 表示已经接收过。"""
    key = f"remote:{delegation_id or task_id}:{attempt}"
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ExecutionRecord(
                id=str(uuid.uuid4()),
                task_id=task_id,
                owner_center_id=ident.center_id,
                delegation_id=delegation_id,
                node_id=node_id,
                attempt=attempt,
                dedupe_key=key,
                status="accepted",
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info(
                "execution duplicate ignored task_id=%s node_id=%s attempt=%s",
                task_id,
                node_id,
                attempt,
            )
            return False
    return True


async def current_execution(task_id: str) -> ExecutionRecord | None:
    factory = get_session_factory()
    async with factory() as session:
        q = (
            select(ExecutionRecord)
            .where(ExecutionRecord.task_id == task_id)
            .order_by(ExecutionRecord.created_at.desc())
        )
        return (await session.execute(q)).scalars().first()


async def mark(
    execution_id: str,
    status: str,
    *,
    handle_kind: str = "",
    handle_token: str = "",
) -> None:
    if not execution_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            return
        row.status = status
        if handle_kind:
            row.handle_kind = handle_kind
        if handle_token:
            row.handle_token = handle_token
        if status == "stopped":
            row.stopped_at = _now()
        row.updated_at = _now()
        await session.commit()
    logger.info("execution status execution_id=%s status=%s", execution_id, status)


async def cancel_requested(task_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(TaskRecord, task_id)
        return bool(task and task.cancel_requested_at)


async def request_cancel(task_id: str) -> str:
    """落库取消请求。已完成的执行返回 already_finished，不改完成事实。"""
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(TaskRecord, task_id)
        if task is None:
            return "missing"
        execution = (
            await session.execute(
                select(ExecutionRecord)
                .where(ExecutionRecord.task_id == task_id)
                .order_by(ExecutionRecord.created_at.desc())
            )
        ).scalars().first()
        exec_status = execution.status if execution else ""
        outcome = reduce_outcome(task.lifecycle_status or task.status, exec_status, "cancel_requested")
        if outcome["outcome"] == "already_finished":
            logger.info("cancel ignored already finished task_id=%s", task_id)
            return "already_finished"
        task.cancel_requested_at = task.cancel_requested_at or _now()
        task.revision = int(task.revision or 0) + 1
        task.updated_at = _now()
        await session.commit()
    logger.info("cancel requested task_id=%s", task_id)
    return "cancel_requested"


async def ack_cancel(execution_id: str) -> None:
    if not execution_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            return
        row.cancel_ack_at = _now()
        row.updated_at = _now()
        await session.commit()
    logger.info("cancel acknowledged execution_id=%s", execution_id)


async def recover() -> int:
    """重启后对照不到可核验句柄的执行标为 unknown，不重新跑。"""
    factory = get_session_factory()
    changed = 0
    async with factory() as session:
        rows = (
            await session.execute(select(ExecutionRecord).where(ExecutionRecord.status.in_(_LIVE)))
        ).scalars().all()
        for row in rows:
            row.status = "unknown"
            row.updated_at = _now()
            task = await session.get(TaskRecord, row.task_id)
            if task and task.status in {"queued", "running"}:
                task.lifecycle_status = "needs_attention"
                task.updated_at = _now()
            changed += 1
            logger.info(
                "execution needs attention task_id=%s execution_id=%s attempt=%s",
                row.task_id,
                row.id,
                row.attempt,
            )
        await session.commit()
    return changed


def reconcile_handle(saved_status: str, handle_alive: bool) -> str:
    """启动点附近崩溃：能核验就接管，不能核验就 unknown。"""
    if saved_status not in _LIVE:
        return saved_status
    if handle_alive:
        return "running"
    return "unknown"
