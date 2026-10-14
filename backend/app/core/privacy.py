"""跨端载荷过滤。私有正文、绝对路径和密钥默认留在本机。"""

from __future__ import annotations

import re

_SECRET_KEYS = {
    "api_key",
    "token",
    "password",
    "secret",
    "authorization",
    "node_token",
    "device_token",
    "enroll_token",
}
_PATH_RE = re.compile(r"(?:^|[\s\"'])(/[^\s\"']+|~[/\\][^\s\"']+)")


def payload_hash(payload: dict) -> str:
    import hashlib
    import json

    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def redact_for_sync(payload: dict, visibility: str = "private") -> dict:
    """私有任务只留元数据。显式 shared 才带正文，并且去掉密钥和绝对路径。"""
    visibility = visibility or "private"
    if visibility == "private":
        return {
            "visibility": "private",
            "shared": False,
            "task_id": str(payload.get("task_id") or payload.get("id") or ""),
            "status": str(payload.get("status") or ""),
        }
    return _scrub(payload)


def _scrub(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                continue
            cleaned[key] = _scrub(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, str):
        return _PATH_RE.sub(" [path] ", value)
    return value


def leaks_private(payload: dict, secret: str = "", private_text: str = "") -> bool:
    import json

    raw = json.dumps(payload, ensure_ascii=False)
    if secret and secret in raw:
        return True
    if private_text and private_text in raw:
        return True
    if _PATH_RE.search(raw):
        return True
    return False
