"""OpenClaw 系统状态监控：Gateway / Cron / Sessions。"""

import asyncio
import glob
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings

logger = logging.getLogger(__name__)

CACHE_TTL = 30


class GatewayStatus(BaseModel):
    running: bool = False
    pid: int = 0
    port: int = 18789
    version: str = ""
    dashboard_url: str = ""
    probe_ok: bool = False


class CronJobInfo(BaseModel):
    id: str
    name: str
    agent_id: str = ""
    schedule: str = ""
    status: str = ""
    enabled: bool = True
    next_run: str = ""
    last_run: str = ""
    last_status: str = ""
    source: str = "openclaw"


class SessionMessage(BaseModel):
    role: str = ""
    content: str = ""
    timestamp: str = ""


class SessionDetail(BaseModel):
    session_id: str
    agent_id: str = ""
    key: str = ""
    model: str = ""
    updated_at: str = ""
    total_tokens: int = 0
    messages: list[SessionMessage] = Field(default_factory=list)


class SessionInfo(BaseModel):
    session_id: str
    agent_id: str = ""
    key: str = ""
    model: str = ""
    updated_at: str = ""
    age_ms: int = 0
    total_tokens: int = 0
    kind: str = ""


class SystemStatus(BaseModel):
    gateway: GatewayStatus
    cron_jobs: list[CronJobInfo] = Field(default_factory=list)
    cron_errors: list[CronJobInfo] = Field(default_factory=list)
    sessions_count: int = 0
    sessions: list[SessionInfo] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.utcnow)


def _ms_to_iso(ms: int | float | None) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ms / 1000).isoformat() + "Z"
    except (OSError, ValueError, OverflowError):
        return ""


def _format_schedule(sched: dict[str, Any] | None) -> str:
    if not sched:
        return ""
    kind = sched.get("kind", "")
    if kind == "cron":
        expr = sched.get("expr", "")
        tz = sched.get("tz", "")
        return f"cron {expr} @{tz}" if tz else f"cron {expr}"
    if kind == "every":
        return f"every {sched.get('everyMs', '')}ms"
    return str(sched)


class OpenClawMonitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = settings.openclaw_executable
        self._cache: SystemStatus | None = None
        self._cache_at: float = 0

    async def _run_cmd(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        logger.debug("openclaw monitor cmd: %s %s", self.executable, " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
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
        port = self.settings.openclaw_gateway_port
        status = GatewayStatus(port=port, dashboard_url=f"http://127.0.0.1:{port}/")
        try:
            _, out, _ = await self._run_cmd("gateway", "status", "--json", timeout=15)
            data = json.loads(out)
            svc = data.get("service", {})
            runtime = svc.get("runtime", {})
            gw = data.get("gateway", {}) or {}
            status.running = runtime.get("status") == "running"
            status.pid = int(runtime.get("pid") or 0)
            status.version = data.get("cli", {}).get("version", "") or gw.get("version", "")
            status.port = int(gw.get("port") or data.get("port") or port)
            status.dashboard_url = f"http://{gw.get('bindHost', '127.0.0.1')}:{status.port}/"
            rpc = data.get("rpc", {})
            if isinstance(rpc, dict):
                status.probe_ok = bool(rpc.get("ok"))
        except Exception as e:
            logger.warning("gateway status failed: %s", e)
            # 文本降级
            try:
                _, out, _ = await self._run_cmd("gateway", "status", timeout=15)
                status.running = "running" in out.lower()
                m = re.search(r"pid\s+(\d+)", out, re.I)
                if m:
                    status.pid = int(m.group(1))
                status.probe_ok = "probe: ok" in out.lower() or "connectivity probe: ok" in out.lower()
            except Exception as e2:
                logger.error("gateway status text fallback failed: %s", e2)
        return status

    async def get_cron_jobs(self) -> list[CronJobInfo]:
        jobs: list[CronJobInfo] = []
        try:
            _, out, _ = await self._run_cmd("cron", "list", "--json", timeout=30)
            data = json.loads(out)
            for j in data.get("jobs", []):
                state = j.get("state", {}) or {}
                jobs.append(
                    CronJobInfo(
                        id=j.get("id", ""),
                        name=j.get("name", ""),
                        agent_id=j.get("agentId", ""),
                        schedule=_format_schedule(j.get("schedule")),
                        status=j.get("status", state.get("lastStatus", "")),
                        enabled=bool(j.get("enabled", True)),
                        next_run=_ms_to_iso(state.get("nextRunAtMs")),
                        last_run=_ms_to_iso(state.get("lastRunAtMs")),
                        last_status=state.get("lastRunStatus", state.get("lastStatus", "")),
                    )
                )
        except Exception as e:
            logger.error("cron list failed: %s", e)
        return jobs

    async def get_sessions(self, limit: int = 50) -> tuple[list[SessionInfo], int]:
        sessions: list[SessionInfo] = []
        total = 0
        try:
            _, out, _ = await self._run_cmd(
                "sessions",
                "list",
                "--json",
                "--all-agents",
                "--limit",
                str(limit),
                timeout=30,
            )
            data = json.loads(out)
            total = int(data.get("totalCount") or data.get("count") or 0)
            for s in data.get("sessions", []):
                sessions.append(
                    SessionInfo(
                        session_id=s.get("sessionId", ""),
                        agent_id=s.get("agentId", ""),
                        key=s.get("key", ""),
                        model=s.get("model", ""),
                        updated_at=_ms_to_iso(s.get("updatedAt")),
                        age_ms=int(s.get("ageMs") or 0),
                        total_tokens=int(s.get("totalTokens") or 0),
                        kind=s.get("kind", ""),
                    )
                )
        except Exception as e:
            logger.error("sessions list failed: %s", e)
        return sessions, total

    async def get_session_detail(self, session_id: str) -> SessionDetail | None:
        """读取 Session 的消息历史。"""
        try:
            # Search all agent sessions directories
            base = os.path.expanduser("~/.openclaw/agents")
            session_file: str | None = None

            for agent_dir in os.listdir(base):
                sessions_dir = os.path.join(base, agent_dir, "sessions")
                if not os.path.isdir(sessions_dir):
                    continue
                for pattern in [
                    os.path.join(sessions_dir, session_id + ".jsonl"),
                    os.path.join(sessions_dir, session_id + ".trajectory.jsonl"),
                    os.path.join(sessions_dir, session_id + ".jsonl.deleted"),
                ]:
                    matches = glob.glob(pattern)
                    if matches:
                        session_file = matches[0]
                        break
                if session_file:
                    break

            if not session_file:
                return SessionDetail(session_id=session_id)

            messages: list[SessionMessage] = []
            with open(session_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("type") == "message":
                            msg = entry.get("message", {})
                            role = msg.get("role", "")
                            content = ""
                            if isinstance(msg.get("content"), list):
                                for block in msg["content"]:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        content += block.get("text", "")
                            elif isinstance(msg.get("content"), str):
                                content = msg["content"]
                            messages.append(SessionMessage(
                                role=role,
                                content=content[:500],
                                timestamp=entry.get("timestamp", ""),
                            ))
                    except json.JSONDecodeError:
                        continue

            # Derive agent_id from path
            agent_id = session_file.split("/agents/")[1].split("/")[0] if "/agents/" in session_file else ""

            return SessionDetail(
                session_id=session_id,
                agent_id=agent_id,
                model="",
                updated_at="",
                total_tokens=0,
                messages=messages[-20:],
            )
        except Exception as e:
            logger.error("session detail failed: %s", e)
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
            j for j in cron_jobs if j.status == "error" or j.last_status == "error"
        ]
        status = SystemStatus(
            gateway=gateway,
            cron_jobs=cron_jobs,
            cron_errors=cron_errors,
            sessions_count=total,
            sessions=sessions,
        )
        self._cache = status
        self._cache_at = now
        logger.info(
            "system status refreshed gateway=%s cron=%d errors=%d sessions=%d",
            gateway.running,
            len(cron_jobs),
            len(cron_errors),
            total,
        )
        return status
