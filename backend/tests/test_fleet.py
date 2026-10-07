"""多端：上报扫描、绑定后才能派单、领取与签名。"""

import asyncio
import json
import time
from datetime import datetime, timedelta

import pytest

from app.config import Settings
from app.core import fleet
from app.core.task_manager import TaskManager
from app.models.db import FleetNodeRecord, TaskRecord, create_tables, get_session_factory, init_db


class _Registry:
    def __init__(self, agents: list[dict]):
        self.agents = agents

    async def list_agents(self, force_refresh: bool = False) -> list[dict]:
        return list(self.agents)

    async def get_agent(self, agent_id: str, runtime: str | None = None):
        for item in self.agents:
            if item["id"] == agent_id and (runtime is None or item["runtime"] == runtime):
                return type("Agent", (), item)()
        return None


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


def test_peers_from_legacy_nodes():
    peers = fleet.peers_from_nodes(
        [
            {
                "id": "self",
                "name": "self",
                "bound": True,
                "online": True,
                "agents": [{"id": "main", "name": "main", "runtime": "openclaw"}],
            },
            {
                "id": "pi",
                "name": "树莓派",
                "bound": True,
                "online": False,
                "mode": "plugin",
                "hostname": "pi.local",
                "agents": [{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
            },
            {"id": "spare", "name": "spare", "bound": False, "agents": []},
        ],
        exclude="self",
    )
    assert [p["id"] for p in peers] == ["pi"]
    assert peers[0]["capabilities"] == ["hermes.chat", "task.execute"]


def test_legacy_cloud_enroll_binds_and_lists_peers(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(fleet.socket, "gethostname", lambda: "Mac-Studio.local")
        monkeypatch.setattr(fleet.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(fleet, "link_path", lambda: tmp_path / "fleet_link.json")
        monkeypatch.setattr(fleet, "link_token_path", lambda: tmp_path / "fleet_link.token")
        calls: list[str] = []

        async def fake_post(url, path, payload, legacy_on_404=False):
            calls.append(path)
            if path == "/api/fleet/handshake":
                raise fleet.FleetLegacyCloud(path)
            if path == "/api/fleet/enroll":
                assert payload["enroll_token"] == "secret"
                return {"node_id": payload["node_id"], "node_token": "edge-token", "bound": False}
            if path == "/api/fleet/bind":
                return {"id": payload["node_id"], "agents": payload["agents"], "bound": True}
            raise AssertionError(path)

        async def fake_get(url, path):
            assert path == "/api/fleet/nodes"
            return [
                {
                    "id": "mac-studio",
                    "name": "mac",
                    "bound": True,
                    "online": True,
                    "mode": "plugin",
                    "agents": [{"id": "main", "name": "main", "runtime": "openclaw"}],
                },
                {
                    "id": "cloud",
                    "name": "云",
                    "bound": True,
                    "online": True,
                    "mode": "local",
                    "hostname": "cloud",
                    "agents": [{"id": "qa", "name": "qa", "runtime": "openclaw"}],
                },
            ]

        monkeypatch.setattr(fleet, "_post_cloud", fake_post)
        monkeypatch.setattr(fleet, "_get_cloud", fake_get)
        linked = await fleet.open_link(
            cloud_url="http://cloud.example:8080",
            workspace_id="ws-cyber",
            registry=_Registry(
                [{"id": "main", "name": "main", "runtime": "openclaw", "model": ""}]
            ),
            enroll_token="secret",
        )
        assert calls == ["/api/fleet/handshake", "/api/fleet/enroll", "/api/fleet/bind"]
        assert linked["state"] == "ok"
        assert linked["node_id"] == "mac-studio"
        assert [p["id"] for p in linked["peers"]] == ["cloud"]
        assert (tmp_path / "fleet_link.token").read_text(encoding="utf-8") == "edge-token"

    asyncio.run(scenario())


def test_saved_cloud_url_not_replaced_by_env(tmp_path, monkeypatch):
    path = tmp_path / "fleet_link.json"
    path.write_text(json.dumps({"cloud_url": ""}), encoding="utf-8")
    monkeypatch.setattr(fleet, "link_path", lambda: path)
    assert fleet.displayed_cloud_url("http://cloud.example:8013") == ""
    assert fleet.normalize_cloud_url("http://cloud.example:8013/") == "http://cloud.example:8013"
    with pytest.raises(fleet.FleetError):
        fleet.normalize_cloud_url("ftp://cloud.example")


def test_handshake_binds_local_and_returns_other_peers(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr(fleet.socket, "gethostname", lambda: "Mac-Studio.local")
        monkeypatch.setattr(fleet.platform, "system", lambda: "Darwin")
        monkeypatch.setattr(fleet, "link_path", lambda: db / "fleet_link.json")
        monkeypatch.setattr(fleet, "link_token_path", lambda: db / "fleet_link.token")
        registry = _Registry(
            [
                {"id": "main", "name": "main", "runtime": "openclaw", "model": "gpt"},
            ]
        )

        offered = await fleet.begin_handshake(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            nonce="nonce-from-pi",
            name="树莓派",
            agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
            hostname="pi.local",
        )
        with pytest.raises(fleet.FleetAuthError):
            await fleet.complete_handshake(
                enroll_token="secret",
                expected_token="secret",
                node_id="pi",
                proof="0" * 64,
            )
        bound_pi = await fleet.complete_handshake(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            proof=fleet.handshake_proof("secret", "client", offered["challenge"]),
        )
        assert bound_pi["bound"] is True
        assert bound_pi["handshake"] == "ok"
        assert bound_pi["capabilities"] == ["hermes.chat", "task.execute"]
        assert bound_pi["peers"] == []
        assert fleet.handshake_proof("secret", "cloud", f"nonce-from-pi.{offered['challenge']}") == offered[
            "cloud_proof"
        ]

        linked = await fleet.open_link(
            cloud_url="",
            workspace_id="ws-cyber",
            registry=registry,
            enroll_token="secret",
        )
        assert linked["state"] == "ok"
        assert linked["node_id"] == "mac-studio"
        assert linked["local_cloud"] is True
        assert [a["id"] for a in linked["agents"]] == ["main"]
        assert [p["id"] for p in linked["peers"]] == ["pi"]
        assert "openclaw.agent" in linked["capabilities"]
        assert "node_token" not in (db / "fleet_link.json").read_text(encoding="utf-8")
        plan = await fleet.plan_dispatch("mac-studio", "openclaw", "main", workspace_id="ws-cyber")
        assert plan == {"node_id": "mac-studio", "local": True}
        again = await fleet.open_link(
            cloud_url="",
            workspace_id="ws-cyber",
            registry=registry,
            enroll_token="",
        )
        assert again["state"] == "ok"
        assert again["enroll_configured"] is False
        with pytest.raises(fleet.FleetAuthError):
            await fleet.open_link(
                cloud_url="http://cloud.example:8013",
                workspace_id="ws-cyber",
                registry=registry,
                enroll_token="",
            )

        await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="spare",
            name="未绑定",
            agents=[{"id": "writer", "name": "writer", "runtime": "openclaw"}],
        )
        peers = await fleet.peer_catalog(exclude="mac-studio", workspace_id="ws-cyber")
        assert [p["id"] for p in peers] == ["pi"]

        stale = await fleet.begin_handshake(
            enroll_token="secret",
            expected_token="secret",
            node_id="late",
            nonce="nonce-late-01",
            agents=[{"id": "default", "name": "Hermes/default", "runtime": "hermes"}],
        )
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(FleetNodeRecord, "late")
            assert row is not None
            row.handshake_expires = datetime.utcnow() - timedelta(seconds=5)
            await session.commit()
        with pytest.raises(fleet.FleetError):
            await fleet.complete_handshake(
                enroll_token="secret",
                expected_token="secret",
                node_id="late",
                proof=fleet.handshake_proof("secret", "client", stale["challenge"]),
            )

    asyncio.run(scenario())


def test_any_endpoint_calls_other_agent_including_cloud(db, monkeypatch):
    """云端、边缘都能把任务派到另一端的主智能体或子智能体，并由对方做完。"""

    async def scenario():
        await create_tables()
        monkeypatch.setattr(fleet.socket, "gethostname", lambda: "Cloud.local")
        monkeypatch.setattr(fleet.platform, "system", lambda: "Linux")
        registry = _Registry(
            [
                {"id": "main", "name": "main", "runtime": "openclaw", "model": ""},
                {"id": "researcher", "name": "researcher", "runtime": "openclaw", "model": ""},
            ]
        )
        await fleet.bind_selection(
            node_id="",
            name="云",
            picks=[
                {"id": "main", "runtime": "openclaw"},
                {"id": "researcher", "runtime": "openclaw"},
            ],
            registry=registry,
        )
        pi = await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="pi",
            name="树莓派",
            agents=[
                {"id": "default", "name": "Hermes/default", "runtime": "hermes"},
                {"id": "coder", "name": "coder", "runtime": "hermes"},
            ],
        )
        await fleet.bind_selection(
            node_id="pi",
            name="树莓派",
            picks=[
                {"id": "default", "runtime": "hermes"},
                {"id": "coder", "runtime": "hermes"},
            ],
            registry=registry,
        )
        laptop = await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="laptop",
            name="笔记本",
            agents=[{"id": "writer", "name": "writer", "runtime": "openclaw"}],
        )
        await fleet.bind_selection(
            node_id="laptop",
            name="笔记本",
            picks=[{"id": "writer", "runtime": "openclaw"}],
            registry=registry,
        )
        spare = await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="spare",
            name="未绑定",
            agents=[{"id": "writer", "name": "writer", "runtime": "openclaw"}],
        )
        voice = await fleet.enroll_voice(
            enroll_token="secret",
            expected_token="secret",
            device_id="esp",
            name="语音",
        )

        manager = TaskManager(
            Settings(knowledge_inject_enabled=False, skill_mine_enabled=False),
            registry,
        )

        async def local_done(task_id, req):
            await manager._update_task(task_id, status="completed", output=f"local:{req.agent_id}")

        manager._dispatch = local_done

        async def settle():
            pending = [job for job in asyncio.all_tasks() if job is not asyncio.current_task()]
            if pending:
                await asyncio.gather(*pending)

        cloud_to_pi = await fleet.call_peer_as_cloud(
            target="pi",
            runtime="hermes",
            agent_id="coder",
            prompt="写一段检查",
            task_manager=manager,
        )
        assert cloud_to_pi["caller"] == "cloud"
        assert cloud_to_pi["node_id"] == "pi"
        assert cloud_to_pi["kind"] == "subagent"
        assert cloud_to_pi["local"] is False
        assert cloud_to_pi["status"] == "queued"
        claimed = await fleet.claim(pi["node_token"])
        assert claimed["id"] == cloud_to_pi["id"]
        assert claimed["agent_id"] == "coder"
        done = await fleet.finish(
            pi["node_token"],
            claimed["id"],
            status="completed",
            output="coder-done",
        )
        assert done["status"] == "completed"
        assert done["output"] == "coder-done"
        with pytest.raises(fleet.FleetAuthError):
            await fleet.finish(
                laptop["node_token"],
                claimed["id"],
                status="completed",
                output="nope",
            )

        edge_to_edge = await fleet.call_peer_from_token(
            laptop["node_token"],
            target="pi",
            runtime="hermes",
            agent_id="default",
            prompt="汇总",
            task_manager=manager,
        )
        assert edge_to_edge["caller"] == "laptop"
        assert edge_to_edge["kind"] == "agent"
        assert edge_to_edge["node_id"] == "pi"
        taken = await fleet.claim(pi["node_token"])
        assert taken["agent_id"] == "default"
        await fleet.finish(pi["node_token"], taken["id"], status="completed", output="default-done")

        edge_to_cloud = await fleet.call_peer_from_token(
            pi["node_token"],
            target="cloud",
            runtime="openclaw",
            agent_id="researcher",
            prompt="查资料",
            task_manager=manager,
        )
        assert edge_to_cloud["caller"] == "pi"
        assert edge_to_cloud["node_id"] == "cloud"
        assert edge_to_cloud["kind"] == "subagent"
        assert edge_to_cloud["local"] is True
        await settle()
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(TaskRecord, edge_to_cloud["id"])
            assert row is not None
            assert row.status == "completed"
            assert row.output == "local:researcher"
            assert row.node_id == "cloud"

        with pytest.raises(fleet.FleetError):
            await fleet.call_peer_from_token(
                pi["node_token"],
                target="pi",
                runtime="hermes",
                agent_id="coder",
                prompt="自己调自己",
                task_manager=manager,
            )
        with pytest.raises(fleet.FleetError):
            await fleet.call_peer_from_token(
                spare["node_token"],
                target="pi",
                runtime="hermes",
                agent_id="default",
                prompt="未绑定",
                task_manager=manager,
            )
        with pytest.raises(fleet.FleetError):
            await fleet.call_peer_from_token(
                voice["device_token"],
                target="pi",
                runtime="hermes",
                agent_id="default",
                prompt="语音",
                task_manager=manager,
            )
        with pytest.raises(fleet.FleetError):
            await fleet.call_peer_as_cloud(
                target="pi",
                runtime="hermes",
                agent_id="missing",
                prompt="没有这个子智能体",
                task_manager=manager,
            )

        await fleet.enroll(
            enroll_token="secret",
            expected_token="secret",
            node_id="beta",
            name="另一队",
            agents=[{"id": "writer", "name": "writer", "runtime": "openclaw"}],
        )
        await fleet.bind_selection(
            node_id="beta",
            name="另一队",
            picks=[{"id": "writer", "runtime": "openclaw"}],
            registry=registry,
            workspace_id="ws-geely",
        )
        await fleet.bind_selection(
            node_id="laptop",
            name="笔记本",
            picks=[{"id": "writer", "runtime": "openclaw"}],
            registry=registry,
            workspace_id="ws-cyber",
        )
        with pytest.raises(fleet.FleetError):
            await fleet.call_peer_from_token(
                laptop["node_token"],
                target="beta",
                runtime="openclaw",
                agent_id="writer",
                prompt="跨团队",
                task_manager=manager,
            )

    asyncio.run(scenario())
