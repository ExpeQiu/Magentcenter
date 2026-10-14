"""跨端委托、工作区映射、深度和循环校验。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.autonomy_state import ancestor_has_cycle, depth_allowed
from app.core.privacy import payload_hash, redact_for_sync
from app.core.sync_bus import enqueue
from app.models.db import DelegationRecord, WorkspaceLinkRecord, get_session_factory

logger = logging.getLogger(__name__)


class DelegationError(ValueError):
    pass


def authorize_workspace(
    local_workspace_id: str,
    remote_center_id: str,
    remote_workspace_id: str,
    links: list[dict],
) -> bool:
    """相同 slug 不算同一工作区，必须有显式映射。"""
    for link in links:
        if (
            link.get("local_workspace_id") == local_workspace_id
            and link.get("remote_center_id") == remote_center_id
            and link.get("remote_workspace_id") == remote_workspace_id
        ):
            return True
    return False


async def link_workspaces(
    local_workspace_id: str,
    remote_center_id: str,
    remote_workspace_id: str,
) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        row = WorkspaceLinkRecord(
            id=str(uuid.uuid4()),
            local_workspace_id=local_workspace_id,
            remote_center_id=remote_center_id,
            remote_workspace_id=remote_workspace_id,
        )
        session.add(row)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
        return {
            "local_workspace_id": local_workspace_id,
            "remote_center_id": remote_center_id,
            "remote_workspace_id": remote_workspace_id,
        }


async def list_links() -> list[dict]:
    factory = get_session_factory()
    async with factory() as session:
        rows = (await session.execute(select(WorkspaceLinkRecord))).scalars().all()
        return [
            {
                "local_workspace_id": row.local_workspace_id,
                "remote_center_id": row.remote_center_id,
                "remote_workspace_id": row.remote_workspace_id,
            }
            for row in rows
        ]


async def create_delegation(
    *,
    owner_center_id: str,
    task_id: str,
    target_node_id: str,
    idempotency_key: str,
    payload: dict,
    source_node_id: str,
    target_center_id: str,
    parent_task_ref: str = "",
    root_task_ref: str = "",
    ancestors: list[str] | None = None,
    depth: int = 1,
    trace_id: str = "",
    visibility: str = "shared",
) -> dict:
    if not depth_allowed(depth):
        raise DelegationError("delegation depth exceeded")
    chain = list(ancestors or [])
    if ancestor_has_cycle(chain, target_node_id):
        raise DelegationError("delegation cycle")
    shared = redact_for_sync({**payload, "task_id": task_id, "visibility": visibility}, visibility)
    digest = payload_hash(shared)
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(DelegationRecord).where(DelegationRecord.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing:
            if existing.payload_hash != digest:
                raise DelegationError("idempotency key reused with different content")
            return _dump(existing)
        delegation_id = str(uuid.uuid4())
        row = DelegationRecord(
            id=delegation_id,
            owner_center_id=owner_center_id,
            task_id=task_id,
            target_node_id=target_node_id,
            idempotency_key=idempotency_key,
            payload_hash=digest,
            payload_json=json.dumps(shared, ensure_ascii=False),
            auth_snapshot_json=json.dumps({"visibility": visibility, "target": target_node_id}),
            delivery_status="pending",
            parent_task_ref=parent_task_ref,
            root_task_ref=root_task_ref or parent_task_ref or task_id,
            trace_id=trace_id or str(uuid.uuid4()),
            depth=depth,
            ancestor_json=json.dumps(chain, ensure_ascii=False),
        )
        session.add(row)
        from app.core.sync_bus import envelope

        message = envelope(
            message_type="delegation.created",
            source_node_id=source_node_id,
            target_center_id=target_center_id,
            owner_center_id=owner_center_id,
            task_id=task_id,
            delegation_id=delegation_id,
            trace_id=row.trace_id,
            payload=shared,
        )
        await enqueue(session, message)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise DelegationError("idempotency key reused with different content") from exc
        dumped = _dump(row)
    logger.info(
        "delegation created delegation_id=%s task_id=%s target=%s depth=%s",
        delegation_id,
        task_id,
        target_node_id,
        depth,
    )
    return dumped


def _dump(row: DelegationRecord) -> dict:
    return {
        "delegation_id": row.id,
        "task_id": row.task_id,
        "target_node_id": row.target_node_id,
        "delivery_status": row.delivery_status,
        "depth": row.depth,
        "trace_id": row.trace_id,
        "owner_center_id": row.owner_center_id,
        "created_at": (row.created_at or datetime.utcnow()).isoformat(),
    }
