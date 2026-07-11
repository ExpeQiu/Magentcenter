"""工作区 API。"""

from fastapi import APIRouter, HTTPException, Query

from app.core import workspaces as workspace_service
from app.models.schemas import CreateWorkspaceRequest, WorkspaceInfo

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceInfo])
async def list_workspaces() -> list[WorkspaceInfo]:
    return await workspace_service.list_workspaces()


@router.get("/by-slug/{slug}", response_model=WorkspaceInfo)
async def get_workspace_by_slug(slug: str) -> WorkspaceInfo:
    ws = await workspace_service.get_workspace_by_slug(slug)
    if not ws:
        raise HTTPException(status_code=404, detail=f"workspace not found: {slug}")
    return ws


@router.get("/{workspace_id}", response_model=WorkspaceInfo)
async def get_workspace(workspace_id: str) -> WorkspaceInfo:
    ws = await workspace_service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")
    return ws


@router.post("", response_model=WorkspaceInfo, status_code=201)
async def create_workspace(req: CreateWorkspaceRequest) -> WorkspaceInfo:
    try:
        return await workspace_service.create_workspace(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
