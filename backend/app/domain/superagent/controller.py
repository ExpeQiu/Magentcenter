"""WorkController：会话归属、follow-up 扇出、不重复建单。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select

from app.models.db import ConversationRecord, WorkItemRecord, get_session_factory

logger = logging.getLogger(__name__)

_ACTIVE = {"ready", "active"}


@dataclass
class FollowupOwner:
    work_item_id: str
    task_id: str
    conversation_id: str
    goal: str
    status: str


async def resolve_followup(
    *,
    session_id: str = "",
    conversation_id: str = "",
    work_item_id: str = "",
) -> FollowupOwner | None:
    """若会话已有未结束 WorkItem，后续消息归属该单。"""
    factory = get_session_factory()
    async with factory() as session:
        wid = (work_item_id or "").strip()
        if not wid and conversation_id:
            conv = await session.get(ConversationRecord, conversation_id)
            if conv is not None:
                wid = (conv.active_work_item_id or "").strip()
        if not wid and session_id:
            # 会话 id 常与 conversation 对齐；也按 conversation 主键查
            conv = await session.get(ConversationRecord, session_id)
            if conv is not None:
                wid = (conv.active_work_item_id or "").strip()
        if not wid:
            return None
        row = await session.get(WorkItemRecord, wid)
        if row is None:
            return None
        if (row.status or "") not in _ACTIVE:
            return None
        return FollowupOwner(
            work_item_id=row.id,
            task_id=row.task_id or "",
            conversation_id=row.conversation_id or conversation_id or session_id,
            goal=row.goal or row.title or "",
            status=row.status or "",
        )


async def bind_conversation(conversation_id: str, work_item_id: str) -> None:
    cid = (conversation_id or "").strip()
    wid = (work_item_id or "").strip()
    if not cid or not wid:
        return
    factory = get_session_factory()
    async with factory() as session:
        conv = await session.get(ConversationRecord, cid)
        if conv is None:
            return
        conv.active_work_item_id = wid
        work = await session.get(WorkItemRecord, wid)
        if work is not None:
            work.conversation_id = cid
        await session.commit()
    logger.info("controller bind conversation=%s work_item=%s", cid[:12], wid[:12])


async def attach_followup(
    work_item_id: str,
    *,
    note: str,
) -> FollowupOwner | None:
    """把修订/追问记到 WorkItem goal，不新建 Task。"""
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(WorkItemRecord, work_item_id)
        if row is None or (row.status or "") not in _ACTIVE:
            return None
        note = (note or "").strip()
        if note:
            prev = (row.goal or "").strip()
            row.goal = f"{prev}\n\n[follow-up] {note}".strip() if prev else note
            row.requirement_revision = int(row.requirement_revision or 1) + 1
            row.state_version = int(row.state_version or 1) + 1
            await session.commit()
        owner = FollowupOwner(
            work_item_id=row.id,
            task_id=row.task_id or "",
            conversation_id=row.conversation_id or "",
            goal=row.goal or "",
            status=row.status or "",
        )
    logger.info(
        "controller attach work_item=%s revision_note_len=%s",
        work_item_id[:12],
        len(note),
    )
    return owner


async def list_active_for_workspace(workspace_id: str, limit: int = 20) -> list[FollowupOwner]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkItemRecord)
                .where(
                    WorkItemRecord.workspace_id == (workspace_id or "cyber"),
                    WorkItemRecord.status.in_(list(_ACTIVE)),
                )
                .order_by(WorkItemRecord.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [
            FollowupOwner(
                work_item_id=r.id,
                task_id=r.task_id or "",
                conversation_id=r.conversation_id or "",
                goal=r.goal or r.title or "",
                status=r.status or "",
            )
            for r in rows
        ]


def looks_like_new_work(text: str) -> bool:
    """明确「新建」才打断 follow-up 归属。"""
    raw = (text or "").strip()
    cues = ("新建任务", "另建", "另外做", "新开一个", "帮我建一个任务", "再开一个任务")
    return any(c in raw for c in cues)
