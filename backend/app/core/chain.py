"""跨设备信息链：对话、派发、推送、领取、回写落在同一张表。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.knowledge import redact_secrets
from app.models.db import ChainRecord, get_session_factory
from app.models.schemas import ChainEvent

logger = logging.getLogger(__name__)

_SUMMARY_LIMIT = 800


def _clip(text: str) -> str:
    text = redact_secrets(" ".join((text or "").split()))
    if len(text) <= _SUMMARY_LIMIT:
        return text
    return text[: _SUMMARY_LIMIT - 1] + "…"


def _detail(raw: dict[str, Any] | None) -> str:
    clean: dict[str, Any] = {}
    for key, value in (raw or {}).items():
        if "token" in key or "secret" in key or "key" in key:
            continue
        if isinstance(value, str):
            clean[key] = _clip(value)
        else:
            clean[key] = value
    return json.dumps(clean, ensure_ascii=False)


def _to_event(row: ChainRecord) -> ChainEvent:
    try:
        detail = json.loads(row.detail_json or "{}")
    except json.JSONDecodeError:
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    return ChainEvent(
        id=row.id,
        kind=row.kind or "",
        run_id=row.run_id or "",
        task_id=row.task_id or "",
        actor_id=row.actor_id or "",
        target_id=row.target_id or "",
        channel=row.channel or "",
        intent=row.intent or "",
        status=row.status or "",
        summary=row.summary or "",
        detail=detail,
        created_at=row.created_at or datetime.utcnow(),
    )


async def append_chain(
    *,
    kind: str,
    run_id: str = "",
    task_id: str = "",
    actor_id: str = "",
    target_id: str = "",
    channel: str = "",
    intent: str = "",
    status: str = "",
    summary: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """写入一条信息链。失败只记日志，不打断原来的请求。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = ChainRecord(
                kind=kind,
                run_id=run_id or "",
                task_id=task_id or "",
                actor_id=actor_id or "",
                target_id=target_id or "",
                channel=channel or "",
                intent=intent or "",
                status=status or "",
                summary=_clip(summary),
                detail_json=_detail(detail),
            )
            session.add(row)
            if kind == "turn" and intent == "confirm_create" and task_id and actor_id:
                prior = (
                    await session.execute(
                        select(ChainRecord)
                        .where(ChainRecord.actor_id == actor_id)
                        .where(ChainRecord.kind == "turn")
                        .where(ChainRecord.intent == "create_task")
                        .where(ChainRecord.task_id == "")
                        .order_by(ChainRecord.id.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if prior is not None:
                    prior.task_id = task_id
            await session.commit()
        logger.info(
            "chain kind=%s run_id=%s task_id=%s actor=%s target=%s intent=%s status=%s",
            kind,
            run_id or "-",
            task_id or "-",
            actor_id or "-",
            target_id or "-",
            intent or "-",
            status or "-",
        )
    except Exception:
        logger.exception(
            "chain append failed kind=%s task_id=%s actor=%s",
            kind,
            task_id or "-",
            actor_id or "-",
        )


async def list_chain(
    *,
    task_id: str = "",
    run_id: str = "",
    actor_id: str = "",
    limit: int = 200,
) -> list[ChainEvent]:
    limit = min(max(limit, 1), 500)
    factory = get_session_factory()
    async with factory() as session:
        q = select(ChainRecord)
        if task_id:
            q = q.where(ChainRecord.task_id == task_id)
        elif run_id:
            q = q.where(ChainRecord.run_id == run_id)
        elif actor_id:
            q = q.where(ChainRecord.actor_id == actor_id)
        else:
            return []
        q = q.order_by(ChainRecord.id.asc()).limit(limit)
        rows = (await session.execute(q)).scalars().all()
    return [_to_event(row) for row in rows]
