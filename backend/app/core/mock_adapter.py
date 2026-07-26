"""Mock 适配器：开发/测试时模拟 OpenClaw / Hermes 调用。"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator

from app.core.runtime_event import RuntimeEvent
from app.models.schemas import AgentInfo, TokenUsage

logger = logging.getLogger(__name__)

MOCK_OPENCLAW_AGENTS = [
    AgentInfo(
        id="main",
        name="小二（指挥官）",
        model="mock/MockModel",
        identity_name="小二",
        identity_emoji="🧢",
        is_default=True,
        runtime="openclaw",
    ),
    AgentInfo(
        id="coder",
        name="Tech Lead",
        model="mock/MockModel",
        identity_name="Coder",
        identity_emoji="💻",
        runtime="openclaw",
    ),
    AgentInfo(
        id="qa",
        name="测试工程师",
        model="mock/MockModel",
        identity_name="QA",
        identity_emoji="🔍",
        runtime="openclaw",
    ),
    AgentInfo(
        id="ops-agent",
        name="运维修复 Agent",
        model="mock/MockModel",
        identity_name="Ops",
        identity_emoji="🛠️",
        runtime="openclaw",
    ),
]

MOCK_HERMES_AGENTS = [
    AgentInfo(
        id="default",
        name="Hermes/default",
        model="mock/Hermes",
        identity_name="default",
        identity_emoji="⚕",
        is_default=True,
        runtime="hermes",
    ),
]

# 兼容旧引用
MOCK_AGENTS = MOCK_OPENCLAW_AGENTS


class MockExecutionResult:
    def __init__(
        self,
        status: str,
        output: str,
        error: str = "",
        session_id: str = "",
        duration_ms: int = 0,
        usage: TokenUsage | None = None,
    ):
        self.status = status
        self.output = output
        self.error = error
        self.session_id = session_id
        self.duration_ms = duration_ms
        self.usage = usage


class MockAdapter:
    """按 runtime 模拟 CLI 行为。"""

    def __init__(self, runtime: str = "openclaw"):
        self.runtime = runtime

    async def list_agents(self) -> list[AgentInfo]:
        logger.info("mock: list_agents runtime=%s", self.runtime)
        if self.runtime == "hermes":
            return list(MOCK_HERMES_AGENTS)
        return list(MOCK_OPENCLAW_AGENTS)

    async def check_health(self) -> tuple[bool, str]:
        if self.runtime == "hermes":
            return True, "mock-0.17.0"
        return True, "mock-2026.6.11"

    async def execute(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int = 600,
    ) -> AsyncIterator[RuntimeEvent]:
        sid = session_id or f"mock-{self.runtime}-{uuid.uuid4().hex[:12]}"
        logger.info(
            "mock execute runtime=%s agent=%s session=%s",
            self.runtime,
            agent_id,
            sid,
        )

        yield RuntimeEvent(type="status", status="running")
        await asyncio.sleep(0.05)

        parts = [
            f"[Mock {self.runtime}/{agent_id}] 收到任务。",
            f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}",
        ]
        if system_prompt:
            parts.append(f"System: {system_prompt[:80]}")

        for part in parts:
            yield RuntimeEvent(type="text", content=part + "\n")
            await asyncio.sleep(0.02)

        yield RuntimeEvent(
            type="tool_use",
            tool="mock_search",
            call_id="mock-call-1",
            input={"query": prompt[:50]},
        )
        await asyncio.sleep(0.02)
        yield RuntimeEvent(
            type="tool_result",
            tool="mock_search",
            call_id="mock-call-1",
            output="mock result: ok",
        )
        yield RuntimeEvent(type="result", content="completed")

    async def run_to_completion(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int = 600,
    ) -> MockExecutionResult:
        start = time.monotonic()
        output_parts: list[str] = []
        sid = session_id or f"mock-{uuid.uuid4().hex[:12]}"

        async for event in self.execute(agent_id, prompt, system_prompt, sid, timeout):
            if event.type == "text":
                output_parts.append(event.content)

        duration_ms = int((time.monotonic() - start) * 1000)
        return MockExecutionResult(
            status="completed",
            output="".join(output_parts),
            session_id=sid,
            duration_ms=duration_ms,
            usage=TokenUsage(input_tokens=100, output_tokens=50),
        )
