"""信息链把开口、确认、派发和回写串在同一条任务上。"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.core.chain import list_chain
from app.core.device_channel import device_task, device_turn, enroll_device
from app.core.fleet import notify_connector
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
        self.rows = {}

    async def list_tasks(self, *args, **kwargs):
        return [], 0

    async def create_task(self, req):
        row = _task(id="t-voice", prompt=req.prompt, status="queued")
        self.rows[row.id] = row
        return row

    async def get_task(self, task_id):
        return self.rows.get(task_id)


class _Monitor:
    async def get_system_status(self, force_refresh=False):
        raise AssertionError("不应打系统状态")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/chain.db")
    return tmp_path


def test_voice_turns_share_task_and_webhook_is_kept(db):
    async def scenario():
        await create_tables()
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
        started = await device_turn(
            token,
            "确认",
            workspace_slug="cyber",
            pending=said.pending,
            registry=_Registry(),
            task_manager=tasks,
            monitor=_Monitor(),
        )
        tasks.rows["t-voice"] = _task(id="t-voice", status="completed", output="本周输出已整理好。")
        await device_task(token, started.task_id, tasks)
        await notify_connector("pi", {"id": started.task_id, "prompt": "整理本周输出"})

        rows = await list_chain(task_id=started.task_id)
        kinds = [row.kind for row in rows]
        assert kinds[:2] == ["turn", "turn"]
        assert rows[0].intent == "create_task"
        assert "整理本周输出" in rows[0].summary
        assert rows[1].intent == "confirm_create"
        assert rows[1].actor_id == "esp32-room"
        assert "deliver" in kinds
        assert kinds[-1] == "webhook"
        assert rows[-1].status == "queued"
        assert rows[-1].target_id == "pi"

        enrolls = await list_chain(actor_id="esp32-room")
        assert enrolls[0].kind == "enroll"
        assert enrolls[0].channel == "esp32"

    asyncio.run(scenario())
