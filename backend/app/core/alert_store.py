"""告警持久化读写。"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select

from app.models.db import AlertRecord, get_session_factory

logger = logging.getLogger(__name__)


async def save_alert(
    *,
    at: str,
    kind: str,
    count: int,
    sent: bool,
    jobs: list[str],
) -> int:
    factory = get_session_factory()
    async with factory() as session:
        rec = AlertRecord(
            at=at,
            kind=kind,
            count=count,
            sent=1 if sent else 0,
            jobs_json=json.dumps(jobs, ensure_ascii=False),
        )
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        logger.info(
            "alert persisted id=%s kind=%s count=%s sent=%s",
            rec.id,
            kind,
            count,
            sent,
        )
        return rec.id


async def load_recent_alerts(limit: int = 40) -> list[dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(AlertRecord)
                .order_by(AlertRecord.id.desc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars().all()
    out: list[dict[str, Any]] = []
    for r in reversed(rows):
        try:
            jobs = json.loads(r.jobs_json or "[]")
        except json.JSONDecodeError:
            jobs = []
        if not isinstance(jobs, list):
            jobs = []
        out.append(
            {
                "at": r.at,
                "kind": r.kind,
                "count": r.count,
                "sent": bool(r.sent),
                "jobs": [str(j) for j in jobs],
            }
        )
    return out
