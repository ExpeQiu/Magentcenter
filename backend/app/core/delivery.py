"""沉默交付：同一 WorkItem 的 ack/result/attention 有序入 outbox，不刷 progress。"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Literal

from sqlalchemy import func, select

from app.core.identity import load_or_create_identity
from app.models.db import OutboxRecord, WorkItemRecord, get_session_factory

logger = logging.getLogger(__name__)

DeliveryKind = Literal["ack", "result", "blocked", "attention", "failed"]
_PUBLIC_KINDS = frozenset({"ack", "result", "blocked", "attention", "failed"})


async def _next_seq(session, work_item_id: str) -> int:
    prefix = f"wi:{work_item_id}:"
    rows = (
        await session.execute(
            select(OutboxRecord.message_id).where(OutboxRecord.message_id.like(f"{prefix}%"))
        )
    ).scalars().all()
    best = 0
    for mid in rows:
        parts = (mid or "").split(":")
        # wi:{id}:{seq}:{kind}
        if len(parts) >= 4:
            try:
                best = max(best, int(parts[2]))
            except ValueError:
                continue
    return best + 1


async def enqueue(
    *,
    kind: DeliveryKind,
    work_item_id: str = "",
    task_id: str = "",
    summary: str = "",
    payload: dict | None = None,
    target_center_id: str = "",
) -> str | None:
    """progress 类直接丢弃；仅公开 kind 入队。"""
    if kind not in _PUBLIC_KINDS:
        logger.debug("delivery skip non-public kind=%s", kind)
        return None
    ident = load_or_create_identity()
    factory = get_session_factory()
    wid = (work_item_id or "").strip()
    async with factory() as session:
        if not wid and task_id:
            work = (
                await session.execute(
                    select(WorkItemRecord).where(WorkItemRecord.task_id == task_id)
                )
            ).scalar_one_or_none()
            if work is not None:
                wid = work.id
        if not wid:
            wid = f"task:{(task_id or uuid.uuid4().hex)[:36]}"
        seq = await _next_seq(session, wid)
        message_id = f"wi:{wid}:{seq}:{kind}"
        body = {
            "kind": kind,
            "work_item_id": work_item_id or "",
            "task_id": task_id or "",
            "summary": (summary or "")[:2000],
            "seq": seq,
            **(payload or {}),
        }
        session.add(
            OutboxRecord(
                message_id=message_id,
                target_center_id=target_center_id or ident.center_id,
                message_type=f"delivery.{kind}",
                payload_json=json.dumps(body, ensure_ascii=False),
                acked=0,
                attempts=0,
            )
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("delivery enqueue failed message_id=%s", message_id)
            return None
    logger.info(
        "delivery enqueued kind=%s work_item=%s task=%s message_id=%s",
        kind,
        (work_item_id or "-")[:12],
        (task_id or "-")[:12],
        message_id,
    )
    return message_id


async def list_for_work_item(work_item_id: str, *, include_acked: bool = False) -> list[dict]:
    wid = (work_item_id or "").strip()
    if not wid:
        return []
    prefix = f"wi:{wid}:"
    factory = get_session_factory()
    async with factory() as session:
        q = select(OutboxRecord).where(OutboxRecord.message_id.like(f"{prefix}%"))
        if not include_acked:
            q = q.where(OutboxRecord.acked == 0)
        rows = (
            await session.execute(q.order_by(OutboxRecord.id.asc()))
        ).scalars().all()
        items = []
        for r in rows:
            try:
                payload = json.loads(r.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            items.append(
                {
                    "message_id": r.message_id,
                    "message_type": r.message_type,
                    "acked": bool(r.acked),
                    "payload": payload,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
            )
        return items


async def ack(message_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(OutboxRecord).where(OutboxRecord.message_id == message_id)
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.acked = 1
        await session.commit()
    logger.info("delivery acked message_id=%s", message_id)
    return True


async def pending_count() -> int:
    factory = get_session_factory()
    async with factory() as session:
        n = (
            await session.execute(
                select(func.count())
                .select_from(OutboxRecord)
                .where(
                    OutboxRecord.acked == 0,
                    OutboxRecord.message_type.like("delivery.%"),
                )
            )
        ).scalar_one()
        return int(n or 0)
