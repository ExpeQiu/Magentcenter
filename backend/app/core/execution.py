"""执行记录：接收去重、句柄、取消和启动恢复。

进程内异步任务在重启后无法核验，进入 unknown，不重新启动。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.autonomy_state import reduce_outcome
from app.core.identity import load_or_create_identity
from app.models.db import (
    CommandAckRecord,
    DelegationRecord,
    ExecutionRecord,
    TaskRecord,
    WorkspaceLinkRecord,
    get_session_factory,
)

logger = logging.getLogger(__name__)

_LIVE = {"accepted", "starting", "running"}
_CLOSED_TASK = {"completed", "failed", "cancelled", "timeout", "succeeded"}
_TERMINAL_EXECUTION = {"succeeded", "failed", "stopped"}
CLAIM_TTL = timedelta(hours=24)
LEASE_TTL = timedelta(minutes=5)


class ClaimError(ValueError):
    def __init__(self, detail: str, status_code: int = 403):
        self.status_code = status_code
        super().__init__(detail)


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
    from app.config import get_settings

    settings = get_settings()
    inbound_cap = max(0, int(getattr(settings, "cloud_inbound_slots", 2) or 0))
    key = f"remote:{delegation_id or task_id}:{attempt}"
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        if inbound_cap > 0:
            live_remote = (
                await session.execute(
                    select(ExecutionRecord).where(
                        ExecutionRecord.status.in_(_LIVE),
                        ExecutionRecord.dedupe_key.like("remote:%"),
                    )
                )
            ).scalars().all()
            if len(live_remote) >= inbound_cap:
                logger.warning(
                    "cloud inbound slots full cap=%s live=%s task_id=%s",
                    inbound_cap,
                    len(live_remote),
                    task_id,
                )
                raise ClaimError("cloud inbound slots exhausted", 429)
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


def _dedupe_key(task_id: str, delegation_id: str, attempt: int) -> str:
    return f"remote:{delegation_id or task_id}:{attempt}"


def _ack_key(node_id: str, task_id: str, delegation_id: str, attempt: int) -> str:
    return f"ack:{node_id}:{delegation_id or task_id}:{attempt}"


async def _execution_by_key(session, key: str) -> ExecutionRecord | None:
    return (
        await session.execute(select(ExecutionRecord).where(ExecutionRecord.dedupe_key == key))
    ).scalar_one_or_none()


async def _authorize_claim(
    session,
    *,
    node_id: str,
    task_id: str,
    delegation_id: str,
    attempt: int,
) -> tuple[TaskRecord | None, DelegationRecord | None, ExecutionRecord | None]:
    """在调用方的事务里核对目标节点、拥有者、工作区、attempt 和过期。"""
    if attempt < 1:
        raise ClaimError("attempt mismatch", 409)
    ident = load_or_create_identity()
    delegation = None
    if delegation_id:
        delegation = await session.get(DelegationRecord, delegation_id)
        if delegation is None:
            raise ClaimError("delegation not found", 404)
        if delegation.target_node_id != node_id:
            raise ClaimError("delegation is assigned to another node", 403)
        if delegation.owner_center_id and delegation.owner_center_id != ident.center_id:
            raise ClaimError("delegation owner mismatch", 403)
        if task_id and delegation.task_id and delegation.task_id != task_id:
            raise ClaimError("task does not match delegation", 409)
        task_id = task_id or delegation.task_id
        snapshot = {}
        try:
            snapshot = json.loads(delegation.auth_snapshot_json or "{}")
        except json.JSONDecodeError:
            snapshot = {}
        expected = int(snapshot.get("attempt") or 1)
        if attempt != expected:
            raise ClaimError("attempt mismatch", 409)
        local_ws = str(snapshot.get("local_workspace_id") or "")
        remote_ws = str(snapshot.get("remote_workspace_id") or "")
        remote_center = str(snapshot.get("remote_center_id") or "")
        if local_ws or remote_ws:
            if not (local_ws and remote_ws and remote_center):
                raise ClaimError("workspace is not linked", 403)
            link = (
                await session.execute(
                    select(WorkspaceLinkRecord).where(
                        WorkspaceLinkRecord.local_workspace_id == local_ws,
                        WorkspaceLinkRecord.remote_center_id == remote_center,
                        WorkspaceLinkRecord.remote_workspace_id == remote_ws,
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                raise ClaimError("workspace is not linked", 403)
    task = await session.get(TaskRecord, task_id) if task_id else None
    if delegation is None and task is None:
        raise ClaimError("task not found", 404)
    if delegation is not None and delegation.task_id and task is None:
        raise ClaimError("task not found", 404)
    if task is not None:
        if (task.node_id or "") != node_id and delegation is None:
            raise ClaimError("task is assigned to another node", 403)
        if task.node_id and task.node_id != node_id:
            raise ClaimError("task is assigned to another node", 403)
        if task.owner_center_id and task.owner_center_id != ident.center_id:
            raise ClaimError("task owner mismatch", 403)
        if delegation is None and attempt != 1:
            raise ClaimError("attempt mismatch", 409)
    existing = await _execution_by_key(session, _dedupe_key(task_id, delegation_id, attempt))
    if existing is not None and existing.node_id != node_id:
        raise ClaimError("execution belongs to another node", 403)
    expired = False
    if delegation is not None and delegation.created_at and delegation.created_at < _now() - CLAIM_TTL:
        expired = True
    if task is not None and task.status in _CLOSED_TASK and existing is None:
        raise ClaimError("command is closed", 409)
    if expired and existing is None:
        raise ClaimError("command expired", 409)
    return task, delegation, existing


async def claim_next(node_id: str) -> dict | None:
    """领取下一条排队给本节点的本地任务（外置 Node Agent 主路径）。"""
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(TaskRecord)
                .where(TaskRecord.status == "queued")
                .where(TaskRecord.owner_center_id.in_([ident.center_id, ""]))
                .order_by(TaskRecord.created_at.asc())
                .limit(20)
            )
        ).scalars().all()
        for task in rows:
            assigned = (task.node_id or "").strip()
            if assigned and assigned != node_id and assigned.lower() != "local":
                continue
            live = (
                await session.execute(
                    select(ExecutionRecord).where(
                        ExecutionRecord.task_id == task.id,
                        ExecutionRecord.status.in_(_LIVE | {"unknown"}),
                    )
                )
            ).scalars().first()
            if live is not None:
                continue
            task.node_id = node_id
            task.updated_at = _now()
            execution_id = str(uuid.uuid4())
            session.add(
                ExecutionRecord(
                    id=execution_id,
                    task_id=task.id,
                    owner_center_id=ident.center_id,
                    node_id=node_id,
                    attempt=1,
                    dedupe_key=_dedupe_key(task.id, "", 1),
                    status="accepted",
                    runtime=task.runtime or "",
                    agent_id=task.agent_id or "",
                    lease_expires_at=_now() + LEASE_TTL,
                    assignment_generation=1,
                )
            )
            await session.commit()
            logger.info(
                "claim_next accepted node_id=%s task_id=%s execution_id=%s",
                node_id,
                task.id,
                execution_id,
            )
            return {
                "accepted": True,
                "task_id": task.id,
                "execution_id": execution_id,
                "delegation_id": "",
                "attempt": 1,
                "assignment_generation": 1,
                "status": "accepted",
                "runtime": task.runtime or "",
                "agent_id": task.agent_id or "",
                "prompt": task.prompt or "",
                "system_prompt": task.system_prompt or "",
                "session_id": task.session_id or "",
                "workspace_id": task.workspace_id or "",
            }
    return None


async def claim_assigned(
    node_id: str,
    *,
    task_id: str = "",
    delegation_id: str = "",
    attempt: int = 1,
) -> dict:
    """核对命令归属后，在同一事务里领取。重放返回同一次结果。"""
    if not task_id and not delegation_id:
        raise ClaimError("task_id or delegation_id required", 400)
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        task, delegation, existing = await _authorize_claim(
            session,
            node_id=node_id,
            task_id=task_id,
            delegation_id=delegation_id,
            attempt=attempt,
        )
        resolved_task = task.id if task is not None else (delegation.task_id if delegation else task_id)
        resolved_delegation = delegation.id if delegation is not None else delegation_id
        if existing is not None:
            logger.info(
                "command claim replay node_id=%s task_id=%s delegation_id=%s attempt=%s",
                node_id,
                resolved_task,
                resolved_delegation,
                attempt,
            )
            return {
                "accepted": False,
                "task_id": resolved_task,
                "delegation_id": resolved_delegation,
                "attempt": attempt,
                "status": "duplicate",
            }
        session.add(
            ExecutionRecord(
                id=str(uuid.uuid4()),
                task_id=resolved_task,
                owner_center_id=ident.center_id,
                delegation_id=resolved_delegation,
                node_id=node_id,
                attempt=attempt,
                dedupe_key=_dedupe_key(resolved_task, resolved_delegation, attempt),
                status="accepted",
            )
        )
        if delegation is not None and delegation.delivery_status == "pending":
            delegation.delivery_status = "acknowledged"
            delegation.updated_at = _now()
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info(
                "command claim duplicate node_id=%s task_id=%s attempt=%s",
                node_id,
                resolved_task,
                attempt,
            )
            return {
                "accepted": False,
                "task_id": resolved_task,
                "delegation_id": resolved_delegation,
                "attempt": attempt,
                "status": "duplicate",
            }
    logger.info(
        "command claim accepted node_id=%s task_id=%s delegation_id=%s attempt=%s",
        node_id,
        resolved_task,
        resolved_delegation,
        attempt,
    )
    return {
        "accepted": True,
        "task_id": resolved_task,
        "delegation_id": resolved_delegation,
        "attempt": attempt,
        "status": "accepted",
    }


async def _command_completed(session, task: TaskRecord | None, delegation_id: str, attempt: int) -> bool:
    if task is not None and task.status in _CLOSED_TASK:
        return True
    task_id = task.id if task is not None else ""
    existing = await _execution_by_key(session, _dedupe_key(task_id, delegation_id, attempt))
    return bool(existing and existing.status in _TERMINAL_EXECUTION)


async def record_command_ack(
    node_id: str,
    *,
    task_id: str = "",
    delegation_id: str = "",
    attempt: int = 1,
) -> dict:
    """持久化命令确认。同一节点对同一命令的重放返回同一结果。"""
    factory = get_session_factory()
    key = _ack_key(node_id, task_id, delegation_id, attempt)
    async with factory() as session:
        prior = (
            await session.execute(select(CommandAckRecord).where(CommandAckRecord.dedupe_key == key))
        ).scalar_one_or_none()
        if prior is not None:
            task = await session.get(TaskRecord, prior.task_id) if prior.task_id else None
            completed = bool(task and task.status in _CLOSED_TASK)
            logger.info(
                "command ack replay node_id=%s task_id=%s attempt=%s completed=%s",
                node_id,
                prior.task_id,
                attempt,
                completed,
            )
            return {
                "acked": True,
                "node_id": node_id,
                "means": "persisted",
                "completed": completed,
            }
        task, _delegation, _existing = await _authorize_claim(
            session,
            node_id=node_id,
            task_id=task_id,
            delegation_id=delegation_id,
            attempt=attempt,
        )
        resolved_task = task.id if task is not None else task_id
        completed = await _command_completed(session, task, delegation_id, attempt)
        session.add(
            CommandAckRecord(
                id=str(uuid.uuid4()),
                dedupe_key=key,
                node_id=node_id,
                task_id=resolved_task,
                delegation_id=delegation_id,
                attempt=attempt,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        logger.info(
            "command ack persisted node_id=%s task_id=%s delegation_id=%s attempt=%s completed=%s",
            node_id,
            resolved_task,
            delegation_id,
            attempt,
            completed,
        )
        return {
            "acked": True,
            "node_id": node_id,
            "means": "persisted",
            "completed": completed,
        }


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


_DELIVERY_ACKS = {"received", "applied", "result_persisted"}


async def renew_lease(execution_id: str, *, generation: int | None = None) -> dict:
    """续约租约。generation 不匹配则拒绝（fencing）。"""
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            raise ClaimError("execution not found", 404)
        current = int(row.assignment_generation or 1)
        if generation is not None and int(generation) != current:
            logger.info(
                "lease rejected stale generation execution_id=%s got=%s want=%s",
                execution_id,
                generation,
                current,
            )
            raise ClaimError("stale assignment generation", 409)
        row.lease_expires_at = _now() + LEASE_TTL
        row.updated_at = _now()
        await session.commit()
        return {
            "execution_id": execution_id,
            "assignment_generation": current,
            "lease_expires_at": row.lease_expires_at.isoformat() + "Z",
        }


async def bump_generation(execution_id: str) -> int:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            raise ClaimError("execution not found", 404)
        row.assignment_generation = int(row.assignment_generation or 1) + 1
        row.lease_expires_at = _now() + LEASE_TTL
        row.updated_at = _now()
        gen = row.assignment_generation
        await session.commit()
    logger.info("execution generation bumped id=%s gen=%s", execution_id, gen)
    return gen


async def set_delivery_ack(
    execution_id: str,
    ack: str,
    *,
    generation: int | None = None,
) -> None:
    """ACK 三分：received → applied → result_persisted。迟到旧代次拒绝。"""
    if ack not in _DELIVERY_ACKS:
        raise ClaimError("invalid delivery_ack", 400)
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            raise ClaimError("execution not found", 404)
        current = int(row.assignment_generation or 1)
        if generation is not None and int(generation) != current:
            raise ClaimError("stale assignment generation", 409)
        if row.lease_expires_at and row.lease_expires_at < _now() and ack != "result_persisted":
            # 租约过期仍允许结果落盘对账，但拒绝新 applied
            if ack == "applied":
                raise ClaimError("lease expired", 409)
        row.delivery_ack = ack
        row.updated_at = _now()
        await session.commit()
    logger.info("delivery_ack execution_id=%s ack=%s", execution_id, ack)


async def reject_stale_write(
    execution_id: str,
    *,
    generation: int,
) -> None:
    """迟到回写入口：代次不符即拒绝。"""
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            raise ClaimError("execution not found", 404)
        if int(generation) != int(row.assignment_generation or 1):
            raise ClaimError("stale assignment generation", 409)


async def finish_execution(
    node_id: str,
    *,
    task_id: str,
    execution_id: str = "",
    status: str,
    output: str = "",
    error: str = "",
    session_id: str = "",
    duration_ms: int = 0,
    generation: int | None = None,
) -> dict:
    """Node Agent 回写结果。代次不符则拒绝（迟到回写）。"""
    if status not in {"completed", "failed", "cancelled", "timeout"}:
        raise ClaimError("status must be completed|failed|cancelled|timeout", 400)
    exec_status = {
        "completed": "succeeded",
        "failed": "failed",
        "cancelled": "stopped",
        "timeout": "interrupted",
    }[status]
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(TaskRecord, task_id)
        if task is None:
            raise ClaimError("task not found", 404)
        if (task.node_id or "") and task.node_id != node_id:
            raise ClaimError("task belongs to another node", 403)
        row = None
        if execution_id:
            row = await session.get(ExecutionRecord, execution_id)
        if row is None:
            row = (
                await session.execute(
                    select(ExecutionRecord)
                    .where(ExecutionRecord.task_id == task_id)
                    .order_by(ExecutionRecord.created_at.desc())
                )
            ).scalars().first()
        if row is not None:
            if row.node_id and row.node_id != node_id:
                raise ClaimError("execution belongs to another node", 403)
            current = int(row.assignment_generation or 1)
            if generation is not None and int(generation) != current:
                raise ClaimError("stale assignment generation", 409)
            row.status = exec_status
            row.delivery_ack = "result_persisted"
            row.updated_at = _now()
        if task.status in _CLOSED_TASK and task.status == status:
            return {"task_id": task_id, "status": task.status, "duplicate": True}
        if task.status in _CLOSED_TASK:
            raise ClaimError(f"task already finished: {task.status}", 409)
        task.status = status
        task.output = output or ""
        task.error = error or ""
        if session_id:
            task.session_id = session_id
        task.duration_ms = int(duration_ms or 0)
        task.updated_at = _now()
        await session.commit()
    logger.info(
        "execution finished node_id=%s task_id=%s status=%s generation=%s",
        node_id,
        task_id,
        status,
        generation,
    )
    return {"task_id": task_id, "execution_id": execution_id, "status": status}
