"""服务端确认单。客户端只回传确认标识，重复确认返回同一个任务。"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.db import ConfirmationRecord, DeviceTaskLinkRecord, get_session_factory

logger = logging.getLogger(__name__)


class ConfirmationError(ValueError):
    pass


def content_hash(summary: str, target: dict) -> str:
    raw = json.dumps({"summary": summary, "target": target}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


async def issue_confirmation(
    *,
    subject_id: str,
    session_id: str,
    summary: str,
    target: dict,
    scope: str = "local",
    ttl_seconds: int = 600,
) -> str:
    confirmation_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            ConfirmationRecord(
                id=confirmation_id,
                subject_id=subject_id,
                session_id=session_id,
                summary=summary,
                content_hash=content_hash(summary, target),
                target_json=json.dumps(target, ensure_ascii=False),
                scope=scope,
                expires_at=datetime.utcnow() + timedelta(seconds=ttl_seconds),
            )
        )
        await session.commit()
    logger.info(
        "confirmation issued confirmation_id=%s subject=%s session=%s",
        confirmation_id,
        subject_id,
        session_id,
    )
    return confirmation_id


async def confirm(
    confirmation_id: str,
    *,
    subject_id: str,
    session_id: str,
    presented_hash: str = "",
) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ConfirmationRecord, confirmation_id)
        if row is None:
            raise ConfirmationError("confirmation not found")
        if row.subject_id and subject_id and row.subject_id != subject_id:
            raise ConfirmationError("confirmation subject mismatch")
        if row.session_id and session_id and row.session_id != session_id:
            raise ConfirmationError("cross-session confirmation rejected")
        if row.expires_at and row.expires_at < datetime.utcnow() and not row.task_id:
            raise ConfirmationError("confirmation expired")
        if presented_hash and presented_hash != row.content_hash:
            raise ConfirmationError("task content changed; confirm again")
        if row.task_id:
            logger.info(
                "confirmation reused confirmation_id=%s task_id=%s",
                confirmation_id,
                row.task_id,
            )
            return {"task_id": row.task_id, "created": False, "target": json.loads(row.target_json or "{}")}
        target = json.loads(row.target_json or "{}")
        return {
            "task_id": "",
            "created": True,
            "target": target,
            "summary": row.summary,
            "confirmation_id": row.id,
        }


async def attach_task(confirmation_id: str, task_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(ConfirmationRecord, confirmation_id)
        if row is None:
            return
        if row.task_id and row.task_id != task_id:
            return
        row.task_id = task_id
        await session.commit()
    logger.info("confirmation consumed confirmation_id=%s task_id=%s", confirmation_id, task_id)


async def bind_device_task(device_id: str, task_id: str, session_id: str = "") -> None:
    if not device_id or not task_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(DeviceTaskLinkRecord).where(
                    DeviceTaskLinkRecord.device_id == device_id,
                    DeviceTaskLinkRecord.task_id == task_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return
        session.add(
            DeviceTaskLinkRecord(device_id=device_id, task_id=task_id, session_id=session_id)
        )
        await session.commit()
    logger.info("device task linked device=%s task_id=%s", device_id, task_id)


async def device_can_read(device_id: str, task_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(DeviceTaskLinkRecord).where(
                    DeviceTaskLinkRecord.device_id == device_id,
                    DeviceTaskLinkRecord.task_id == task_id,
                )
            )
        ).scalar_one_or_none()
        return row is not None
