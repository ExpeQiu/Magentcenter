"""项目 CRUD、Lead、资源 API。"""

from fastapi import APIRouter, HTTPException, Query

from app.core import projects as project_service
from app.core import workspaces as workspace_service
from app.models.schemas import (
    CreateProjectRequest,
    CreateProjectResourceRequest,
    ProjectInfo,
    ProjectResourceInfo,
    UpdateProjectRequest,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectInfo])
async def list_projects(
    workspace_id: str | None = Query(None, description="工作区 ID 或 slug"),
) -> list[ProjectInfo]:
    wid = None
    if workspace_id:
        wid = await workspace_service.resolve_workspace_id(workspace_id)
        if not wid:
            raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")
    return await project_service.list_projects(wid)


@router.get("/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str) -> ProjectInfo:
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return project


@router.post("", response_model=ProjectInfo, status_code=201)
async def create_project(req: CreateProjectRequest) -> ProjectInfo:
    try:
        return await project_service.create_project(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{project_id}", response_model=ProjectInfo)
async def update_project(project_id: str, req: UpdateProjectRequest) -> ProjectInfo:
    try:
        return await project_service.update_project(project_id, req)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{project_id}/resources", response_model=list[ProjectResourceInfo])
async def list_resources(project_id: str) -> list[ProjectResourceInfo]:
    project = await project_service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"project not found: {project_id}")
    return await project_service.list_resources(project_id)


@router.post("/{project_id}/resources", response_model=ProjectResourceInfo, status_code=201)
async def create_resource(
    project_id: str, req: CreateProjectResourceRequest
) -> ProjectResourceInfo:
    try:
        return await project_service.create_resource(project_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{project_id}/resources/{resource_id}", status_code=204)
async def delete_resource(project_id: str, resource_id: str) -> None:
    try:
        await project_service.delete_resource(project_id, resource_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
