"""WorkItem 最小主线：长期工作与 Task 关联。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.identity import load_or_create_identity
from app.models.db import (
    ConversationMessageRecord,
    ConversationRecord,
    TriggerRecord,
    WorkItemRecord,
    get_session_factory,
)

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.utcnow()


async def ensure_conversation(
    conversation_id: str,
    *,
    workspace_id: str = "cyber",
    title: str = "",
) -> str:
    cid = (conversation_id or "").strip() or str(uuid.uuid4())
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ConversationRecord, cid)
        if row is None:
            session.add(
                ConversationRecord(
                    id=cid,
                    workspace_id=workspace_id or "cyber",
                    owner_center_id=ident.center_id,
                    title=title or "",
                )
            )
            await session.commit()
            logger.info("conversation created id=%s workspace=%s", cid, workspace_id)
        return cid


async def append_message(
    conversation_id: str,
    *,
    role: str,
    content: str,
    actor_id: str = "",
    channel: str = "",
    work_item_id: str = "",
    task_id: str = "",
    idempotency_key: str = "",
) -> str:
    mid = str(uuid.uuid4())
    key = (idempotency_key or "").strip() or mid
    factory = get_session_factory()
    async with factory() as session:
        if idempotency_key:
            existing = (
                await session.execute(
                    select(ConversationMessageRecord).where(
                        ConversationMessageRecord.conversation_id == conversation_id,
                        ConversationMessageRecord.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing.id
        session.add(
            ConversationMessageRecord(
                id=mid,
                conversation_id=conversation_id,
                role=role,
                content=content or "",
                actor_id=actor_id,
                channel=channel,
                work_item_id=work_item_id,
                task_id=task_id,
                idempotency_key=key,
            )
        )
        conv = await session.get(ConversationRecord, conversation_id)
        if conv is not None:
            conv.updated_at = _now()
            if work_item_id:
                conv.active_work_item_id = work_item_id
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = (
                await session.execute(
                    select(ConversationMessageRecord).where(
                        ConversationMessageRecord.conversation_id == conversation_id,
                        ConversationMessageRecord.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                return existing.id
            raise
    return mid


async def list_conversation_messages(conversation_id: str, limit: int = 40) -> list[dict]:
    cid = (conversation_id or "").strip()
    if not cid:
        return []
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(ConversationMessageRecord)
                .where(ConversationMessageRecord.conversation_id == cid)
                .order_by(ConversationMessageRecord.created_at.asc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars().all()
        return [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content or "",
                "task_id": r.task_id or "",
                "channel": r.channel or "",
            }
            for r in rows
        ]


async def record_trigger(
    *,
    source: str,
    external_event_id: str,
    workspace_id: str = "cyber",
    owner_id: str = "local",
    kind: str = "message",
    payload: dict | None = None,
    conversation_id: str = "",
) -> str | None:
    """返回 trigger id；同键已存在则返回 None（调用方应视为去重命中）。"""
    import json

    tid = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            TriggerRecord(
                id=tid,
                owner_id=owner_id or "local",
                workspace_id=workspace_id or "cyber",
                source=source,
                external_event_id=external_event_id,
                kind=kind,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
                conversation_id=conversation_id,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info(
                "trigger deduped source=%s external=%s", source, external_event_id
            )
            return None
    logger.info("trigger recorded id=%s source=%s", tid, source)
    return tid


async def create_work_item(
    *,
    title: str,
    goal: str,
    workspace_id: str = "cyber",
    conversation_id: str = "",
    task_id: str = "",
) -> str:
    ident = load_or_create_identity()
    wid = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            WorkItemRecord(
                id=wid,
                owner_center_id=ident.center_id,
                workspace_id=workspace_id or "cyber",
                conversation_id=conversation_id,
                title=title or (goal[:80] if goal else "work"),
                goal=goal or "",
                status="ready",
                task_id=task_id,
            )
        )
        if conversation_id:
            conv = await session.get(ConversationRecord, conversation_id)
            if conv is not None:
                conv.active_work_item_id = wid
                conv.updated_at = _now()
        await session.commit()
    try:
        from app.domain.superagent import mandate as mandate_svc

        await mandate_svc.issue(
            wid,
            issued_by="local",
            permitted_actions=["task.execute", "task.cancel", "artifact.accept"],
            policy_version=1,
        )
    except Exception:
        logger.exception("mandate issue failed work_item=%s", wid)
    logger.info(
        "work_item created id=%s task_id=%s conversation=%s",
        wid,
        task_id,
        conversation_id,
    )
    return wid


async def bind_task(work_item_id: str, task_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(WorkItemRecord, work_item_id)
        if row is None:
            return
        row.task_id = task_id
        row.status = "active"
        row.updated_at = _now()
        await session.commit()


async def accept_work_item(work_item_id: str, artifact_id: str = "") -> bool:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(WorkItemRecord, work_item_id)
        if row is None:
            return False
        row.status = "accepted"
        row.accepted_artifact_id = artifact_id or row.accepted_artifact_id
        row.state_version = int(row.state_version or 1) + 1
        row.updated_at = _now()
        await session.commit()
    logger.info("work_item accepted id=%s", work_item_id)
    return True


def _work_dict(row: WorkItemRecord) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "goal": row.goal,
        "status": row.status,
        "wait_reason": row.wait_reason,
        "task_id": row.task_id,
        "conversation_id": row.conversation_id,
        "workspace_id": row.workspace_id,
        "owner_center_id": row.owner_center_id,
        "requirement_revision": row.requirement_revision,
        "state_version": row.state_version,
        "accepted_artifact_id": row.accepted_artifact_id,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else "",
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else "",
    }


async def get_work_item(work_item_id: str) -> dict | None:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(WorkItemRecord, work_item_id)
        if row is None:
            return None
        return _work_dict(row)


async def list_work_items(
    *,
    workspace_id: str = "",
    status: str = "",
    limit: int = 50,
) -> list[dict]:
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(WorkItemRecord).order_by(WorkItemRecord.updated_at.desc()).limit(
            max(1, min(limit, 200))
        )
        if workspace_id:
            stmt = stmt.where(WorkItemRecord.workspace_id == workspace_id)
        if status:
            stmt = stmt.where(WorkItemRecord.status == status)
        rows = (await session.execute(stmt)).scalars().all()
        return [_work_dict(r) for r in rows]
