"""多端：上报扫描、绑定后才能派单、领取与签名。"""

import asyncio
import time
from datetime import datetime, timedelta

import pytest

from app.core import fleet
from app.models.db import FleetNodeRecord, TaskRecord, create_tables, get_session_factory, init_db


class _Registry:
    def __init__(self, agents: list[dict]):
        self.agents = agents

    async def list_agents(self, force_refresh: bool = False) -> list[dict]:
        return list(self.agents)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/fleet.db")
    return tmp_path


def test_report_stays_unbound_until_bind(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr(fleet.socket, "gethostname", lambda: "studio.local")
        monkeypatch.setattr(fleet.platform, "system", lambda: "Darwin")

        with pytest.raises(fleet.FleetAuthError):
            await fleet.enroll(
                enroll_token="nope",
                expected_token="secret",
                node_id="pi",
                agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
            )

        reported = await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            name="树莓派",
            agents=[
                {"id": "default", "name": "Hermes/default", "runtime": "hermes", "model": "m"},
            ],
            hostname="pi.local",
        )
        assert reported["node_token"]
        assert reported["bound"] is False
        assert reported["seen"][0]["id"] == "default"

        with pytest.raises(fleet.FleetError):
            await fleet.plan_dispatch("pi", "hermes", "default")

        bound = await fleet.bind_selection(
            node_id="pi",
            name="树莓派",
            picks=[{"id": "default", "runtime": "hermes"}],
            registry=_Registry([]),
        )
        assert bound["bound"] is True
        assert bound["agents"][0]["runtime"] == "hermes"
        assert await fleet.plan_dispatch("pi", "hermes", "default") == {
            "node_id": "pi",
            "local": False,
        }
        with pytest.raises(fleet.FleetError):
            await fleet.plan_dispatch("pi", "openclaw", "default")

        info = await fleet.heartbeat(
            reported["node_token"],
            agents=[
                {"id": "default", "runtime": "hermes", "name": "Hermes/default"},
                {"id": "coder", "runtime": "openclaw", "name": "coder"},
            ],
            hostname="pi.local",
        )
        assert info["online"] is True
        assert info["bound"] is True
        assert {a["id"] for a in info["seen"]} == {"default", "coder"}
        assert [a["id"] for a in info["agents"]] == ["default"]

        body = b'{"type":"task.dispatch"}'
        ts = str(int(time.time()))
        sig = fleet.sign_body("secret", ts, body)
        assert fleet.verify_signature("secret", ts, body, sig)
        assert not fleet.verify_signature("secret", ts, body, "deadbeef")

    asyncio.run(scenario())


def test_local_scan_bind_and_claim_guard(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr(fleet.socket, "gethostname", lambda: "Mac-Studio.local")
        monkeypatch.setattr(fleet.platform, "system", lambda: "Darwin")
        registry = _Registry(
            [
                {"id": "main", "name": "main", "runtime": "openclaw", "model": "gpt"},
                {"id": "writer", "name": "writer", "runtime": "openclaw", "model": ""},
            ]
        )
        scan = await fleet.scan_host(registry)
        assert scan["node_id"] == "mac-studio"
        assert len(scan["agents"]) == 2

        bound = await fleet.bind_selection(
            node_id="",
            name="工作室",
            picks=[{"id": "main", "runtime": "openclaw"}],
            registry=registry,
        )
        assert bound["id"] == "mac-studio"
        assert bound["mode"] == "local"
        assert bound["online"] is True
        assert [a["id"] for a in bound["agents"]] == ["main"]
        plan = await fleet.plan_dispatch("auto", "openclaw", "main")
        assert plan == {"node_id": "mac-studio", "local": True}

        with pytest.raises(fleet.FleetError):
            await fleet.plan_dispatch("auto", "openclaw", "writer")

        removed = await fleet.unbind_node("mac-studio")
        assert removed["removed"] is True
        assert await fleet.list_nodes() == []

        enrolled = await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            name="树莓派",
            agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
        )
        token = enrolled["node_token"]
        assert await fleet.claim(token) is None

        await fleet.bind_selection(
            node_id="pi",
            name="树莓派",
            picks=[{"id": "default", "runtime": "hermes"}],
            registry=registry,
        )
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                TaskRecord(
                    id="task-1",
                    agent_id="default",
                    runtime="hermes",
                    prompt="ping",
                    status="queued",
                    node_id="pi",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()

        first = await fleet.claim(token)
        second = await fleet.claim(token)
        assert first and first["id"] == "task-1"
        assert second is None
        done = await fleet.finish(token, "task-1", status="completed", output="pong")
        assert done["status"] == "completed"

        async with factory() as session:
            row = await session.get(FleetNodeRecord, "pi")
            assert row is not None
            row.last_seen = datetime.utcnow() - timedelta(hours=1)
            await session.commit()
        with pytest.raises(fleet.FleetError):
            await fleet.plan_dispatch("auto", "hermes", "default")
        await fleet.heartbeat(token, hostname="pi.local")
        assert (await fleet.plan_dispatch("auto", "hermes", "default"))["node_id"] == "pi"

        unbound = await fleet.unbind_node("pi")
        assert unbound["bound"] is False
        assert unbound["workspace_id"] == ""
        assert await fleet.claim(token) is None

    asyncio.run(scenario())


def test_terminal_belongs_to_team(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr(fleet.socket, "gethostname", lambda: "studio.local")
        monkeypatch.setattr(fleet.platform, "system", lambda: "Darwin")
        await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            name="树莓派",
            agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
        )
        visible = await fleet.list_nodes("ws-geely")
        assert [n["id"] for n in visible] == ["pi"]

        bound = await fleet.bind_selection(
            node_id="pi",
            name="树莓派",
            picks=[{"id": "default", "runtime": "hermes"}],
            registry=_Registry([]),
            workspace_id="ws-cyber",
        )
        assert bound["workspace_id"] == "ws-cyber"
        assert [n["id"] for n in await fleet.list_nodes("ws-cyber")] == ["pi"]
        assert await fleet.list_nodes("ws-geely") == []
        with pytest.raises(fleet.FleetError):
            await fleet.plan_dispatch("pi", "hermes", "default", workspace_id="ws-geely")
        assert (await fleet.plan_dispatch("pi", "hermes", "default", workspace_id="ws-cyber"))[
            "node_id"
        ] == "pi"

    asyncio.run(scenario())
