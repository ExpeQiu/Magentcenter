"""Cron 错误告警：定期检查并推送飞书。"""

import asyncio
import logging
from datetime import datetime

import httpx

from app.config import Settings
from app.core.openclaw_monitor import CronJobInfo, OpenClawMonitor

logger = logging.getLogger(__name__)


class CronAlertWatcher:
    def __init__(self, settings: Settings, monitor: OpenClawMonitor):
        self.settings = settings
        self.monitor = monitor
        self._task: asyncio.Task | None = None
        self._last_alerted: set[str] = set()
        self.recent_alerts: list[dict] = []

    async def _send_feishu(self, text: str) -> bool:
        url = self.settings.feishu_webhook_url
        if not url:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    url,
                    json={"msg_type": "text", "content": {"text": text}},
                )
                return resp.status_code == 200
        except Exception as e:
            logger.error("feishu alert failed: %s", e)
            return False

    def _format_alert(self, jobs: list[CronJobInfo]) -> str:
        lines = ["⚠️ AgentCenter Cron 错误告警", f"时间: {datetime.utcnow().isoformat()}Z", ""]
        for j in jobs[:10]:
            lines.append(f"• {j.name} ({j.agent_id}) — {j.status or j.last_status}")
        if len(jobs) > 10:
            lines.append(f"... 共 {len(jobs)} 条")
        return "\n".join(lines)

    async def check_once(self) -> list[CronJobInfo]:
        if self.settings.ai_mock_mode:
            return []
        status = await self.monitor.get_system_status(force_refresh=True)
        errors = status.cron_errors
        if not errors:
            self._last_alerted.clear()
            return []

        new_errors = [j for j in errors if j.id not in self._last_alerted]
        if new_errors:
            text = self._format_alert(new_errors)
            sent = await self._send_feishu(text)
            for j in new_errors:
                self._last_alerted.add(j.id)
            self.recent_alerts.append(
                {
                    "at": datetime.utcnow().isoformat() + "Z",
                    "count": len(new_errors),
                    "sent": sent,
                    "jobs": [j.name for j in new_errors],
                }
            )
            self.recent_alerts = self.recent_alerts[-20:]
            logger.warning("cron alert: %d new errors, feishu=%s", len(new_errors), sent)
        return errors

    async def _loop(self) -> None:
        interval = max(60, self.settings.cron_alert_interval)
        while True:
            try:
                await asyncio.sleep(interval)
                await self.check_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cron alert watcher error: %s", e)

    def start(self) -> None:
        if self._task:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("cron alert watcher started interval=%ds", self.settings.cron_alert_interval)

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
