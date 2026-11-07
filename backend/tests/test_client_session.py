"""Client Session：对话身份与 Node Token 互斥；可调用云端超级AI turn。"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.core.access import enforce
from app.core import client_session as client_svc
from app.models.db import create_tables, init_db
from app.models.schemas import SuperAiTurnResponse


def _guard_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings

    @app.middleware("http")
    async def guard(request, call_next):
        denied = await enforce(request, settings)
        if denied is not None:
            return denied
        return await call_next(request)

    @app.post("/api/v2/clients/enroll")
    async def enroll(body: dict):
        from fastapi import HTTPException
        from app.core.client_session import ClientSessionError

        try:
            return await client_svc.enroll(
                enroll_token=body.get("enroll_token") or "",
                expected_token=settings.fleet_enroll_token,
                center_id=body.get("center_id") or "",
                client_id=body.get("client_id") or "",
                workspace_id=body.get("workspace_id") or "cyber",
            )
        except ClientSessionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @app.post("/api/super-ai/client/turn")
    async def client_turn():
        return SuperAiTurnResponse(
            run_id="r1",
            reply="ok",
            intent="chat",
            service="",
            href="",
            pending=None,
        )

    @app.post("/api/v2/commands/claim-next")
    async def claim_next():
        return {"ok": True}

    @app.get("/api/tasks")
    async def tasks():
        return {"ok": True}

    return app


def test_client_session_enroll_and_path_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/client.db")

    async def prepare():
        await create_tables()

    asyncio.run(prepare())
    settings = Settings(local_auth_enabled=True, fleet_enroll_token="secret")
    app = _guard_app(settings)

    async def run():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            bad = await client.post(
                "/api/v2/clients/enroll",
                json={"enroll_token": "wrong", "center_id": "c1"},
            )
            assert bad.status_code == 401

            enrolled = await client.post(
                "/api/v2/clients/enroll",
                json={"enroll_token": "secret", "center_id": "center-a", "client_id": "cli-a"},
            )
            assert enrolled.status_code == 200
            data = enrolled.json()
            token = data["client_token"]
            assert data["client_id"] == "cli-a"
            assert data["center_id"] == "center-a"

            ok = await client.post(
                "/api/super-ai/client/turn",
                headers={"X-Client-Token": token},
            )
            assert ok.status_code == 200
            assert ok.json()["reply"] == "ok"

            # Client 不可 claim
            denied = await client.post(
                "/api/v2/commands/claim-next",
                headers={"X-Client-Token": token},
            )
            assert denied.status_code == 403

            # Client 不可进管理面
            tasks = await client.get("/api/tasks", headers={"X-Client-Token": token})
            assert tasks.status_code == 403

            # Node token 不可调 client turn（无凭证时走会话门禁）
            from app.core import fleet

            node = await fleet.enroll(
                enroll_token="secret",
                expected_token="secret",
                node_id="pi",
                name="树莓派",
                agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
            )
            node_denied = await client.post(
                "/api/super-ai/client/turn",
                headers={"X-Node-Token": node["node_token"]},
            )
            assert node_denied.status_code == 403

    asyncio.run(run())


def test_mandate_blocks_cancel_without_permission(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/mandate.db")

    async def run():
        await create_tables()
        from app.core import work_items as wi
        from app.core.agent_registry import AgentRegistry
        from app.core.task_manager import TaskManager
        from app.domain.superagent import mandate as mandate_svc
        from app.models.db import MandateRecord, TaskRecord, get_session_factory
        from sqlalchemy import select

        settings = Settings(ai_mock_mode=True, local_auth_enabled=False)
        tm = TaskManager(settings=settings, registry=AgentRegistry(settings))
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                TaskRecord(
                    id="t-mandate",
                    agent_id="coder",
                    runtime="openclaw",
                    prompt="x",
                    status="queued",
                    origin="super_ai",
                )
            )
            await session.commit()
        wid = await wi.create_work_item(title="w", goal="g", task_id="t-mandate")
        async with factory() as session:
            rows = (
                await session.execute(
                    select(MandateRecord).where(MandateRecord.work_item_id == wid)
                )
            ).scalars().all()
            for row in rows:
                row.status = "revoked"
            await session.commit()
        await mandate_svc.issue(wid, permitted_actions=["task.execute"], policy_version=1)
        try:
            await tm.cancel_task("t-mandate")
            raise AssertionError("expected mandate deny")
        except ValueError as exc:
            assert "mandate" in str(exc)

    asyncio.run(run())
