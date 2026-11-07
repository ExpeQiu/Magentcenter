"""协议 v2：登记、委托、领取、确认和契约。未知主版本拒绝派单。"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.autonomy_state import PROTOCOL_VERSION, ProtocolError, accept_protocol
from app.core.capabilities import catalog_for_profile
from app.core.confirmations import ConfirmationError, attach_task, confirm as confirm_record
from app.core.delegations import DelegationError, create_delegation
from app.core.execution import (
    ClaimError,
    claim_assigned,
    claim_next,
    finish_execution,
    record_command_ack,
)
from app.core.identity import load_or_create_identity
from app.core.observability import snapshot
from app.core.sync_bus import SyncConflict, ingest
from app.models.db import (
    EnrollmentVoucherRecord,
    NodeCredentialRecord,
    get_session_factory,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["v2"])
_CLAIM_ROLES = {"full", "edge"}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def openapi_document() -> dict:
    paths = [
        "/api/v2/enrollments",
        "/api/v2/nodes/enroll",
        "/api/v2/nodes/heartbeat",
        "/api/v2/nodes/revoke-local",
        "/api/v2/clients/enroll",
        "/api/v2/clients/refresh",
        "/api/v2/clients/revoke",
        "/api/v2/delegations",
        "/api/v2/commands/claim",
        "/api/v2/commands/claim-next",
        "/api/v2/commands/ack",
        "/api/v2/commands/finish",
        "/api/v2/events/batch",
        "/api/v2/tasks/{id}/events",
        "/api/v2/tasks/{id}/cancel",
        "/api/v2/conversations/{id}/turns",
        "/api/v2/confirmations/{id}/confirm",
        "/api/v2/openapi.json",
        "/api/v2/metrics",
    ]
    more = [
        "/api/v2/work-items",
        "/api/v2/work-items/{id}",
        "/api/v2/work-items/{id}/accept",
        "/api/v2/work-items/{id}/deliveries",
        "/api/v2/attention",
        "/api/v2/attention/{id}/dismiss",
        "/api/v2/superagent/policy",
        "/api/v2/superagent/overview",
        "/api/v2/executions/{id}/lease",
        "/api/v2/executions/{id}/delivery-ack",
        "/api/v2/hardware/commands",
        "/api/v2/channels/interrupt",
    ]
    all_paths = paths + [p for p in more if p not in paths]
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "AgentCenter Autonomy",
            "version": "2.1.0",
            "description": (
                "自治协议 v2。fleet v1 仍兼容；outbox 对本中心落地确认，"
                "对已配置 fleet_link peer 尝试真实投递；未知远端记 waiting。"
                "能力协商：superagent_control=1、client_session=1、attention_inbox=1。"
            ),
        },
        "paths": {
            **{path: {"post": {"summary": path}} for path in all_paths},
            "/api/v2/openapi.json": {"get": {"summary": "openapi"}},
            "/api/v2/attention": {"get": {"summary": "list attention"}},
            "/api/v2/superagent/policy": {"get": {"summary": "policy"}, "put": {"summary": "policy"}},
            "/api/v2/superagent/overview": {"get": {"summary": "overview"}},
            "/api/v2/metrics": {"get": {"summary": "metrics"}},
        },
        "x-protocol-version": PROTOCOL_VERSION,
        "x-features": {
            "superagent_control": 1,
            "client_session": 1,
            "attention_inbox": 1,
            "silent_delivery": 1,
            "feishu_inbound": 1,
            "worker_slots": 1,
        },
    }


class EnrollmentRequest(BaseModel):
    role: str = "edge"
    uses: int = 1
    ttl_seconds: int = 600


class NodeEnrollRequest(BaseModel):
    voucher: str
    node_id: str = ""
    protocol_version: int = 2


class ClientEnrollRequest(BaseModel):
    enroll_token: str
    center_id: str
    client_id: str = ""
    workspace_id: str = "cyber"
    device_id: str = ""
    ttl_seconds: int = 30 * 24 * 3600
    protocol_version: int = 2


class ClientRefreshRequest(BaseModel):
    ttl_seconds: int = 30 * 24 * 3600


class HeartbeatRequest(BaseModel):
    protocol_version: int = 2
    capabilities: list[str] = Field(default_factory=list)


class DelegationRequest(BaseModel):
    protocol_version: int = 2
    task_id: str
    target_node_id: str
    idempotency_key: str
    payload: dict = Field(default_factory=dict)
    visibility: str = "shared"
    depth: int = 1
    ancestors: list[str] = Field(default_factory=list)
    parent_task_ref: str = ""
    local_workspace_id: str = ""
    remote_workspace_id: str = ""
    remote_center_id: str = ""


class ClaimRequest(BaseModel):
    protocol_version: int = 2
    task_id: str = ""
    delegation_id: str = ""
    attempt: int = 1


class FinishRequest(BaseModel):
    protocol_version: int = 2
    task_id: str
    execution_id: str = ""
    status: str = "completed"
    output: str = ""
    error: str = ""
    session_id: str = ""
    duration_ms: int = 0
    assignment_generation: int | None = None


class BatchRequest(BaseModel):
    protocol_version: int = 2
    events: list[dict] = Field(default_factory=list)


class TurnRequest(BaseModel):
    protocol_version: int = 2
    text: str = ""
    session_id: str = ""
    subject_id: str = "local"


class ConfirmRequest(BaseModel):
    protocol_version: int = 2
    subject_id: str = ""
    session_id: str = ""
    content_hash: str = ""


def _check_protocol(version: int) -> None:
    try:
        accept_protocol(version)
    except ProtocolError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def _node_from_token(token: str) -> NodeCredentialRecord:
    if not token:
        raise HTTPException(status_code=401, detail="node token required")
    factory = get_session_factory()
    async with factory() as session:
        row = (
            await session.execute(
                select(NodeCredentialRecord).where(NodeCredentialRecord.token_hash == _hash(token))
            )
        ).scalar_one_or_none()
    if row is None or row.revoked:
        raise HTTPException(status_code=401, detail="node credential revoked or unknown")
    return row


@router.get("/openapi.json")
async def spec() -> dict:
    return openapi_document()


@router.get("/metrics")
async def metrics() -> dict:
    return await snapshot()


@router.post("/enrollments", status_code=201)
async def create_enrollment(req: EnrollmentRequest) -> dict:
    role = req.role if req.role in {"full", "edge", "conversation", "center"} else "edge"
    raw = secrets.token_urlsafe(24)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            EnrollmentVoucherRecord(
                id=str(uuid.uuid4()),
                token_hash=_hash(raw),
                role=role,
                uses_left=max(1, min(req.uses, 3)),
                expires_at=datetime.utcnow() + timedelta(seconds=max(30, min(req.ttl_seconds, 3600))),
            )
        )
        await session.commit()
    logger.info("enrollment voucher issued role=%s", role)
    return {"voucher": raw, "role": role}


@router.post("/nodes/enroll", status_code=201)
async def enroll_node(req: NodeEnrollRequest) -> dict:
    _check_protocol(req.protocol_version)
    factory = get_session_factory()
    async with factory() as session:
        voucher = (
            await session.execute(
                select(EnrollmentVoucherRecord).where(
                    EnrollmentVoucherRecord.token_hash == _hash(req.voucher)
                )
            )
        ).scalar_one_or_none()
        if voucher is None or voucher.uses_left <= 0:
            raise HTTPException(status_code=401, detail="voucher invalid")
        if voucher.expires_at and voucher.expires_at < datetime.utcnow():
            raise HTTPException(status_code=401, detail="voucher expired")
        node_id = (req.node_id or str(uuid.uuid4())).strip()
        raw = secrets.token_urlsafe(32)
        existing = await session.get(NodeCredentialRecord, node_id)
        if existing:
            existing.token_hash = _hash(raw)
            existing.role = voucher.role
            existing.revoked = 0
        else:
            session.add(
                NodeCredentialRecord(node_id=node_id, token_hash=_hash(raw), role=voucher.role)
            )
        voucher.uses_left -= 1
        await session.commit()
        role = voucher.role
    logger.info("node enrolled node_id=%s role=%s", node_id, role)
    return {"node_id": node_id, "node_token": raw, "role": role}


@router.post("/clients/enroll", status_code=201)
async def enroll_client(req: ClientEnrollRequest, request: Request) -> dict:
    """用 FLEET_ENROLL_TOKEN + center_id 换取 Client Session（对话用，不可 claim）。"""
    _check_protocol(req.protocol_version)
    from app.core.client_session import ClientSessionError, enroll

    settings = request.app.state.settings
    try:
        return await enroll(
            enroll_token=req.enroll_token,
            expected_token=settings.fleet_enroll_token,
            center_id=req.center_id,
            client_id=req.client_id,
            workspace_id=req.workspace_id,
            device_id=req.device_id,
            ttl_seconds=req.ttl_seconds,
        )
    except ClientSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/clients/refresh")
async def refresh_client(
    req: ClientRefreshRequest,
    x_client_token: str = Header(default=""),
) -> dict:
    from app.core.client_session import ClientSessionError, refresh

    try:
        return await refresh(x_client_token, ttl_seconds=req.ttl_seconds)
    except ClientSessionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@router.post("/clients/revoke")
async def revoke_client(x_client_token: str = Header(default="")) -> dict:
    from app.core.client_session import revoke

    ok = await revoke(x_client_token)
    return {"ok": True, "revoked": ok}


@router.post("/nodes/heartbeat")
async def heartbeat(
    req: HeartbeatRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role == "conversation":
        raise HTTPException(status_code=403, detail="conversation devices have no execution catalog")
    ident = load_or_create_identity()
    listed = catalog_for_profile(ident.profile, [])
    logger.info("heartbeat node_id=%s role=%s", node.node_id, node.role)
    return {"node_id": node.node_id, "role": node.role, "catalog": listed, "reported": req.capabilities}


@router.post("/nodes/revoke-local")
async def revoke_local_node(request: Request) -> dict:
    """本机显式撤销 Node Agent 凭证；本地 Core 功能保留。仅 loopback。"""
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="revoke-local is loopback only")
    from app.core.node_bootstrap import revoke_local_node_credential

    await revoke_local_node_credential()
    return {"ok": True, "revoked": True}


@router.post("/delegations", status_code=201)
async def post_delegation(
    req: DelegationRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role == "conversation":
        raise HTTPException(status_code=403, detail="conversation devices cannot delegate")
    if req.local_workspace_id or req.remote_workspace_id:
        from app.core.delegations import authorize_workspace, list_links

        allowed = authorize_workspace(
            req.local_workspace_id,
            req.remote_center_id,
            req.remote_workspace_id,
            await list_links(),
        )
        if not allowed:
            raise HTTPException(status_code=403, detail="workspace is not linked")
    ident = load_or_create_identity()
    try:
        created = await create_delegation(
            owner_center_id=ident.center_id,
            task_id=req.task_id,
            target_node_id=req.target_node_id,
            idempotency_key=req.idempotency_key,
            payload=req.payload,
            source_node_id=node.node_id,
            target_center_id=req.remote_center_id or ident.center_id,
            local_workspace_id=req.local_workspace_id,
            remote_workspace_id=req.remote_workspace_id,
            attempt=int(req.payload.get("attempt") or 1),
            parent_task_ref=req.parent_task_ref,
            ancestors=req.ancestors,
            depth=req.depth,
            visibility=req.visibility,
        )
    except DelegationError as exc:
        status = 409 if "different content" in str(exc) or "depth" in str(exc) or "cycle" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return created


@router.post("/commands/claim")
async def claim_command(
    req: ClaimRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role not in _CLAIM_ROLES:
        raise HTTPException(status_code=403, detail="role cannot claim executions")
    if not req.task_id and not req.delegation_id:
        raise HTTPException(status_code=400, detail="task_id or delegation_id required")
    try:
        claimed = await claim_assigned(
            node.node_id,
            task_id=req.task_id,
            delegation_id=req.delegation_id,
            attempt=req.attempt,
        )
    except ClaimError as exc:
        logger.info(
            "command claim denied node_id=%s task_id=%s delegation_id=%s attempt=%s status=%s detail=%s",
            node.node_id,
            req.task_id,
            req.delegation_id,
            req.attempt,
            exc.status_code,
            exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return claimed


@router.post("/commands/claim-next")
async def claim_next_command(
    req: ClaimRequest | None = None,
    x_node_token: str = Header(default=""),
) -> dict:
    body = req or ClaimRequest()
    _check_protocol(body.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role not in _CLAIM_ROLES:
        raise HTTPException(status_code=403, detail="role cannot claim executions")
    claimed = await claim_next(node.node_id)
    if claimed is None:
        return {"accepted": False, "task": None}
    return claimed


@router.post("/commands/finish")
async def finish_command(
    req: FinishRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role not in _CLAIM_ROLES:
        raise HTTPException(status_code=403, detail="role cannot finish executions")
    try:
        return await finish_execution(
            node.node_id,
            task_id=req.task_id,
            execution_id=req.execution_id,
            status=req.status,
            output=req.output,
            error=req.error,
            session_id=req.session_id,
            duration_ms=req.duration_ms,
            generation=req.assignment_generation,
        )
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/commands/ack")
async def ack_command(
    req: ClaimRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role not in _CLAIM_ROLES:
        raise HTTPException(status_code=403, detail="role cannot ack executions")
    try:
        return await record_command_ack(
            node.node_id,
            task_id=req.task_id,
            delegation_id=req.delegation_id,
            attempt=req.attempt,
        )
    except ClaimError as exc:
        logger.info(
            "command ack denied node_id=%s task_id=%s delegation_id=%s attempt=%s status=%s detail=%s",
            node.node_id,
            req.task_id,
            req.delegation_id,
            req.attempt,
            exc.status_code,
            exc,
        )
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/events/batch")
async def events_batch(
    req: BatchRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role == "conversation":
        raise HTTPException(status_code=403, detail="conversation devices cannot upload executions")
    results = []
    for event in req.events:
        event = dict(event)
        event.setdefault("protocol_version", req.protocol_version)
        try:
            results.append(await ingest(event, authenticated_node_id=node.node_id))
        except SyncConflict as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"results": results}


@router.get("/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, after: int = 0) -> dict:
    tm = request.app.state.task_manager
    events = await tm.get_events(task_id, after_id=after)
    return {"items": [ev.model_dump(mode="json") for ev in events]}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str, request: Request) -> dict:
    tm = request.app.state.task_manager
    try:
        task = await tm.cancel_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task.model_dump(mode="json")


@router.post("/conversations/{conversation_id}/turns")
async def conversation_turn(conversation_id: str, req: TurnRequest, request: Request) -> dict:
    _check_protocol(req.protocol_version)
    from app.core.super_ai import handle_turn

    result = await handle_turn(
        req.text,
        workspace_slug="cyber",
        pending=None,
        last_href="",
        registry=request.app.state.registry,
        task_manager=request.app.state.task_manager,
        monitor=request.app.state.monitor,
        session_id=req.session_id or conversation_id,
        subject_id=req.subject_id,
    )
    return result.model_dump(mode="json")


@router.post("/confirmations/{confirmation_id}/confirm")
async def confirm_once(confirmation_id: str, req: ConfirmRequest, request: Request) -> dict:
    _check_protocol(req.protocol_version)
    try:
        opened = await confirm_record(
            confirmation_id,
            subject_id=req.subject_id,
            session_id=req.session_id,
            presented_hash=req.content_hash,
        )
    except ConfirmationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if opened.get("task_id"):
        return {"task_id": opened["task_id"], "created": False}
    target = opened.get("target") or {}
    from app.models.schemas import CreateTaskRequest

    tm = request.app.state.task_manager
    created = await tm.create_task(
        CreateTaskRequest(
            agent_id=target.get("agent_id") or "",
            prompt=target.get("prompt") or opened.get("summary") or "",
            runtime=target.get("runtime"),
            workspace_id=target.get("workspace_id") or "",
        )
    )
    await attach_task(confirmation_id, created.id)
    return {"task_id": created.id, "created": True}


class WorkItemCreate(BaseModel):
    title: str = ""
    goal: str
    workspace_id: str = "cyber"
    conversation_id: str = ""
    task_id: str = ""
    protocol_version: int = 2


class LeaseRequest(BaseModel):
    assignment_generation: int | None = None
    protocol_version: int = 2


class DeliveryAckRequest(BaseModel):
    ack: str
    assignment_generation: int | None = None
    protocol_version: int = 2


class HardwareEnqueue(BaseModel):
    device_id: str
    command: str
    payload: dict = Field(default_factory=dict)
    idempotency_key: str = ""
    ttl_seconds: int = 120
    protocol_version: int = 2


class InterruptRequest(BaseModel):
    device_id: str = ""
    channel: str = "voice"
    stop_audio_only: bool = True
    cancel_task: bool = False
    task_id: str = ""
    protocol_version: int = 2


@router.post("/work-items")
async def create_work(req: WorkItemCreate) -> dict:
    _check_protocol(req.protocol_version)
    from app.core import work_items as wi

    if req.conversation_id:
        await wi.ensure_conversation(req.conversation_id, workspace_id=req.workspace_id)
    wid = await wi.create_work_item(
        title=req.title,
        goal=req.goal,
        workspace_id=req.workspace_id,
        conversation_id=req.conversation_id,
        task_id=req.task_id,
    )
    return {"id": wid, **((await wi.get_work_item(wid)) or {})}


@router.get("/work-items")
async def list_works(
    workspace_id: str = "",
    status: str = "",
    limit: int = 50,
) -> dict:
    from app.core import work_items as wi

    items = await wi.list_work_items(
        workspace_id=workspace_id, status=status, limit=limit
    )
    return {"items": items, "count": len(items)}


@router.get("/work-items/{work_item_id}")
async def get_work(work_item_id: str) -> dict:
    from app.core import work_items as wi

    row = await wi.get_work_item(work_item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="work item not found")
    return row


@router.post("/work-items/{work_item_id}/accept")
async def accept_work(work_item_id: str, artifact_id: str = "") -> dict:
    from app.core import work_items as wi

    ok = await wi.accept_work_item(work_item_id, artifact_id=artifact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="work item not found")
    return await wi.get_work_item(work_item_id) or {}


@router.get("/attention")
async def attention_list() -> dict:
    from app.core.supervisor import list_open

    return {"items": await list_open()}


@router.post("/attention/{attention_id}/dismiss")
async def attention_dismiss(attention_id: str) -> dict:
    from app.core.supervisor import dismiss

    ok = await dismiss(attention_id)
    if not ok:
        raise HTTPException(status_code=404, detail="attention not found")
    return {"ok": True, "id": attention_id, "status": "dismissed"}


@router.get("/superagent/overview")
async def superagent_overview(request: Request) -> dict:
    """健康三问：待办 / 健康 / 近期历史。健康态 compact=true。"""
    from app.core.overview import build_overview

    return await build_overview(
        settings=request.app.state.settings,
        monitor=getattr(request.app.state, "monitor", None),
    )


@router.get("/superagent/policy")
async def get_superagent_policy() -> dict:
    from app.domain.superagent import policy as policy_svc

    p = policy_svc.load_policy()
    return {
        "version": p.version,
        "mode": p.mode,
        "allowed_sources": p.allowed_sources,
        "allowed_actors": p.allowed_actors,
    }


class PolicyUpdateRequest(BaseModel):
    mode: str = ""
    allowed_sources: list[str] | None = None
    allowed_actors: list[str] | None = None


@router.put("/superagent/policy")
async def put_superagent_policy(req: PolicyUpdateRequest) -> dict:
    from app.domain.superagent import policy as policy_svc

    updates: dict = {}
    if req.mode:
        updates["mode"] = req.mode
    if req.allowed_sources is not None:
        updates["allowed_sources"] = req.allowed_sources
    if req.allowed_actors is not None:
        updates["allowed_actors"] = req.allowed_actors
    if not updates:
        p = policy_svc.load_policy()
    else:
        p = policy_svc.bump_policy(**updates)
    return {
        "version": p.version,
        "mode": p.mode,
        "allowed_sources": p.allowed_sources,
        "allowed_actors": p.allowed_actors,
    }


@router.get("/work-items/{work_item_id}/deliveries")
async def work_item_deliveries(work_item_id: str) -> dict:
    from app.core import delivery as delivery_svc

    return {"items": await delivery_svc.list_for_work_item(work_item_id, include_acked=True)}


@router.post("/executions/{execution_id}/lease")
async def execution_lease(execution_id: str, req: LeaseRequest) -> dict:
    _check_protocol(req.protocol_version)
    from app.core.execution import ClaimError, renew_lease

    try:
        return await renew_lease(execution_id, generation=req.assignment_generation)
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/executions/{execution_id}/delivery-ack")
async def execution_delivery_ack(execution_id: str, req: DeliveryAckRequest) -> dict:
    _check_protocol(req.protocol_version)
    from app.core.execution import ClaimError, set_delivery_ack

    try:
        await set_delivery_ack(
            execution_id, req.ack, generation=req.assignment_generation
        )
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"execution_id": execution_id, "delivery_ack": req.ack}


@router.post("/hardware/commands")
async def hardware_enqueue(req: HardwareEnqueue) -> dict:
    _check_protocol(req.protocol_version)
    from app.core.hardware_commands import HardwareCommandError, enqueue

    try:
        return await enqueue(
            req.device_id,
            req.command,
            payload=req.payload,
            idempotency_key=req.idempotency_key,
            ttl_seconds=req.ttl_seconds,
        )
    except HardwareCommandError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/channels/interrupt")
async def channel_interrupt(req: InterruptRequest, request: Request) -> dict:
    """打断播报默认只停音频；取消任务需 cancel_task=true 且带权限。"""
    _check_protocol(req.protocol_version)
    logger.info(
        "channel interrupt device=%s stop_audio=%s cancel_task=%s task_id=%s",
        req.device_id,
        req.stop_audio_only,
        req.cancel_task,
        req.task_id,
    )
    result = {
        "audio_stopped": bool(req.stop_audio_only or not req.cancel_task),
        "task_cancelled": False,
        "task_id": req.task_id or "",
    }
    if req.cancel_task and req.task_id:
        tm = request.app.state.task_manager
        try:
            task = await tm.cancel_task(req.task_id)
            result["task_cancelled"] = task is not None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif req.cancel_task and not req.task_id:
        raise HTTPException(status_code=400, detail="cancel_task requires task_id")
    return result


@router.post("/conversations/{conversation_id}/messages")
async def conversation_message(
    conversation_id: str,
    request: Request,
    text: str = "",
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
) -> dict:
    """持久消息落盘；202 语义用同步回执简化。"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    content = str(body.get("text") or text or "")
    from app.core import work_items as wi

    cid = await wi.ensure_conversation(conversation_id, workspace_id=body.get("workspace_id") or "cyber")
    external = idempotency_key or str(body.get("idempotency_key") or "")
    if external:
        trig = await wi.record_trigger(
            source="conversation",
            external_event_id=external,
            workspace_id=body.get("workspace_id") or "cyber",
            conversation_id=cid,
            payload={"text": content},
        )
        if trig is None and external:
            # 去重：仍追加查询已有消息
            pass
    mid = await wi.append_message(
        cid,
        role="user",
        content=content,
        actor_id=str(body.get("actor_id") or ""),
        channel=str(body.get("channel") or ""),
        work_item_id=str(body.get("work_item_id") or ""),
        idempotency_key=external,
    )
    return {
        "status": "accepted",
        "conversation_id": cid,
        "message_id": mid,
        "routing_status": "queued",
    }
