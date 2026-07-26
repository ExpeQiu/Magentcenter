"""知识库检索 / Session 消息索引 API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.core.knowledge import (
    KnowledgeHit,
    backfill_from_tasks,
    index_session_messages,
    search_knowledge,
)
from app.core.text_embed import embedder_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/status")
async def knowledge_status():
    return {"status": "ok", "embedding": embedder_status()}


@router.get("/search", response_model=list[KnowledgeHit])
async def knowledge_search(
    q: str = Query(..., min_length=1, description="检索关键词"),
    limit: int = Query(20, ge=1, le=50),
    runtime: str | None = Query(None, description="openclaw|hermes"),
    mode: str = Query("hybrid", description="keyword|vector|hybrid"),
):
    if runtime and runtime not in ("openclaw", "hermes"):
        runtime = None
    hits = await search_knowledge(q, limit=limit, runtime=runtime, mode=mode)
    logger.info("api knowledge search q=%r mode=%s hits=%d", q[:80], mode, len(hits))
    return hits


@router.post("/backfill")
async def knowledge_backfill(limit: int = Query(200, ge=1, le=1000)):
    n = await backfill_from_tasks(limit=limit)
    return {"indexed": n, "status": "ok", "embedding": embedder_status()}


@router.post("/index-session/{session_id}")
async def index_session(
    request: Request,
    session_id: str = Path(..., description="Session ID"),
):
    """拉取 Session 详情并将消息写入知识库。"""
    monitor = request.app.state.monitor
    detail = await monitor.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    if not detail.messages:
        return {
            "status": "ok",
            "session_id": session_id,
            "indexed": 0,
            "message": "no messages",
        }
    n = await index_session_messages(detail)
    return {
        "status": "ok",
        "session_id": session_id,
        "runtime": detail.runtime,
        "indexed": n,
    }
