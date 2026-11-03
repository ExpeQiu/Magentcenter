"""Mandate：工作级授权快照 ≤ Grant。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

from app.models.db import MandateRecord, get_session_factory

logger = logging.getLogger(__name__)


async def issue(
    work_item_id: str,
    *,
    issued_by: str = "local",
    scope: dict | None = None,
    permitted_actions: list[str] | None = None,
    budget: dict | None = None,
    ttl_seconds: int = 86400,
    policy_version: int = 1,
) -> str:
    mid = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(seconds=max(60, ttl_seconds))
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            MandateRecord(
                id=mid,
                work_item_id=work_item_id,
                issued_by=issued_by,
                scope_json=json.dumps(scope or {}, ensure_ascii=False),
                permitted_actions=json.dumps(permitted_actions or ["task.execute"], ensure_ascii=False),
                budget_json=json.dumps(budget or {}, ensure_ascii=False),
                policy_version=policy_version,
                status="active",
                expires_at=expires,
            )
        )
        await session.commit()
    logger.info("mandate issued id=%s work_item=%s", mid, work_item_id)
    return mid


async def revoke(mandate_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(MandateRecord, mandate_id)
        if row is None:
            return False
        row.status = "revoked"
        await session.commit()
    logger.info("mandate revoked id=%s", mandate_id)
    return True


async def is_action_allowed(work_item_id: str, action: str) -> bool:
    from sqlalchemy import select

    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(MandateRecord).where(
                    MandateRecord.work_item_id == work_item_id,
                    MandateRecord.status == "active",
                )
            )
        ).scalars().all()
        now = datetime.utcnow()
        for row in rows:
            if row.expires_at and row.expires_at < now:
                continue
            try:
                actions = json.loads(row.permitted_actions or "[]")
            except json.JSONDecodeError:
                actions = []
            if action in actions or "*" in actions:
                return True
    return False
