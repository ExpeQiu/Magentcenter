"""v2 claim-next + finish + 迟到 generation 拒绝。"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

os.environ.setdefault("AI_MOCK_MODE", "true")

from app.core.execution import ClaimError, claim_next, finish_execution
from app.core.identity import load_or_create_identity
from app.models.db import TaskRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/claim.db")
    return tmp_path


def test_claim_next_and_stale_finish(db):
    async def scenario():
        await create_tables()
        ident = load_or_create_identity()
        task_id = str(uuid.uuid4())
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                TaskRecord(
                    id=task_id,
                    agent_id="main",
                    runtime="openclaw",
                    prompt="hello",
                    status="queued",
                    owner_center_id=ident.center_id,
                    node_id=ident.node_id,
                )
            )
            await session.commit()

        claimed = await claim_next(ident.node_id)
        assert claimed is not None
        assert claimed["accepted"] is True
        assert claimed["task_id"] == task_id
        execution_id = claimed["execution_id"]

        done = await finish_execution(
            ident.node_id,
            task_id=task_id,
            execution_id=execution_id,
            status="completed",
            output="ok",
            generation=1,
        )
        assert done["status"] == "completed"

        task2 = str(uuid.uuid4())
        async with factory() as session:
            session.add(
                TaskRecord(
                    id=task2,
                    agent_id="main",
                    runtime="openclaw",
                    prompt="again",
                    status="queued",
                    owner_center_id=ident.center_id,
                    node_id=ident.node_id,
                )
            )
            await session.commit()
        claimed2 = await claim_next(ident.node_id)
        assert claimed2 is not None
        with pytest.raises(ClaimError) as exc:
            await finish_execution(
                ident.node_id,
                task_id=claimed2["task_id"],
                execution_id=claimed2["execution_id"],
                status="completed",
                output="late",
                generation=99,
            )
        assert exc.value.status_code == 409

    asyncio.run(scenario())
