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
from app.core.execution import accept_remote
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
        "/api/v2/delegations",
        "/api/v2/commands/claim",
        "/api/v2/commands/ack",
        "/api/v2/events/batch",
        "/api/v2/tasks/{id}/events",
        "/api/v2/tasks/{id}/cancel",
        "/api/v2/conversations/{id}/turns",
        "/api/v2/confirmations/{id}/confirm",
        "/api/v2/openapi.json",
        "/api/v2/metrics",
    ]
    return {
        "openapi": "3.0.3",
        "info": {"title": "AgentCenter Autonomy", "version": "2.0.0"},
        "paths": {path: {"post": {"summary": path}} for path in paths},
        "x-protocol-version": PROTOCOL_VERSION,
    }


class EnrollmentRequest(BaseModel):
    role: str = "edge"
    uses: int = 1
    ttl_seconds: int = 600


class NodeEnrollRequest(BaseModel):
    voucher: str
    node_id: str = ""
    protocol_version: int = 2


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
    fresh = await accept_remote(
        req.task_id or req.delegation_id,
        node.node_id,
        attempt=req.attempt,
        delegation_id=req.delegation_id,
    )
    logger.info(
        "command claim node_id=%s task_id=%s attempt=%s fresh=%s",
        node.node_id,
        req.task_id,
        req.attempt,
        fresh,
    )
    return {
        "accepted": fresh,
        "task_id": req.task_id,
        "delegation_id": req.delegation_id,
        "attempt": req.attempt,
        "status": "accepted" if fresh else "duplicate",
    }


@router.post("/commands/ack")
async def ack_command(
    req: ClaimRequest,
    x_node_token: str = Header(default=""),
) -> dict:
    _check_protocol(req.protocol_version)
    node = await _node_from_token(x_node_token)
    if node.role not in _CLAIM_ROLES:
        raise HTTPException(status_code=403, detail="role cannot ack executions")
    return {"acked": True, "node_id": node.node_id, "means": "persisted", "completed": False}


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
