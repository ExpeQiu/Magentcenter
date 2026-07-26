"""双运行时监控聚合。"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime

from app.config import Settings
from app.core.hermes_adapter import HermesAdapter
from app.core.hermes_monitor import HermesMonitor
from app.core.openclaw_adapter import OpenClawAdapter
from app.core.openclaw_monitor import (
    CronJobInfo,
    OpenClawMonitor,
    RuntimePane,
    SessionDetail,
    SessionInfo,
    SystemStatus,
)

logger = logging.getLogger(__name__)
CACHE_TTL = 30


class MonitorHub:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.openclaw = OpenClawMonitor(settings)
        self.hermes = HermesMonitor(settings)
        self._oc_adapter = OpenClawAdapter(settings)
        self._hermes_adapter = HermesAdapter(settings)
        self._cache: SystemStatus | None = None
        self._cache_at: float = 0

    async def get_system_status(self, force_refresh: bool = False) -> SystemStatus:
        now = time.monotonic()
        if not force_refresh and self._cache and (now - self._cache_at) < CACHE_TTL:
            return self._cache

        enabled = self.settings.enabled_runtimes()
        panes: list[RuntimePane] = []
        cron_jobs: list[CronJobInfo] = []
        sessions: list[SessionInfo] = []

        named_coros: list[tuple[str, object]] = []
        if "openclaw" in enabled:
            named_coros.append(
                ("openclaw", self.openclaw.get_system_status(force_refresh=True))
            )
        if "hermes" in enabled:
            named_coros.append(
                ("hermes", self.hermes.get_system_status(force_refresh=True))
            )

        results = await asyncio.gather(
            *(c for _, c in named_coros), return_exceptions=True
        )
        oc_status: SystemStatus | None = None
        hermes_status: SystemStatus | None = None

        for (name, _), result in zip(named_coros, results):
            if isinstance(result, Exception):
                logger.error("monitor %s failed: %s", name, result)
                panes.append(RuntimePane(runtime=name, available=False))
                continue
            if name == "openclaw":
                oc_status = result
                if self.settings.ai_mock_mode:
                    ok, ver = True, "mock"
                else:
                    ok, ver = await self._oc_adapter.check_health()
                panes.append(
                    RuntimePane(
                        runtime="openclaw",
                        available=ok,
                        version=ver,
                        gateway=result.gateway,
                    )
                )
                cron_jobs.extend(result.cron_jobs)
                sessions.extend(result.sessions)
            else:
                hermes_status = result
                if self.settings.ai_mock_mode:
                    ok, ver = True, "mock-0.17.0"
                else:
                    ok, ver = await self._hermes_adapter.check_health()
                panes.append(
                    RuntimePane(
                        runtime="hermes",
                        available=ok,
                        version=ver,
                        gateway=result.gateway,
                    )
                )
                cron_jobs.extend(result.cron_jobs)
                sessions.extend(result.sessions)

        # 兼容旧字段：gateway 仍指向 OpenClaw（若启用）
        if oc_status:
            primary_gateway = oc_status.gateway
        elif hermes_status:
            primary_gateway = hermes_status.gateway
        else:
            primary_gateway = await self.openclaw.get_gateway_status()
        cron_errors = [
            j
            for j in cron_jobs
            if j.status == "error"
            or j.last_status == "error"
            or "fail" in (j.status or "").lower()
        ]
        status = SystemStatus(
            gateway=primary_gateway,
            runtimes=panes,
            cron_jobs=cron_jobs,
            cron_errors=cron_errors,
            sessions_count=len(sessions),
            sessions=sessions[:50],
            checked_at=datetime.utcnow(),
        )
        self._cache = status
        self._cache_at = now
        logger.info(
            "monitor hub refreshed runtimes=%s cron=%d errors=%d sessions=%d",
            [p.runtime for p in panes],
            len(cron_jobs),
            len(cron_errors),
            len(sessions),
        )
        return status

    async def get_sessions(self, limit: int = 50) -> tuple[list[SessionInfo], int]:
        status = await self.get_system_status()
        items = status.sessions[:limit]
        return items, status.sessions_count

    async def get_session_detail(self, session_id: str) -> SessionDetail | None:
        # Hermes session id 常见前缀；优先对应运行时，再交叉回退
        looks_hermes = (
            session_id.startswith("hermes")
            or session_id.startswith("cron_")
            or session_id.startswith("api-")
            or bool(re.match(r"^\d{8}_\d{6}_", session_id))
        )
        if looks_hermes:
            detail = await self.hermes.get_session_detail(session_id)
            if detail:
                return detail
        detail = await self.openclaw.get_session_detail(session_id)
        if detail:
            detail.runtime = "openclaw"
            return detail
        if not looks_hermes:
            return await self.hermes.get_session_detail(session_id)
        return None

    async def get_cron_jobs(self) -> list[CronJobInfo]:
        status = await self.get_system_status(force_refresh=True)
        return status.cron_jobs
