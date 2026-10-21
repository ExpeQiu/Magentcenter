"""多运行时 Agent 发现与缓存。"""

import logging
import time
from collections.abc import AsyncIterator
from typing import Protocol

from app.config import Settings
from app.core.hermes_adapter import HermesAdapter
from app.core.mock_adapter import MockAdapter
from app.core.openclaw_adapter import OpenClawAdapter
from app.core.runtime_event import RuntimeEvent
from app.models.runtime import normalize_runtime
from app.models.schemas import AgentInfo, RuntimeHealth

logger = logging.getLogger(__name__)

CACHE_TTL = 60


class AgentProvider(Protocol):
    async def list_agents(self) -> list[AgentInfo]: ...
    async def check_health(self) -> tuple[bool, str]: ...

    def execute(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int | None = None,
    ) -> AsyncIterator[RuntimeEvent]: ...


class AgentRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: list[AgentInfo] = []
        self._cache_at: float = 0
        self._providers: dict[str, AgentProvider] = {}

        for runtime in settings.enabled_runtimes():
            if settings.ai_mock_mode:
                self._providers[runtime] = MockAdapter(runtime=runtime)
            elif runtime == "openclaw":
                self._providers[runtime] = OpenClawAdapter(settings)
            elif runtime == "hermes":
                self._providers[runtime] = HermesAdapter(settings)

        logger.info(
            "agent registry providers=%s mock=%s",
            list(self._providers.keys()),
            settings.ai_mock_mode,
        )

    def get_executor(self, runtime: str) -> AgentProvider:
        rt = normalize_runtime(runtime, self.settings.default_runtime)
        provider = self._providers.get(rt)
        if not provider:
            raise ValueError(f"runtime not enabled: {rt}")
        return provider

    async def list_agents(self, force_refresh: bool = False) -> list[AgentInfo]:
        now = time.monotonic()
        if not force_refresh and self._cache and (now - self._cache_at) < CACHE_TTL:
            return self._cache

        agents: list[AgentInfo] = []
        for runtime, provider in self._providers.items():
            try:
                items = await provider.list_agents()
                for a in items:
                    if not a.runtime:
                        a.runtime = runtime  # type: ignore[assignment]
                    agents.append(a)
            except Exception as e:
                logger.error("list_agents runtime=%s failed: %s", runtime, e)

        self._cache = agents
        self._cache_at = now
        logger.info("agent registry refreshed: %d agents", len(agents))
        return agents

    async def get_agent(
        self, agent_id: str, runtime: str | None = None
    ) -> AgentInfo | None:
        agents = await self.list_agents()
        if runtime:
            rt = normalize_runtime(runtime, self.settings.default_runtime)
            for a in agents:
                if a.id == agent_id and a.runtime == rt:
                    return a
            return None

        matches = [a for a in agents if a.id == agent_id]
        if not matches:
            return None
        preferred = self.settings.default_runtime
        for a in matches:
            if a.runtime == preferred:
                return a
        return matches[0]

    async def check_health(self) -> tuple[bool, str]:
        """兼容旧接口：返回默认运行时健康状态。"""
        rt = self.settings.default_runtime
        if rt not in self._providers and self._providers:
            rt = next(iter(self._providers))
        provider = self._providers.get(rt)
        if not provider:
            return False, ""
        return await provider.check_health()

    async def check_all_health(self) -> list[RuntimeHealth]:
        out: list[RuntimeHealth] = []
        for runtime, provider in self._providers.items():
            try:
                ok, ver = await provider.check_health()
            except Exception as e:
                logger.error("health runtime=%s failed: %s", runtime, e)
                ok, ver = False, ""
            out.append(RuntimeHealth(runtime=runtime, available=ok, version=ver))
        return out

    @property
    def cache_age_seconds(self) -> float:
        if not self._cache_at:
            return -1
        return time.monotonic() - self._cache_at
