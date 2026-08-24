"""工作区管理。"""

import logging
import uuid

import yaml
from sqlalchemy import select

from app.models.db import WorkspaceRecord, get_session_factory
from app.models.schemas import CreateWorkspaceRequest, WorkspaceInfo
from app.paths import guide_dir

logger = logging.getLogger(__name__)

WORKSPACES_YML = guide_dir() / "workspaces.yml"
DEFAULT_WORKSPACE_SLUG = "cyber"


def _record_to_info(rec: WorkspaceRecord) -> WorkspaceInfo:
    return WorkspaceInfo(
        id=rec.id,
        slug=rec.slug,
        name=rec.name,
        description=rec.description or "",
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


async def sync_seed_workspaces() -> None:
    if not WORKSPACES_YML.exists():
        logger.warning("workspaces.yml not found: %s", WORKSPACES_YML)
        return
    with open(WORKSPACES_YML, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    seeds = data.get("workspaces") or []
    factory = get_session_factory()
    async with factory() as session:
        for item in seeds:
            wid = item.get("id") or f"ws-{item.get('slug', uuid.uuid4().hex[:8])}"
            slug = item.get("slug") or wid
            existing = await session.get(WorkspaceRecord, wid)
            if existing:
                continue
            session.add(
                WorkspaceRecord(
                    id=wid,
                    slug=slug,
                    name=item.get("name", slug),
                    description=item.get("description", ""),
                )
            )
        await session.commit()
    logger.info("workspaces synced count=%d", len(seeds))


async def list_workspaces() -> list[WorkspaceInfo]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(select(WorkspaceRecord).order_by(WorkspaceRecord.name))
        ).scalars().all()
        return [_record_to_info(r) for r in rows]


async def get_workspace(workspace_id: str) -> WorkspaceInfo | None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(WorkspaceRecord, workspace_id)
        return _record_to_info(rec) if rec else None


async def get_workspace_by_slug(slug: str) -> WorkspaceInfo | None:
    factory = get_session_factory()
    async with factory() as session:
        q = select(WorkspaceRecord).where(WorkspaceRecord.slug == slug)
        rec = (await session.execute(q)).scalar_one_or_none()
        return _record_to_info(rec) if rec else None


async def create_workspace(req: CreateWorkspaceRequest) -> WorkspaceInfo:
    wid = req.id or f"ws-{req.slug}"
    factory = get_session_factory()
    async with factory() as session:
        q = select(WorkspaceRecord).where(WorkspaceRecord.slug == req.slug)
        if (await session.execute(q)).scalar_one_or_none():
            raise ValueError(f"workspace slug already exists: {req.slug}")
        if await session.get(WorkspaceRecord, wid):
            raise ValueError(f"workspace already exists: {wid}")
        rec = WorkspaceRecord(
            id=wid,
            slug=req.slug,
            name=req.name,
            description=req.description or "",
        )
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        logger.info("workspace created slug=%s id=%s", req.slug, wid)
        return _record_to_info(rec)


async def resolve_workspace_id(slug_or_id: str) -> str | None:
    if not slug_or_id:
        return None
    ws = await get_workspace_by_slug(slug_or_id)
    if ws:
        return ws.id
    ws = await get_workspace(slug_or_id)
    return ws.id if ws else None
