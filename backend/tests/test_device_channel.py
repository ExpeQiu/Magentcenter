"""语音终端：注册、对话、确认后取回任务结果。"""

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
        assert said.pending is not None
        assert said.task_id == ""
        assert tasks.created == []

        started = await device_turn(
            token,
            "确认",
            workspace_slug="cyber",
            pending=said.pending,
            registry=_Registry(),
            task_manager=tasks,
            monitor=_Monitor(),
        )
        assert started.task_id == "t-voice"
        assert started.task_status == "queued"
        assert "AgentCenter" in started.reply

        waiting = await device_task(token, started.task_id, tasks)
        assert waiting["done"] is False
        assert "排队" in waiting["reply"]

        tasks.rows["t-voice"] = _task(
            id="t-voice", status="completed", output="本周输出已整理好。"
        )
        done = await device_task(token, started.task_id, tasks)
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
