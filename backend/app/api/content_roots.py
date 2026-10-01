"""知识库与技能读取目录。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import content_roots

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ContentRootsUpdate(BaseModel):
    knowledge_wiki_dir: str | None = None
    skills_catalog_dir: str | None = None
    outputs_vault_dir: str | None = None


@router.get("/content-roots")
async def get_content_roots():
    snap = content_roots.snapshot()
    logger.info(
        "content roots read wiki_exists=%s skills_exists=%s outputs_exists=%s",
        snap["knowledge"]["exists"],
        snap["skills"]["exists"],
        snap["outputs"]["exists"],
    )
    return snap


@router.patch("/content-roots")
async def patch_content_roots(req: ContentRootsUpdate):
    try:
        snap = content_roots.update(
            knowledge_wiki_dir=req.knowledge_wiki_dir,
            skills_catalog_dir=req.skills_catalog_dir,
            outputs_vault_dir=req.outputs_vault_dir,
        )
    except ValueError as exc:
        logger.info("content roots rejected err=%s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return snap
