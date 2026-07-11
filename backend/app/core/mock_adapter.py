"""Mock 适配器：开发/测试时模拟 OpenClaw 调用。"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.models.schemas import AgentInfo, TokenUsage

logger = logging.getLogger(__name__)

MOCK_AGENTS = [
    AgentInfo(
        id="main",
        name="小二（指挥官）",
        model="mock/MockModel",
        identity_name="小二",
        identity_emoji="🧢",
        is_default=True,
    ),
    AgentInfo(
        id="coder",
        name="Tech Lead",
        model="mock/MockModel",
        identity_name="Coder",
        identity_emoji="💻",
    ),
    AgentInfo(
        id="qa",
        name="测试工程师",
        model="mock/MockModel",
        identity_name="QA",
        identity_emoji="🔍",
    ),
]


@dataclass
class MockExecutionResult:
    status: str
    output: str
    error: str = ""
    session_id: str = ""
    duration_ms: int = 0
    usage: TokenUsage | None = None


@dataclass
class MockEvent:
    type: str
    content: str = ""
    tool: str = ""
    call_id: str = ""
    input: dict | None = None
    output: str = ""


class MockAdapter:
    """模拟 OpenClaw CLI 行为。"""

    async def list_agents(self) -> list[AgentInfo]:
        logger.info("mock: list_agents")
        return list(MOCK_AGENTS)

    async def check_health(self) -> tuple[bool, str]:
        return True, "mock-2026.6.11"

    async def execute(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int = 600,
    ) -> AsyncIterator[MockEvent]:
        sid = session_id or f"mock-{uuid.uuid4().hex[:12]}"
        logger.info("mock execute agent=%s session=%s", agent_id, sid)

        yield MockEvent(type="status", content="running")

        await asyncio.sleep(0.1)

        parts = [
            f"[Mock {agent_id}] 收到任务。",
            f"Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}",
        ]
        if system_prompt:
            parts.append(f"System: {system_prompt[:80]}")

        for part in parts:
            yield MockEvent(type="text", content=part + "\n")
            await asyncio.sleep(0.05)

        yield MockEvent(
            type="tool_use",
            tool="mock_search",
            call_id="mock-call-1",
            input={"query": prompt[:50]},
        )
        await asyncio.sleep(0.05)
        yield MockEvent(
            type="tool_result",
            tool="mock_search",
            call_id="mock-call-1",
            output="mock result: ok",
        )

        yield MockEvent(type="result", content="completed")

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
