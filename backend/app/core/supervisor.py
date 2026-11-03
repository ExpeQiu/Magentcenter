"""确定性 Supervisor：投递年龄、租约、unknown 执行 → Attention。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.db import AttentionRecord, ExecutionRecord, OutboxRecord, get_session_factory

logger = logging.getLogger(__name__)

_OUTBOX_AGE = timedelta(minutes=10)
_LEASE_GRACE = timedelta(minutes=1)


def _now() -> datetime:
    return datetime.utcnow()


async def _open_attention(
    *,
    dedupe_key: str,
    kind: str,
    summary: str,
    work_item_id: str = "",
    task_id: str = "",
    execution_id: str = "",
) -> None:
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(AttentionRecord).where(
                    AttentionRecord.dedupe_key == dedupe_key,
                    AttentionRecord.status == "open",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(
            AttentionRecord(
                id=str(uuid.uuid4()),
                dedupe_key=dedupe_key,
                kind=kind,
                summary=summary,
                work_item_id=work_item_id,
                task_id=task_id,
                execution_id=execution_id,
                status="open",
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return
    logger.info("attention open kind=%s key=%s", kind, dedupe_key)


async def run_once() -> dict:
    opened = 0
    factory = get_session_factory()
    async with factory() as session:
        pending = (
            await session.execute(
                select(OutboxRecord).where(OutboxRecord.acked == 0).limit(50)
            )
        ).scalars().all()
        cutoff = _now() - _OUTBOX_AGE
        for row in pending:
            if row.created_at and row.created_at < cutoff:
                key = f"outbox_age:{row.message_id}"
                await _open_attention(
                    dedupe_key=key,
                    kind="outbox_age",
                    summary=f"发件箱消息过久未确认: {row.message_id}",
                )
                opened += 1

        live = (
            await session.execute(
                select(ExecutionRecord).where(
                    ExecutionRecord.status.in_(
                        {"accepted", "starting", "running", "unknown"}
                    )
                )
            )
        ).scalars().all()
        for row in live:
            if row.status == "unknown":
                key = f"exec_unknown:{row.id}"
                await _open_attention(
                    dedupe_key=key,
                    kind="execution_unknown",
                    summary=f"执行无法核验: {row.id}",
                    task_id=row.task_id or "",
                    execution_id=row.id,
                )
                opened += 1
            elif row.lease_expires_at and row.lease_expires_at < _now() - _LEASE_GRACE:
                key = f"lease_expired:{row.id}:{row.assignment_generation}"
                await _open_attention(
                    dedupe_key=key,
                    kind="lease_expired",
                    summary=f"执行租约过期: {row.id}",
                    task_id=row.task_id or "",
                    execution_id=row.id,
                )
                opened += 1

    # 语义 Watchdog 占位：本阶段不扩权，只记日志
    if opened:
        logger.info("supervisor tick opened=%s", opened)
    return {"opened": opened}


async def list_open(limit: int = 50) -> list[dict]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(AttentionRecord)
                .where(AttentionRecord.status == "open")
                .order_by(AttentionRecord.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "summary": r.summary,
                "task_id": r.task_id,
                "execution_id": r.execution_id,
                "work_item_id": r.work_item_id,
            }
            for r in rows
        ]
