"""Hermes CLI 适配器：profile 发现、oneshot/chat 执行。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from collections.abc import AsyncIterator

from app.config import Settings
from app.core.runtime_event import RuntimeEvent
from app.models.schemas import AgentInfo

logger = logging.getLogger(__name__)

SESSION_ID_RE = re.compile(r"^session_id:\s*(\S+)\s*$", re.M)
PROFILE_ROW_RE = re.compile(
    r"^[◆*\s]*([A-Za-z0-9_.-]+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?",
    re.M,
)


def _parse_profiles(text: str) -> list[AgentInfo]:
    agents: list[AgentInfo] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Profile") or set(stripped) <= {"─", "-", " "}:
            continue
        m = PROFILE_ROW_RE.match(stripped)
        if not m:
            continue
        profile_id = m.group(1)
        if profile_id.lower() in {"profile", "model", "gateway", "alias", "distribution"}:
            continue
        if profile_id in seen:
            continue
        seen.add(profile_id)
        model = m.group(2) if m.group(2) not in {"—", "-"} else ""
        is_default = "◆" in line or profile_id == "default"
        agents.append(
            AgentInfo(
                id=profile_id,
                name=f"Hermes/{profile_id}",
                model=model,
                identity_name=profile_id,
                identity_emoji="⚕",
                is_default=is_default,
                runtime="hermes",
            )
        )
    if not agents:
        # 保底：至少暴露 default，避免空列表阻塞 UI
        agents.append(
            AgentInfo(
                id="default",
                name="Hermes/default",
                identity_name="default",
                identity_emoji="⚕",
                is_default=True,
                runtime="hermes",
            )
        )
    return agents


def _parse_quiet_output(stdout: str) -> tuple[str, str]:
    """返回 (session_id, final_text)。"""
    sid = ""
    m = SESSION_ID_RE.search(stdout)
    if m:
        sid = m.group(1)
    text = SESSION_ID_RE.sub("", stdout).strip()
    return sid, text


class HermesAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = settings.hermes_executable

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.settings.hermes_home:
            env["HERMES_HOME"] = os.path.expanduser(self.settings.hermes_home)
        return env

    async def _run_cmd(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        logger.info("hermes cmd: %s %s", self.executable, " ".join(args))
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

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    async def check_health(self) -> tuple[bool, str]:
        if not self.is_available():
            return False, ""
        try:
            code, out, err = await self._run_cmd("version", timeout=15)
            text = out or err
            version = ""
            m = re.search(r"v?(\d+\.\d+\.\d+)", text)
            if m:
                version = m.group(1)
            elif "Hermes" in text:
                version = text.strip().splitlines()[0][:64]
            return code == 0 or bool(version), version
        except Exception as e:
            logger.error("hermes health check failed: %s", e)
            return False, ""

    async def list_agents(self) -> list[AgentInfo]:
        if not self.is_available():
            return []
        try:
            code, out, err = await self._run_cmd("profile", "list", timeout=30)
            text = out or err
            agents = _parse_profiles(text)
            logger.info("hermes discovered %d profiles (exit=%s)", len(agents), code)
            return agents
        except Exception as e:
            logger.error("hermes profile list failed: %s", e)
            return []

    def _build_args(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str,
        session_id: str | None,
        timeout: int,
    ) -> list[str]:
        args: list[str] = []
        profile = (agent_id or "default").strip()
        if profile and profile != "default":
            args.extend(["--profile", profile])

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        args.extend(
            [
                "chat",
                "-q",
                full_prompt,
                "--quiet",
                "--source",
                "tool",
                "--accept-hooks",
            ]
        )
        if session_id and not session_id.startswith("agentcenter-"):
            args.extend(["--resume", session_id])
        if timeout > 0:
            # Hermes 无全局 timeout CLI；用 max-turns 作软上限兜底
            args.extend(["--max-turns", "90"])
        return args

    async def execute(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        if not self.is_available():
            yield RuntimeEvent(type="error", content="hermes executable not found")
            yield RuntimeEvent(type="result", content="failed")
            return

        ok, version = await self.check_health()
        if not ok:
            yield RuntimeEvent(
                type="error",
                content=f"hermes unavailable (version={version or 'unknown'})",
            )
            yield RuntimeEvent(type="result", content="failed")
            return

        t = timeout or self.settings.hermes_default_timeout
        args = self._build_args(agent_id, prompt, system_prompt, session_id, t)
        yield RuntimeEvent(type="status", status="running")

        logger.info(
            "hermes execute profile=%s timeout=%s args=%s",
            agent_id,
            t,
            " ".join(args[:8]),
        )
        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )

        start = time.monotonic()
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=t + 30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            yield RuntimeEvent(type="error", content=f"hermes timed out after {t}s")
            yield RuntimeEvent(type="result", content="timeout")
            return

        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        if stderr.strip():
            for line in stderr.splitlines()[-20:]:
                logger.debug("[hermes:stderr] %s", line)

        sid, text = _parse_quiet_output(stdout)
        if text:
            yield RuntimeEvent(type="text", content=text)
        if sid:
            logger.info(
                "hermes finished profile=%s session=%s duration_ms=%s",
                agent_id,
                sid,
                duration_ms,
            )

        if proc.returncode:
            err = stderr.strip() or f"hermes exited with code {proc.returncode}"
            yield RuntimeEvent(type="error", content=err)
            yield RuntimeEvent(type="result", content="failed")
            return

        if not text:
            yield RuntimeEvent(type="error", content="hermes returned empty output")
            yield RuntimeEvent(type="result", content="failed")
            return

        yield RuntimeEvent(type="result", content="completed")
