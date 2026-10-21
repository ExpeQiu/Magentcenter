"""语音终端：注册、直接派发、取回转译后的结果。"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.core import fleet
from app.core.device_channel import DeviceAuthError, device_task, device_turn, enroll_device
from app.models.db import create_tables, init_db
from app.models.schemas import AgentInfo, TaskInfo

_NOW = datetime.now(timezone.utc)


def _task(**kwargs) -> TaskInfo:
    base = dict(
        id="t-voice",
        agent_id="a1",
        prompt="整理本周输出",
        status="queued",
        created_at=_NOW,
        updated_at=_NOW,
    )
    base.update(kwargs)
    return TaskInfo(**base)


class _Registry:
    async def list_agents(self, force_refresh=False):
        return [AgentInfo(id="a1", name="助手", runtime="openclaw", is_default=True)]


class _Tasks:
    def __init__(self):
        self.created = []
        self.rows = {}

    async def list_tasks(self, *args, **kwargs):
        return [], 0

    async def create_task(self, req):
        self.created.append(req)
        row = _task(id="t-voice", prompt=req.prompt, status="queued")
        self.rows[row.id] = row
        return row

    async def get_task(self, task_id):
        return self.rows.get(task_id)


class _Monitor:
    async def get_system_status(self, force_refresh=False):
        raise AssertionError("对话查任务不应打系统状态")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.core.super_ai_session.session_path", lambda: tmp_path / "sessions.json"
    )
    init_db(f"sqlite+aiosqlite:///{tmp_path}/voice.db")
    return tmp_path


def test_voice_device_talks_and_collects_task(db):
    async def scenario():
        await create_tables()
        with pytest.raises(fleet.FleetAuthError):
            await enroll_device(
                enroll_token="nope",
                expected_token="secret",
                device_id="esp32-room",
                name="客厅",
            )
        enrolled = await enroll_device(
            enroll_token="secret",
            expected_token="secret",
            device_id="esp32-room",
            name="客厅",
        )
        token = enrolled["device_token"]
        tasks = _Tasks()
        said = await device_turn(
            token,
            "帮我建一个任务：整理本周输出",
            workspace_slug="cyber",
            pending=None,
            registry=_Registry(),
            task_manager=tasks,
            monitor=_Monitor(),
        )
        assert said.pending is None
        assert said.task_id == "t-voice"
        assert said.task_status == "queued"
        assert "已交给" in said.reply
        assert tasks.created

        waiting = await device_task(token, said.task_id, tasks)
        assert waiting["done"] is False
        assert "排队" in waiting["reply"]

        tasks.rows["t-voice"] = _task(
            id="t-voice", status="completed", output="本周输出已整理好。"
        )
        done = await device_task(token, said.task_id, tasks)
        assert done["done"] is True
        assert done["reply"] == "本周输出已整理好。"

        with pytest.raises(DeviceAuthError):
            await device_turn(
                "bad",
                "你好",
                workspace_slug="cyber",
                pending=None,
                registry=_Registry(),
                task_manager=tasks,
                monitor=_Monitor(),
            )

    asyncio.run(scenario())


def test_desktop_channel_keeps_longer_reply(db, monkeypatch):
    from app.models.db import FleetNodeRecord, get_session_factory
    from app.models.schemas import SuperAiTurnResponse

    async def scenario():
        await create_tables()
        enrolled = await enroll_device(
            enroll_token="secret",
            expected_token="secret",
            device_id="ox-steward",
            name="桌面小牛",
            platform="desktop",
        )
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(FleetNodeRecord, "ox-steward")
            assert rec is not None
            assert rec.platform == "desktop"
            assert rec.mode == "voice"

        long = "甲" * 600

        async def fake_turn(*args, **kwargs):
            return SuperAiTurnResponse(run_id="r1", reply=long, intent="help")

        monkeypatch.setattr("app.core.device_channel.handle_turn", fake_turn)
        desktop = await device_turn(
            enrolled["device_token"],
            "你好",
            workspace_slug="cyber",
            pending=None,
            registry=_Registry(),
            task_manager=_Tasks(),
            monitor=_Monitor(),
            channel="desktop",
        )
        assert len(desktop.reply) == 600
        voice = await device_turn(
            enrolled["device_token"],
            "你好",
            workspace_slug="cyber",
            pending=None,
            registry=_Registry(),
            task_manager=_Tasks(),
            monitor=_Monitor(),
            channel="voice",
        )
        assert len(voice.reply) == 480
        assert voice.reply.endswith("…")

    asyncio.run(scenario())
