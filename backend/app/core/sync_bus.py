"""可靠消息收件箱和发件箱。业务写入和 outbox 用同一个会话提交。"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.autonomy_state import ProtocolError, accept_protocol
from app.core.privacy import payload_hash, redact_for_sync
from app.models.db import InboxRecord, OutboxRecord, get_session_factory

logger = logging.getLogger(__name__)


class SyncConflict(ValueError):
    pass


def envelope(
    *,
    message_type: str,
    source_node_id: str,
    target_center_id: str,
    owner_center_id: str,
    task_id: str = "",
    delegation_id: str = "",
    execution_id: str = "",
    attempt: int = 1,
    sequence: int = 1,
    trace_id: str = "",
    payload: dict | None = None,
    message_id: str = "",
) -> dict[str, Any]:
    return {
        "protocol_version": 2,
        "message_id": message_id or str(uuid.uuid4()),
        "type": message_type,
        "source_node_id": source_node_id,
        "target_center_id": target_center_id,
        "owner_center_id": owner_center_id,
        "task_id": task_id,
        "delegation_id": delegation_id,
        "execution_id": execution_id,
        "attempt": attempt,
        "sequence": sequence,
        "trace_id": trace_id or str(uuid.uuid4()),
        "payload": payload or {},
    }


async def enqueue(session: AsyncSession, message: dict) -> None:
    accept_protocol(message.get("protocol_version", 2))
    session.add(
        OutboxRecord(
            message_id=message["message_id"],
            target_center_id=message.get("target_center_id") or "",
            message_type=message.get("type") or "",
            payload_json=json.dumps(message, ensure_ascii=False),
            acked=0,
        )
    )


async def ingest(message: dict, *, authenticated_node_id: str) -> dict:
    """同一事务写去重记录。重复 message_id 只确认，不重复应用。"""
    try:
        accept_protocol(message.get("protocol_version", 0))
    except ProtocolError as exc:
        raise SyncConflict(str(exc)) from exc
    source = message.get("source_node_id") or ""
    if source != authenticated_node_id:
        raise SyncConflict("source does not match authenticated node")
    message_id = message.get("message_id") or ""
    if not message_id:
        raise SyncConflict("message_id required")
    body = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    visibility = str(body.get("visibility") or "private")
    stored = dict(message)
    stored["payload"] = redact_for_sync(body, visibility)
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(select(InboxRecord).where(InboxRecord.message_id == message_id))
        ).scalar_one_or_none()
        if existing:
            logger.info("inbox duplicate message_id=%s", message_id)
            return {"message_id": message_id, "status": "duplicate"}
        digest = payload_hash(stored["payload"])
        prior = (
            await session.execute(
                select(InboxRecord).where(InboxRecord.message_type == f"idem:{message.get('idempotency_key') or ''}")
            )
        ).scalar_one_or_none()
        idem = str(message.get("idempotency_key") or "")
        if idem and prior and prior.payload_json and digest not in prior.payload_json:
            raise SyncConflict("idempotency key reused with different content")
        session.add(
            InboxRecord(
                message_id=message_id,
                source_node_id=source,
                message_type=message.get("type") or "",
                payload_json=json.dumps({"hash": digest, "body": stored["payload"]}, ensure_ascii=False),
                acked=1,
            )
        )
        if idem:
            session.add(
                InboxRecord(
                    message_id=f"idem:{idem}:{message_id}",
                    source_node_id=source,
                    message_type=f"idem:{idem}",
                    payload_json=digest,
                    acked=1,
                )
            )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"message_id": message_id, "status": "duplicate"}
    logger.info(
        "inbox acked message_id=%s source=%s type=%s",
        message_id,
        source,
        message.get("type"),
    )
    return {"message_id": message_id, "status": "acked"}


async def pending_outbox(limit: int = 50) -> list[dict]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(OutboxRecord).where(OutboxRecord.acked == 0).order_by(OutboxRecord.id).limit(limit)
            )
        ).scalars().all()
        items = []
        for row in rows:
            try:
                items.append(json.loads(row.payload_json or "{}"))
            except json.JSONDecodeError:
                continue
        return items


async def ack_outbox(message_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(select(OutboxRecord).where(OutboxRecord.message_id == message_id))
        ).scalar_one_or_none()
        if row is None:
            return
        row.acked = 1
        await session.commit()
    logger.info("outbox acked message_id=%s", message_id)
