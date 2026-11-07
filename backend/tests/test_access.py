"""身份边界：无效令牌不能进管理接口，WebSocket 要先核对会话和任务。"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.v2 import create_enrollment, enroll_node
from app.api.ws import router as ws_router
from app.config import Settings
from app.core import fleet
from app.core.access import enforce
from app.core.device_channel import enroll_device
from app.core.local_auth import (
    ensure_entry_code,
    ensure_local_session,
    revoke_local_session,
    session_matches,
)
from app.models.db import create_tables, init_db
from app.models.schemas import TaskEvent


def _guard_app(settings: Settings) -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def guard(request, call_next):
        denied = await enforce(request, settings)
        if denied is not None:
            return denied
        return await call_next(request)

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/tasks")
    async def tasks():
        return {"ok": True}

    @app.post("/api/v2/enrollments")
    async def enrollments():
        return {"ok": True}

    @app.patch("/api/settings/content-roots")
    async def roots():
        return {"ok": True}

    @app.post("/api/fleet/claim")
    async def claim():
        return {"ok": True}

    @app.post("/api/super-ai/device/turn")
    async def device_turn():
        return {"ok": True}

    @app.post("/api/super-ai/client/turn")
    async def client_turn():
        return {"ok": True}

    return app


class _Tasks:
    def __init__(self):
        now = datetime.now(timezone.utc)
        self.task = type(
            "Task",
            (),
            {"id": "t1", "status": "running", "attention_required": False, "node_id": "pi"},
        )()
        self.now = now

    async def get_task(self, task_id):
        if task_id == "t1":
            return self.task
        return None

    async def get_events(self, task_id, after_id=0):
        events = [
            TaskEvent(id=1, type="status", content="running", timestamp=self.now),
            TaskEvent(id=2, type="result", content="done", timestamp=self.now),
        ]
        return [item for item in events if (item.id or 0) > after_id]


def test_tokens_cannot_bypass_management_or_open_websocket(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/access.db")
    settings = Settings(
        local_auth_enabled=True,
        entry_code="test-entry",
        admin_token="admin-secret",
        fleet_enroll_token="secret",
    )

    async def prepare():
        await create_tables()
        device = await enroll_device(
            enroll_token="secret",
            expected_token="secret",
            device_id="esp32-room",
            name="客厅",
        )
        node = await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            name="树莓派",
            agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
        )
        voucher = await create_enrollment(
            type("Req", (), {"role": "conversation", "uses": 1, "ttl_seconds": 60})()
        )
        conversation = await enroll_node(
            type(
                "Enroll",
                (),
                {"voucher": voucher["voucher"], "node_id": "talk", "protocol_version": 2},
            )()
        )
        return device["device_token"], node["node_token"], conversation["node_token"]

    device_token, node_token, conversation_token = asyncio.run(prepare())
    session = ensure_local_session()
    app = _guard_app(settings)

    async def http_case():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/api/health")).status_code == 200
            assert (await client.get("/api/tasks")).status_code == 401
            assert (
                await client.get("/api/tasks", headers={"X-Node-Token": "not-a-token"})
            ).status_code == 401
            assert (
                await client.get("/api/tasks", headers={"X-Device-Token": "not-a-token"})
            ).status_code == 401
            assert (
                await client.get("/api/tasks", headers={"X-AgentCenter-Session": session})
            ).status_code == 200
            assert (
                await client.get("/api/tasks", headers={"X-Admin-Token": "admin-secret"})
            ).status_code == 200
            for header in (
                {"X-Device-Token": device_token},
                {"X-Node-Token": conversation_token},
            ):
                assert (await client.get("/api/tasks", headers=header)).status_code == 403
                # enrollments 为公开登记口；设备令牌不能进管理写接口
                assert (await client.post("/api/v2/enrollments", headers=header)).status_code == 200
                assert (
                    await client.patch("/api/settings/content-roots", headers=header)
                ).status_code == 403
            # Client Session 不可 claim / 管理面
            from app.core import client_session as client_svc

            client_enrolled = await client_svc.enroll(
                enroll_token="secret",
                expected_token="secret",
                center_id="center-test",
                client_id="client-test",
            )
            client_headers = {"X-Client-Token": client_enrolled["client_token"]}
            assert (await client.get("/api/tasks", headers=client_headers)).status_code == 403
            assert (
                await client.post("/api/fleet/claim", headers=client_headers)
            ).status_code == 403
            assert (
                await client.post("/api/super-ai/client/turn", headers=client_headers)
            ).status_code == 200
            assert (
                await client.post(
                    "/api/super-ai/client/turn", headers={"X-Node-Token": node_token}
                )
            ).status_code == 403
            assert (
                await client.post("/api/super-ai/device/turn", headers={"X-Device-Token": device_token})
            ).status_code == 200
            assert (
                await client.post("/api/fleet/claim", headers={"X-Node-Token": node_token})
            ).status_code == 200
            assert (
                await client.get("/api/tasks", headers={"X-Node-Token": node_token})
            ).status_code == 403

    asyncio.run(http_case())

    socket_app = FastAPI()
    socket_app.include_router(ws_router)
    socket_app.state.settings = settings
    socket_app.state.task_manager = _Tasks()
    with TestClient(socket_app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/tasks/t1") as ws:
                ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/tasks/t1",
                headers={
                    "x-agentcenter-session": session,
                    "origin": "https://evil.example",
                },
            ) as ws:
                ws.receive_json()
        with client.websocket_connect(
            "/ws/tasks/t1?after=1",
            headers={
                "x-agentcenter-session": session,
                "origin": "http://127.0.0.1:3013",
            },
        ) as ws:
            payload = ws.receive_json()
        assert payload["type"] == "result"
        assert payload["content"] == "done"
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/ws/tasks/t1",
                headers={"x-node-token": device_token, "origin": "http://127.0.0.1:3013"},
            ) as ws:
                ws.receive_json()
        with client.websocket_connect(
            "/ws/tasks/t1?after=1",
            headers={"x-node-token": node_token},
        ) as ws:
            owned = ws.receive_json()
        assert owned["type"] == "result"


def test_entry_code_is_unique_and_session_can_expire(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    first = ensure_entry_code("")
    second = ensure_entry_code("")
    assert first == second
    assert first != "Qb123!456"
    assert (tmp_path / "entry_code").is_file()
    assert ensure_entry_code("configured-secret") == "configured-secret"

    current = ensure_local_session()
    assert session_matches(current) is True
    meta = tmp_path / "local_session.meta"
    meta.write_text('{"issued_at": 1, "expires_at": 1}', encoding="utf-8")
    assert session_matches(current) is False
    rotated = (tmp_path / "local_session.token").read_text(encoding="utf-8").strip()
    assert rotated != current
    assert session_matches(rotated) is True
    revoke_local_session()
    assert session_matches(rotated) is False
