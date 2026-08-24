"""项目管理：工作区隔离、Lead、资源绑定。"""

import json
import logging
import uuid
from datetime import datetime

import yaml
from sqlalchemy import func, select

from app.core import workspaces as workspace_service
from app.paths import guide_dir
from app.models.db import (
    ProjectRecord,
    ProjectResourceRecord,
    TaskRecord,
    get_session_factory,
)
from app.models.schemas import (
    CreateProjectRequest,
    CreateProjectResourceRequest,
    GithubRepoRef,
    LocalDirectoryRef,
    ProjectInfo,
    ProjectResourceInfo,
    UpdateProjectRequest,
)

logger = logging.getLogger(__name__)

PROJECTS_YML = guide_dir() / "projects.yml"


def _record_to_info(rec: ProjectRecord) -> ProjectInfo:
    return ProjectInfo(
        id=rec.id,
        workspace_id=rec.workspace_id or "",
        name=rec.name,
        description=rec.description or "",
        color=rec.color or "slate",
        lead_type=rec.lead_type or "",
        lead_id=rec.lead_id or "",
        task_count=rec.task_count or 0,
        resource_count=rec.resource_count or 0,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


def _resource_to_info(rec: ProjectResourceRecord) -> ProjectResourceInfo:
    ref_data = json.loads(rec.ref_json or "{}")
    if rec.resource_type == "github_repo":
        ref: GithubRepoRef | LocalDirectoryRef = GithubRepoRef(**ref_data)
    else:
        ref = LocalDirectoryRef(**ref_data)
    return ProjectResourceInfo(
        id=rec.id,
        project_id=rec.project_id,
        workspace_id=rec.workspace_id,
        resource_type=rec.resource_type,  # type: ignore[arg-type]
        label=rec.label or "",
        position=rec.position or 0,
        ref=ref,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


def _normalize_ref(
    resource_type: str, ref: GithubRepoRef | LocalDirectoryRef
) -> dict:
    if resource_type == "github_repo":
        if not isinstance(ref, GithubRepoRef):
            raise ValueError("github_repo requires GithubRepoRef")
        if not ref.url.strip():
            raise ValueError("github_repo url is required")
        return ref.model_dump()
    if resource_type == "local_directory":
        if not isinstance(ref, LocalDirectoryRef):
            raise ValueError("local_directory requires LocalDirectoryRef")
        if not ref.local_path.strip():
            raise ValueError("local_directory local_path is required")
        return ref.model_dump()
    raise ValueError(f"unsupported resource_type: {resource_type}")


async def _add_resource(
    session,
    project: ProjectRecord,
    req: CreateProjectResourceRequest,
    position: int | None = None,
) -> ProjectResourceRecord:
    ref_json = json.dumps(_normalize_ref(req.resource_type, req.ref), ensure_ascii=False)
    rec = ProjectResourceRecord(
        id=str(uuid.uuid4()),
        workspace_id=project.workspace_id,
        project_id=project.id,
        resource_type=req.resource_type,
        label=req.label or "",
        position=position if position is not None else (project.resource_count or 0),
        ref_json=ref_json,
    )
    session.add(rec)
    project.resource_count = (project.resource_count or 0) + 1
    project.updated_at = datetime.utcnow()
    return rec


async def sync_seed_projects() -> None:
    if not PROJECTS_YML.exists():
        logger.warning("projects.yml not found: %s", PROJECTS_YML)
        return
    with open(PROJECTS_YML, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    seeds = data.get("projects") or []
    factory = get_session_factory()
    async with factory() as session:
        for item in seeds:
            pid = item.get("id") or str(uuid.uuid4())[:8]
            existing = await session.get(ProjectRecord, pid)
            ws_slug = item.get("workspace_slug") or workspace_service.DEFAULT_WORKSPACE_SLUG
            ws_id = await workspace_service.resolve_workspace_id(ws_slug)
            if not ws_id:
                logger.warning("skip project %s: workspace %s not found", pid, ws_slug)
                continue
            if not existing:
                existing = ProjectRecord(
                    id=pid,
                    workspace_id=ws_id,
                    name=item.get("name", pid),
                    description=item.get("description", ""),
                    color=item.get("color", "slate"),
                    lead_type=item.get("lead_type", ""),
                    lead_id=item.get("lead_id", ""),
                )
                session.add(existing)
                await session.flush()
            else:
                if not existing.workspace_id:
                    existing.workspace_id = ws_id
                if not existing.lead_id and item.get("lead_id"):
                    existing.lead_type = item.get("lead_type", "agent")
                    existing.lead_id = item.get("lead_id", "")

            for idx, res in enumerate(item.get("resources") or []):
                rtype = res.get("resource_type")
                ref = res.get("ref") or {}
                label = res.get("label", "")
                q = select(ProjectResourceRecord).where(
                    ProjectResourceRecord.project_id == pid,
                    ProjectResourceRecord.label == label,
                    ProjectResourceRecord.resource_type == rtype,
                )
                if (await session.execute(q)).scalar_one_or_none():
                    continue
                if rtype == "github_repo":
                    req = CreateProjectResourceRequest(
                        resource_type="github_repo",
                        label=label,
                        ref=GithubRepoRef(**ref),
                    )
                elif rtype == "local_directory":
                    req = CreateProjectResourceRequest(
                        resource_type="local_directory",
                        label=label,
                        ref=LocalDirectoryRef(**ref),
                    )
                else:
                    continue
                await _add_resource(session, existing, req, position=idx)
        await session.commit()
    logger.info("projects synced count=%d", len(seeds))


async def list_projects(workspace_id: str | None = None) -> list[ProjectInfo]:
    factory = get_session_factory()
    async with factory() as session:
        q = select(ProjectRecord).order_by(ProjectRecord.name)
        if workspace_id:
            q = q.where(ProjectRecord.workspace_id == workspace_id)
        rows = (await session.execute(q)).scalars().all()
        return [_record_to_info(r) for r in rows]


async def get_project(project_id: str) -> ProjectInfo | None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(ProjectRecord, project_id)
        return _record_to_info(rec) if rec else None


async def create_project(req: CreateProjectRequest) -> ProjectInfo:
    pid = req.id or str(uuid.uuid4())[:8]
    if req.workspace_id:
        ws = await workspace_service.get_workspace(req.workspace_id)
        if not ws:
            ws_id = await workspace_service.resolve_workspace_id(req.workspace_id)
            if not ws_id:
                raise ValueError(f"workspace not found: {req.workspace_id}")
            req.workspace_id = ws_id
    factory = get_session_factory()
    async with factory() as session:
        if await session.get(ProjectRecord, pid):
            raise ValueError(f"project already exists: {pid}")
        rec = ProjectRecord(
            id=pid,
            workspace_id=req.workspace_id or "",
            name=req.name,
            description=req.description or "",
            color=req.color or "slate",
            lead_type=req.lead_type or "",
            lead_id=req.lead_id or "",
        )
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        logger.info("project created id=%s workspace=%s", pid, req.workspace_id)
        return _record_to_info(rec)


async def update_project(project_id: str, req: UpdateProjectRequest) -> ProjectInfo:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(ProjectRecord, project_id)
        if not rec:
            raise ValueError(f"project not found: {project_id}")
        if req.name is not None:
            rec.name = req.name
        if req.description is not None:
            rec.description = req.description
        if req.color is not None:
            rec.color = req.color
        if req.lead_type is not None:
            rec.lead_type = req.lead_type
        if req.lead_id is not None:
            rec.lead_id = req.lead_id
        rec.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(rec)
        return _record_to_info(rec)


async def list_resources(project_id: str) -> list[ProjectResourceInfo]:
    factory = get_session_factory()
    async with factory() as session:
        q = (
            select(ProjectResourceRecord)
            .where(ProjectResourceRecord.project_id == project_id)
            .order_by(ProjectResourceRecord.position)
        )
        rows = (await session.execute(q)).scalars().all()
        return [_resource_to_info(r) for r in rows]


async def create_resource(
    project_id: str, req: CreateProjectResourceRequest
) -> ProjectResourceInfo:
    factory = get_session_factory()
    async with factory() as session:
        project = await session.get(ProjectRecord, project_id)
        if not project:
            raise ValueError(f"project not found: {project_id}")
        rec = await _add_resource(session, project, req)
        await session.commit()
        await session.refresh(rec)
        logger.info(
            "resource created project=%s type=%s", project_id, req.resource_type
        )
        return _resource_to_info(rec)


async def delete_resource(project_id: str, resource_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(ProjectResourceRecord, resource_id)
        if not rec or rec.project_id != project_id:
            raise ValueError(f"resource not found: {resource_id}")
        project = await session.get(ProjectRecord, project_id)
        await session.delete(rec)
        if project:
            project.resource_count = max(0, (project.resource_count or 1) - 1)
            project.updated_at = datetime.utcnow()
        await session.commit()


async def update_task_count(project_id: str, delta: int) -> None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(ProjectRecord, project_id)
        if not rec:
            return
        rec.task_count = max(0, (rec.task_count or 0) + delta)
        rec.updated_at = datetime.utcnow()
        await session.commit()


async def refresh_task_counts() -> None:
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(TaskRecord.project_id, func.count())
                .where(TaskRecord.project_id != "")
                .group_by(TaskRecord.project_id)
            )
        ).all()
        counts = {pid: cnt for pid, cnt in rows if pid}
        projects = (await session.execute(select(ProjectRecord))).scalars().all()
        for p in projects:
            p.task_count = counts.get(p.id, 0)
            p.updated_at = datetime.utcnow()
        await session.commit()
