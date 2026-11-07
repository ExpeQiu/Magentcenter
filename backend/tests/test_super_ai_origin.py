"""超级AI 建单 origin=super_ai；任务台建单 origin=local。"""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.core.agent_registry import AgentRegistry
from app.core.super_ai import _commit_create
from app.core.task_manager import TaskManager
from app.models.db import create_tables, init_db
from app.models.schemas import CreateTaskRequest, SuperAiPending


def test_super_ai_vs_local_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AI_MOCK_MODE", "true")
    init_db(f"sqlite+aiosqlite:///{tmp_path}/origin.db")

    async def run():
        await create_tables()
        settings = Settings(ai_mock_mode=True, local_auth_enabled=False)
        registry = AgentRegistry(settings)
        tm = TaskManager(settings=settings, registry=registry)

        local = await tm.create_task(
            CreateTaskRequest(
                agent_id="coder",
                prompt="local only",
                runtime="openclaw",
                origin="local",
            )
        )
        assert local.origin == "local"

        import time

        pending = SuperAiPending(
            action="create_task",
            prompt="via super ai",
            agent_id="coder",
            agent_name="coder",
            runtime="openclaw",
        )
        result = await _commit_create(
            "run1",
            pending,
            "cyber",
            tm,
            started=time.perf_counter(),
            workspace="cyber",
            origin="super_ai",
        )
        assert result.task_id
        task = await tm.get_task(result.task_id)
        assert task is not None
        assert task.origin == "super_ai"

    asyncio.run(run())
