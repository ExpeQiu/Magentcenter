"""超级AI 意图路由：认服务、写操作先确认。"""

import asyncio
from datetime import datetime, timezone

from app.core.super_ai import handle_turn, parse_turn
from app.models.schemas import AgentInfo, SuperAiPending, TaskInfo

_NOW = datetime.now(timezone.utc)


def _task(**kwargs) -> TaskInfo:
    base = dict(
        id="t1",
        agent_id="a1",
        prompt="整理周报",
        status="running",
        created_at=_NOW,
        updated_at=_NOW,
    )
    base.update(kwargs)
    return TaskInfo(**base)


def test_list_tasks_intent():
    parsed = parse_turn("有哪些进行中的任务", None, "", "cyber")
    assert parsed.intent == "list_tasks"
    assert parsed.active_only is True
    assert parsed.service == "tasks"


def test_create_task_waits_for_confirm():
    parsed = parse_turn("帮我建一个任务：整理本周输出", None, "", "cyber")
    assert parsed.intent == "create_task"
    assert parsed.query == "整理本周输出"


def test_confirm_only_when_pending():
    assert parse_turn("确认", None, "", "cyber").intent == "unknown"
    pending = SuperAiPending(
        action="create_task",
        prompt="整理",
        agent_id="a1",
        agent_name="助手",
    )
    assert parse_turn("确认", pending, "", "cyber").intent == "confirm_create"
    assert parse_turn("取消", pending, "", "cyber").intent == "cancel"


def test_navigate_and_last_href():
    opened = parse_turn("打开知识库", None, "", "cyber")
    assert opened.href == "/cyber/knowledge"
    again = parse_turn("打开刚才那个", None, "/cyber/tasks", "cyber")
    assert again.href == "/cyber/tasks"
    blocked = parse_turn("打开刚才那个", None, "https://evil", "cyber")
    assert blocked.intent == "clarify"


def test_unknown_does_not_guess_service():
    parsed = parse_turn("今天天气怎么样", None, "", "cyber")
    assert parsed.intent == "unknown"
    assert parsed.service == ""


class _Registry:
    async def list_agents(self, force_refresh=False):
        return [AgentInfo(id="a1", name="助手", runtime="openclaw", is_default=True)]


class _Tasks:
    def __init__(self):
        self.created = []

    async def list_tasks(
        self,
        page=1,
        page_size=20,
        status=None,
        agent_id=None,
        project_id=None,
        workspace_id=None,
        scheduled=False,
        node_id=None,
        remote_only=False,
    ):
        if status == "running":
            return [_task()], 1
        return [], 0

    async def create_task(self, req):
        self.created.append(req)
        return _task(id="t9", agent_id=req.agent_id, prompt=req.prompt, status="queued")


class _Monitor:
    async def get_system_status(self, force_refresh=False):
        raise AssertionError("不应在建任务时查系统")


def _turn(text, tasks, pending=None):
    return handle_turn(
        text,
        workspace_slug="cyber",
        pending=pending,
        last_href="",
        registry=_Registry(),
        task_manager=tasks,
        monitor=_Monitor(),
    )


def test_create_then_confirm(monkeypatch):
    async def _wid(slug):
        return "ws-1"

    monkeypatch.setattr("app.core.super_ai.workspace_service.resolve_workspace_id", _wid)
    tasks = _Tasks()

    async def _run():
        prepared = await _turn("帮我建一个任务：整理本周输出", tasks)
        assert prepared.pending is not None
        assert prepared.pending.prompt == "整理本周输出"
        assert tasks.created == []
        done = await _turn("确认", tasks, prepared.pending)
        assert done.intent == "confirm_create"
        assert "AgentCenter" in done.reply
        assert done.href.startswith("/cyber/tasks/detail")
        assert tasks.created[0].prompt == "整理本周输出"

    asyncio.run(_run())


def test_cancel_does_not_create():
    tasks = _Tasks()
    pending = SuperAiPending(
        action="create_task", prompt="整理", agent_id="a1", agent_name="助手"
    )

    async def _run():
        return await _turn("取消", tasks, pending)

    result = asyncio.run(_run())
    assert "没有创建" in result.reply
    assert tasks.created == []


def test_list_running_tasks(monkeypatch):
    async def _wid(slug):
        return None

    monkeypatch.setattr("app.core.super_ai.workspace_service.resolve_workspace_id", _wid)

    async def _run():
        return await _turn("有哪些进行中的任务", _Tasks())

    result = asyncio.run(_run())
    assert result.service == "tasks"
    assert "整理周报" in result.reply
    assert result.href == "/cyber/tasks"
