"""超级AI 意图路由：认服务，分配任务直接执行。"""

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


def test_extract_result_text_reads_payload():
    from app.core.super_ai import extract_result_text

    raw = (
        '{"result":{"payloads":[{"text":"正在热映三部。"}]}}'
    )
    assert extract_result_text(raw) == "正在热映三部。"
    assert extract_result_text("普通一句。") == "普通一句。"


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


def test_connection_question_is_direct_system():
    parsed = parse_turn("尝试连接一下超级AI那边，看看连接状态", None, "", "cyber")
    assert parsed.intent == "system"
    assert parsed.service == "system"


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


def test_create_runs_immediately(monkeypatch):
    async def _wid(slug):
        return "ws-1"

    monkeypatch.setattr("app.core.super_ai.workspace_service.resolve_workspace_id", _wid)
    tasks = _Tasks()

    async def _run():
        return await _turn("帮我建一个任务：整理本周输出", tasks)

    done = asyncio.run(_run())
    assert done.pending is None
    assert done.intent == "dispatch"
    assert done.task_id == "t9"
    assert "已交给" in done.reply
    assert done.href.startswith("/cyber/tasks/detail")
    assert tasks.created[0].prompt == "整理本周输出"


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


class _MockSettings:
    def __init__(self, on: bool):
        self.ai_mock_mode = on


def _mock(monkeypatch, on: bool = True):
    from app.core import super_ai_llm as llm

    monkeypatch.setattr(
        "app.core.super_ai_llm.get_settings", lambda: _MockSettings(on)
    )
    llm.inject_mock(None)


def test_hello_uses_model_reply(monkeypatch):
    from app.core import super_ai_llm as llm

    _mock(monkeypatch, True)

    async def _roster(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.super_ai.list_roster", _roster)

    async def _run():
        return await _turn("你好", _Tasks())

    try:
        result = asyncio.run(_run())
    finally:
        llm.inject_mock(None)
    assert result.intent == "chat"
    assert "超级AI" in result.reply


def test_dispatch_local_creates_immediately(monkeypatch):
    from app.core import super_ai_llm as llm

    _mock(monkeypatch, True)
    llm.inject_mock(
        {
            "action": "dispatch",
            "node_id": "",
            "runtime": "openclaw",
            "agent_id": "a1",
            "prompt": "总结今天",
        }
    )

    async def _roster(*_args, **_kwargs):
        return [
            {
                "node_id": "",
                "runtime": "openclaw",
                "agent_id": "a1",
                "name": "助手",
                "local": True,
            }
        ]

    async def _wid(slug):
        return "ws-1"

    monkeypatch.setattr("app.core.super_ai.list_roster", _roster)
    monkeypatch.setattr("app.core.super_ai.workspace_service.resolve_workspace_id", _wid)
    tasks = _Tasks()

    async def _run():
        done = await _turn("让助手总结今天", tasks)
        assert done.intent == "dispatch"
        assert done.dispatch is True
        assert done.pending is None
        assert done.task_id == "t9"
        assert tasks.created[0].agent_id == "a1"
        assert tasks.created[0].prompt == "总结今天"

    try:
        asyncio.run(_run())
    finally:
        llm.inject_mock(None)


def test_dispatch_remote_calls_peer(monkeypatch):
    from app.core import super_ai_llm as llm

    _mock(monkeypatch, True)
    llm.inject_mock(
        {
            "action": "dispatch",
            "node_id": "mac-2",
            "runtime": "hermes",
            "agent_id": "h1",
            "prompt": "整理纪要",
        }
    )
    calls = []

    async def _roster(*_args, **_kwargs):
        return [
            {
                "node_id": "mac-2",
                "runtime": "hermes",
                "agent_id": "h1",
                "name": "远方",
                "local": False,
            }
        ]

    async def _peer(**kwargs):
        calls.append(kwargs)
        return {"id": "t-remote", "status": "queued"}

    async def _wid(slug):
        return "ws-1"

    monkeypatch.setattr("app.core.super_ai.list_roster", _roster)
    monkeypatch.setattr("app.core.super_ai.fleet_service.call_peer_as_cloud", _peer)
    monkeypatch.setattr("app.core.super_ai.workspace_service.resolve_workspace_id", _wid)
    tasks = _Tasks()

    async def _run():
        done = await _turn("让远方整理纪要", tasks)
        assert done.pending is None
        assert done.task_id == "t-remote"
        assert done.dispatch is True
        assert calls[0]["target"] == "mac-2"
        assert calls[0]["agent_id"] == "h1"
        assert calls[0]["runtime"] == "hermes"
        assert tasks.created == []

    try:
        asyncio.run(_run())
    finally:
        llm.inject_mock(None)


def test_dispatch_outside_roster_does_not_create(monkeypatch):
    from app.core import super_ai_llm as llm

    _mock(monkeypatch, True)
    llm.inject_mock(
        {
            "action": "dispatch",
            "node_id": "mac-9",
            "runtime": "hermes",
            "agent_id": "missing",
            "prompt": "做一件事",
        }
    )

    async def _roster(*_args, **_kwargs):
        return [
            {
                "node_id": "mac-2",
                "runtime": "hermes",
                "agent_id": "h1",
                "name": "远方",
                "local": False,
            }
        ]

    monkeypatch.setattr("app.core.super_ai.list_roster", _roster)
    tasks = _Tasks()

    async def _run():
        return await _turn("排查线上故障原因", tasks)

    try:
        result = asyncio.run(_run())
    finally:
        llm.inject_mock(None)
    assert result.intent == "chat"
    assert result.pending is None
    assert "名册" in result.reply
    assert tasks.created == []


def test_unconfigured_model_keeps_unknown(monkeypatch):
    from app.core import super_ai_llm as llm

    _mock(monkeypatch, False)
    monkeypatch.setattr(
        llm,
        "load_provider",
        lambda: {"base_url": "", "model": "", "api_key": ""},
    )

    async def _run():
        return await _turn("今天天气怎么样", _Tasks())

    result = asyncio.run(_run())
    assert result.intent == "unknown"
    assert "没对上" in result.reply


class _CloudMonitor:
    class settings:
        @staticmethod
        def executors_enabled():
            return False


def test_connection_question_answers_without_dispatch():
    async def _run():
        return await handle_turn(
            "尝试连接一下超级AI那边，看看连接状态",
            workspace_slug="cyber",
            pending=None,
            last_href="",
            registry=_Registry(),
            task_manager=_Tasks(),
            monitor=_CloudMonitor(),
        )

    result = asyncio.run(_run())
    assert result.intent == "system"
    assert result.reply
    assert result.task_id == ""
    assert result.dispatch is False
    assert "协调器" in result.reply


def test_simple_question_blocks_model_dispatch(monkeypatch):
    from app.core import super_ai_llm as llm

    _mock(monkeypatch, True)
    llm.inject_mock(
        {
            "action": "dispatch",
            "node_id": "mac-2",
            "runtime": "hermes",
            "agent_id": "h1",
            "prompt": "系统状态自检并报告连接状态",
        }
    )

    async def _roster(*_args, **_kwargs):
        return [
            {
                "node_id": "mac-2",
                "runtime": "hermes",
                "agent_id": "h1",
                "name": "远方",
                "local": False,
            }
        ]

    monkeypatch.setattr("app.core.super_ai.list_roster", _roster)
    tasks = _Tasks()

    async def _run():
        return await _turn("今天天气怎么样", tasks)

    try:
        result = asyncio.run(_run())
    finally:
        llm.inject_mock(None)
    assert result.intent == "chat"
    assert result.reply
    assert result.task_id == ""
    assert tasks.created == []


def test_named_role_still_dispatches(monkeypatch):
    from app.core.super_ai import needs_agent

    roster = [{"name": "远方", "agent_id": "h1", "runtime": "hermes"}]
    assert needs_agent("让远方整理纪要", roster) is True
    assert needs_agent("请远方做一份持仓分析", roster) is True
    assert needs_agent("看看连接状态", roster) is False
    assert needs_agent("今天天气怎么样", roster) is False


def test_session_keeps_recent_turns(monkeypatch, tmp_path):
    from app.core import super_ai_llm as llm
    from app.core import super_ai_session as sessions

    _mock(monkeypatch, True)
    monkeypatch.setattr(sessions, "session_path", lambda: tmp_path / "sessions.json")

    async def _roster(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.core.super_ai.list_roster", _roster)

    async def _run():
        await handle_turn(
            "你好",
            workspace_slug="cyber",
            pending=None,
            last_href="",
            registry=_Registry(),
            task_manager=_Tasks(),
            monitor=_Monitor(),
            session_id="sess-1",
        )
        return await sessions.recent("sess-1")

    try:
        rows = asyncio.run(_run())
    finally:
        llm.inject_mock(None)
    assert rows[0]["role"] == "user"
    assert rows[0]["text"] == "你好"
    assert rows[1]["role"] == "assistant"
    assert "超级AI" in rows[1]["text"]
