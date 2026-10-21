"""ESP32 等语音终端：登记、短码绑定、对话、取回任务结果。"""

from __future__ import annotations

import hmac
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update

from app.core import fleet as fleet_service
from app.core.fleet import FleetError
from app.core.super_ai import brief_for_device, handle_turn, task_spoken
from app.models.db import DevicePairRecord, FleetNodeRecord, get_session_factory
from app.models.schemas import SuperAiPending, SuperAiTurnResponse

logger = logging.getLogger(__name__)


class DeviceAuthError(Exception):
    pass


class DevicePairError(Exception):
    pass


_PAIR_TTL_SECONDS = 600


_VOICE_LIMIT = 480
_DESKTOP_LIMIT = 2000


def _clip_reply(text: str, limit: int = _VOICE_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


async def enroll_device(
    *,
    enroll_token: str,
    expected_token: str,
    device_id: str,
    name: str = "",
    platform: str = "esp32",
) -> dict[str, str]:
    return await fleet_service.enroll_voice(
        enroll_token=enroll_token,
        expected_token=expected_token,
        device_id=device_id,
        name=name,
        hostname=device_id,
        platform=platform,
    )


def _pair_left(expires_at: datetime | None) -> int:
    if expires_at is None:
        return 0
    return max(0, int((expires_at - datetime.utcnow()).total_seconds()))


async def start_device_pair(
    *,
    device_id: str,
    name: str = "",
    platform: str = "esp32",
) -> dict[str, str | int]:
    """设备发起绑定。只发短码和轮询密文，不发长期令牌。"""
    device_id = (device_id or "").strip().lower()
    if not fleet_service.NODE_ID_RE.match(device_id):
        raise DevicePairError("设备标识无效")
    platform = platform if platform in ("esp32", "desktop") else "esp32"
    factory = get_session_factory()
    async with factory() as session:
        node = await session.get(FleetNodeRecord, device_id)
        if node is not None and (node.mode or "plugin") != "voice":
            raise FleetError("device id already registered")
        await session.execute(delete(DevicePairRecord).where(DevicePairRecord.device_id == device_id))
        code = ""
        code_hash = ""
        for _ in range(8):
            code = f"{secrets.randbelow(900000) + 100000}"
            code_hash = fleet_service.hash_token(code)
            taken = await session.scalar(
                select(DevicePairRecord.id).where(DevicePairRecord.code_hash == code_hash)
            )
            if taken is None:
                break
        else:
            raise DevicePairError("暂时无法生成验证码")
        poll_secret = secrets.token_urlsafe(24)
        session.add(
            DevicePairRecord(
                id=str(uuid.uuid4()),
                device_id=device_id,
                name=name or device_id,
                platform=platform,
                code_hash=code_hash,
                poll_secret_hash=fleet_service.hash_token(poll_secret),
                device_token="",
                expires_at=datetime.utcnow() + timedelta(seconds=_PAIR_TTL_SECONDS),
            )
        )
        await session.commit()
    logger.info("super_ai pair start device=%s ttl_s=%s", device_id, _PAIR_TTL_SECONDS)
    return {
        "device_id": device_id,
        "code": code,
        "poll_secret": poll_secret,
        "bind_path": "/bind",
        "expires_in": _PAIR_TTL_SECONDS,
    }


async def claim_device_pair(code: str) -> dict[str, str]:
    """已登录的人提交短码。长期令牌只写进配对记录，不返回给浏览器。"""
    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(digits) != 6:
        logger.info("super_ai pair claim rejected reason=format")
        raise DevicePairError("验证码无效或已过期")
    code_hash = fleet_service.hash_token(digits)
    now = datetime.utcnow()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            update(DevicePairRecord)
            .where(
                DevicePairRecord.code_hash == code_hash,
                DevicePairRecord.claimed_at.is_(None),
                DevicePairRecord.expires_at > now,
            )
            .values(claimed_at=now)
        )
        await session.commit()
        if result.rowcount != 1:
            logger.info("super_ai pair claim rejected reason=missing")
            raise DevicePairError("验证码无效或已过期")
        rec = await session.scalar(
            select(DevicePairRecord).where(DevicePairRecord.code_hash == code_hash)
        )
        if rec is None:
            raise DevicePairError("验证码无效或已过期")
        device_id = rec.device_id
        name = rec.name or device_id
        platform = rec.platform or "esp32"
    try:
        token = await fleet_service._store_voice_device(
            device_id,
            name=name,
            hostname=device_id,
            platform=platform,
        )
    except FleetError:
        async with factory() as session:
            await session.execute(
                update(DevicePairRecord)
                .where(DevicePairRecord.code_hash == code_hash)
                .values(claimed_at=None)
            )
            await session.commit()
        logger.warning("super_ai pair claim failed device=%s reason=occupied", device_id)
        raise
    async with factory() as session:
        rec = await session.scalar(
            select(DevicePairRecord).where(DevicePairRecord.code_hash == code_hash)
        )
        if rec is None:
            raise DevicePairError("验证码无效或已过期")
        rec.device_token = token
        await session.commit()
        device_id = rec.device_id
        name = rec.name or device_id
    logger.info("super_ai pair claimed device=%s", device_id)
    return {"device_id": device_id, "name": name, "status": "bound"}


async def poll_device_pair(device_id: str, poll_secret: str) -> dict[str, str | int]:
    """只有持有轮询密文的那台设备能在有效期内取回长期令牌。"""
    device_id = (device_id or "").strip().lower()
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.scalar(
            select(DevicePairRecord)
            .where(DevicePairRecord.device_id == device_id)
            .order_by(DevicePairRecord.created_at.desc())
        )
        if rec is None:
            raise DevicePairError("没有进行中的绑定")
        presented = fleet_service.hash_token(poll_secret or "")
        if not hmac.compare_digest(presented, rec.poll_secret_hash or ""):
            logger.warning("super_ai pair poll rejected device=%s", device_id)
            raise DeviceAuthError("invalid pair secret")
        now = datetime.utcnow()
        if rec.expires_at is None or rec.expires_at < now:
            rec.device_token = ""
            await session.commit()
            logger.info("super_ai pair expired device=%s", device_id)
            return {
                "status": "expired",
                "device_id": device_id,
                "name": rec.name or device_id,
                "device_token": "",
                "expires_in": 0,
            }
        if rec.claimed_at is None or not rec.device_token:
            return {
                "status": "pending",
                "device_id": device_id,
                "name": rec.name or device_id,
                "device_token": "",
                "expires_in": _pair_left(rec.expires_at),
            }
        return {
            "status": "ready",
            "device_id": device_id,
            "name": rec.name or device_id,
            "device_token": rec.device_token,
            "expires_in": _pair_left(rec.expires_at),
        }


async def _require_voice(token: str):
    rec = await fleet_service.authenticate(token)
    if rec is None or (rec.mode or "") != "voice":
        raise DeviceAuthError("invalid device token")
    await fleet_service.heartbeat(token)
    return rec


async def device_turn(
    token: str,
    text: str,
    *,
    workspace_slug: str,
    pending: SuperAiPending | None,
    registry,
    task_manager,
    monitor,
    channel: str = "voice",
    confirmation_id: str = "",
    session_id: str = "",
) -> SuperAiTurnResponse:
    rec = await _require_voice(token)
    channel = channel if channel in ("voice", "desktop") else "voice"
    result = await handle_turn(
        text,
        workspace_slug=workspace_slug,
        pending=pending,
        last_href="",
        registry=registry,
        task_manager=task_manager,
        monitor=monitor,
        confirmation_id=confirmation_id,
        session_id=session_id or rec.id,
        subject_id=rec.id,
    )
    limit = _DESKTOP_LIMIT if channel == "desktop" else _VOICE_LIMIT
    result.reply = _clip_reply(result.reply, limit)
    from app.core.chain import append_chain

    pending_prompt = pending.prompt if pending else ""
    await append_chain(
        kind="turn",
        run_id=result.run_id,
        task_id=result.task_id,
        actor_id=rec.id,
        channel=channel,
        intent=result.intent,
        status=result.task_status,
        summary=text,
        detail={
            "service": result.service,
            "href": result.href,
            "pending_prompt": pending_prompt,
            "reply": result.reply,
            "session_id": session_id or rec.id,
            "dispatch": result.dispatch,
        },
    )
    logger.info(
        "super_ai device turn run_id=%s device=%s intent=%s task_id=%s channel=%s",
        result.run_id,
        rec.id,
        result.intent,
        result.task_id or "-",
        channel,
    )
    if result.task_id:
        from app.core.confirmations import bind_device_task

        try:
            await bind_device_task(rec.id, result.task_id, session_id or rec.id)
        except RuntimeError:
            logger.info("device task link skipped device=%s", rec.id)
    return result


async def device_task(token: str, task_id: str, task_manager) -> dict:
    rec = await _require_voice(token)
    from app.core.confirmations import device_can_read

    try:
        allowed = await device_can_read(rec.id, task_id)
    except RuntimeError:
        allowed = False
    if not allowed:
        logger.info("super_ai device task denied device=%s task_id=%s", rec.id, task_id)
        raise DeviceAuthError("task is outside this device session")
    task = await task_manager.get_task(task_id)
    if task is None:
        logger.info("super_ai device task missing device=%s task_id=%s", rec.id, task_id)
        return {}
    spoken = task_spoken(task)
    if spoken.get("done") and spoken.get("status") == "completed":
        spoken["reply"] = await brief_for_device(task, actor_id=rec.id)
    if spoken.get("done"):
        from app.core.chain import append_chain

        await append_chain(
            kind="deliver",
            task_id=task.id,
            actor_id=rec.id,
            status=str(spoken.get("status") or ""),
            summary=str(spoken.get("reply") or ""),
        )
    logger.info(
        "super_ai device task device=%s task_id=%s status=%s done=%s",
        rec.id,
        task_id,
        spoken["status"],
        spoken["done"],
    )
    return spoken
