"""本机会话令牌。桌面、本地网页和 CLI 共用，不放进 URL。"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from pathlib import Path

from app.paths import data_dir

logger = logging.getLogger(__name__)

_FILENAME = "local_session.token"
_META_FILENAME = "local_session.meta"
_ENTRY_FILENAME = "entry_code"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
FAILURE_LIMIT = 8
COOLDOWN_SECONDS = 60
_FAILURES: dict[str, int] = {}
_LOCK_UNTIL: dict[str, float] = {}


def session_path() -> Path:
    return data_dir() / _FILENAME


def session_meta_path() -> Path:
    return data_dir() / _META_FILENAME


def entry_code_path() -> Path:
    return data_dir() / _ENTRY_FILENAME


def ensure_entry_code(configured: str) -> str:
    """配置了口令就用配置。空配置生成一次实例独有口令，不再回落到源码里的固定值。"""
    text = (configured or "").strip()
    if text:
        return text
    path = entry_code_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    code = secrets.token_urlsafe(18)
    path.write_text(code, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    logger.warning("entry code generated path=%s", path)
    return code


def _read_meta() -> dict | None:
    path = session_meta_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("local session meta unreadable path=%s", path)
        return None
    return raw if isinstance(raw, dict) else None


def _write_meta(issued_at: float, expires_at: float) -> None:
    path = session_meta_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"issued_at": issued_at, "expires_at": expires_at}),
        encoding="utf-8",
    )
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_session() -> str:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    now = time.time()
    _write_meta(now, now + SESSION_TTL_SECONDS)
    return token


def ensure_local_session() -> str:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    meta = _read_meta()
    now = time.time()
    if token and meta is None:
        _write_meta(now, now + SESSION_TTL_SECONDS)
        logger.info("local session expiry attached")
        return token
    expires_at = float(meta.get("expires_at") or 0) if meta else 0.0
    if token and expires_at > now:
        return token
    logger.info("local session rotated reason=%s", "expired" if token else "missing")
    return _write_session()


def revoke_local_session() -> str:
    logger.info("local session revoked")
    return _write_session()


def session_matches(presented: str) -> bool:
    presented = (presented or "").strip()
    if not presented:
        return False
    expected = ensure_local_session()
    return secrets.compare_digest(presented, expected)


def code_matches(presented: str, expected: str) -> bool:
    presented = presented or ""
    expected = expected or ""
    if not presented or not expected:
        return False
    return secrets.compare_digest(presented, expected)


def reset_entry_attempts() -> None:
    _FAILURES.clear()
    _LOCK_UNTIL.clear()


def cooldown_remaining(host: str, now: float | None = None) -> float:
    current = time.monotonic() if now is None else now
    until = _LOCK_UNTIL.get(host) or 0.0
    if until <= current:
        return 0.0
    return until - current


def register_failure(host: str, *, now: float | None = None) -> int:
    current = time.monotonic() if now is None else now
    if cooldown_remaining(host, current) > 0:
        return FAILURE_LIMIT
    locked_until = _LOCK_UNTIL.get(host) or 0.0
    if locked_until and locked_until <= current:
        _LOCK_UNTIL.pop(host, None)
        _FAILURES[host] = 0
    count = _FAILURES.get(host, 0) + 1
    _FAILURES[host] = count
    if count >= FAILURE_LIMIT:
        _LOCK_UNTIL[host] = current + COOLDOWN_SECONDS
    return count


def clear_failures(host: str) -> None:
    _FAILURES.pop(host, None)
    _LOCK_UNTIL.pop(host, None)
