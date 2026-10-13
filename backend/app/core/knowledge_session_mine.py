"""从 OpenClaw / Hermes 会话里抽出可复用主张，写入知识库。

不归档原文。只有偏好、拍板、可重复步骤、失败教训才会入库。
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.core.knowledge import _upsert_entry, redact_secrets
from app.core.wiki_layers import find_preference, namespaced_tags

logger = logging.getLogger(__name__)

_DECISION = re.compile(r"决定|拍板|约定如下|原则是|以后都|不要再")
_INCIDENT = re.compile(r"失败|报错|根因|异常|修不好")
_INCIDENT_OK = re.compile(r"无异常|没有失败|运行正常|所有检查完成")
_STEP = re.compile(r"^(?:\d+[\.、)]|步骤\s*\d+|[-*] )")
_NOISE = re.compile(r"heartbeat poll|^NO_REPLY$", re.I)

_OPENCLAW_AGENTS = Path.home() / ".openclaw" / "agents"
_HERMES_SESSIONS = Path.home() / ".hermes" / "sessions"


def _clip(text: str, limit: int = 3500) -> str:
    cleaned = redact_secrets(text or "").strip()
    return cleaned[-limit:]


def _sentence_around(text: str, pattern: re.Pattern[str], span: int = 90) -> str:
    match = pattern.search(text or "")
    if not match:
        return ""
    start = max(0, match.start() - 24)
    end = min(len(text), match.end() + span)
    return re.sub(r"\s+", " ", text[start:end]).strip()


def extract_claims(user_text: str, assistant_text: str) -> list[dict[str, Any]]:
    """从一段用户/助手正文抽出 0..N 条主张。无信号则返回空。"""
    user = user_text or ""
    assistant = assistant_text or ""
    blob = f"{user}\n{assistant}".strip()
    compact = re.sub(r"\s+", " ", blob)
    if len(compact) < 40:
        return []
    if _NOISE.search(compact) and len(compact) < 160:
        return []

    claims: list[dict[str, Any]] = []
    preference = find_preference(blob)
    if preference:
        claims.append(
            {
                "facet": "preferences",
                "layer": "L1",
                "kind": "shared_fact",
                "title": f"偏好 · {preference[:48]}",
                "summary": preference,
                "payload": {"summary": preference, "body": preference},
            }
        )

    decision = _sentence_around(user, _DECISION) or _sentence_around(assistant[:800], _DECISION)
    if decision:
        claims.append(
            {
                "facet": "decisions",
                "layer": "L2",
                "kind": "precedent",
                "title": f"决策 · {decision[:48]}",
                "summary": decision,
                "payload": {"summary": decision},
            }
        )

    steps = [
        re.sub(r"\s+", " ", line.strip())
        for line in assistant.splitlines()
        if _STEP.match(line.strip()) and len(line.strip()) >= 8
    ][:8]
    if len(steps) >= 2:
        title_src = re.sub(r"\s+", " ", user).strip()[:60] or steps[0][:60]
        claims.append(
            {
                "facet": "procedural",
                "layer": "L3",
                "kind": "playbook",
                "title": f"步骤 · {title_src}",
                "summary": "；".join(steps[:4]),
                "payload": {"problem": title_src, "steps": steps, "pitfalls": []},
            }
        )

    if _INCIDENT.search(blob) and not _INCIDENT_OK.search(assistant[:240]):
        lesson = _sentence_around(blob, _INCIDENT)
        if lesson:
            claims.append(
                {
                    "facet": "reflections",
                    "layer": "L2",
                    "kind": "incident",
                    "title": f"教训 · {lesson[:48]}",
                    "summary": lesson,
                    "payload": {
                        "symptom": lesson,
                        "root_cause": lesson[:240],
                        "fix": "",
                        "automated": False,
                    },
                }
            )
    return claims


def _rows_to_text(rows: list[tuple[str, str]]) -> tuple[str, str]:
    users: list[str] = []
    assistants: list[str] = []
    for role, text in rows:
        body = (text or "").strip()
        if len(body) < 2 or body == "NO_REPLY":
            continue
        if "heartbeat poll" in body.lower():
            continue
        if role == "user":
            users.append(body)
        elif role == "assistant":
            assistants.append(body)
    return _clip("\n".join(users[-6:])), _clip("\n".join(assistants[-6:]))


def read_openclaw_turns(agent_id: str, session_id: str) -> tuple[str, str]:
    agent = (agent_id or "").strip()
    sid = (session_id or "").strip()
    if not agent or not sid or agent in (".", "..") or "/" in agent:
        return "", ""
    db_path = _OPENCLAW_AGENTS / agent / "agent" / "openclaw-agent.sqlite"
    if not db_path.is_file():
        return "", ""
    uri = f"file:{db_path}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=2)
    except sqlite3.Error as e:
        logger.warning("openclaw transcript open failed agent=%s err=%s", agent, e)
        return "", ""
    try:
        rows = con.execute(
            "SELECT c3, c0 FROM session_transcript_fts_content WHERE c1 = ?",
            (sid,),
        ).fetchall()
    except sqlite3.Error as e:
        logger.warning("openclaw transcript read failed session=%s err=%s", sid, e)
        return "", ""
    finally:
        con.close()
    return _rows_to_text([(str(role or ""), str(text or "")) for role, text in rows])


def read_hermes_jsonl(path: Path) -> tuple[str, str]:
    rows: list[tuple[str, str]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = str(item.get("role") or "")
                content = item.get("content") or ""
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            parts.append(str(block.get("text") or ""))
                        else:
                            parts.append(str(block))
                    content = "\n".join(parts)
                if role in ("user", "assistant") and isinstance(content, str):
                    rows.append((role, content))
    except OSError as e:
        logger.warning("hermes session read failed path=%s err=%s", path.name, e)
        return "", ""
    return _rows_to_text(rows)


async def _write_claims(
    *,
    claims: list[dict[str, Any]],
    session_id: str,
    agent_id: str,
    runtime: str,
    stats: dict[str, int],
) -> None:
    for claim in claims:
        facet = claim["facet"]
        tags = namespaced_tags(
            src="session",
            facet=facet,
            topic=claim["title"],
            extra=[runtime, agent_id],
        )
        await _upsert_entry(
            kind=claim["kind"],
            layer=claim["layer"],
            facet=facet,
            source_type="session",
            source_id=f"{session_id}:{facet}",
            title=claim["title"],
            content=claim["summary"],
            agent_id=agent_id,
            runtime=runtime,
            session_id=session_id,
            status="mined",
            tags=tags,
            payload=claim["payload"],
        )
        stats["written"] += 1
        stats[facet] = stats.get(facet, 0) + 1


def _empty_stats() -> dict[str, int]:
    return {
        "scanned": 0,
        "written": 0,
        "skipped": 0,
        "errors": 0,
        "preferences": 0,
        "decisions": 0,
        "procedural": 0,
        "reflections": 0,
    }


async def mine_recent_sessions(monitor: Any, limit: int = 24) -> dict[str, int]:
    """扫最近会话。OpenClaw 读本地库，Hermes 读本地 jsonl，不逐条调 CLI。"""
    stats = _empty_stats()
    cap = max(0, min(int(limit or 0), 80))
    if cap == 0:
        return stats

    try:
        sessions, _ = await monitor.get_sessions(limit=cap)
    except Exception as e:
        logger.error("session mine list failed: %s", e)
        stats["errors"] += 1
        sessions = []

    seen: set[str] = set()
    for item in sessions:
        if stats["scanned"] >= cap:
            break
        runtime = str(getattr(item, "runtime", "") or "")
        session_id = str(getattr(item, "session_id", "") or "")
        agent_id = str(getattr(item, "agent_id", "") or "")
        if runtime != "openclaw" or not session_id or session_id in seen:
            continue
        seen.add(session_id)
        stats["scanned"] += 1
        try:
            user_text, assistant_text = read_openclaw_turns(agent_id, session_id)
            claims = extract_claims(user_text, assistant_text)
            if not claims:
                stats["skipped"] += 1
                continue
            await _write_claims(
                claims=claims,
                session_id=session_id,
                agent_id=agent_id,
                runtime="openclaw",
                stats=stats,
            )
        except Exception as e:
            stats["errors"] += 1
            logger.warning("session mine openclaw failed session=%s err=%s", session_id, e)

    if _HERMES_SESSIONS.is_dir() and stats["scanned"] < cap:
        files = sorted(
            _HERMES_SESSIONS.glob("*.jsonl"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in files:
            if stats["scanned"] >= cap:
                break
            session_id = path.stem
            if session_id in seen:
                continue
            seen.add(session_id)
            stats["scanned"] += 1
            try:
                user_text, assistant_text = read_hermes_jsonl(path)
                claims = extract_claims(user_text, assistant_text)
                if not claims:
                    stats["skipped"] += 1
                    continue
                await _write_claims(
                    claims=claims,
                    session_id=session_id,
                    agent_id="default",
                    runtime="hermes",
                    stats=stats,
                )
            except Exception as e:
                stats["errors"] += 1
                logger.warning("session mine hermes failed session=%s err=%s", session_id, e)

    logger.info(
        "knowledge session mine scanned=%d written=%d skipped=%d errors=%d "
        "preferences=%d decisions=%d procedural=%d reflections=%d",
        stats["scanned"],
        stats["written"],
        stats["skipped"],
        stats["errors"],
        stats["preferences"],
        stats["decisions"],
        stats["procedural"],
        stats["reflections"],
    )
    return stats
