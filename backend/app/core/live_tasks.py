"""将 OpenClaw / Hermes 近期 Session 映射为任务看板中的「执行中」条目。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.core.openclaw_monitor import SessionInfo
from app.models.schemas import TaskInfo

logger = logging.getLogger(__name__)

# 近期更新的 session 视为「进行中」（OpenClaw sessions 无显式 running 字段）
LIVE_SESSION_MAX_AGE_MS = 15 * 60 * 1000


def _parse_ts(raw: str) -> datetime:
    if not raw:
        return datetime.utcnow()
    try:
        text = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return datetime.utcnow()


def session_to_live_task(s: SessionInfo) -> TaskInfo:
    runtime = (s.runtime or "openclaw").lower()
    if runtime not in ("openclaw", "hermes"):
        runtime = "openclaw"
    kind = (s.kind or "session").strip() or "session"
    label = s.key or s.session_id
    ts = _parse_ts(s.updated_at)
    age_s = max(0, int((s.age_ms or 0) / 1000))
    return TaskInfo(
        id=f"live:{runtime}:{s.session_id}",
        workspace_id="",
        project_id="",
        agent_id=s.agent_id or "unknown",
        runtime=runtime,  # type: ignore[arg-type]
        prompt=f"[Live · {runtime} · {kind}] {label}",
        system_prompt="",
        status="running",
        session_id=s.session_id,
        output=f"tokens={s.total_tokens or 0} age={age_s}s model={s.model or '—'}",
        error="",
        duration_ms=s.age_ms or 0,
        start_date="",
        due_date="",
        created_at=ts,
        updated_at=ts,
    )


def collect_live_tasks(
    sessions: list[SessionInfo],
    *,
    known_session_ids: set[str] | None = None,
    agent_id: str | None = None,
    status: str | None = None,
    max_age_ms: int = LIVE_SESSION_MAX_AGE_MS,
) -> list[TaskInfo]:
    """从近期 session 生成 running 伪任务；已有本地 task 绑定同 session 则跳过。"""
    if status and status not in ("running", "all"):
        return []
    known = known_session_ids or set()
    out: list[TaskInfo] = []
    for s in sessions:
        if not s.session_id:
            continue
        if s.session_id in known:
            continue
        age = int(s.age_ms or 0)
        if age <= 0 or age > max_age_ms:
            continue
        if agent_id and s.agent_id != agent_id:
            continue
        out.append(session_to_live_task(s))
    out.sort(key=lambda t: t.updated_at, reverse=True)
    logger.info(
        "live_tasks collected count=%d from_sessions=%d max_age_ms=%d",
        len(out),
        len(sessions),
        max_age_ms,
    )
    return out
