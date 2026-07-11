"""Agent 发现与缓存。"""

import logging
import time
from typing import Protocol

from app.config import Settings
from app.core.mock_adapter import MockAdapter
from app.core.openclaw_adapter import OpenClawAdapter
from app.models.schemas import AgentInfo

logger = logging.getLogger(__name__)

CACHE_TTL = 60


class AgentProvider(Protocol):
    async def list_agents(self) -> list[AgentInfo]: ...
    async def check_health(self) -> tuple[bool, str]: ...


class AgentRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: list[AgentInfo] = []
        self._cache_at: float = 0
        self._provider: AgentProvider = (
            MockAdapter() if settings.ai_mock_mode else OpenClawAdapter(settings)
        )

    async def list_agents(self, force_refresh: bool = False) -> list[AgentInfo]:
        now = time.monotonic()
        if not force_refresh and self._cache and (now - self._cache_at) < CACHE_TTL:
            return self._cache

        agents = await self._provider.list_agents()
        self._cache = agents
        self._cache_at = now
        logger.info("agent registry refreshed: %d agents", len(agents))
        return agents

    async def get_agent(self, agent_id: str) -> AgentInfo | None:
        agents = await self.list_agents()
        for a in agents:
            if a.id == agent_id:
                return a
        return None

    async def check_health(self) -> tuple[bool, str]:
        return await self._provider.check_health()

    @property
    def cache_age_seconds(self) -> float:
        if not self._cache_at:
            return -1
        return time.monotonic() - self._cache_at
