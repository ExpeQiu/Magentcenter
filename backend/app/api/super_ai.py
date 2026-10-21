"""超级AI 对话入口。网页与 ESP32 走同一条意图管道。"""

import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.core.device_channel import (
    DeviceAuthError,
    DevicePairError,
    claim_device_pair,
    device_task,
    device_turn,
    enroll_device,
    poll_device_pair,
    start_device_pair,
)
from app.core.fleet import FleetAuthError, FleetError
from app.core.super_ai import handle_turn
from app.core import super_ai_llm
from app.models.schemas import (
    DeviceEnrollRequest,
    DeviceEnrollResponse,
    DevicePairClaimRequest,
    DevicePairClaimResponse,
    DevicePairStartRequest,
    DevicePairStartResponse,
    DevicePairStatusRequest,
    DevicePairStatusResponse,
    DeviceTaskResponse,
    DeviceTurnRequest,
    SuperAiProviderUpdate,
    SuperAiTurnRequest,
    SuperAiTurnResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/super-ai", tags=["super-ai"])


@router.get("/provider")
async def get_provider() -> dict:
    return super_ai_llm.public_provider()


@router.put("/provider")
async def put_provider(req: SuperAiProviderUpdate) -> dict:
    return super_ai_llm.save_provider(
        base_url=req.base_url,
        model=req.model,
        api_key=req.api_key,
    )


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
        confirmation_id=req.confirmation_id,
        session_id=req.session_id,
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
            "session_id": req.session_id,
            "dispatch": result.dispatch,
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


@router.post("/device/pair", response_model=DevicePairStartResponse)
async def device_pair_start(req: DevicePairStartRequest) -> DevicePairStartResponse:
    try:
        started = await start_device_pair(
            device_id=req.device_id,
            name=req.name,
            platform=req.platform,
        )
    except DevicePairError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FleetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DevicePairStartResponse(**started)


@router.post("/device/pair/status", response_model=DevicePairStatusResponse)
async def device_pair_status(req: DevicePairStatusRequest) -> DevicePairStatusResponse:
    try:
        status = await poll_device_pair(req.device_id, req.poll_secret)
    except DevicePairError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DeviceAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return DevicePairStatusResponse(**status)


@router.post("/device/pair/claim", response_model=DevicePairClaimResponse)
async def device_pair_claim(req: DevicePairClaimRequest) -> DevicePairClaimResponse:
    try:
        claimed = await claim_device_pair(req.code)
    except DevicePairError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FleetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DevicePairClaimResponse(**claimed)


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
            confirmation_id=req.confirmation_id,
            session_id=req.session_id,
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
