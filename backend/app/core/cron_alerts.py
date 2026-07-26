"""Cron / Gateway / Disk 告警：定期检查并推送飞书。"""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings
from app.core import alert_store
from app.core.openclaw_monitor import CronJobInfo

logger = logging.getLogger(__name__)


class CronAlertWatcher:
    """兼容旧名；同时监控 Cron 错误、Gateway 宕机与磁盘阈值。"""

    def __init__(self, settings: Settings, monitor: Any):
        self.settings = settings
        self.monitor = monitor
        self._task: asyncio.Task | None = None
        self._last_cron_alerted: set[str] = set()
        self._last_gateway_down: set[str] = set()
        self._disk_alerted: bool = False
        self.recent_alerts: list[dict] = []
        self._persist_lock = asyncio.Lock()

    async def load_persisted(self) -> None:
        try:
            self.recent_alerts = await alert_store.load_recent_alerts(40)
            logger.info("alert history loaded count=%d", len(self.recent_alerts))
        except Exception as e:
            logger.warning("alert history load failed: %s", e)

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

    def _format_cron_alert(self, jobs: list[CronJobInfo]) -> str:
        lines = [
            "⚠️ AgentCenter Cron 错误告警",
            f"时间: {datetime.utcnow().isoformat()}Z",
            "",
        ]
        for j in jobs[:10]:
            rt = getattr(j, "runtime", None) or getattr(j, "source", "") or ""
            label = f"[{rt}] " if rt else ""
            lines.append(
                f"• {label}{j.name} ({j.agent_id}) — {j.status or j.last_status}"
            )
        if len(jobs) > 10:
            lines.append(f"... 共 {len(jobs)} 条")
        return "\n".join(lines)

    def _format_gateway_alert(self, down: list[dict[str, Any]]) -> str:
        lines = [
            "🚨 AgentCenter Gateway 宕机告警",
            f"时间: {datetime.utcnow().isoformat()}Z",
            "",
        ]
        for g in down:
            lines.append(
                f"• [{g.get('runtime')}] available={g.get('available')} "
                f"running={g.get('running')} pid={g.get('pid') or '—'}"
            )
        return "\n".join(lines)

    def _record(
        self,
        *,
        kind: str,
        count: int,
        sent: bool,
        jobs: list[str],
    ) -> None:
        entry = {
            "at": datetime.utcnow().isoformat() + "Z",
            "kind": kind,
            "count": count,
            "sent": sent,
            "jobs": jobs,
        }
        self.recent_alerts.append(entry)
        self.recent_alerts = self.recent_alerts[-40:]
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._persist(entry))
        except RuntimeError:
            pass

    async def _persist(self, entry: dict[str, Any]) -> None:
        async with self._persist_lock:
            try:
                await alert_store.save_alert(
                    at=str(entry.get("at") or ""),
                    kind=str(entry.get("kind") or "cron"),
                    count=int(entry.get("count") or 0),
                    sent=bool(entry.get("sent")),
                    jobs=list(entry.get("jobs") or []),
                )
            except Exception as e:
                logger.error("alert persist failed: %s", e)

    async def _check_cron(self, status: Any) -> list[CronJobInfo]:
        # Mock 也处理，便于 System 页演示；飞书仅在配置了 webhook 时发送
        errors = list(status.cron_errors or [])
        if not getattr(self.settings, "cron_alert_enabled", True):
            return errors
        if not errors:
            self._last_cron_alerted.clear()
            return []

        new_errors = [j for j in errors if j.id not in self._last_cron_alerted]
        if new_errors:
            text = self._format_cron_alert(new_errors)
            sent = False if self.settings.ai_mock_mode else await self._send_feishu(text)
            for j in new_errors:
                self._last_cron_alerted.add(j.id)
            self._record(
                kind="cron",
                count=len(new_errors),
                sent=sent,
                jobs=[j.name for j in new_errors],
            )
            logger.warning(
                "cron alert: %d new errors mock=%s feishu=%s",
                len(new_errors),
                self.settings.ai_mock_mode,
                sent,
            )
        return errors

    async def _check_gateways(self, status: Any) -> list[dict[str, Any]]:
        if not self.settings.gateway_alert_enabled:
            return []
        down: list[dict[str, Any]] = []
        for pane in status.runtimes or []:
            gw = pane.gateway
            unhealthy = (not pane.available) or (not gw.running)
            if unhealthy:
                down.append(
                    {
                        "runtime": pane.runtime,
                        "available": pane.available,
                        "running": gw.running,
                        "pid": gw.pid,
                    }
                )

        down_keys = {d["runtime"] for d in down}
        recovered = self._last_gateway_down - down_keys
        if recovered:
            logger.info("gateway recovered: %s", sorted(recovered))
        self._last_gateway_down = down_keys

        # 仅对新宕机告警（集合差：本轮 down 且上次未告警）
        # 用独立集合跟踪已告警，恢复后清除以便再次告警
        if not hasattr(self, "_gateway_alerted"):
            self._gateway_alerted: set[str] = set()
        newly = [d for d in down if d["runtime"] not in self._gateway_alerted]
        for d in list(self._gateway_alerted):
            if d not in down_keys:
                self._gateway_alerted.discard(d)

        if newly:
            text = self._format_gateway_alert(newly)
            sent = False if self.settings.ai_mock_mode else await self._send_feishu(text)
            for d in newly:
                self._gateway_alerted.add(d["runtime"])
            self._record(
                kind="gateway",
                count=len(newly),
                sent=sent,
                jobs=[d["runtime"] for d in newly],
            )
            logger.warning(
                "gateway alert: %s mock=%s feishu=%s",
                [d["runtime"] for d in newly],
                self.settings.ai_mock_mode,
                sent,
            )
        return down

    def _disk_usage_percent(self) -> float | None:
        """检测 AgentCenter 数据目录所在卷的占用百分比。"""
        try:
            # 优先仓库 data/，否则 HOME
            candidates = [
                Path.cwd() / "data",
                Path.cwd(),
                Path.home(),
            ]
            path = next((p for p in candidates if p.exists()), Path.home())
            usage = shutil.disk_usage(path)
            if usage.total <= 0:
                return None
            return round(100.0 * usage.used / usage.total, 1)
        except OSError as e:
            logger.warning("disk usage check failed: %s", e)
            return None

    async def _check_disk(self) -> None:
        threshold = int(getattr(self.settings, "disk_alert_threshold", 0) or 0)
        if threshold <= 0:
            self._disk_alerted = False
            return
        pct = self._disk_usage_percent()
        if pct is None:
            return
        if pct < threshold:
            if self._disk_alerted:
                logger.info("disk recovered: %.1f%% < %d%%", pct, threshold)
            self._disk_alerted = False
            return
        if self._disk_alerted:
            return
        text = (
            f"💾 AgentCenter 磁盘告警\n"
            f"时间: {datetime.utcnow().isoformat()}Z\n"
            f"占用: {pct}%（阈值 {threshold}%）"
        )
        sent = False if self.settings.ai_mock_mode else await self._send_feishu(text)
        self._disk_alerted = True
        self._record(
            kind="disk",
            count=1,
            sent=sent,
            jobs=[f"{pct}%"],
        )
        logger.warning(
            "disk alert: %.1f%% >= %d%% mock=%s feishu=%s",
            pct,
            threshold,
            self.settings.ai_mock_mode,
            sent,
        )

    async def check_once(self) -> list[CronJobInfo]:
        status = await self.monitor.get_system_status(force_refresh=True)
        errors = await self._check_cron(status)
        await self._check_gateways(status)
        await self._check_disk()
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
                logger.error("alert watcher error: %s", e)

    def start(self) -> None:
        if self._task:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "alert watcher started interval=%ds gateway=%s",
            self.settings.cron_alert_interval,
            self.settings.gateway_alert_enabled,
        )

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
