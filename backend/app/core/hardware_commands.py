"""硬件指令：有效期、幂等、急停本地优先。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.db import HardwareCommandRecord, get_session_factory

logger = logging.getLogger(__name__)

_DEFAULT_TTL = timedelta(seconds=120)


class HardwareCommandError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(detail)


def _now() -> datetime:
    return datetime.utcnow()


async def enqueue(
    device_id: str,
    command: str,
    *,
    payload: dict | None = None,
    idempotency_key: str = "",
    ttl_seconds: int = 120,
) -> dict:
    device_id = (device_id or "").strip()
    command = (command or "").strip()
    if not device_id or not command:
        raise HardwareCommandError("device_id and command required")
    if command == "emergency_stop":
        # 急停：立即标记 applied，不依赖云端确认循环
        return await _apply_emergency(device_id, payload or {})

    key = (idempotency_key or "").strip() or f"{device_id}:{command}:{uuid.uuid4()}"
    cid = str(uuid.uuid4())
    expires = _now() + timedelta(seconds=max(1, ttl_seconds))
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            HardwareCommandRecord(
                id=cid,
                device_id=device_id,
                command=command,
                payload_json=json.dumps(payload or {}, ensure_ascii=False),
                idempotency_key=key,
                status="queued",
                expires_at=expires,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = (
                await session.execute(
                    select(HardwareCommandRecord).where(
                        HardwareCommandRecord.idempotency_key == key
                    )
                )
            ).scalar_one_or_none()
            if existing:
                logger.info("hardware command deduped key=%s id=%s", key, existing.id)
                return _row(existing)
            raise
    logger.info("hardware command queued id=%s device=%s cmd=%s", cid, device_id, command)
    return {
        "id": cid,
        "device_id": device_id,
        "command": command,
        "status": "queued",
        "expires_at": expires.isoformat() + "Z",
    }


async def _apply_emergency(device_id: str, payload: dict) -> dict:
    cid = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            HardwareCommandRecord(
                id=cid,
                device_id=device_id,
                command="emergency_stop",
                payload_json=json.dumps(payload, ensure_ascii=False),
                idempotency_key=f"estop:{device_id}:{cid}",
                status="applied",
                expires_at=_now() + _DEFAULT_TTL,
                applied_at=_now(),
            )
        )
        await session.commit()
    logger.warning("hardware emergency_stop device=%s id=%s", device_id, cid)
    return {"id": cid, "device_id": device_id, "command": "emergency_stop", "status": "applied"}


def _row(rec: HardwareCommandRecord) -> dict:
    return {
        "id": rec.id,
        "device_id": rec.device_id,
        "command": rec.command,
        "status": rec.status,
        "expires_at": rec.expires_at.isoformat() + "Z" if rec.expires_at else "",
    }


async def claim_next(device_id: str) -> dict | None:
    """设备拉取下一条未过期指令。过期标记 rejected。"""
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(HardwareCommandRecord)
                .where(
                    HardwareCommandRecord.device_id == device_id,
                    HardwareCommandRecord.status == "queued",
                )
                .order_by(HardwareCommandRecord.created_at.asc())
                .limit(5)
            )
        ).scalars().all()
        now = _now()
        for row in rows:
            if row.expires_at and row.expires_at < now:
                row.status = "rejected"
                logger.info("hardware command expired id=%s", row.id)
                continue
            row.status = "delivered"
            await session.commit()
            return _row(row)
        await session.commit()
    return None


async def ack_applied(command_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(HardwareCommandRecord, command_id)
        if row is None:
            raise HardwareCommandError("not found", 404)
        if row.status == "rejected":
            raise HardwareCommandError("command expired or rejected", 409)
        row.status = "applied"
        row.applied_at = _now()
        await session.commit()
        return _row(row)
