"""接口身份。人类会话、执行节点和对话设备各自只能走自己的路径。"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.core.local_auth import session_matches
from app.models.db import NodeCredentialRecord, get_session_factory

logger = logging.getLogger(__name__)

_PUBLIC_PATHS = {
    "/api/health",
    "/api/session/bootstrap",
    "/api/session/status",
    "/api/session/unlock",
    "/api/v2/openapi.json",
    "/api/v2/nodes/enroll",
    "/api/super-ai/device/enroll",
    "/api/super-ai/device/pair",
    "/api/super-ai/device/pair/status",
}
_NODE_RULES = (
    ("POST", re.compile(r"^/api/fleet/heartbeat$")),
    ("POST", re.compile(r"^/api/fleet/claim$")),
    ("POST", re.compile(r"^/api/fleet/tasks/[^/]+/finish$")),
    ("GET", re.compile(r"^/api/fleet/catalog$")),
    ("POST", re.compile(r"^/api/fleet/call$")),
    ("POST", re.compile(r"^/api/v2/nodes/heartbeat$")),
    ("POST", re.compile(r"^/api/v2/delegations$")),
    ("POST", re.compile(r"^/api/v2/commands/claim$")),
    ("POST", re.compile(r"^/api/v2/commands/ack$")),
    ("POST", re.compile(r"^/api/v2/events/batch$")),
)
_DEVICE_RULES = (
    ("POST", re.compile(r"^/api/super-ai/device/turn$")),
    ("GET", re.compile(r"^/api/super-ai/device/tasks/[^/]+$")),
)
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_EXACT_ORIGINS = {
    "tauri://localhost",
    "https://tauri.localhost",
    "http://tauri.localhost",
}


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


@dataclass
class Principal:
    kind: str
    node_id: str = ""
    role: str = ""


def session_public(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True
    if not path.startswith("/api") and not path.startswith("/ws"):
        return True
    return False


def origin_allowed(origin: str) -> bool:
    origin = (origin or "").strip()
    if not origin:
        return False
    if origin in _EXACT_ORIGINS:
        return True
    from urllib.parse import urlparse

    parsed = urlparse(origin)
    if parsed.scheme not in {"http", "https"}:
        return False
    return (parsed.hostname or "").lower() in _LOOPBACK_HOSTS


def _matches(rules: tuple[tuple[str, re.Pattern[str]], ...], method: str, path: str) -> bool:
    for allowed_method, pattern in rules:
        if method == allowed_method and pattern.match(path):
            return True
    return False


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _credential(token: str) -> NodeCredentialRecord | None:
    if not token:
        return None
    factory = get_session_factory()
    async with factory() as session:
        return (
            await session.execute(
                select(NodeCredentialRecord).where(NodeCredentialRecord.token_hash == _hash(token))
            )
        ).scalar_one_or_none()


async def resolve_token(node_token: str, device_token: str) -> Principal:
    node_token = (node_token or "").strip()
    device_token = (device_token or "").strip()
    if node_token and device_token:
        raise AuthError(401, "send one credential")
    if node_token:
        from app.core import fleet as fleet_service

        rec = await fleet_service.authenticate(node_token)
        if rec is not None and (rec.mode or "") != "voice":
            logger.debug("access node fleet node_id=%s", rec.id)
            return Principal(kind="node", node_id=rec.id, role="edge")
        row = await _credential(node_token)
        if row is not None and not row.revoked and row.role in {"full", "edge", "center"}:
            logger.debug("access node v2 node_id=%s role=%s", row.node_id, row.role)
            return Principal(kind="node", node_id=row.node_id, role=row.role)
        if row is not None and not row.revoked and row.role == "conversation":
            logger.debug("access conversation node_id=%s", row.node_id)
            return Principal(kind="device", node_id=row.node_id, role="conversation")
        logger.info("access rejected reason=invalid_node_token")
        raise AuthError(401, "node credential revoked or unknown")
    from app.core import channels as channel_service
    from app.core import fleet as fleet_service

    ch = await channel_service.authenticate_channel(device_token)
    if ch is not None:
        logger.debug("access device channel device_id=%s kind=%s", ch.device_id, ch.kind)
        return Principal(kind="device", node_id=ch.device_id, role="conversation")
    rec = await fleet_service.authenticate(device_token)
    if rec is not None and (rec.mode or "") == "voice":
        logger.debug("access device node_id=%s", rec.id)
        return Principal(kind="device", node_id=rec.id, role="conversation")
    row = await _credential(device_token)
    if row is not None and not row.revoked and row.role == "conversation":
        logger.debug("access device credential node_id=%s", row.node_id)
        return Principal(kind="device", node_id=row.node_id, role="conversation")
    logger.info("access rejected reason=invalid_device_token")
    raise AuthError(401, "device credential revoked or unknown")


def path_allowed(principal: Principal, method: str, path: str) -> bool:
    if principal.kind == "node":
        return _matches(_NODE_RULES, method, path)
    if principal.kind == "device":
        return _matches(_DEVICE_RULES, method, path)
    return True


async def enforce(request: Request, settings) -> JSONResponse | None:
    if not settings.local_auth_enabled:
        return None
    path = request.url.path
    if request.method == "OPTIONS" or session_public(path):
        return None
    node_token = request.headers.get("x-node-token") or ""
    device_token = request.headers.get("x-device-token") or ""
    try:
        if node_token or device_token:
            principal = await resolve_token(node_token, device_token)
            if not path_allowed(principal, request.method, path):
                logger.info(
                    "access denied status=403 method=%s path=%s kind=%s node_id=%s",
                    request.method,
                    path,
                    principal.kind,
                    principal.node_id,
                )
                raise AuthError(403, "credential cannot call this endpoint")
            request.state.principal = principal
            return None
        presented_header = request.headers.get("x-agentcenter-session") or ""
        presented_cookie = request.cookies.get("ac_session") or ""
        if session_matches(presented_header) or session_matches(presented_cookie):
            request.state.principal = Principal(kind="session")
            return None
        admin = (settings.admin_token or "").strip()
        if admin and request.headers.get("x-admin-token") == admin:
            request.state.principal = Principal(kind="admin")
            return None
        raise AuthError(401, "local session required")
    except AuthError as exc:
        if exc.status_code != 403:
            logger.info(
                "access denied status=%s method=%s path=%s detail=%s",
                exc.status_code,
                request.method,
                path,
                exc.detail,
            )
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


async def authenticate_websocket(websocket, settings) -> Principal:
    if not settings.local_auth_enabled:
        return Principal(kind="disabled")
    origin = websocket.headers.get("origin") or ""
    node_token = websocket.headers.get("x-node-token") or ""
    device_token = websocket.headers.get("x-device-token") or ""
    if node_token or device_token:
        principal = await resolve_token(node_token, device_token)
    else:
        header = websocket.headers.get("x-agentcenter-session") or ""
        cookie = websocket.cookies.get("ac_session") or ""
        if session_matches(header) or session_matches(cookie):
            principal = Principal(kind="session")
        else:
            admin = (settings.admin_token or "").strip()
            presented = websocket.headers.get("x-admin-token") or ""
            if admin and presented == admin:
                principal = Principal(kind="admin")
            else:
                raise AuthError(401, "local session required")
    if origin and not origin_allowed(origin):
        logger.info("ws origin rejected origin=%s kind=%s", origin, principal.kind)
        raise AuthError(403, "origin not allowed")
    if principal.kind in {"session", "admin"} and not origin_allowed(origin):
        logger.info("ws origin missing kind=%s", principal.kind)
        raise AuthError(403, "origin not allowed")
    return principal


async def task_visible(principal: Principal, task) -> bool:
    if principal.kind in {"session", "admin", "disabled"}:
        return True
    task_id = getattr(task, "id", "")
    node_id = getattr(task, "node_id", "") or ""
    if principal.kind == "node":
        return bool(node_id) and node_id == principal.node_id
    if principal.kind == "device":
        from app.core.confirmations import device_can_read

        try:
            return await device_can_read(principal.node_id, task_id)
        except Exception:
            logger.info("ws device visibility failed device=%s task_id=%s", principal.node_id, task_id)
            return False
    return False
