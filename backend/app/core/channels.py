"""交互通道：与执行 Node 解耦，同一 device 可并存。"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime

from sqlalchemy import select

from app.core.fleet import FleetError, hash_token
from app.core.identity import load_or_create_identity
from app.models.db import ChannelRecord, DeviceRecord, FleetNodeRecord, get_session_factory

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.utcnow()


def channel_id_for(device_id: str, kind: str = "voice") -> str:
    return f"{device_id}:{kind}"


async def ensure_device(device_id: str, *, name: str = "", platform: str = "") -> None:
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(DeviceRecord, device_id)
        if rec is None:
            session.add(
                DeviceRecord(
                    id=device_id,
                    name=name or device_id,
                    platform=platform or "",
                    owner_center_id=ident.center_id,
                )
            )
        else:
            if name:
                rec.name = name
            if platform:
                rec.platform = platform
            rec.updated_at = _now()
        await session.commit()


async def issue_voice_channel(
    device_id: str,
    *,
    name: str = "",
    platform: str = "esp32",
    kind: str = "voice",
) -> str:
    """签发语音/桌面通道令牌。不覆盖同 device 上的执行 Node。"""
    kind = kind if kind in ("voice", "desktop") else "voice"
    platform = platform if platform in ("esp32", "desktop") else "esp32"
    if kind == "desktop":
        # 桌面小牛仍用 voice 通道语义领令牌，kind 记 desktop
        pass
    await ensure_device(device_id, name=name, platform=platform)
    token = secrets.token_urlsafe(32)
    cid = channel_id_for(device_id, "voice" if kind != "desktop" else "desktop")
    # 统一用 voice 名册兼容旧客户端：channel kind 区分 platform
    store_kind = "desktop" if platform == "desktop" else "voice"
    cid = channel_id_for(device_id, store_kind)
    factory = get_session_factory()
    has_exec = False
    async with factory() as session:
        node = await session.get(FleetNodeRecord, device_id)
        if node is not None and (node.mode or "plugin") not in ("", "voice"):
            has_exec = True
        elif node is not None and (node.mode or "") == "voice":
            # 令牌改存 Channel；名册行仅作发现用
            node.token_hash = ""
            node.name = name or node.name or device_id
            node.platform = platform
            node.last_seen = _now()
            node.updated_at = _now()
        elif node is None:
            # 纯语音设备：保留 mode=voice 名册行便于列表，令牌在 Channel
            session.add(
                FleetNodeRecord(
                    id=device_id,
                    name=name or device_id,
                    token_hash="",
                    runtimes_json="[]",
                    agents_json="[]",
                    seen_json="[]",
                    mode="voice",
                    bound=0,
                    platform=platform,
                    hostname=device_id,
                    last_seen=_now(),
                )
            )

        rec = await session.get(ChannelRecord, cid)
        if rec is None:
            rec = ChannelRecord(
                id=cid,
                device_id=device_id,
                kind=store_kind,
                name=name or device_id,
                platform=platform,
            )
            session.add(rec)
        rec.name = name or rec.name or device_id
        rec.platform = platform
        rec.token_hash = hash_token(token)
        rec.last_seen = _now()
        rec.updated_at = _now()
        await session.commit()
    logger.info(
        "channel issued device=%s kind=%s channel_id=%s has_exec_node=%s",
        device_id,
        store_kind,
        cid,
        has_exec,
    )
    return token


async def authenticate_channel(token: str) -> ChannelRecord | None:
    token = (token or "").strip()
    if not token:
        return None
    digest = hash_token(token)
    factory = get_session_factory()
    async with factory() as session:
        rec = (
            await session.execute(select(ChannelRecord).where(ChannelRecord.token_hash == digest))
        ).scalar_one_or_none()
        if rec is None:
            return None
        rec.last_seen = _now()
        await session.commit()
        await session.refresh(rec)
        return rec


async def touch_channel(device_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(select(ChannelRecord).where(ChannelRecord.device_id == device_id))
        ).scalars().all()
        for rec in rows:
            rec.last_seen = _now()
        if rows:
            await session.commit()


async def assert_can_pair(device_id: str) -> None:
    """绑定短码：执行 Node 已存在时仍允许开语音通道。"""
    factory = get_session_factory()
    async with factory() as session:
        node = await session.get(FleetNodeRecord, device_id)
        if node is None:
            return
        # 仅当已是语音占位且要重绑时允许；执行节点并存一律允许
        if (node.mode or "plugin") != "voice" and (node.bound or node.token_hash):
            logger.info("channel pair alongside exec node device=%s mode=%s", device_id, node.mode)
            return
        if (node.mode or "") == "voice":
            return
    # 不再抛 device id already registered
