"""超级AI 的短会话。只留最近几轮，供模型接着说。"""

from __future__ import annotations

import json
import logging

from app.core.knowledge import redact_secrets
from app.paths import data_dir

logger = logging.getLogger(__name__)

_LIMIT = 8
_TEXT = 500


def session_path():
    return data_dir() / "super_ai_sessions.json"


def _load() -> dict[str, list[dict[str, str]]]:
    path = session_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("super_ai session unreadable err=%s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[dict[str, str]]] = {}
    for key, rows in data.items():
        if not isinstance(key, str) or not isinstance(rows, list):
            continue
        cleaned = []
        for row in rows[-_LIMIT:]:
            if not isinstance(row, dict):
                continue
            role = row.get("role") if row.get("role") in ("user", "assistant") else "user"
            text = str(row.get("text") or "").strip()
            if text:
                cleaned.append({"role": role, "text": text})
        if cleaned:
            out[key] = cleaned
    return out


def _save(data: dict[str, list[dict[str, str]]]) -> None:
    path = session_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _clip(text: str) -> str:
    text = redact_secrets(" ".join((text or "").split()))
    if len(text) <= _TEXT:
        return text
    return text[: _TEXT - 1] + "…"


async def recent(session_id: str) -> list[dict[str, str]]:
    key = (session_id or "").strip()
    if not key:
        return []
    return list(_load().get(key) or [])


async def remember(session_id: str, user_text: str, reply: str) -> None:
    key = (session_id or "").strip()
    if not key:
        return
    data = _load()
    rows = list(data.get(key) or [])
    user = _clip(user_text)
    answer = _clip(reply)
    if user:
        rows.append({"role": "user", "text": user})
    if answer:
        rows.append({"role": "assistant", "text": answer})
    data[key] = rows[-_LIMIT:]
    if len(data) > 40:
        for old in list(data)[:-40]:
            data.pop(old, None)
    _save(data)
    logger.info("super_ai session session=%s messages=%d", key[:12], len(data[key]))
