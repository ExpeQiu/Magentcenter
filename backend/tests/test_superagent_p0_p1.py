"""P0/P1：Gate、Controller attach、Attention dismiss、沉默交付、Policy。"""

from __future__ import annotations

import asyncio
import time

from app.config import Settings
from app.core.agent_registry import AgentRegistry
from app.core import delivery as delivery_svc
from app.core import supervisor as attention_svc
from app.core import work_items as wi
from app.core.super_ai import handle_turn
from app.core.task_manager import TaskManager
from app.domain.superagent import controller as work_ctrl
from app.domain.superagent import policy as policy_svc
from app.models.db import create_tables, init_db


def test_policy_gate_and_bump(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    pol = policy_svc.load_policy()
    assert pol.mode == "observe"
    deny = policy_svc.gate(source="unknown-src", addressed=True, policy=pol)
    assert deny.strength == "deny"
    ok = policy_svc.gate(source="web", addressed=True, policy=pol)
    assert ok.strength == "explicit"
    inferred = policy_svc.gate(source="web", addressed=False, policy=pol)
    assert inferred.strength == "inferred"
    assert inferred.would_accept is False
    bumped = policy_svc.bump_policy(mode="auto")
    assert bumped.version == pol.version + 1
    assert bumped.mode == "auto"
    auto = policy_svc.gate(source="web", addressed=False, policy=bumped)
    assert auto.would_accept is True


def test_controller_attach_no_duplicate_task(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_MOCK_MODE", "true")
    init_db(f"sqlite+aiosqlite:///{tmp_path}/ctrl.db")

    async def run():
        await create_tables()
        settings = Settings(ai_mock_mode=True, local_auth_enabled=False)
        registry = AgentRegistry(settings)
        tm = TaskManager(settings=settings, registry=registry)
        session_id = "sess-follow"

        class Mon:
            pass

        first = await handle_turn(
            "新建任务：整理周报",
            workspace_slug="cyber",
            pending=None,
            last_href="",
            registry=registry,
            task_manager=tm,
            monitor=Mon(),
            session_id=session_id,
            channel="web",
            origin="super_ai",
        )
        assert first.task_id, first.reply
        owner = await work_ctrl.resolve_followup(session_id=session_id)
        assert owner is not None
        second = await handle_turn(
            "再加上本周重点",
            workspace_slug="cyber",
            pending=None,
            last_href="",
            registry=registry,
            task_manager=tm,
            monitor=Mon(),
            session_id=session_id,
            channel="web",
            origin="super_ai",
        )
        assert second.task_id == first.task_id or second.intent == "dispatch"
        # 不应新建第二个 task：follow-up 走 attach
        assert "没有新建" in second.reply or second.task_id == first.task_id

    asyncio.run(run())


def test_attention_dismiss_and_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/att.db")

    async def run():
        await create_tables()
        aid = await attention_svc.open_question(
            summary="需要确认修订",
            work_item_id="w1",
            task_id="t1",
            kind="revise_confirm",
            dedupe_key="revise:w1:1",
        )
        assert aid
        items = await attention_svc.list_open()
        assert any(i["id"] == aid for i in items)
        assert await attention_svc.dismiss(aid) is True
        items2 = await attention_svc.list_open()
        assert all(i["id"] != aid for i in items2)

        mid = await delivery_svc.enqueue(
            kind="result",
            work_item_id="w1",
            task_id="t1",
            summary="done",
        )
        assert mid and mid.startswith("wi:w1:")
        # progress 被丢弃
        assert await delivery_svc.enqueue(kind="progress", work_item_id="w1") is None  # type: ignore[arg-type]
        listed = await delivery_svc.list_for_work_item("w1", include_acked=True)
        assert len(listed) == 1
        assert listed[0]["payload"]["kind"] == "result"

    asyncio.run(run())


def test_gate_deny_unknown_source(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_MOCK_MODE", "true")
    init_db(f"sqlite+aiosqlite:///{tmp_path}/gate.db")

    async def run():
        await create_tables()
        settings = Settings(ai_mock_mode=True, local_auth_enabled=False)
        registry = AgentRegistry(settings)
        tm = TaskManager(settings=settings, registry=registry)

        class Mon:
            pass

        policy_svc.bump_policy(allowed_sources=["client"])
        res = await handle_turn(
            "新建任务：不该建",
            workspace_slug="cyber",
            pending=None,
            last_href="",
            registry=registry,
            task_manager=tm,
            monitor=Mon(),
            session_id="s1",
            channel="web",
            origin="super_ai",
        )
        assert res.intent == "clarify"
        assert not res.task_id

    asyncio.run(run())
