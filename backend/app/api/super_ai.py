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


@router.get("/session/{session_id}")
async def session_history(session_id: str) -> dict:
    from app.core import super_ai_session as sessions

    items = await sessions.recent(session_id)
    return {"session_id": session_id, "messages": items}


@router.post("/turn", response_model=SuperAiTurnResponse)
async def turn(req: SuperAiTurnRequest, request: Request) -> SuperAiTurnResponse:
    """本机网页入口。联网协同时转发云端 Client turn；本机即云端时本地处理。"""
    settings = request.app.state.settings
    from app.core.cloud_super_ai import CloudSuperAiError, forward_turn, remote_cloud_target

    target = await remote_cloud_target(settings)
    if target is not None:
        body = req.model_dump()
        try:
            data = await forward_turn(settings, body, workspace_id=req.workspace_slug or "cyber")
        except CloudSuperAiError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        result = SuperAiTurnResponse(**data)
        from app.core.chain import append_chain

        await append_chain(
            kind="turn",
            run_id=result.run_id,
            task_id=result.task_id,
            actor_id="console",
            channel="web_via_cloud",
            intent=result.intent,
            status=result.task_status,
            summary=req.text,
            detail={
                "service": result.service,
                "session_id": req.session_id,
                "dispatch": result.dispatch,
                "origin": "super_ai",
                "via": "cloud_client",
            },
        )
        return result

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
        channel="web",
        origin="super_ai",
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
            "origin": "super_ai",
        },
    )
    return result


@router.post("/client/turn", response_model=SuperAiTurnResponse)
async def client_turn(
    req: SuperAiTurnRequest,
    request: Request,
    x_client_token: str = Header(default=""),
) -> SuperAiTurnResponse:
    """跨端 Client Session 调用云端超级AI。"""
    from app.core.client_session import ClientSessionError, authenticate

    try:
        principal = await authenticate(x_client_token)
    except ClientSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if "super_ai.turn" not in principal.scopes and "*" not in principal.scopes:
        raise HTTPException(status_code=403, detail="scope super_ai.turn required")
    result = await handle_turn(
        req.text,
        workspace_slug=req.workspace_slug or principal.workspace_id or "cyber",
        pending=req.pending,
        last_href=req.last_href,
        registry=request.app.state.registry,
        task_manager=request.app.state.task_manager,
        monitor=request.app.state.monitor,
        confirmation_id=req.confirmation_id,
        session_id=req.session_id or principal.session_id,
        subject_id=principal.client_id,
        channel="client",
        origin="super_ai",
        client_id=principal.client_id,
    )
    from app.core.chain import append_chain

    await append_chain(
        kind="turn",
        run_id=result.run_id,
        task_id=result.task_id,
        actor_id=principal.client_id,
        channel="client",
        intent=result.intent,
        status=result.task_status,
        summary=req.text,
        detail={
            "service": result.service,
            "session_id": req.session_id or principal.session_id,
            "dispatch": result.dispatch,
            "origin": "super_ai",
            "client_id": principal.client_id,
            "center_id": principal.center_id,
        },
    )
    return result


@router.get("/client/session/{session_id}")
async def client_session_history(
    session_id: str,
    x_client_token: str = Header(default=""),
) -> dict:
    from app.core.client_session import ClientSessionError, authenticate
    from app.core import super_ai_session as sessions

    try:
        principal = await authenticate(x_client_token)
    except ClientSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if "super_ai.session" not in principal.scopes and "super_ai.turn" not in principal.scopes:
        raise HTTPException(status_code=403, detail="scope super_ai.session required")
    items = await sessions.recent(session_id)
    return {"session_id": session_id, "messages": items, "client_id": principal.client_id}


@router.get("/client/tasks/{task_id}")
async def client_task_status(
    task_id: str,
    request: Request,
    x_client_token: str = Header(default=""),
) -> dict:
    from app.core.client_session import ClientSessionError, authenticate

    try:
        principal = await authenticate(x_client_token)
    except ClientSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    if "super_ai.task_read" not in principal.scopes and "super_ai.turn" not in principal.scopes:
        raise HTTPException(status_code=403, detail="scope super_ai.task_read required")
    task = await request.app.state.task_manager.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "id": task.id,
        "status": task.status,
        "lifecycle_status": task.lifecycle_status,
        "origin": getattr(task, "origin", "") or "",
        "owner_center_id": getattr(task, "owner_center_id", "") or "",
        "node_id": getattr(task, "node_id", "") or "",
        "output": (task.output or "")[:2000],
        "error": task.error or "",
        "client_id": principal.client_id,
    }


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
