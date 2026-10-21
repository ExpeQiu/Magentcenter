"""可靠消息收件箱和发件箱。业务写入和 outbox 用同一个会话提交。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.autonomy_state import ProtocolError, accept_protocol
from app.core.identity import load_or_create_identity
from app.core.privacy import payload_hash, redact_for_sync
from app.models.db import (
    DelegationRecord,
    ExecutionRecord,
    InboxRecord,
    OutboxRecord,
    TaskRecord,
    get_session_factory,
)

logger = logging.getLogger(__name__)

_RESULT_STATUS = {
    "execution.completed": "completed",
    "execution.succeeded": "completed",
    "execution.failed": "failed",
    "execution.cancelled": "cancelled",
    "execution.timeout": "timeout",
}
_EXECUTION_STATUS = {
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "stopped",
    "timeout": "interrupted",
}
_TERMINAL_TASK = {"completed", "failed", "cancelled", "timeout"}
_TERMINAL_EXECUTION = {"succeeded", "failed", "stopped"}


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


def _result_status(message: dict, body: dict) -> str:
    kind = str(message.get("type") or "")
    if kind in _RESULT_STATUS:
        return _RESULT_STATUS[kind]
    if kind in {"execution.result", "result"}:
        status = str(body.get("status") or "")
        if status in _TERMINAL_TASK:
            return status
    return ""


async def _apply_message(session: AsyncSession, message: dict, node_id: str) -> str:
    """把收件箱事件应用到任务或执行。调用方和去重记录共用同一个事务。"""
    body = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    kind = str(message.get("type") or "")
    if kind == "delegation.created":
        delegation_id = str(message.get("delegation_id") or "")
        if not delegation_id:
            return "ignored"
        row = await session.get(DelegationRecord, delegation_id)
        if row is None:
            logger.info("inbox delegation missing delegation_id=%s", delegation_id)
            return "ignored"
        logger.info(
            "inbox delegation present delegation_id=%s status=%s",
            delegation_id,
            row.delivery_status,
        )
        return "applied"
    status = _result_status(message, body)
    if not status:
        return "ignored"
    task_id = str(message.get("task_id") or body.get("task_id") or "")
    if not task_id:
        return "ignored"
    task = await session.get(TaskRecord, task_id)
    if task is None:
        return "ignored"
    if task.node_id != node_id:
        raise SyncConflict("task belongs to another node")
    attempt = int(message.get("attempt") or body.get("attempt") or 1)
    delegation_id = str(message.get("delegation_id") or "")
    key = f"remote:{delegation_id or task_id}:{attempt}"
    execution = (
        await session.execute(select(ExecutionRecord).where(ExecutionRecord.dedupe_key == key))
    ).scalar_one_or_none()
    if execution is not None and execution.node_id and execution.node_id != node_id:
        raise SyncConflict("execution belongs to another node")
    others = (
        await session.execute(select(ExecutionRecord).where(ExecutionRecord.task_id == task_id))
    ).scalars().all()
    other_terminal = any(
        row.attempt != attempt and row.status in _TERMINAL_EXECUTION for row in others
    )
    if task.status in _TERMINAL_TASK or other_terminal:
        logger.info(
            "inbox kept terminal task_id=%s status=%s incoming=%s attempt=%s",
            task_id,
            task.status,
            status,
            attempt,
        )
        return "kept"
    if task.status not in {"queued", "running"}:
        return "kept"
    task.status = status
    if body.get("output"):
        task.output = str(body.get("output"))
    if body.get("error"):
        task.error = str(body.get("error"))
    task.updated_at = datetime.utcnow()
    if execution is not None and execution.status not in _TERMINAL_EXECUTION:
        execution.status = _EXECUTION_STATUS.get(status, execution.status)
        execution.updated_at = datetime.utcnow()
    logger.info(
        "inbox applied task_id=%s status=%s node_id=%s attempt=%s",
        task_id,
        status,
        node_id,
        attempt,
    )
    return "applied"


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
        applied = await _apply_message(session, message, source)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"message_id": message_id, "status": "duplicate"}
    logger.info(
        "inbox acked message_id=%s source=%s type=%s applied=%s",
        message_id,
        source,
        message.get("type"),
        applied,
    )
    return {"message_id": message_id, "status": "acked", "applied": applied}


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


async def bump_outbox_attempt(message_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(select(OutboxRecord).where(OutboxRecord.message_id == message_id))
        ).scalar_one_or_none()
        if row is None or row.acked:
            return
        row.attempts = int(row.attempts or 0) + 1
        await session.commit()
        logger.info("outbox retry message_id=%s attempts=%s", message_id, row.attempts)


async def dispatch_pending(limit: int = 50) -> dict:
    """本中心的发件在收件箱落地后确认。远端目标只记录重试，不假装已经送达。"""
    ident = load_or_create_identity()
    acked = 0
    waiting = 0
    for message in await pending_outbox(limit):
        message_id = str(message.get("message_id") or "")
        target = str(message.get("target_center_id") or "")
        if not message_id:
            continue
        if target and target != ident.center_id:
            await bump_outbox_attempt(message_id)
            waiting += 1
            logger.info("outbox waiting remote message_id=%s target=%s", message_id, target)
            continue
        source = str(message.get("source_node_id") or ident.node_id)
        try:
            await ingest(message, authenticated_node_id=source)
        except SyncConflict as exc:
            await bump_outbox_attempt(message_id)
            waiting += 1
            logger.warning("outbox apply rejected message_id=%s err=%s", message_id, exc)
            continue
        await ack_outbox(message_id)
        acked += 1
    if acked or waiting:
        logger.info("outbox dispatch acked=%s waiting=%s", acked, waiting)
    return {"acked": acked, "waiting": waiting}


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
