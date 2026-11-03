"""WorkItem、租约 fencing、硬件指令、Router。"""

import asyncio
from datetime import datetime, timedelta

import pytest

from app.core.execution import ClaimError, bump_generation, open_local, reject_stale_write, set_delivery_ack
from app.core.hardware_commands import enqueue, claim_next
from app.core.work_items import (
    accept_work_item,
    append_message,
    create_work_item,
    ensure_conversation,
    record_trigger,
)
from app.domain.superagent.router import controller_accept, evaluate
from app.domain.superagent.watchdog import inspect_attempts
from app.models.db import ExecutionRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/wi.db")
    return tmp_path


def test_work_item_trigger_and_accept(db):
    async def scenario():
        await create_tables()
        cid = await ensure_conversation("c1", workspace_id="cyber")
        assert cid == "c1"
        t1 = await record_trigger(
            source="conversation",
            external_event_id="idem-1",
            conversation_id=cid,
        )
        assert t1
        t2 = await record_trigger(
            source="conversation",
            external_event_id="idem-1",
            conversation_id=cid,
        )
        assert t2 is None
        mid = await append_message(cid, role="user", content="整理文档", idempotency_key="m1")
        mid2 = await append_message(cid, role="user", content="整理文档", idempotency_key="m1")
        assert mid == mid2
        wid = await create_work_item(title="整理", goal="整理文档", conversation_id=cid)
        assert await accept_work_item(wid)

    asyncio.run(scenario())


def test_lease_fencing(db):
    async def scenario():
        await create_tables()
        eid = await open_local("task-1", "openclaw", "coder")
        gen = await bump_generation(eid)
        assert gen >= 2
        await set_delivery_ack(eid, "received", generation=gen)
        with pytest.raises(ClaimError):
            await reject_stale_write(eid, generation=gen - 1)
        await reject_stale_write(eid, generation=gen)

        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(ExecutionRecord, eid)
            row.lease_expires_at = datetime.utcnow() - timedelta(minutes=10)
            await session.commit()
        with pytest.raises(ClaimError):
            await set_delivery_ack(eid, "applied", generation=gen)

    asyncio.run(scenario())


def test_hardware_expiry_and_estop(db):
    async def scenario():
        await create_tables()
        estop = await enqueue("esp1", "emergency_stop")
        assert estop["status"] == "applied"
        queued = await enqueue("esp1", "blink", ttl_seconds=1, idempotency_key="b1")
        assert queued["status"] == "queued"
        again = await enqueue("esp1", "blink", ttl_seconds=1, idempotency_key="b1")
        assert again["id"] == queued["id"]
        # 过期
        factory = get_session_factory()
        from app.models.db import HardwareCommandRecord

        async with factory() as session:
            row = await session.get(HardwareCommandRecord, queued["id"])
            row.expires_at = datetime.utcnow() - timedelta(seconds=5)
            await session.commit()
        nxt = await claim_next("esp1")
        assert nxt is None

    asyncio.run(scenario())


def test_router_and_watchdog():
    async def scenario():
        s = await evaluate(text="停止吧", work_item_id="w1")
        assert s.action == "stop"
        assert controller_accept(s, expected_policy=1, actual_policy=1)
        assert not controller_accept(s, expected_policy=1, actual_policy=2)
        advice = inspect_attempts(fail_streak=3, same_error_count=3)
        assert advice.kind == "suggest_pause"

    asyncio.run(scenario())


def test_legacy_work_items_table_rebuild(db):
    import sqlite3

    from sqlalchemy import select

    from app.models.db import WorkItemRecord

    path = db / "legacy-wi.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE work_items (
            id VARCHAR(36) NOT NULL,
            owner_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(64) NOT NULL,
            conversation_id VARCHAR(128) NOT NULL,
            title VARCHAR(256) NOT NULL,
            goal TEXT NOT NULL,
            state VARCHAR(32) NOT NULL,
            state_version INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            requirements_revision INTEGER NOT NULL,
            plan_revision INTEGER NOT NULL,
            target_json TEXT NOT NULL,
            constraints_json TEXT NOT NULL,
            waiting_reason TEXT NOT NULL,
            question_id VARCHAR(128) NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
            PRIMARY KEY (id)
        )
        """
    )
    conn.execute(
        "INSERT INTO work_items VALUES ("
        "'w-legacy','owner','ws-cyber','conv','旧标题','旧目标','waiting',3,0,4,1,"
        "'{}','{}','need-confirm','q1',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    init_db(f"sqlite+aiosqlite:///{path}")

    async def scenario():
        await create_tables()
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(select(WorkItemRecord))).scalars().all()
            assert len(rows) == 1
            assert rows[0].id == "w-legacy"
            assert rows[0].status == "waiting"
            assert rows[0].wait_reason == "need-confirm"
            assert rows[0].requirement_revision == 4
            assert rows[0].owner_center_id == ""

    asyncio.run(scenario())
