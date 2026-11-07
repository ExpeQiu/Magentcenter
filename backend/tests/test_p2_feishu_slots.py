"""P2：飞书入站、Worker 槽位隔离、Overview 三问。"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.sources import router as sources_router
from app.config import Settings
from app.core.overview import build_overview
from app.core.worker_slots import WorkerSlotPool
from app.models.db import create_tables, init_db
from app.sources import feishu as feishu_src


def test_feishu_parse_challenge_and_message():
    assert feishu_src.parse_challenge({"type": "url_verification", "challenge": "abc"}) == "abc"
    inbound = feishu_src.extract_inbound(
        {
            "header": {"event_type": "im.message.receive_v1", "token": "tok"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_1"}},
                "message": {
                    "message_id": "om_1",
                    "chat_id": "oc_1",
                    "chat_type": "group",
                    "content": '{"text":"@_user_1 帮我查一下任务"}',
                    "mentions": [{"key": "@_user_1"}],
                },
            },
        }
    )
    assert inbound is not None
    assert "查一下任务" in inbound["text"]
    assert inbound["message_id"] == "om_1"
    assert feishu_src.is_addressed(inbound["event"]) is True

    group_no_mention = {
        "message": {
            "chat_type": "group",
            "content": '{"text":"闲聊一句"}',
            "mentions": [],
        }
    }
    assert feishu_src.is_addressed(group_no_mention) is False
    assert feishu_src.is_addressed(
        {"message": {"chat_type": "p2p", "content": '{"text":"你好"}'}}
    ) is True


def test_feishu_events_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_MOCK_MODE", "true")
    init_db(f"sqlite+aiosqlite:///{tmp_path}/feishu.db")

    async def prepare():
        await create_tables()

    asyncio.run(prepare())

    class FakeResult:
        run_id = "run-feishu-1"
        intent = "chat"
        task_id = ""
        reply = "收到，系统正常"

    async def fake_turn(*_a, **_k):
        return FakeResult()

    monkeypatch.setattr("app.core.super_ai.handle_turn", fake_turn)

    settings = Settings(
        ai_mock_mode=True,
        local_auth_enabled=False,
        feishu_verification_token="secret-token",
        feishu_webhook_url="",
    )
    app = FastAPI()
    app.state.settings = settings

    class Reg:
        async def list_agents(self, force_refresh=False):
            return []

    class Mon:
        pass

    app.state.registry = Reg()
    app.state.task_manager = object()
    app.state.monitor = Mon()
    app.include_router(sources_router)

    async def run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            ch = await client.post(
                "/api/sources/feishu/events",
                json={"type": "url_verification", "challenge": "ping", "token": "secret-token"},
            )
            assert ch.status_code == 200
            assert ch.json()["challenge"] == "ping"

            bad = await client.post(
                "/api/sources/feishu/events",
                json={
                    "header": {"event_type": "im.message.receive_v1", "token": "wrong"},
                    "event": {
                        "message": {
                            "message_id": "om_x",
                            "chat_id": "oc_x",
                            "chat_type": "p2p",
                            "content": '{"text":"你好"}',
                        }
                    },
                },
            )
            assert bad.status_code == 401

            ok = await client.post(
                "/api/sources/feishu/events",
                json={
                    "header": {"event_type": "im.message.receive_v1", "token": "secret-token"},
                    "event": {
                        "sender": {"sender_id": {"open_id": "ou_x"}},
                        "message": {
                            "message_id": "om_ok",
                            "chat_id": "oc_ok",
                            "chat_type": "p2p",
                            "content": '{"text":"系统是否正常"}',
                        },
                    },
                },
            )
            assert ok.status_code == 200
            body = ok.json()
            assert body.get("ok") is True
            assert body.get("run_id") == "run-feishu-1"

            again = await client.post(
                "/api/sources/feishu/events",
                json={
                    "header": {"event_type": "im.message.receive_v1", "token": "secret-token"},
                    "event": {
                        "sender": {"sender_id": {"open_id": "ou_x"}},
                        "message": {
                            "message_id": "om_ok",
                            "chat_id": "oc_ok",
                            "chat_type": "p2p",
                            "content": '{"text":"系统是否正常"}',
                        },
                    },
                },
            )
            assert again.status_code == 200
            assert again.json().get("deduped") is True

    asyncio.run(run())


def test_worker_slots_isolation():
    async def case():
        pool = WorkerSlotPool(capacity=2)
        a = await pool.try_acquire("t1", session_id="s1", work_item_id="w1")
        b = await pool.try_acquire("t2", session_id="s2", work_item_id="w2")
        assert a and b
        assert a.session_id != b.session_id
        c = await pool.try_acquire("t3", session_id="s1")
        assert c is None
        d = await pool.try_acquire("t4", session_id="s4")
        assert d is None
        await pool.release("t1")
        e = await pool.try_acquire("t4", session_id="s4")
        assert e is not None
        snap = pool.snapshot()
        assert snap["active"] == 2
        assert snap["capacity"] == 2

    asyncio.run(case())


def test_overview_compact(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/ov.db")

    async def run():
        await create_tables()
        settings = Settings(ai_mock_mode=True, max_concurrent_tasks=3)
        ov = await build_overview(settings=settings)
        assert "attention" in ov and "health" in ov and "recent" in ov
        assert ov["health"]["ok"] is True
        assert ov["compact"] is True
        assert ov["questions"]["healthy"]

    asyncio.run(run())
