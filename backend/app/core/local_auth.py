"""本机会话令牌。桌面、本地网页和 CLI 共用，不放进 URL。"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from app.paths import data_dir

_FILENAME = "local_session.token"
FAILURE_LIMIT = 8
COOLDOWN_SECONDS = 60
_FAILURES: dict[str, int] = {}
_LOCK_UNTIL: dict[str, float] = {}


def session_path() -> Path:
    return data_dir() / _FILENAME


def ensure_local_session() -> str:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


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
