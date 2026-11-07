"""超级AI Panel：健康三问（要我做什么 / 系统是否健康 / 近期历史）。"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core import delivery as delivery_svc
from app.core import supervisor as attention_svc
from app.core.worker_slots import get_pool
from app.models.db import WorkItemRecord, get_session_factory

logger = logging.getLogger(__name__)


async def build_overview(*, settings=None, monitor=None) -> dict:
    attention = await attention_svc.list_open(limit=20)
    slots = get_pool(
        settings.execution_slots() if settings else None
    ).snapshot() if settings else get_pool().snapshot()

    issues: list[str] = []
    if slots["free"] == 0 and slots["active"] > 0:
        issues.append("worker_slots_full")
    pending_delivery = await delivery_svc.pending_count()
    if pending_delivery > 20:
        issues.append("delivery_backlog")

    health_ok = True
    health_detail: dict = {
        "mock_mode": bool(getattr(settings, "ai_mock_mode", False)) if settings else False,
        "slots": slots,
        "pending_deliveries": pending_delivery,
        "open_attention": len(attention),
    }
    if monitor is not None:
        try:
            status = await monitor.get_status() if hasattr(monitor, "get_status") else None
            if isinstance(status, dict):
                health_detail["monitor"] = {
                    k: status.get(k)
                    for k in ("openclaw", "hermes", "cron_errors", "gateway")
                    if k in status
                }
        except Exception:
            logger.exception("overview monitor snapshot failed")
            issues.append("monitor_unavailable")

    if issues:
        health_ok = False

    factory = get_session_factory()
    recent: list[dict] = []
    async with factory() as session:
        rows = (
            await session.execute(
                select(WorkItemRecord)
                .order_by(WorkItemRecord.updated_at.desc())
                .limit(8)
            )
        ).scalars().all()
        for r in rows:
            recent.append(
                {
                    "id": r.id,
                    "title": r.title or (r.goal or "")[:80],
                    "status": r.status,
                    "task_id": r.task_id or "",
                    "updated_at": r.updated_at.isoformat() + "Z" if r.updated_at else "",
                }
            )

    # 健康态：attention 空且无 issue → 紧凑摘要
    compact = (not attention) and health_ok
    logger.info(
        "overview built attention=%s health_ok=%s compact=%s slots=%s/%s",
        len(attention),
        health_ok,
        compact,
        slots["active"],
        slots["capacity"],
    )
    return {
        "compact": compact,
        "attention": attention,
        "health": {
            "ok": health_ok,
            "issues": issues,
            "detail": health_detail,
        },
        "recent": recent,
        "questions": {
            "need_me": "要我做什么？" if attention else "",
            "healthy": "系统是否正常？",
            "history": "最近工作",
        },
    }
