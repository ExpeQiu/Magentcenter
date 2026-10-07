"""超级AI 对话入口。网页与 ESP32 走同一条意图管道。"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.device_channel import DeviceAuthError, device_task, device_turn, enroll_device
from app.core.fleet import FleetAuthError, FleetError
from app.core.super_ai import handle_turn
from app.models.schemas import (
    DeviceEnrollRequest,
    DeviceEnrollResponse,
    DeviceTaskResponse,
    DeviceTurnRequest,
    SuperAiTurnRequest,
    SuperAiTurnResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/super-ai", tags=["super-ai"])


@router.post("/turn", response_model=SuperAiTurnResponse)
async def turn(req: SuperAiTurnRequest, request: Request) -> SuperAiTurnResponse:
    result = await handle_turn(
        req.text,
        workspace_slug=req.workspace_slug,
        pending=req.pending,
        last_href=req.last_href,
        registry=request.app.state.registry,
        task_manager=request.app.state.task_manager,
        monitor=request.app.state.monitor,
    )
    from app.core.chain import append_chain

    pending_prompt = req.pending.prompt if req.pending else ""
    await append_chain(
        kind="turn",
        run_id=result.run_id,
        task_id=result.task_id,
        actor_id="console",
        channel="web",
        intent=result.intent,
        status=result.task_status,
        summary=req.text,
        detail={
            "service": result.service,
            "href": result.href,
            "pending_prompt": pending_prompt,
        },
    )
    return result


@router.post("/device/enroll", response_model=DeviceEnrollResponse)
async def device_enroll(req: DeviceEnrollRequest, request: Request) -> DeviceEnrollResponse:
    settings = request.app.state.settings
    try:
        enrolled = await enroll_device(
            enroll_token=req.enroll_token,
            expected_token=settings.fleet_enroll_token,
            device_id=req.device_id,
            name=req.name,
            platform=req.platform,
        )
    except FleetAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except FleetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeviceEnrollResponse(**enrolled)


@router.post("/device/turn", response_model=SuperAiTurnResponse)
async def device_say(
    req: DeviceTurnRequest,
    request: Request,
    x_device_token: str = Header(default=""),
) -> SuperAiTurnResponse:
    try:
        return await device_turn(
            x_device_token,
            req.text,
            workspace_slug=req.workspace_slug,
            pending=req.pending,
            registry=request.app.state.registry,
            task_manager=request.app.state.task_manager,
            monitor=request.app.state.monitor,
            channel=req.channel,
        )
    except DeviceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/device/tasks/{task_id}", response_model=DeviceTaskResponse)
async def device_task_result(
    task_id: str,
    request: Request,
    x_device_token: str = Header(default=""),
) -> DeviceTaskResponse:
    try:
        spoken = await device_task(x_device_token, task_id, request.app.state.task_manager)
    except DeviceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if not spoken:
        raise HTTPException(status_code=404, detail="task not found")
    return DeviceTaskResponse(**spoken)
