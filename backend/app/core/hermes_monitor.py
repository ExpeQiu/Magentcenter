"""Hermes 系统状态监控：Gateway / Cron / Sessions。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from app.config import Settings
from app.core.openclaw_monitor import (
    CronJobInfo,
    GatewayStatus,
    SessionDetail,
    SessionInfo,
    SessionMessage,
    SystemStatus,
)

logger = logging.getLogger(__name__)

CACHE_TTL = 30
PID_RE = re.compile(r"PID\s+(\d+)", re.I)
CRON_ID_RE = re.compile(r"^\s*([a-f0-9]{8,})\s+\[(\w+)\]", re.M)
CRON_FIELD_RE = re.compile(
    r"^\s*(Name|Schedule|Next run|Last run|Skills|Deliver):\s*(.+)$", re.M
)
SESSION_ROW_RE = re.compile(
    r"^(?P<title>.+?)\s{2,}(?P<preview>.+?)\s{2,}(?P<active>\S+)\s+(?P<sid>\S+)\s*$"
)


class HermesMonitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = settings.hermes_executable
        self._cache: SystemStatus | None = None
        self._cache_at: float = 0

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.settings.hermes_home:
            env["HERMES_HOME"] = os.path.expanduser(self.settings.hermes_home)
        return env

    async def _run_cmd(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        logger.debug("hermes monitor cmd: %s %s", self.executable, " ".join(args))
        if not shutil.which(self.executable):
            return 127, "", "hermes not found"
        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def get_gateway_status(self) -> GatewayStatus:
        status = GatewayStatus(port=0, dashboard_url="")
        if self.settings.ai_mock_mode:
            status.running = True
            status.pid = 1
            status.probe_ok = True
            status.version = "mock"
            return status
        try:
            _, out, err = await self._run_cmd("gateway", "status", timeout=15)
            text = out or err
            status.running = "supervised by launchd" in text or "running" in text.lower()
            m = PID_RE.search(text)
            if m:
                status.pid = int(m.group(1))
            status.probe_ok = status.running
            if "Service definition matches" in text:
                status.version = "launchd"
        except Exception as e:
            logger.warning("hermes gateway status failed: %s", e)
        return status

    async def get_version(self) -> str:
        if self.settings.ai_mock_mode:
            return "mock-0.17.0"
        try:
            _, out, err = await self._run_cmd("version", timeout=15)
            text = out or err
            m = re.search(r"v?(\d+\.\d+\.\d+)", text)
            return m.group(1) if m else text.strip().splitlines()[0][:64]
        except Exception:
            return ""

    def _parse_cron(self, text: str) -> list[CronJobInfo]:
        jobs: list[CronJobInfo] = []
        blocks = re.split(r"\n\s*\n", text)
        for block in blocks:
            id_m = CRON_ID_RE.search(block)
            if not id_m:
                continue
            job_id = id_m.group(1)
            state = id_m.group(2)
            fields = {k.lower(): v.strip() for k, v in CRON_FIELD_RE.findall(block)}
            last_run_raw = fields.get("last run", "")
            last_status = "ok"
            if "fail" in last_run_raw.lower() or "error" in block.lower():
                last_status = "error"
            elif last_run_raw.endswith(" ok") or " ok" in last_run_raw:
                last_status = "ok"
            jobs.append(
                CronJobInfo(
                    id=f"hermes:{job_id}",
                    name=fields.get("name", job_id),
                    agent_id="default",
                    schedule=fields.get("schedule", ""),
                    status=state,
                    enabled=state != "paused",
                    next_run=fields.get("next run", ""),
                    last_run=last_run_raw.split()[0] if last_run_raw else "",
                    last_status=last_status,
                    source="hermes",
                    runtime="hermes",
                )
            )
        return jobs

    async def get_cron_jobs(self) -> list[CronJobInfo]:
        if self.settings.ai_mock_mode:
            return [
                CronJobInfo(
                    id="hermes:mock-cron-1",
                    name="【Mock Hermes】情报扫描",
                    agent_id="default",
                    schedule="0 8 * * 1-5",
                    status="active",
                    enabled=True,
                    last_status="ok",
                    source="hermes",
                    runtime="hermes",
                )
            ]
        try:
            _, out, err = await self._run_cmd("cron", "list", timeout=30)
            return self._parse_cron(out or err)
        except Exception as e:
            logger.error("hermes cron list failed: %s", e)
            return []

    def _parse_sessions(self, text: str, limit: int) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        for line in text.splitlines():
            if "──" in line or line.startswith("Title"):
                continue
            m = SESSION_ROW_RE.match(line.rstrip())
            if not m:
                continue
            sid = m.group("sid")
            sessions.append(
                SessionInfo(
                    session_id=sid,
                    agent_id="default",
                    key=m.group("title").strip(),
                    updated_at=m.group("active"),
                    kind="hermes",
                    runtime="hermes",
                )
            )
            if len(sessions) >= limit:
                break
        return sessions

    async def get_sessions(self, limit: int = 50) -> tuple[list[SessionInfo], int]:
        if self.settings.ai_mock_mode:
            sessions = [
                SessionInfo(
                    session_id="hermes-mock-session-1",
                    agent_id="default",
                    key="Mock Hermes Session",
                    kind="hermes",
                    runtime="hermes",
                )
            ]
            return sessions, len(sessions)
        try:
            _, out, err = await self._run_cmd(
                "sessions", "list", "--limit", str(limit), timeout=30
            )
            sessions = self._parse_sessions(out or err, limit)
            return sessions, len(sessions)
        except Exception as e:
            logger.error("hermes sessions list failed: %s", e)
            return [], 0

    async def get_session_detail(self, session_id: str) -> SessionDetail | None:
        if self.settings.ai_mock_mode:
            if not session_id.startswith("hermes"):
                return None
            return SessionDetail(
                session_id=session_id,
                agent_id="default",
                model="mock/Hermes",
                runtime="hermes",
                messages=[
                    SessionMessage(
                        role="user",
                        content="[Mock Hermes] hello",
                        timestamp="",
                    ),
                    SessionMessage(
                        role="assistant",
                        content="[Mock Hermes] world",
                        timestamp="",
                    ),
                ],
            )

        # export 到临时文件，避免 stdout 混入 banner
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as tmp:
                tmp_path = tmp.name
            code, out, err = await self._run_cmd(
                "sessions",
                "export",
                tmp_path,
                "--session-id",
                session_id,
                timeout=60,
            )
            path = Path(tmp_path)
            try:
                if not path.exists() or path.stat().st_size == 0:
                    # 回退：stdout
                    raw = (out or err).strip()
                else:
                    raw = path.read_text(encoding="utf-8", errors="replace").strip()
            finally:
                path.unlink(missing_ok=True)

            if code != 0 and not raw:
                logger.warning(
                    "hermes session export failed session=%s err=%s",
                    session_id,
                    err[:200],
                )
                return None
            if not raw:
                return None

            # 取首行 JSON 对象（session 元数据 + messages）
            line = raw.splitlines()[0]
            data = json.loads(line)
            messages: list[SessionMessage] = []
            for m in data.get("messages") or []:
                role = m.get("role") or ""
                content = m.get("content") or ""
                if isinstance(content, list):
                    parts = []
                    for block in content:
                        if isinstance(block, dict):
                            parts.append(block.get("text") or str(block))
                        else:
                            parts.append(str(block))
                    content = "\n".join(parts)
                if not content and m.get("tool_name"):
                    content = f"[tool:{m.get('tool_name')}]"
                messages.append(
                    SessionMessage(
                        role=role,
                        content=str(content)[:2000],
                        timestamp=str(m.get("timestamp") or ""),
                    )
                )
            logger.info(
                "hermes session detail session=%s messages=%d",
                session_id,
                len(messages),
            )
            return SessionDetail(
                session_id=data.get("id") or session_id,
                agent_id="default",
                model=data.get("model") or "",
                updated_at=str(data.get("ended_at") or data.get("started_at") or ""),
                total_tokens=int(data.get("input_tokens") or 0)
                + int(data.get("output_tokens") or 0),
                messages=messages[-40:],
                runtime="hermes",
            )
        except Exception as e:
            logger.error("hermes session detail failed session=%s: %s", session_id, e)
            return None

    async def get_system_status(self, force_refresh: bool = False) -> SystemStatus:
        now = time.monotonic()
        if not force_refresh and self._cache and (now - self._cache_at) < CACHE_TTL:
            return self._cache

        gateway, cron_jobs, (sessions, total) = await asyncio.gather(
            self.get_gateway_status(),
            self.get_cron_jobs(),
            self.get_sessions(),
        )
        cron_errors = [
            j
            for j in cron_jobs
            if j.last_status == "error" or "fail" in (j.status or "").lower()
        ]
        status = SystemStatus(
            gateway=gateway,
            cron_jobs=cron_jobs,
            cron_errors=cron_errors,
            sessions_count=total,
            sessions=sessions,
            checked_at=datetime.utcnow(),
        )
        self._cache = status
        self._cache_at = now
        return status
