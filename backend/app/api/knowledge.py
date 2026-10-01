"""知识库检索 / 卡片管理 / Session 归档 / 注入预览 API。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from app.core.knowledge import (
    KnowledgeEntryCreate,
    KnowledgeHit,
    build_task_inject_context,
    create_entry,
    delete_entry,
    get_entry,
    index_session_messages,
    list_entries,
    search_knowledge,
    backfill_from_tasks,
    backfill_layers,
    upsert_artifact_ref,
)
from app.core.knowledge_vault_mine import mine_vault_docs
from app.core.text_embed import embedder_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class ArtifactRefRequest(BaseModel):
    path: str
    title: str
    summary: str = ""
    runtime: str = ""
    workspace_id: str = ""
    tags: list[str] = Field(default_factory=list)
    structure_notes: str = ""
    task_id: str = ""
    session_id: str = ""


class InjectPreviewResponse(BaseModel):
    block: str
    hits: list[KnowledgeHit]


class MineVaultRequest(BaseModel):
    scope: str = "openclaw"
    limit: int = Field(300, ge=1, le=2000)
    distill_high_value: bool = True
    workspace_id: str = ""


@router.get("/status")
async def knowledge_status():
    return {
        "status": "ok",
        "embedding": embedder_status(),
        "kinds": [
            "playbook",
            "precedent",
            "incident",
            "artifact_ref",
            "shared_fact",
            "archive",
        ],
        "layers": ["L2", "L3", "L1", "notes"],
        "inject_default_layers": ["L2", "L3", "L1"],
    }


@router.get("/search", response_model=list[KnowledgeHit])
async def knowledge_search(
    q: str = Query(..., min_length=1, description="检索关键词"),
    limit: int = Query(20, ge=1, le=50),
    runtime: str | None = Query(None, description="openclaw|hermes"),
    workspace_id: str | None = Query(None),
    kind: str | None = Query(None, description="逗号分隔 kind 过滤"),
    layer: str | None = Query(None, description="逗号分隔 L2,L3,L1,notes"),
    mode: str = Query("hybrid", description="keyword|vector|hybrid"),
    include_archive: bool = Query(False),
):
    if runtime and runtime not in ("openclaw", "hermes"):
        runtime = None
    kinds = [k.strip() for k in (kind or "").split(",") if k.strip()] or None
    layers = [x.strip() for x in (layer or "").split(",") if x.strip()] or None
    if layers and "notes" in layers:
        include_archive = True
    hits = await search_knowledge(
        q,
        limit=limit,
        runtime=runtime,
        workspace_id=workspace_id,
        kinds=kinds,
        layers=layers,
        mode=mode,
        include_archive=include_archive,
    )
    logger.info(
        "api knowledge search q=%r mode=%s kinds=%s hits=%d",
        q[:80],
        mode,
        kinds,
        len(hits),
    )
    return hits


@router.get("/entries", response_model=list[KnowledgeHit])
async def knowledge_list(
    limit: int = Query(50, ge=1, le=200),
    kind: str | None = None,
    layer: str | None = None,
    workspace_id: str | None = None,
    runtime: str | None = None,
):
    return await list_entries(
        limit=limit,
        kind=kind,
        layer=layer,
        workspace_id=workspace_id,
        runtime=runtime,
    )


@router.get("/entries/{entry_id}", response_model=KnowledgeHit)
async def knowledge_get(entry_id: str = Path(...)):
    if entry_id.startswith("wiki:"):
        from app.core.wiki_files import get_wiki_hit

        wiki_hit = get_wiki_hit(entry_id)
        if not wiki_hit:
            raise HTTPException(status_code=404, detail="entry not found")
        return wiki_hit
    hit = await get_entry(entry_id)
    if not hit:
        raise HTTPException(status_code=404, detail="entry not found")
    return hit


@router.post("/entries", response_model=KnowledgeHit, status_code=201)
async def knowledge_create(req: KnowledgeEntryCreate):
    try:
        return await create_entry(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/entries/{entry_id}")
async def knowledge_delete(entry_id: str = Path(...)):
    ok = await delete_entry(entry_id)
    if not ok:
        raise HTTPException(status_code=404, detail="entry not found")
    return {"status": "ok", "deleted": entry_id}


@router.post("/artifact-refs", response_model=dict)
async def knowledge_artifact_ref(req: ArtifactRefRequest):
    kid = await upsert_artifact_ref(
        path=req.path,
        title=req.title,
        summary=req.summary,
        runtime=req.runtime,
        workspace_id=req.workspace_id,
        tags=req.tags,
        structure_notes=req.structure_notes,
        task_id=req.task_id,
        session_id=req.session_id,
    )
    return {"status": "ok", "id": kid, "kind": "artifact_ref"}


@router.get("/inject-preview", response_model=InjectPreviewResponse)
async def knowledge_inject_preview(
    q: str = Query(..., min_length=1),
    workspace_id: str | None = None,
    runtime: str | None = None,
    top_k: int = Query(3, ge=1, le=10),
    for_ops: bool = False,
):
    block, hits = await build_task_inject_context(
        q,
        workspace_id=workspace_id or "",
        runtime=runtime,
        top_k=top_k,
        for_ops=for_ops,
    )
    return InjectPreviewResponse(block=block, hits=hits)


@router.post("/backfill")
async def knowledge_backfill(limit: int = Query(200, ge=1, le=1000)):
    n = await backfill_from_tasks(limit=limit)
    layers_filled = await backfill_layers()
    return {
        "indexed": n,
        "layers_filled": layers_filled,
        "status": "ok",
        "embedding": embedder_status(),
    }


@router.post("/mine-vault")
async def knowledge_mine_vault(req: MineVaultRequest):
    """从 Obsidian vault 子树挖掘 ArtifactRef + 高价值蒸馏。"""
    try:
        result = await mine_vault_docs(
            scope=req.scope,
            limit=req.limit,
            distill_high_value=req.distill_high_value,
            workspace_id=req.workspace_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        logger.exception("mine-vault failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    result["embedding"] = embedder_status()
    return result


@router.post("/index-session/{session_id}")
async def index_session(
    request: Request,
    session_id: str = Path(..., description="Session ID"),
    workspace_id: str = Query(""),
):
    """拉取 Session 详情并将消息写入 archive（非默认检索主路径）。"""
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
            "kind": "archive",
        }
    n = await index_session_messages(detail, workspace_id=workspace_id)
    return {
        "status": "ok",
        "session_id": session_id,
        "runtime": detail.runtime,
        "indexed": n,
        "kind": "archive",
    }
