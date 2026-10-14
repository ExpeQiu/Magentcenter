"""运行观察。未知执行、未确认消息和磁盘空间分开计数。"""

from __future__ import annotations

import shutil
from datetime import datetime

from sqlalchemy import func, select

from app.models.db import ExecutionRecord, InboxRecord, OutboxRecord, TaskRecord, get_session_factory
from app.paths import data_dir


async def snapshot() -> dict:
    factory = get_session_factory()
    async with factory() as session:
        unknown = (
            await session.execute(
                select(func.count()).select_from(ExecutionRecord).where(ExecutionRecord.status == "unknown")
            )
        ).scalar_one()
        unacked = (
            await session.execute(
                select(func.count()).select_from(OutboxRecord).where(OutboxRecord.acked == 0)
            )
        ).scalar_one()
        oldest = (
            await session.execute(
                select(func.min(OutboxRecord.created_at)).where(OutboxRecord.acked == 0)
            )
        ).scalar_one()
        queued = (
            await session.execute(
                select(func.count()).select_from(TaskRecord).where(TaskRecord.status == "queued")
            )
        ).scalar_one()
        inbox_dupes = (
            await session.execute(select(func.count()).select_from(InboxRecord))
        ).scalar_one()
    age = 0
    if isinstance(oldest, datetime):
        age = int((datetime.utcnow() - oldest).total_seconds())
    usage = shutil.disk_usage(data_dir())
    return {
        "queued_tasks": int(queued or 0),
        "unknown_executions": int(unknown or 0),
        "unacked_outbox": int(unacked or 0),
        "oldest_unacked_age_seconds": age,
        "inbox_messages": int(inbox_dupes or 0),
        "disk_free_bytes": int(usage.free),
        "disk_total_bytes": int(usage.total),
    }
