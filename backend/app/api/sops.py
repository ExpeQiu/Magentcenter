"""SOP 工作流 API。"""

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from app.core import sops as sop_service
from app.core import workspaces as workspace_service
from app.models.schemas import (
    CreateSopRequest,
    CreateSopStepRequest,
    ReorderSopStepsRequest,
    RunSopRequest,
    SopInfo,
    SopRunResult,
    UpdateSopRequest,
    UpdateSopStepRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sops", tags=["sops"])


async def _workspace_filter(workspace_id: str | None) -> str | None:
    if not workspace_id:
        return None
    resolved = await workspace_service.resolve_workspace_id(workspace_id)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"workspace not found: {workspace_id}")
    return resolved


@router.get("", response_model=list[SopInfo])
async def list_sops(
    workspace_id: str | None = Query(None, description="工作区 ID 或 slug"),
) -> list[SopInfo]:
    wid = await _workspace_filter(workspace_id)
    return await sop_service.list_sops(wid)


@router.post("", response_model=SopInfo, status_code=201)
async def create_sop(req: CreateSopRequest) -> SopInfo:
    try:
        return await sop_service.create_sop(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{sop_id}", response_model=SopInfo)
async def get_sop(sop_id: str) -> SopInfo:
    sop = await sop_service.get_sop(sop_id)
    if not sop:
        raise HTTPException(status_code=404, detail=f"sop not found: {sop_id}")
    return sop


@router.patch("/{sop_id}", response_model=SopInfo)
async def update_sop(sop_id: str, req: UpdateSopRequest) -> SopInfo:
    try:
        return await sop_service.update_sop(sop_id, req)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.delete("/{sop_id}", status_code=204)
async def delete_sop(sop_id: str) -> None:
    try:
        await sop_service.delete_sop(sop_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{sop_id}/steps", response_model=SopInfo, status_code=201)
async def add_step(sop_id: str, req: CreateSopStepRequest) -> SopInfo:
    try:
        return await sop_service.add_step(sop_id, req)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.patch("/{sop_id}/steps/{step_id}", response_model=SopInfo)
async def update_step(sop_id: str, step_id: str, req: UpdateSopStepRequest) -> SopInfo:
    try:
        return await sop_service.update_step(sop_id, step_id, req)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.delete("/{sop_id}/steps/{step_id}", response_model=SopInfo)
async def delete_step(sop_id: str, step_id: str) -> SopInfo:
    try:
        return await sop_service.delete_step(sop_id, step_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{sop_id}/steps/reorder", response_model=SopInfo)
async def reorder_steps(sop_id: str, req: ReorderSopStepsRequest) -> SopInfo:
    try:
        return await sop_service.reorder_steps(sop_id, req)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.post("/{sop_id}/run", response_model=SopRunResult)
async def run_sop(sop_id: str, req: RunSopRequest, request: Request) -> SopRunResult:
    tm = request.app.state.task_manager
    try:
        return await sop_service.run_sop(sop_id, req, tm)
    except ValueError as e:
        status = 404 if "not found" in str(e) else 400
        logger.warning("sop run failed sop_id=%s detail=%s", sop_id, e)
        raise HTTPException(status_code=status, detail=str(e))
