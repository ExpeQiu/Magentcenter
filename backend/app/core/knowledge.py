"""任务/会话消息知识库：入库 + 关键词预筛 + 哈希向量余弦重排。"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import or_, select

from app.core.text_embed import cosine, embed_text, embedder_status, hash_embed
from app.models.db import KnowledgeRecord, TaskRecord, get_session_factory

logger = logging.getLogger(__name__)

MAX_CONTENT = 20000
SNIPPET_LEN = 220


class KnowledgeHit(BaseModel):
    id: str
    source_type: str
    source_id: str
    runtime: str = ""
    agent_id: str = ""
    session_id: str = ""
    title: str = ""
    snippet: str = ""
    status: str = ""
    score: float = 0.0
    created_at: str = ""


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


async def _upsert_entry(
    *,
    source_type: str,
    source_id: str,
    title: str,
    content: str,
    agent_id: str = "",
    runtime: str = "",
    session_id: str = "",
    status: str = "",
) -> str:
    content = (content or "").strip()[:MAX_CONTENT]
    title = re.sub(r"\s+", " ", (title or "").strip())[:120] or source_id[:120]
    emb = await _embed_json(f"{title}\n{content}")
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(KnowledgeRecord).where(
                    KnowledgeRecord.source_type == source_type,
                    KnowledgeRecord.source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.title = title
            existing.content = content
            existing.agent_id = agent_id or existing.agent_id
            existing.runtime = runtime or existing.runtime
            existing.session_id = session_id or existing.session_id
            existing.status = status or existing.status
            existing.embedding_json = emb
            existing.updated_at = datetime.utcnow()
            kid = existing.id
        else:
            kid = str(uuid.uuid4())
            session.add(
                KnowledgeRecord(
                    id=kid,
                    source_type=source_type,
                    source_id=source_id,
                    runtime=runtime or "",
                    agent_id=agent_id or "",
                    session_id=session_id or "",
                    title=title,
                    content=content,
                    status=status or "",
                    embedding_json=emb,
                )
            )
        await session.commit()
    return kid


async def upsert_from_task(
    *,
    task_id: str,
    prompt: str,
    output: str,
    agent_id: str = "",
    runtime: str = "",
    session_id: str = "",
    status: str = "",
) -> str | None:
    """任务完成后写入/更新知识条目。"""
    if status and status not in ("completed", "failed", "timeout"):
        return None
    body = (output or "").strip()
    if not body and not (prompt or "").strip():
        return None

    title = re.sub(r"\s+", " ", (prompt or "").strip())[:120] or f"task:{task_id[:8]}"
    content = f"{prompt or ''}\n---\n{body}".strip()
    kid = await _upsert_entry(
        source_type="task",
        source_id=task_id,
        title=title,
        content=content,
        agent_id=agent_id,
        runtime=runtime,
        session_id=session_id,
        status=status,
    )
    logger.info(
        "knowledge upsert source=task id=%s task=%s runtime=%s status=%s",
        kid,
        task_id,
        runtime,
        status,
    )
    return kid


async def index_session_messages(detail: Any) -> int:
    """将 SessionDetail.messages 逐条写入知识库（幂等）。"""
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
        content = str(getattr(msg, "content", "") or "").strip()
        if len(content) < 2:
            continue
        # 跳过纯工具噪声
        if role in ("tool", "toolResult") and len(content) < 8:
            continue
        source_id = f"{session_id}:{i}:{role}"
        title = f"[{runtime or '?'}] {role} · {session_id[:12]}"
        await _upsert_entry(
            source_type="session_msg",
            source_id=source_id,
            title=title,
            content=content,
            agent_id=agent_id,
            runtime=runtime,
            session_id=session_id,
            status=role,
        )
        count += 1
    logger.info(
        "knowledge session indexed session=%s messages=%d indexed=%d runtime=%s",
        session_id,
        len(messages),
        count,
        runtime,
    )
    return count


async def backfill_from_tasks(limit: int = 200) -> int:
    """从已有任务表补索引（幂等）。"""
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
        kid = await upsert_from_task(
            task_id=rec.id,
            prompt=rec.prompt or "",
            output=rec.output or "",
            agent_id=rec.agent_id or "",
            runtime=rec.runtime or "",
            session_id=rec.session_id or "",
            status=rec.status or "",
        )
        if kid:
            count += 1
    logger.info("knowledge backfill tasks=%d indexed=%d", len(rows), count)
    return count


async def search_knowledge(
    query: str,
    *,
    limit: int = 20,
    runtime: str | None = None,
    auto_backfill: bool = True,
    mode: str = "hybrid",
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

    factory = get_session_factory()
    async with factory() as session:
        if mode == "vector":
            stmt = select(KnowledgeRecord)
            if runtime:
                stmt = stmt.where(KnowledgeRecord.runtime == runtime)
            stmt = stmt.order_by(KnowledgeRecord.updated_at.desc()).limit(300)
            rows = (await session.execute(stmt)).scalars().all()
        else:
            like_clauses = []
            for t in tokens:
                pattern = f"%{t}%"
                like_clauses.append(KnowledgeRecord.title.ilike(pattern))
                like_clauses.append(KnowledgeRecord.content.ilike(pattern))
            stmt = select(KnowledgeRecord).where(or_(*like_clauses))
            if runtime:
                stmt = stmt.where(KnowledgeRecord.runtime == runtime)
            stmt = stmt.order_by(KnowledgeRecord.updated_at.desc()).limit(
                max(limit * 6, 80)
            )
            rows = list((await session.execute(stmt)).scalars().all())

            # hybrid：关键词命中偏少时，补一批最近条目做向量重排
            if mode == "hybrid" and len(rows) < limit:
                extra_stmt = select(KnowledgeRecord).order_by(
                    KnowledgeRecord.updated_at.desc()
                ).limit(120)
                if runtime:
                    extra_stmt = extra_stmt.where(KnowledgeRecord.runtime == runtime)
                seen = {r.id for r in rows}
                for r in (await session.execute(extra_stmt)).scalars().all():
                    if r.id not in seen:
                        rows.append(r)
                        seen.add(r.id)

    hits: list[KnowledgeHit] = []
    for r in rows:
        # 缺 embedding 时即时补
        emb = _parse_embed(getattr(r, "embedding_json", "") or "")
        if not emb and (r.title or r.content):
            # 维度不一致时用 hash 兜底（与旧条目兼容）
            emb = hash_embed(f"{r.title}\n{r.content}")
        # 维度不同无法余弦 → 跳过向量分
        vec = cosine(q_vec, emb) if emb and len(emb) == len(q_vec) else 0.0
        if vec == 0.0 and emb and len(emb) != len(q_vec):
            # 与 query 维度不一致时用 hash 双方对齐
            hq = hash_embed(q)
            he = hash_embed(f"{r.title}\n{r.content}")
            vec = cosine(hq, he)
        kw = _keyword_score(r.title, r.content, tokens)
        if mode == "keyword":
            score = kw
        elif mode == "vector":
            score = vec * 10.0
        else:
            score = kw + vec * 8.0
        if score <= 0:
            continue
        hits.append(
            KnowledgeHit(
                id=r.id,
                source_type=r.source_type,
                source_id=r.source_id,
                runtime=r.runtime,
                agent_id=r.agent_id,
                session_id=r.session_id,
                title=r.title,
                snippet=_snip(r.content, q),
                status=r.status,
                score=round(score, 4),
                created_at=(r.created_at.isoformat() + "Z") if r.created_at else "",
            )
        )
    hits.sort(key=lambda h: (-h.score, h.created_at or ""))
    result = hits[: max(1, min(limit, 50))]
    logger.info(
        "knowledge search q=%r mode=%s provider=%s hits=%d",
        q[:80],
        mode,
        embedder_status().get("provider"),
        len(result),
    )
    return result
