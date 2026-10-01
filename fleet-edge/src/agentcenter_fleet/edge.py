"""设备侧连接器。

扫描本机 OpenClaw / Hermes，上报给云端协调器，绑定后领取任务并在本机执行。
只使用标准库，可单独安装：pip install agentcenter-fleet && fleet-edge

环境变量：
  AGENTCENTER_URL        云端协调器，默认 http://127.0.0.1:8013
  FLEET_ENROLL_TOKEN     与云端 .env 相同
  FLEET_NODE_ID          缺省用主机名
  FLEET_NODE_NAME
  FLEET_NODE_TOKEN_FILE  令牌落盘路径
  FLEET_MOCK=1           不调用本机 CLI
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logger = logging.getLogger("fleet-edge")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def sign_body(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return mac.hexdigest()


class Cloud:
    def __init__(self, base: str, enroll_token: str, node_token: str = ""):
        self.base = base.rstrip("/")
        self.enroll_token = enroll_token
        self.node_token = node_token

    def _request(self, method: str, path: str, payload: dict | None = None, auth: bool = False) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("X-Node-Token", self.node_token)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            logger.error("cloud %s %s -> %s %s", method, path, e.code, detail[:300])
            raise

    def enroll(self, body: dict) -> dict:
        body = {**body, "enroll_token": self.enroll_token}
        result = self._request("POST", "/api/fleet/enroll", body)
        self.node_token = result.get("node_token") or ""
        logger.info("enrolled node=%s mode=%s", result.get("node_id"), result.get("mode"))
        return result

    def heartbeat(self, body: dict) -> None:
        self._request("POST", "/api/fleet/heartbeat", body, auth=True)

    def claim(self) -> dict | None:
        data = self._request("POST", "/api/fleet/claim", {}, auth=True)
        return data.get("task")

    def finish(self, task_id: str, body: dict) -> None:
        self._request("POST", f"/api/fleet/tasks/{task_id}/finish", body, auth=True)


def slug_node_id(hostname: str) -> str:
    base = (hostname or "").split(".")[0].lower()
    base = re.sub(r"[^a-z0-9_-]", "-", base).strip("-")
    return (base or "device")[:64]


def _run_scan(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("scan failed cmd=%s err=%s", cmd[0], e)
        return ""
    return proc.stdout or ""


def _agents_from_openclaw_text(raw: str) -> list[dict]:
    start = raw.find("[")
    brace = raw.find("{")
    if start < 0 or (brace >= 0 and brace < start):
        start = brace
    if start < 0:
        return []
    try:
        data = json.loads(raw[start:])
    except json.JSONDecodeError:
        logger.warning("openclaw scan json unparsed head=%r", raw[:180])
        return []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("agents") or []
    else:
        return []
    agents: list[dict] = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get("id") or item.get("name") or "").strip()
        if not agent_id:
            continue
        agents.append(
            {
                "id": agent_id,
                "name": str(item.get("name") or agent_id),
                "runtime": "openclaw",
                "model": str(item.get("model") or ""),
            }
        )
    return agents


def _scan_openclaw() -> list[dict]:
    agents: list[dict] = []
    if shutil.which("openclaw"):
        agents = _agents_from_openclaw_text(_run_scan(["openclaw", "agents", "list", "--json"]))
    if agents:
        return agents
    root = Path.home() / ".openclaw" / "agents"
    if not root.is_dir():
        return []
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            agents.append(
                {
                    "id": child.name,
                    "name": child.name,
                    "runtime": "openclaw",
                    "model": "",
                }
            )
    return agents


def _scan_hermes() -> list[dict]:
    if not shutil.which("hermes"):
        return []
    text = _run_scan(["hermes", "profile", "list"])
    agents: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("profile") or set(stripped) <= {"─", "-", " "}:
            continue
        token = stripped.lstrip("◆* ").split()
        if not token:
            continue
        profile_id = token[0]
        if profile_id.lower() in {"profile", "model", "gateway", "alias", "distribution"}:
            continue
        if not re.match(r"^[A-Za-z0-9_.-]+$", profile_id) or profile_id in seen:
            continue
        seen.add(profile_id)
        model = token[1] if len(token) > 1 and token[1] not in {"—", "-"} else ""
        agents.append(
            {
                "id": profile_id,
                "name": f"Hermes/{profile_id}",
                "runtime": "hermes",
                "model": model,
            }
        )
    return agents


def scan_agents() -> list[dict]:
    started = time.perf_counter()
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in _scan_openclaw() + _scan_hermes():
        key = (item["runtime"], item["id"])
        if key in seen:
            continue
        seen.add(key)
        found.append(item)
    logger.info(
        "local scan agents=%d elapsed_ms=%.0f",
        len(found),
        (time.perf_counter() - started) * 1000,
    )
    return found


def openclaw_gateway_running() -> bool:
    """本机 Gateway 已在跑时，agent --local 会被拒绝。"""
    if not shutil.which("openclaw"):
        return False
    try:
        proc = subprocess.run(
            ["openclaw", "gateway", "status"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("gateway status failed err=%s", e)
        return False
    text = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    running = "Runtime: running" in text
    logger.info("openclaw gateway running=%s", running)
    return running


def gateway_blocks_local(text: str) -> bool:
    return "Run without --local" in text or "Gateway is running" in text


def openclaw_command(task: dict, prompt: str, *, local: bool) -> list[str]:
    agent = task.get("agent_id") or "default"
    session = task.get("session_id") or f"fleet-{str(task.get('id') or '')[:8]}"
    cmd = ["openclaw", "agent"]
    if local:
        cmd.append("--local")
    cmd.extend(
        [
            "--json",
            "--session-id",
            session,
            "--agent",
            agent,
            "--message",
            prompt,
        ]
    )
    return cmd


def run_local(task: dict, mock: bool) -> dict:
    runtime = task.get("runtime") or "openclaw"
    agent = task.get("agent_id") or "default"
    prompt = task.get("prompt") or ""
    system_prompt = task.get("system_prompt") or ""
    started = time.monotonic()
    logger.info(
        "execute task=%s runtime=%s agent=%s prompt_len=%d mock=%s",
        task.get("id"),
        runtime,
        agent,
        len(prompt),
        mock,
    )
    if mock:
        text = f"[mock:{runtime}/{agent}] {prompt[:200]}"
        return {
            "status": "completed",
            "output": text,
            "error": "",
            "duration_ms": int((time.monotonic() - started) * 1000),
        }

    full = f"{system_prompt}\n\n{prompt}".strip() if system_prompt else prompt
    if runtime == "hermes":
        commands = [["hermes"]]
        if agent and agent != "default":
            commands[0].extend(["--profile", agent])
        commands[0].extend(["chat", "-q", full, "--quiet", "--source", "tool", "--accept-hooks"])
    else:
        use_local = not openclaw_gateway_running()
        commands = [openclaw_command(task, full, local=use_local)]
        if use_local:
            commands.append(openclaw_command(task, full, local=False))

    last = {"status": "failed", "output": "", "error": "runtime failed", "duration_ms": 0}
    for index, cmd in enumerate(commands):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except FileNotFoundError:
            return {"status": "failed", "output": "", "error": f"{cmd[0]} not found", "duration_ms": 0}
        except subprocess.TimeoutExpired:
            return {
                "status": "timeout",
                "output": "",
                "error": "local runtime timeout",
                "duration_ms": 600000,
            }
        duration_ms = int((time.monotonic() - started) * 1000)
        if proc.returncode == 0:
            logger.info("execute done task=%s duration_ms=%s local_flag=%s", task.get("id"), duration_ms, "--local" in cmd)
            return {
                "status": "completed",
                "output": (proc.stdout or "").strip(),
                "error": "",
                "duration_ms": duration_ms,
            }
        err = (proc.stderr or proc.stdout or "runtime failed").strip()
        last = {
            "status": "failed",
            "output": proc.stdout or "",
            "error": err[:4000],
            "duration_ms": duration_ms,
        }
        if index + 1 < len(commands) and gateway_blocks_local(err):
            logger.warning("retry without --local task=%s", task.get("id"))
            continue
        logger.error("execute failed task=%s code=%s", task.get("id"), proc.returncode)
        return last
    return last


def execute_and_finish(cloud: Cloud, task: dict, mock: bool) -> None:
    result = run_local(task, mock)
    try:
        cloud.finish(task["id"], result)
        logger.info("reported task=%s status=%s", task["id"], result["status"])
    except Exception:
        logger.exception("finish failed task=%s", task.get("id"))


def serve_webhook(cloud: Cloud, port: int, secret: str, mock: bool) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            ts = self.headers.get("X-Fleet-Timestamp") or ""
            sig = self.headers.get("X-Fleet-Signature") or ""
            try:
                fresh = abs(int(time.time()) - int(ts)) <= 300
            except ValueError:
                fresh = False
            expected = sign_body(secret, ts, body)
            if not fresh or not hmac.compare_digest(expected, sig):
                logger.warning("webhook signature rejected")
                self.send_response(401)
                self.end_headers()
                return
            try:
                payload = json.loads(body.decode())
                task = payload.get("task") or {}
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
                return
            if not task.get("id"):
                self.send_response(400)
                self.end_headers()
                return
            logger.info("webhook accepted task=%s", task["id"])
            threading.Thread(
                target=execute_and_finish, args=(cloud, task, mock), daemon=True
            ).start()
            raw = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, fmt: str, *args) -> None:
            logger.info("webhook " + fmt, *args)

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("webhook listening port=%s", port)
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="AgentCenter 设备连接器")
    parser.add_argument("--base-url", default=_env("AGENTCENTER_URL", "http://127.0.0.1:8013"))
    parser.add_argument("--enroll-token", default=_env("FLEET_ENROLL_TOKEN"))
    parser.add_argument("--node-id", default=_env("FLEET_NODE_ID"))
    parser.add_argument("--name", default=_env("FLEET_NODE_NAME"))
    parser.add_argument("--runtimes", default=_env("FLEET_RUNTIMES", "openclaw,hermes"))
    parser.add_argument("--token-file", default=_env("FLEET_NODE_TOKEN_FILE"))
    parser.add_argument("--mode", choices=["plugin", "webhook"], default=_env("FLEET_MODE", "plugin"))
    parser.add_argument("--webhook-url", default=_env("FLEET_WEBHOOK_URL"))
    parser.add_argument("--webhook-port", type=int, default=int(_env("FLEET_WEBHOOK_PORT", "8766") or "8766"))
    parser.add_argument("--mock", action="store_true", default=_env("FLEET_MOCK") in {"1", "true", "yes"})
    parser.add_argument("--once", action="store_true", help="领取并执行一条后退出")
    args = parser.parse_args()

    log_dir = Path.home() / ".agentcenter" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "fleet-edge.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    logger.info("log file=%s", log_path)
    if not args.enroll_token:
        logger.error("需要 FLEET_ENROLL_TOKEN")
        return 2

    hostname = socket.gethostname()
    node_id = (args.node_id or slug_node_id(hostname)).strip().lower()
    agents = scan_agents()
    if not agents:
        logger.error("本机没有扫到 OpenClaw 或 Hermes 智能体，无法上报")
        return 2
    token_path = Path(args.token_file or str(Path.home() / ".agentcenter" / f"{node_id}.token"))
    cloud = Cloud(args.base_url, args.enroll_token)
    identity = {
        "hostname": hostname,
        "platform": platform.system().lower(),
        "agents": agents,
    }
    if token_path.is_file():
        cloud.node_token = token_path.read_text(encoding="utf-8").strip()
        logger.info("loaded node token file=%s", token_path)
    else:
        enrolled = cloud.enroll(
            {
                "node_id": node_id,
                "name": args.name or hostname.split(".")[0] or node_id,
                "hostname": hostname,
                "platform": identity["platform"],
                "agents": agents,
                "mode": args.mode,
                "webhook_url": args.webhook_url if args.mode == "webhook" else "",
            }
        )
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(enrolled["node_token"], encoding="utf-8")
        try:
            token_path.chmod(0o600)
        except OSError:
            logger.warning("chmod token file failed path=%s", token_path)
        logger.info(
            "reported node=%s agents=%d bound=%s，请在控制台绑定后再派单",
            node_id,
            len(agents),
            enrolled.get("bound"),
        )

    if args.mode == "webhook":
        threading.Thread(
            target=serve_webhook,
            args=(cloud, args.webhook_port, args.enroll_token, args.mock),
            daemon=True,
        ).start()

    scan_box = {"at": time.time(), "agents": agents}

    def current_agents() -> list[dict]:
        if time.time() - scan_box["at"] >= 60:
            scan_box["agents"] = scan_agents()
            scan_box["at"] = time.time()
        return scan_box["agents"]

    def beat_loop() -> None:
        while True:
            try:
                cloud.heartbeat(
                    {
                        "hostname": hostname,
                        "platform": identity["platform"],
                        "agents": current_agents(),
                    }
                )
            except Exception:
                logger.exception("heartbeat failed")
            time.sleep(15)

    threading.Thread(target=beat_loop, name="fleet-heartbeat", daemon=True).start()

    while True:
        if args.mode == "plugin":
            try:
                task = cloud.claim()
            except Exception:
                logger.exception("claim failed")
                task = None
            if task:
                execute_and_finish(cloud, task, args.mock)
                if args.once:
                    return 0
        elif args.once:
            return 0
        time.sleep(3)


if __name__ == "__main__":
    raise SystemExit(main())
