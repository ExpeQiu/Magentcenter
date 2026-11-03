"""Supervisor Attention 单测：租约过期 / outbox 积压。"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("AI_MOCK_MODE", "true")

from app.core import supervisor
from app.core.identity import load_or_create_identity
from app.models.db import ExecutionRecord, OutboxRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/sup.db")
    return tmp_path


def test_supervisor_opens_lease_and_outbox_attention(db):
    async def scenario():
        await create_tables()
        ident = load_or_create_identity()
        factory = get_session_factory()
        old = datetime.utcnow() - timedelta(minutes=30)
        async with factory() as session:
            session.add(
                ExecutionRecord(
                    id=str(uuid.uuid4()),
                    task_id=str(uuid.uuid4()),
                    owner_center_id=ident.center_id,
                    node_id=ident.node_id,
                    attempt=1,
                    dedupe_key=f"remote:t:1:{uuid.uuid4()}",
                    status="running",
                    lease_expires_at=old,
                    assignment_generation=1,
                )
            )
            session.add(
                OutboxRecord(
                    message_id=str(uuid.uuid4()),
                    target_center_id="peer",
                    message_type="execution.completed",
                    payload_json="{}",
                    acked=0,
                    created_at=old,
                )
            )
            await session.commit()

        result = await supervisor.run_once()
        assert result["opened"] >= 1
        open_rows = await supervisor.list_open()
        kinds = {r["kind"] for r in open_rows}
        assert "lease_expired" in kinds or "outbox_age" in kinds

    asyncio.run(scenario())
