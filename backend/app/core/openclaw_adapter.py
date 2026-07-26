"""OpenClaw CLI 适配器：发现 Agent、执行调用、解析输出。"""

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.core.runtime_event import RuntimeEvent
from app.models.schemas import AgentInfo, TokenUsage

logger = logging.getLogger(__name__)

MIN_OPENCLAW_VERSION = "2026.5.5"
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")


# 兼容旧命名；统一事件请用 RuntimeEvent
OpenClawEvent = RuntimeEvent


@dataclass
class OpenClawResult:
    status: str
    output: str
    error: str = ""
    session_id: str = ""
    duration_ms: int = 0
    usage: TokenUsage | None = None
    model: str = ""


def _compare_version(a: str, b: str) -> int:
    a_parts = [int(x) for x in a.split(".")[:3]]
    b_parts = [int(x) for x in b.split(".")[:3]]
    for ai, bi in zip(a_parts, b_parts):
        if ai < bi:
            return -1
        if ai > bi:
            return 1
    return 0


def _parse_version(raw: str) -> str | None:
    m = VERSION_PATTERN.search(raw)
    return m.group(0) if m else None


def _is_identifier(s: str) -> bool:
    if not s or s.endswith(":"):
        return False
    if not s[0].isalpha():
        return False
    return all(c.isalnum() or c in "-_./" for c in s)


def _parse_agents_json(raw: bytes) -> list[AgentInfo] | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    entries: list[dict] = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict) and "agents" in data:
        entries = data["agents"]
    else:
        return None

    agents: list[AgentInfo] = []
    seen: set[str] = set()
    for e in entries:
        agent_id = e.get("id") or e.get("name", "")
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        name = e.get("name") or agent_id
        agents.append(
            AgentInfo(
                id=agent_id,
                name=name,
                model=e.get("model", ""),
                workspace=e.get("workspace", ""),
                identity_name=e.get("identityName", ""),
                identity_emoji=e.get("identityEmoji", ""),
                is_default=bool(e.get("isDefault", False)),
                runtime="openclaw",
            )
        )
    return agents


def _parse_agents_text(output: str) -> list[AgentInfo]:
    agents: list[AgentInfo] = []
    seen: set[str] = set()
    for line in output.splitlines():
        line = line.strip().lstrip("-").strip()
        if not line:
            continue
        # 格式: main (default) (小二（指挥官）)
        m = re.match(r"^(\S+)(?:\s+\(default\))?\s+\((.+)\)$", line)
        if m:
            agent_id, name = m.group(1), m.group(2)
            if agent_id not in seen:
                seen.add(agent_id)
                agents.append(AgentInfo(id=agent_id, name=name))
            continue
        fields = line.split()
        if len(fields) >= 2 and _is_identifier(fields[0]) and _is_identifier(fields[1]):
            if fields[0] not in seen:
                seen.add(fields[0])
                agents.append(AgentInfo(id=fields[0], name=fields[0], model=fields[1]))
    return agents


def _parse_usage(data: dict[str, Any]) -> TokenUsage:
    def _int(*keys: str) -> int:
        for k in keys:
            v = data.get(k)
            if v is not None:
                return int(v)
        return 0

    return TokenUsage(
        input_tokens=_int("input", "inputTokens", "input_tokens"),
        output_tokens=_int("output", "outputTokens", "output_tokens"),
        cache_read_tokens=_int(
            "cacheRead", "cachedInputTokens", "cached_input_tokens", "cache_read"
        ),
        cache_write_tokens=_int(
            "cacheWrite", "cacheCreationInputTokens", "cache_creation_input_tokens", "cache_write"
        ),
    )


def _try_parse_result_blob(text: str) -> dict | None:
    text = text.strip()
    if not text or text[0] != "{":
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    # Support both direct payloads (local) and nested result.payloads (gateway)
    inner = data if "payloads" in data else data.get("result", {})
    if "payloads" in inner or inner.get("meta", {}).get("durationMs"):
        return data
    return None


def _extract_from_result(data: dict) -> tuple[str, str, TokenUsage | None, str]:
    output_parts: list[str] = []
    # Support both direct payloads (local) and nested result.payloads (gateway)
    inner = data if "payloads" in data else data.get("result", {})
    for p in inner.get("payloads", []):
        if isinstance(p, dict) and p.get("text"):
            output_parts.append(p["text"])

    session_id = ""
    model = ""
    usage: TokenUsage | None = None
    meta = inner.get("meta", {})
    agent_meta = meta.get("agentMeta", {})
    if isinstance(agent_meta, dict):
        session_id = agent_meta.get("sessionId", "")
        model = agent_meta.get("model", "")
        if u := agent_meta.get("usage"):
            if isinstance(u, dict):
                usage = _parse_usage(u)

    return "".join(output_parts), session_id, usage, model

def _parse_stdout_events(buf: str) -> tuple[list[OpenClawEvent], OpenClawResult | None]:
    events: list[OpenClawEvent] = []
    output_parts: list[str] = []
    session_id = ""
    model = ""
    usage: TokenUsage | None = None
    final_status = "completed"
    final_error = ""

    trimmed = buf.strip()
    if trimmed:
        # 整段 JSON 快速路径
        for i, line in enumerate(trimmed.split("\n")):
            if line.strip().startswith("{"):
                candidate = "\n".join(trimmed.split("\n")[i:])
                if result_data := _try_parse_result_blob(candidate):
                    out, sid, u, m = _extract_from_result(result_data)
                    if out:
                        events.append(OpenClawEvent(type="text", content=out))
                        output_parts.append(out)
                    return events, OpenClawResult(
                        status="completed",
                        output=out,
                        session_id=sid,
                        usage=u,
                        model=m,
                    )

    got_events = False
    for line in buf.splitlines():
        line = line.strip()
        if not line or line[0] != "{":
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "type" in event:
            got_events = True
            etype = event.get("type", "")
            if event.get("sessionId"):
                session_id = event["sessionId"]
            if etype == "text" and event.get("text"):
                events.append(OpenClawEvent(type="text", content=event["text"]))
                output_parts.append(event["text"])
            elif etype == "tool_use":
                events.append(
                    OpenClawEvent(
                        type="tool_use",
                        tool=event.get("tool", ""),
                        call_id=event.get("callId", ""),
                        input=event.get("input"),
                    )
                )
            elif etype == "tool_result":
                events.append(
                    OpenClawEvent(
                        type="tool_result",
                        tool=event.get("tool", ""),
                        call_id=event.get("callId", ""),
                        output=event.get("text", ""),
                    )
                )
            elif etype in ("error", "lifecycle"):
                err = event.get("text") or event.get("message", "unknown error")
                if etype == "lifecycle" and event.get("phase") not in (
                    "error",
                    "failed",
                    "cancelled",
                ):
                    continue
                events.append(OpenClawEvent(type="error", content=err))
                final_status = "failed"
                final_error = err
            elif etype == "step_start":
                events.append(OpenClawEvent(type="status", status="running"))
            elif etype == "step_finish" and event.get("usage"):
                usage = _parse_usage(event["usage"])
            continue

        if result_data := _try_parse_result_blob(line):
            got_events = True
            out, sid, u, m = _extract_from_result(result_data)
            if out:
                events.append(OpenClawEvent(type="text", content=out))
                output_parts.append(out)
            if sid:
                session_id = sid
            if u:
                usage = u
            if m:
                model = m

    if not got_events and trimmed:
        return [], OpenClawResult(status="completed", output=trimmed)

    if not got_events:
        return events, OpenClawResult(
            status="failed",
            output="",
            error="openclaw returned no parseable output",
        )

    return events, OpenClawResult(
        status=final_status,
        output="".join(output_parts),
        error=final_error,
        session_id=session_id,
        usage=usage,
        model=model,
    )


class OpenClawAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = settings.openclaw_executable

    async def _run_cmd(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        logger.info("openclaw cmd: %s %s", self.executable, " ".join(args))
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

    def is_available(self) -> bool:
        return shutil.which(self.executable) is not None

    async def check_health(self) -> tuple[bool, str]:
        if not self.is_available():
            return False, ""
        try:
            _, out, _ = await self._run_cmd("--version", timeout=10)
            version = _parse_version(out) or ""
            if version and _compare_version(version, self.settings.openclaw_min_version) < 0:
                logger.warning(
                    "openclaw version %s below minimum %s",
                    version,
                    self.settings.openclaw_min_version,
                )
                return False, version
            return True, version
        except Exception as e:
            logger.error("openclaw health check failed: %s", e)
            return False, ""

    async def list_agents(self) -> list[AgentInfo]:
        if not self.is_available():
            return []

        for json_args in (
            ("agents", "list", "--json"),
            ("agents", "list", "--output", "json"),
            ("agents", "list", "-o", "json"),
        ):
            try:
                code, out, err = await self._run_cmd(*json_args, timeout=30)
                if agents := _parse_agents_json(out.encode()):
                    logger.info("discovered %d agents via JSON", len(agents))
                    return agents
            except Exception as e:
                logger.debug("agents list %s failed: %s", json_args, e)

        try:
            _, out, _ = await self._run_cmd("agents", "list", timeout=30)
            agents = _parse_agents_text(out)
            logger.info("discovered %d agents via text fallback", len(agents))
            return agents
        except Exception as e:
            logger.error("agents list failed: %s", e)
            return []

    def _build_args(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str,
        session_id: str,
        timeout: int,
    ) -> list[str]:
        args = ["agent"]
        if self.settings.openclaw_mode != "gateway":
            args.append("--local")
        args.extend(["--json", "--session-id", session_id])
        if timeout > 0:
            args.extend(["--timeout", str(timeout)])
        if agent_id:
            args.extend(["--agent", agent_id])
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"
        args.extend(["--message", full_prompt])
        return args

    async def execute(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int | None = None,
    ) -> AsyncIterator[OpenClawEvent]:
        if not self.is_available():
            yield OpenClawEvent(type="error", content="openclaw executable not found")
            yield OpenClawEvent(type="result", content="failed")
            return

        ok, version = await self.check_health()
        if not ok:
            msg = f"openclaw unavailable or version {version} too old"
            yield OpenClawEvent(type="error", content=msg)
            yield OpenClawEvent(type="result", content="failed")
            return

        sid = session_id or f"agentcenter-{uuid.uuid4().hex[:12]}"
        t = timeout or self.settings.openclaw_default_timeout
        args = self._build_args(agent_id, prompt, system_prompt, sid, t)

        yield OpenClawEvent(type="status", status="running")

        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        async def _read_stream(stream, chunks: list[str], label: str) -> None:
            if stream is None:
                return
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                chunks.append(text)
                if label == "stderr":
                    for line in text.splitlines():
                        if line.strip():
                            logger.debug("[openclaw:stderr] %s", line)

        start = time.monotonic()
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(proc.stdout, stdout_chunks, "stdout"),
                    _read_stream(proc.stderr, stderr_chunks, "stderr"),
                    proc.wait(),
                ),
                timeout=t + 30,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            yield OpenClawEvent(type="error", content=f"openclaw timed out after {t}s")
            yield OpenClawEvent(type="result", content="timeout")
            return

        duration_ms = int((time.monotonic() - start) * 1000)
        stdout = "".join(stdout_chunks)
        events, result = _parse_stdout_events(stdout)

        for ev in events:
            yield ev

        if result:
            if proc.returncode and result.status == "completed":
                result.status = "failed"
                result.error = f"openclaw exited with code {proc.returncode}"
            result.duration_ms = duration_ms
            if not result.session_id:
                result.session_id = sid
            yield OpenClawEvent(type="result", content=result.status)
        else:
            yield OpenClawEvent(type="result", content="failed")

    async def run_to_completion(
        self,
        agent_id: str,
        prompt: str,
        system_prompt: str = "",
        session_id: str | None = None,
        timeout: int | None = None,
    ) -> OpenClawResult:
        start = time.monotonic()
        output_parts: list[str] = []
        sid = session_id or f"agentcenter-{uuid.uuid4().hex[:12]}"
        final_status = "failed"
        final_error = ""
        usage: TokenUsage | None = None

        async for event in self.execute(agent_id, prompt, system_prompt, sid, timeout):
            if event.type == "text":
                output_parts.append(event.content)
            elif event.type == "error":
                final_error = event.content
                final_status = "failed"
            elif event.type == "result":
                final_status = event.content if event.content else "failed"

        duration_ms = int((time.monotonic() - start) * 1000)
        return OpenClawResult(
            status=final_status,
            output="".join(output_parts),
            error=final_error,
            session_id=sid,
            duration_ms=duration_ms,
            usage=usage,
        )
