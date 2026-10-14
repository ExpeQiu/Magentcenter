"""本机会话令牌。桌面、本地网页和 CLI 共用，不放进 URL。"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from app.paths import data_dir

_FILENAME = "local_session.token"


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
