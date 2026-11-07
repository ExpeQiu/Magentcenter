"""Center/Client Session：跨端调用云端超级AI 的对话身份（不可 claim）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.models.db import ClientSessionRecord, get_session_factory
from app.paths import data_dir

logger = logging.getLogger(__name__)

DEFAULT_SCOPES = ["super_ai.turn", "super_ai.session", "super_ai.task_read"]
DEFAULT_TTL_SECONDS = 30 * 24 * 3600


class ClientSessionError(Exception):
    def __init__(self, detail: str, status_code: int = 401):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass
class ClientPrincipal:
    session_id: str
    client_id: str
    center_id: str
    workspace_id: str
    device_id: str
    scopes: list[str]


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _local_store() -> Path:
    return data_dir() / "cloud_client_session.json"


def save_local_client_session(payload: dict) -> None:
    path = _local_store()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "client session saved locally client_id=%s cloud=%s",
        payload.get("client_id") or "-",
        (payload.get("cloud_url") or "")[:64],
    )


def load_local_client_session() -> dict | None:
    path = _local_store()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("client session local unreadable err=%s", exc)
        return None
    if not isinstance(data, dict):
        return None
    return data


def clear_local_client_session() -> None:
    path = _local_store()
    if path.is_file():
        path.unlink()
        logger.info("client session local cleared")


async def enroll(
    *,
    enroll_token: str,
    expected_token: str,
    center_id: str,
    client_id: str = "",
    workspace_id: str = "",
    device_id: str = "",
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    scopes: list[str] | None = None,
) -> dict:
    if not (expected_token or "").strip():
        raise ClientSessionError("fleet enroll token is not configured", 503)
    if not hmac.compare_digest(enroll_token or "", expected_token):
        logger.warning("client enroll rejected center=%s", (center_id or "")[:12])
        raise ClientSessionError("invalid enroll token", 401)
    center_id = (center_id or "").strip()
    if not center_id:
        raise ClientSessionError("center_id required", 400)
    client_id = (client_id or "").strip() or str(uuid.uuid4())
    workspace_id = (workspace_id or "").strip() or "cyber"
    device_id = (device_id or "").strip()
    scope_list = list(scopes or DEFAULT_SCOPES)
    raw = secrets.token_urlsafe(32)
    session_id = str(uuid.uuid4())
    expires = datetime.utcnow() + timedelta(seconds=max(300, min(int(ttl_seconds), DEFAULT_TTL_SECONDS)))
    factory = get_session_factory()
    async with factory() as session:
        # 同 client_id 旧会话作废，避免堆积
        rows = (
            await session.execute(
                select(ClientSessionRecord).where(
                    ClientSessionRecord.client_id == client_id,
                    ClientSessionRecord.revoked == 0,
                )
            )
        ).scalars().all()
        for row in rows:
            row.revoked = 1
        session.add(
            ClientSessionRecord(
                id=session_id,
                client_id=client_id,
                center_id=center_id,
                workspace_id=workspace_id,
                device_id=device_id,
                token_hash=_hash(raw),
                scopes_json=json.dumps(scope_list, ensure_ascii=False),
                revoked=0,
                expires_at=expires,
                last_seen=datetime.utcnow(),
            )
        )
        await session.commit()
    logger.info(
        "client enrolled session=%s client_id=%s center=%s workspace=%s",
        session_id[:12],
        client_id[:12],
        center_id[:12],
        workspace_id,
    )
    return {
        "session_id": session_id,
        "client_id": client_id,
        "center_id": center_id,
        "workspace_id": workspace_id,
        "device_id": device_id,
        "client_token": raw,
        "scopes": scope_list,
        "expires_at": expires.isoformat() + "Z",
    }


async def authenticate(token: str) -> ClientPrincipal:
    token = (token or "").strip()
    if not token:
        raise ClientSessionError("client token required", 401)
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(ClientSessionRecord).where(ClientSessionRecord.token_hash == _hash(token))
            )
        ).scalar_one_or_none()
        if row is None or row.revoked:
            raise ClientSessionError("client credential revoked or unknown", 401)
        if row.expires_at and row.expires_at < datetime.utcnow():
            raise ClientSessionError("client credential expired", 401)
        row.last_seen = datetime.utcnow()
        await session.commit()
        try:
            scopes = json.loads(row.scopes_json or "[]")
        except json.JSONDecodeError:
            scopes = list(DEFAULT_SCOPES)
        if not isinstance(scopes, list):
            scopes = list(DEFAULT_SCOPES)
        return ClientPrincipal(
            session_id=row.id,
            client_id=row.client_id,
            center_id=row.center_id,
            workspace_id=row.workspace_id,
            device_id=row.device_id,
            scopes=[str(s) for s in scopes],
        )


async def refresh(token: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> dict:
    principal = await authenticate(token)
    factory = get_session_factory()
    raw = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(seconds=max(300, min(int(ttl_seconds), DEFAULT_TTL_SECONDS)))
    async with factory() as session:
        row = await session.get(ClientSessionRecord, principal.session_id)
        if row is None or row.revoked:
            raise ClientSessionError("client credential revoked or unknown", 401)
        row.token_hash = _hash(raw)
        row.expires_at = expires
        row.last_seen = datetime.utcnow()
        await session.commit()
        scopes = principal.scopes
    logger.info("client refreshed session=%s client_id=%s", principal.session_id[:12], principal.client_id[:12])
    return {
        "session_id": principal.session_id,
        "client_id": principal.client_id,
        "center_id": principal.center_id,
        "workspace_id": principal.workspace_id,
        "client_token": raw,
        "scopes": scopes,
        "expires_at": expires.isoformat() + "Z",
    }


async def revoke(token: str) -> bool:
    token = (token or "").strip()
    if not token:
        return False
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(ClientSessionRecord).where(ClientSessionRecord.token_hash == _hash(token))
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        row.revoked = 1
        await session.commit()
    logger.info("client revoked session=%s", row.id[:12])
    return True
