"""Autopilot 定时任务模块。"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.task_manager import TaskManager
from app.models.schemas import CreateTaskRequest, TaskInfo

logger = logging.getLogger(__name__)


class AutopilotConfig(BaseModel):
    id: str
    name: str
    agent_id: str
    prompt: str
    cron: str  # 简化：interval 秒数 或 "daily"/"hourly"
    enabled: bool = True
    last_run: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AutopilotManager:
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self._configs: dict[str, AutopilotConfig] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def list_autopilots(self) -> list[AutopilotConfig]:
        return list(self._configs.values())

    def get_autopilot(self, autopilot_id: str) -> AutopilotConfig | None:
        return self._configs.get(autopilot_id)

    def create_autopilot(
        self,
        name: str,
        agent_id: str,
        prompt: str,
        cron: str = "3600",
        enabled: bool = True,
    ) -> AutopilotConfig:
        cfg = AutopilotConfig(
            id=str(uuid.uuid4()),
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            cron=cron,
            enabled=enabled,
        )
        self._configs[cfg.id] = cfg
        if enabled:
            self._schedule(cfg)
        logger.info("autopilot created id=%s agent=%s cron=%s", cfg.id, agent_id, cron)
        return cfg

    def delete_autopilot(self, autopilot_id: str) -> bool:
        if autopilot_id not in self._configs:
            return False
        if autopilot_id in self._tasks:
            self._tasks[autopilot_id].cancel()
            del self._tasks[autopilot_id]
        del self._configs[autopilot_id]
        return True

    def _parse_interval(self, cron: str) -> int:
        if cron == "hourly":
            return 3600
        if cron == "daily":
            return 86400
        try:
            return max(60, int(cron))
        except ValueError:
            return 3600

    def _schedule(self, cfg: AutopilotConfig) -> None:
        if cfg.id in self._tasks:
            self._tasks[cfg.id].cancel()

        interval = self._parse_interval(cfg.cron)

        async def _loop():
            while cfg.id in self._configs and self._configs[cfg.id].enabled:
                try:
                    await asyncio.sleep(interval)
                    await self._trigger(cfg)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("autopilot %s error: %s", cfg.id, e)

        self._tasks[cfg.id] = asyncio.create_task(_loop())

    async def _trigger(self, cfg: AutopilotConfig) -> TaskInfo:
        logger.info("autopilot trigger id=%s agent=%s", cfg.id, cfg.agent_id)
        req = CreateTaskRequest(
            agent_id=cfg.agent_id,
            prompt=f"[Autopilot: {cfg.name}] {cfg.prompt}",
        )
        task = await self.task_manager.create_task(req)
        cfg.last_run = datetime.utcnow()
        return task

    async def trigger_now(self, autopilot_id: str) -> TaskInfo:
        cfg = self._configs.get(autopilot_id)
        if not cfg:
            raise ValueError(f"autopilot not found: {autopilot_id}")
        return await self._trigger(cfg)

    def start(self) -> None:
        self._running = True
        for cfg in self._configs.values():
            if cfg.enabled:
                self._schedule(cfg)
        logger.info("autopilot manager started, %d active", len(self._tasks))

    def stop(self) -> None:
        self._running = False
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()
