"""知识库：卡片内容模型（Playbook / Precedent / Incident / ArtifactRef / SharedFact）。

检索主路径走结构化卡片摘要；原始任务全文仅作可选 archive。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.core.text_embed import cosine, embed_text, embedder_status, hash_embed
from app.models.db import KnowledgeRecord, TaskRecord, get_session_factory

logger = logging.getLogger(__name__)

MAX_CONTENT = 20000
SNIPPET_LEN = 220
SUMMARY_LEN = 500
INJECT_BLOCK_MAX = 2400

KnowledgeKind = Literal[
    "playbook",
    "precedent",
    "incident",
    "artifact_ref",
    "shared_fact",
    "archive",
]

CARD_KINDS = (
    "playbook",
    "precedent",
    "incident",
    "artifact_ref",
    "shared_fact",
)

# 注入默认检索种类（不含 archive 噪声）
INJECT_KINDS_DEFAULT = ("playbook", "precedent", "shared_fact")
OPS_INJECT_KINDS = ("incident", "playbook", "shared_fact")

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
    re.compile(r"https://open\.feishu\.cn/open-apis/bot/v2/hook/\S+"),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
]


class KnowledgeHit(BaseModel):
    id: str
    kind: str = "archive"
    source_type: str
    source_id: str
    runtime: str = ""
    agent_id: str = ""
    session_id: str = ""
    workspace_id: str = ""
    title: str = ""
    snippet: str = ""
    status: str = ""
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0
    created_at: str = ""


class KnowledgeEntryCreate(BaseModel):
    kind: KnowledgeKind
    title: str
    summary: str = ""
    workspace_id: str = ""
    runtime: str = ""
    agent_id: str = ""
    session_id: str = ""
    source_type: str = "manual"
    source_id: str = ""
    tags: list[str] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)


def redact_secrets(text: str) -> str:
    out = text or ""
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def _snip(text: str, query: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return ""
    q = (query or "").strip().lower()
    if q:
        idx = text.lower().find(q)
        if idx >= 0:
            start = max(0, idx - 40)
            end = min(len(text), idx + SNIPPET_LEN)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(text) else ""
            return f"{prefix}{text[start:end]}{suffix}"
    return text[:SNIPPET_LEN] + ("…" if len(text) > SNIPPET_LEN else "")


def _keyword_score(title: str, content: str, tokens: list[str]) -> float:
    hay = f"{title}\n{content}".lower()
    if not tokens:
        return 0.0
    hits = sum(1 for t in tokens if t in hay)
    bonus = 2.0 if any(t in (title or "").lower() for t in tokens) else 0.0
    return hits + bonus


def _parse_tags(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def _parse_payload(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


async def _embed_json(text: str) -> str:
    vec = await embed_text(text)
    return json.dumps(vec, separators=(",", ":"))


def _parse_embed(raw: str) -> list[float]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [float(x) for x in data]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def _record_kind(rec: KnowledgeRecord) -> str:
    kind = (getattr(rec, "kind", None) or "").strip()
    if kind:
        return kind
    # 旧数据：任务/会话原文视为 archive
    return "archive"


def _content_from_card(
    *,
    kind: str,
    title: str,
    summary: str,
    payload: dict[str, Any],
    tags: list[str],
) -> str:
    parts = [title, summary]
    if kind == "playbook":
        for key in ("problem", "steps", "outcome", "pitfalls"):
            val = payload.get(key)
            if val:
                parts.append(f"{key}: {val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)}")
    elif kind == "incident":
        for key in ("symptom", "root_cause", "fix", "cron_id"):
            val = payload.get(key)
            if val:
                parts.append(f"{key}: {val}")
    elif kind == "artifact_ref":
        for key in ("path", "structure_notes"):
            val = payload.get(key)
            if val:
                parts.append(f"{key}: {val}")
    elif kind == "shared_fact":
        body = payload.get("body") or payload.get("fact")
        if body:
            parts.append(str(body))
    if tags:
        parts.append("tags: " + ", ".join(tags))
    text = "\n".join(p for p in parts if p).strip()
    return redact_secrets(text)[:MAX_CONTENT]


def _hit_from_record(r: KnowledgeRecord, query: str, score: float) -> KnowledgeHit:
    return KnowledgeHit(
        id=r.id,
        kind=_record_kind(r),
        source_type=r.source_type or "",
        source_id=r.source_id or "",
        runtime=r.runtime or "",
        agent_id=r.agent_id or "",
        session_id=r.session_id or "",
        workspace_id=getattr(r, "workspace_id", "") or "",
        title=r.title or "",
        snippet=_snip(r.content, query),
        status=r.status or "",
        tags=_parse_tags(getattr(r, "tags_json", "") or ""),
        payload=_parse_payload(getattr(r, "payload_json", "") or ""),
        score=round(score, 4),
        created_at=(r.created_at.isoformat() + "Z") if r.created_at else "",
    )


async def _upsert_entry(
    *,
    kind: str,
    source_type: str,
    source_id: str,
    title: str,
    content: str,
    agent_id: str = "",
    runtime: str = "",
    session_id: str = "",
    status: str = "",
    workspace_id: str = "",
    tags: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    content = redact_secrets((content or "").strip())[:MAX_CONTENT]
    title = re.sub(r"\s+", " ", redact_secrets(title or "").strip())[:120] or source_id[:120]
    tags = tags or []
    payload = payload or {}
    emb = await _embed_json(f"{title}\n{content}")
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.kind == kind,
                    KnowledgeRecord.source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        # 兼容旧库：无 kind 列匹配时按 source_type+source_id
        if existing is None and kind == "archive":
            existing = (
                await session.execute(
                    select(KnowledgeRecord).where(
                        KnowledgeRecord.source_type == source_type,
                        KnowledgeRecord.source_id == source_id,
                    )
                )
            ).scalar_one_or_none()
        if existing:
            existing.kind = kind
            existing.source_type = source_type
            existing.title = title
            existing.content = content
            existing.agent_id = agent_id or existing.agent_id
            existing.runtime = runtime or existing.runtime
            existing.session_id = session_id or existing.session_id
            existing.status = status or existing.status
            existing.workspace_id = workspace_id or getattr(existing, "workspace_id", "") or ""
            existing.tags_json = json.dumps(tags, ensure_ascii=False)
            existing.payload_json = json.dumps(payload, ensure_ascii=False)
            existing.embedding_json = emb
            existing.updated_at = datetime.utcnow()
            kid = existing.id
        else:
            kid = str(uuid.uuid4())
            session.add(
                KnowledgeRecord(
                    id=kid,
                    kind=kind,
                    source_type=source_type,
                    source_id=source_id,
                    runtime=runtime or "",
                    agent_id=agent_id or "",
                    session_id=session_id or "",
                    workspace_id=workspace_id or "",
                    title=title,
                    content=content,
                    status=status or "",
                    tags_json=json.dumps(tags, ensure_ascii=False),
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    embedding_json=emb,
                )
            )
        await session.commit()
    return kid


def _rule_summary(prompt: str, output: str, error: str = "") -> str:
    prompt = redact_secrets((prompt or "").strip())
    output = redact_secrets((output or "").strip())
    error = redact_secrets((error or "").strip())
    head = re.sub(r"\s+", " ", prompt)[:160]
    body = re.sub(r"\s+", " ", output or error)[:320]
    text = f"{head} → {body}".strip(" →")
    return text[:SUMMARY_LEN]


def _rule_steps(output: str) -> list[str]:
    lines = [ln.strip(" -*\t") for ln in (output or "").splitlines() if ln.strip()]
    steps = [ln for ln in lines if len(ln) >= 8][:8]
    if not steps and output.strip():
        steps = [re.sub(r"\s+", " ", output.strip())[:200]]
    return steps[:8]


async def distill_from_task(
    *,
    task_id: str,
    prompt: str,
    output: str,
    agent_id: str = "",
    runtime: str = "",
    session_id: str = "",
    status: str = "",
    workspace_id: str = "",
    error: str = "",
    keep_archive: bool = False,
) -> dict[str, str]:
    """任务结束后蒸馏卡片。成功→precedent+playbook；失败→precedent+incident。"""
    if status and status not in ("completed", "failed", "timeout"):
        return {}
    if not (prompt or "").strip() and not (output or "").strip() and not (error or "").strip():
        return {}

    summary = _rule_summary(prompt, output, error)
    title = re.sub(r"\s+", " ", redact_secrets(prompt or "").strip())[:120] or f"task:{task_id[:8]}"
    tags = [t for t in (runtime, agent_id, status) if t]
    created: dict[str, str] = {}

    # 先例索引（轻量）
    precedent_payload = {
        "summary": summary,
        "task_id": task_id,
        "session_id": session_id,
    }
    content = _content_from_card(
        kind="precedent",
        title=title,
        summary=summary,
        payload=precedent_payload,
        tags=tags,
    )
    created["precedent"] = await _upsert_entry(
        kind="precedent",
        source_type="task",
        source_id=task_id,
        title=title,
        content=content,
        agent_id=agent_id,
        runtime=runtime,
        session_id=session_id,
        status=status,
        workspace_id=workspace_id,
        tags=tags,
        payload=precedent_payload,
    )

    if status == "completed":
        steps = _rule_steps(output)
        playbook_payload = {
            "problem": title,
            "steps": steps,
            "outcome": summary[-200:] if summary else "completed",
            "pitfalls": [],
            "source_refs": {"task_id": task_id, "session_id": session_id},
        }
        pb_content = _content_from_card(
            kind="playbook",
            title=f"Playbook · {title[:80]}",
            summary=summary,
            payload=playbook_payload,
            tags=tags + ["playbook"],
        )
        created["playbook"] = await _upsert_entry(
            kind="playbook",
            source_type="task",
            source_id=f"{task_id}:playbook",
            title=f"Playbook · {title[:80]}",
            content=pb_content,
            agent_id=agent_id,
            runtime=runtime,
            session_id=session_id,
            status=status,
            workspace_id=workspace_id,
            tags=tags + ["playbook"],
            payload=playbook_payload,
        )
    elif status in ("failed", "timeout"):
        incident_payload = {
            "symptom": title,
            "root_cause": redact_secrets(error or output or "unknown")[:400],
            "fix": "见关联任务日志；优先查环境变量 / 网络 / 余额 / Mock",
            "task_id": task_id,
            "automated": False,
        }
        inc_content = _content_from_card(
            kind="incident",
            title=f"Incident · {title[:80]}",
            summary=summary,
            payload=incident_payload,
            tags=tags + ["incident"],
        )
        created["incident"] = await _upsert_entry(
            kind="incident",
            source_type="task",
            source_id=f"{task_id}:incident",
            title=f"Incident · {title[:80]}",
            content=inc_content,
            agent_id=agent_id,
            runtime=runtime,
            session_id=session_id,
            status=status,
            workspace_id=workspace_id,
            tags=tags + ["incident"],
            payload=incident_payload,
        )

    if keep_archive:
        body = f"{prompt or ''}\n---\n{output or error or ''}".strip()
        created["archive"] = await _upsert_entry(
            kind="archive",
            source_type="task",
            source_id=f"{task_id}:archive",
            title=title,
            content=redact_secrets(body),
            agent_id=agent_id,
            runtime=runtime,
            session_id=session_id,
            status=status,
            workspace_id=workspace_id,
            tags=tags + ["archive"],
            payload={"task_id": task_id},
        )

    logger.info(
        "knowledge distill task=%s status=%s kinds=%s workspace=%s",
        task_id,
        status,
        list(created.keys()),
        workspace_id or "-",
    )
    return created


async def upsert_from_task(
    *,
    task_id: str,
    prompt: str,
    output: str,
    agent_id: str = "",
    runtime: str = "",
    session_id: str = "",
    status: str = "",
    workspace_id: str = "",
    error: str = "",
) -> str | None:
    """兼容旧调用：蒸馏卡片并返回 precedent id。"""
    created = await distill_from_task(
        task_id=task_id,
        prompt=prompt,
        output=output,
        agent_id=agent_id,
        runtime=runtime,
        session_id=session_id,
        status=status,
        workspace_id=workspace_id,
        error=error,
        keep_archive=False,
    )
    return created.get("precedent") or next(iter(created.values()), None)


async def index_session_messages(detail: Any, workspace_id: str = "") -> int:
    """Session 消息写入 archive（非默认检索主路径；保留手工归档）。"""
    if not detail:
        return 0
    session_id = str(getattr(detail, "session_id", "") or "")
    if not session_id:
        return 0
    runtime = str(getattr(detail, "runtime", "") or "")
    agent_id = str(getattr(detail, "agent_id", "") or "")
    messages = list(getattr(detail, "messages", None) or [])
    count = 0
    for i, msg in enumerate(messages):
        role = str(getattr(msg, "role", "") or "")
        content = redact_secrets(str(getattr(msg, "content", "") or "").strip())
        if len(content) < 2:
            continue
        if role in ("tool", "toolResult") and len(content) < 8:
            continue
        source_id = f"{session_id}:{i}:{role}"
        title = f"[{runtime or '?'}] {role} · {session_id[:12]}"
        await _upsert_entry(
            kind="archive",
            source_type="session_msg",
            source_id=source_id,
            title=title,
            content=content,
            agent_id=agent_id,
            runtime=runtime,
            session_id=session_id,
            status=role,
            workspace_id=workspace_id,
            tags=[runtime, "session_msg"] if runtime else ["session_msg"],
            payload={"role": role, "index": i},
        )
        count += 1
    logger.info(
        "knowledge session archived session=%s messages=%d indexed=%d runtime=%s",
        session_id,
        len(messages),
        count,
        runtime,
    )
    return count


async def create_entry(req: KnowledgeEntryCreate) -> KnowledgeHit:
    kind = req.kind
    if kind not in CARD_KINDS and kind != "archive":
        raise ValueError(f"unsupported kind: {kind}")
    source_id = req.source_id or f"manual:{uuid.uuid4().hex[:12]}"
    summary = redact_secrets(req.summary or req.payload.get("summary", "") or "")[:SUMMARY_LEN]
    payload = {k: v for k, v in (req.payload or {}).items()}
    if summary and "summary" not in payload:
        payload["summary"] = summary
    content = _content_from_card(
        kind=kind,
        title=req.title,
        summary=summary,
        payload=payload,
        tags=req.tags,
    )
    kid = await _upsert_entry(
        kind=kind,
        source_type=req.source_type or "manual",
        source_id=source_id,
        title=req.title,
        content=content,
        agent_id=req.agent_id,
        runtime=req.runtime,
        session_id=req.session_id,
        status="active",
        workspace_id=req.workspace_id,
        tags=req.tags,
        payload=payload,
    )
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(KnowledgeRecord, kid)
    assert rec is not None
    return _hit_from_record(rec, "", 1.0)


async def get_entry(entry_id: str) -> KnowledgeHit | None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(KnowledgeRecord, entry_id)
    if not rec:
        return None
    return _hit_from_record(rec, "", 1.0)


async def delete_entry(entry_id: str) -> bool:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(KnowledgeRecord, entry_id)
        if not rec:
            return False
        await session.delete(rec)
        await session.commit()
    logger.info("knowledge entry deleted id=%s", entry_id)
    return True


async def list_entries(
    *,
    limit: int = 50,
    kind: str | None = None,
    workspace_id: str | None = None,
    runtime: str | None = None,
) -> list[KnowledgeHit]:
    kinds = [k.strip() for k in (kind or "").split(",") if k.strip()]
    factory = get_session_factory()
    async with factory() as session:
        stmt = select(KnowledgeRecord).order_by(KnowledgeRecord.updated_at.desc()).limit(
            max(1, min(limit, 200))
        )
        if len(kinds) == 1:
            stmt = stmt.where(KnowledgeRecord.kind == kinds[0])
        elif len(kinds) > 1:
            stmt = stmt.where(KnowledgeRecord.kind.in_(kinds))
        else:
            # 默认不列 archive 原文
            stmt = stmt.where(KnowledgeRecord.kind.in_(CARD_KINDS))
        if workspace_id:
            stmt = stmt.where(
                or_(
                    KnowledgeRecord.workspace_id == workspace_id,
                    KnowledgeRecord.workspace_id == "",
                    KnowledgeRecord.workspace_id.is_(None),
                )
            )
        if runtime:
            stmt = stmt.where(KnowledgeRecord.runtime == runtime)
        rows = (await session.execute(stmt)).scalars().all()
    return [_hit_from_record(r, "", 1.0) for r in rows]


async def backfill_from_tasks(limit: int = 200) -> int:
    """从已有任务表蒸馏卡片（幂等）。"""
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(TaskRecord)
                .where(TaskRecord.status.in_(("completed", "failed", "timeout")))
                .order_by(TaskRecord.updated_at.desc())
                .limit(limit)
            )
        ).scalars().all()

    count = 0
    for rec in rows:
        created = await distill_from_task(
            task_id=rec.id,
            prompt=rec.prompt or "",
            output=rec.output or "",
            agent_id=rec.agent_id or "",
            runtime=rec.runtime or "",
            session_id=rec.session_id or "",
            status=rec.status or "",
            workspace_id=getattr(rec, "workspace_id", "") or "",
            error=rec.error or "",
        )
        if created:
            count += 1
    logger.info("knowledge backfill tasks=%d distilled=%d", len(rows), count)
    return count


async def upsert_artifact_ref(
    *,
    path: str,
    title: str,
    summary: str = "",
    runtime: str = "",
    workspace_id: str = "",
    tags: list[str] | None = None,
    structure_notes: str = "",
    task_id: str = "",
    session_id: str = "",
) -> str:
    tags = tags or []
    payload = {
        "path": path,
        "summary": summary,
        "structure_notes": structure_notes,
        "task_id": task_id,
        "session_id": session_id,
    }
    content = _content_from_card(
        kind="artifact_ref",
        title=title,
        summary=summary,
        payload=payload,
        tags=tags,
    )
    return await _upsert_entry(
        kind="artifact_ref",
        source_type="outputs",
        source_id=path,
        title=title,
        content=content,
        runtime=runtime,
        session_id=session_id,
        status="active",
        workspace_id=workspace_id,
        tags=tags,
        payload=payload,
    )


async def upsert_incident_from_alert(
    *,
    alert_key: str,
    title: str,
    symptom: str,
    root_cause: str = "",
    fix: str = "",
    cron_id: str = "",
    runtime: str = "",
    workspace_id: str = "",
) -> str:
    payload = {
        "symptom": symptom,
        "root_cause": root_cause,
        "fix": fix,
        "cron_id": cron_id,
        "automated": False,
    }
    tags = [t for t in (runtime, "incident", "alert") if t]
    content = _content_from_card(
        kind="incident",
        title=title,
        summary=symptom[:SUMMARY_LEN],
        payload=payload,
        tags=tags,
    )
    return await _upsert_entry(
        kind="incident",
        source_type="alert",
        source_id=alert_key,
        title=title,
        content=content,
        runtime=runtime,
        status="open",
        workspace_id=workspace_id,
        tags=tags,
        payload=payload,
    )


def format_inject_block(hits: list[KnowledgeHit], *, max_chars: int = INJECT_BLOCK_MAX) -> str:
    if not hits:
        return ""
    lines = [
        "## AgentCenter 知识库参考（自动注入）",
        "以下为已验证经验/先例，请优先沿用；细节可按 source 溯源。勿复述密钥。",
        "",
    ]
    for h in hits:
        lines.append(f"### [{h.kind}] {h.title or h.source_id}")
        summary = h.payload.get("summary") or h.snippet
        if summary:
            lines.append(str(summary)[:280])
        if h.kind == "playbook" and h.payload.get("steps"):
            steps = h.payload["steps"]
            if isinstance(steps, list):
                for i, s in enumerate(steps[:5], 1):
                    lines.append(f"{i}. {s}")
        if h.kind == "incident":
            if h.payload.get("fix"):
                lines.append(f"修复建议: {h.payload['fix']}")
            if h.payload.get("root_cause"):
                lines.append(f"根因线索: {h.payload['root_cause']}")
        refs = []
        if h.source_type == "task" or h.payload.get("task_id"):
            tid = h.payload.get("task_id") or (
                h.source_id.split(":")[0] if h.source_type == "task" else ""
            )
            if tid:
                refs.append(f"task:{tid}")
        if h.session_id:
            refs.append(f"session:{h.session_id}")
        if h.payload.get("path"):
            refs.append(f"path:{h.payload['path']}")
        if refs:
            lines.append("source: " + ", ".join(refs))
        lines.append("")
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n…(截断)"
    return text


async def search_knowledge(
    query: str,
    *,
    limit: int = 20,
    runtime: str | None = None,
    workspace_id: str | None = None,
    kinds: list[str] | None = None,
    auto_backfill: bool = True,
    mode: str = "hybrid",
    include_archive: bool = False,
) -> list[KnowledgeHit]:
    """mode: keyword | vector | hybrid（默认）。"""
    q = (query or "").strip()
    if not q:
        return []
    tokens = [t for t in re.split(r"\s+", q.lower()) if len(t) >= 2][:8]
    if not tokens:
        tokens = [q.lower()]
    mode = mode if mode in ("keyword", "vector", "hybrid") else "hybrid"
    q_vec = await embed_text(q)

    factory = get_session_factory()
    async with factory() as session:
        total = (
            await session.execute(select(KnowledgeRecord.id).limit(1))
        ).scalar_one_or_none()
    if total is None and auto_backfill:
        await backfill_from_tasks()

    allow_kinds = list(kinds) if kinds else list(CARD_KINDS)
    if include_archive and "archive" not in allow_kinds:
        allow_kinds.append("archive")

    factory = get_session_factory()
    async with factory() as session:
        if mode == "vector":
            stmt = select(KnowledgeRecord)
            if runtime:
                stmt = stmt.where(KnowledgeRecord.runtime == runtime)
            if workspace_id:
                stmt = stmt.where(
                    or_(
                        KnowledgeRecord.workspace_id == workspace_id,
                        KnowledgeRecord.workspace_id == "",
                        KnowledgeRecord.workspace_id.is_(None),
                    )
                )
            stmt = stmt.order_by(KnowledgeRecord.updated_at.desc()).limit(300)
            rows = list((await session.execute(stmt)).scalars().all())
        else:
            like_clauses = []
            for t in tokens:
                pattern = f"%{t}%"
                like_clauses.append(KnowledgeRecord.title.ilike(pattern))
                like_clauses.append(KnowledgeRecord.content.ilike(pattern))
            stmt = select(KnowledgeRecord).where(or_(*like_clauses))
            if runtime:
                stmt = stmt.where(KnowledgeRecord.runtime == runtime)
            if workspace_id:
                stmt = stmt.where(
                    or_(
                        KnowledgeRecord.workspace_id == workspace_id,
                        KnowledgeRecord.workspace_id == "",
                        KnowledgeRecord.workspace_id.is_(None),
                    )
                )
            stmt = stmt.order_by(KnowledgeRecord.updated_at.desc()).limit(
                max(limit * 6, 80)
            )
            rows = list((await session.execute(stmt)).scalars().all())

            if mode == "hybrid" and len(rows) < limit:
                extra_stmt = select(KnowledgeRecord).order_by(
                    KnowledgeRecord.updated_at.desc()
                ).limit(120)
                if runtime:
                    extra_stmt = extra_stmt.where(KnowledgeRecord.runtime == runtime)
                if workspace_id:
                    extra_stmt = extra_stmt.where(
                        or_(
                            KnowledgeRecord.workspace_id == workspace_id,
                            KnowledgeRecord.workspace_id == "",
                            KnowledgeRecord.workspace_id.is_(None),
                        )
                    )
                seen = {r.id for r in rows}
                for r in (await session.execute(extra_stmt)).scalars().all():
                    if r.id not in seen:
                        rows.append(r)
                        seen.add(r.id)

    hits: list[KnowledgeHit] = []
    for r in rows:
        kind = _record_kind(r)
        if kind not in allow_kinds:
            continue
        emb = _parse_embed(getattr(r, "embedding_json", "") or "")
        if not emb and (r.title or r.content):
            emb = hash_embed(f"{r.title}\n{r.content}")
        vec = cosine(q_vec, emb) if emb and len(emb) == len(q_vec) else 0.0
        if vec == 0.0 and emb and len(emb) != len(q_vec):
            hq = hash_embed(q)
            he = hash_embed(f"{r.title}\n{r.content}")
            vec = cosine(hq, he)
        kw = _keyword_score(r.title, r.content, tokens)
        # 卡片加权：playbook/shared_fact 略优先
        kind_bonus = {
            "playbook": 1.5,
            "shared_fact": 1.2,
            "incident": 1.3,
            "precedent": 1.0,
            "artifact_ref": 0.9,
            "archive": 0.3,
        }.get(kind, 0.5)
        if mode == "keyword":
            score = (kw + kind_bonus) if kw > 0 else 0.0
        elif mode == "vector":
            score = vec * 10.0 + kind_bonus
        else:
            score = kw + vec * 8.0 + kind_bonus
        if score <= 0:
            continue
        hits.append(_hit_from_record(r, q, score))
    hits.sort(key=lambda h: (-h.score, h.created_at or ""))
    result = hits[: max(1, min(limit, 50))]
    logger.info(
        "knowledge search q=%r mode=%s kinds=%s provider=%s hits=%d",
        q[:80],
        mode,
        allow_kinds,
        embedder_status().get("provider"),
        len(result),
    )
    return result


async def build_task_inject_context(
    prompt: str,
    *,
    workspace_id: str = "",
    runtime: str | None = None,
    top_k: int = 3,
    kinds: list[str] | None = None,
    for_ops: bool = False,
) -> tuple[str, list[KnowledgeHit]]:
    """任务前检索 → 注入块。返回 (block, hits)。"""
    q = (prompt or "").strip()
    if not q:
        return "", []
    use_kinds = list(kinds) if kinds else list(
        OPS_INJECT_KINDS if for_ops else INJECT_KINDS_DEFAULT
    )
    hits = await search_knowledge(
        q,
        limit=top_k,
        runtime=runtime,
        workspace_id=workspace_id or None,
        kinds=use_kinds,
        auto_backfill=False,
        mode="hybrid",
        include_archive=False,
    )
    block = format_inject_block(hits)
    logger.info(
        "knowledge inject hits=%d workspace=%s runtime=%s for_ops=%s",
        len(hits),
        workspace_id or "-",
        runtime or "-",
        for_ops,
    )
    return block, hits
