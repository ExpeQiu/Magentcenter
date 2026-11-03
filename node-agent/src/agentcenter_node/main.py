"""PC Node Agent：v2 claim-next / lease / finish；身份对齐 Core node_identity.json。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger("node-agent")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _data_dir() -> Path:
    raw = _env("AGENTCENTER_DATA_DIR")
    if raw:
        return Path(raw)
    return Path.home() / "Library/Application Support/AgentCenter/data"


def _load_identity_node_id() -> str:
    path = _data_dir() / "node_identity.json"
    if not path.is_file():
        return ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(raw.get("node_id") or "").strip()


def _read_token() -> str:
    path = _data_dir() / "node_agent.token"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return _env("NODE_AGENT_TOKEN")


class CoreClient:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("X-Node-Token", self.token)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            logger.error("core %s %s -> %s %s", method, path, e.code, detail[:300])
            raise

    def heartbeat(self) -> None:
        self._request(
            "POST",
            "/api/v2/nodes/heartbeat",
            {"protocol_version": 2, "capabilities": ["task.execute"]},
        )

    def claim_next(self) -> dict | None:
        data = self._request(
            "POST",
            "/api/v2/commands/claim-next",
            {"protocol_version": 2},
        )
        if not data or not data.get("accepted"):
            return None
        return data

    def renew_lease(self, execution_id: str, generation: int) -> dict:
        return self._request(
            "POST",
            f"/api/v2/executions/{execution_id}/lease",
            {"assignment_generation": generation},
        )

    def delivery_ack(self, execution_id: str, ack: str, generation: int) -> None:
        self._request(
            "POST",
            f"/api/v2/executions/{execution_id}/delivery-ack",
            {"ack": ack, "assignment_generation": generation},
        )

    def finish(self, body: dict) -> dict:
        return self._request("POST", "/api/v2/commands/finish", body)


def _within_allowed(path: str, roots: list[Path]) -> bool:
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _run_mock(task: dict) -> tuple[str, str]:
    return f"[mock] done agent={task.get('agent_id')} prompt={(task.get('prompt') or '')[:80]}", ""


def _run_openclaw(task: dict) -> tuple[str, str]:
    agent = task.get("agent_id") or "main"
    prompt = task.get("prompt") or ""
    cmd = [
        _env("OPENCLAW_EXECUTABLE", "openclaw"),
        "--local",
        "--json",
        "--agent",
        agent,
        "--message",
        prompt,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return "", (proc.stderr or proc.stdout or f"exit {proc.returncode}")[:4000]
    return (proc.stdout or "").strip(), ""


def _run_hermes(task: dict) -> tuple[str, str]:
    prompt = task.get("prompt") or ""
    cmd = [_env("HERMES_EXECUTABLE", "hermes"), "chat", "-q", prompt, "--quiet", "--source", "tool"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        return "", (proc.stderr or proc.stdout or f"exit {proc.returncode}")[:4000]
    return (proc.stdout or "").strip(), ""


def execute_task(task: dict, mock: bool, allowed_roots: list[Path]) -> tuple[str, str, str]:
    """返回 (status, output, error)。禁止任意 shell；仅白名单 runtime。"""
    # 目录白名单：system_prompt / prompt 中若含绝对路径且不在根内则拒绝
    blob = f"{task.get('prompt') or ''}\n{task.get('system_prompt') or ''}"
    for token in blob.split():
        if token.startswith("/") and len(token) > 1 and not _within_allowed(token, allowed_roots):
            # 仅当像路径且存在时才硬拒绝，避免误伤普通文本
            if Path(token).exists() and allowed_roots:
                return "failed", "", f"path outside allowlist: {token}"

    if mock:
        out, err = _run_mock(task)
        return ("completed", out, err) if not err else ("failed", out, err)
    runtime = (task.get("runtime") or "openclaw").lower()
    try:
        if runtime == "hermes":
            out, err = _run_hermes(task)
        else:
            out, err = _run_openclaw(task)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "failed", "", str(exc)
    if err:
        return "failed", out, err
    return "completed", out, ""


def _lease_loop(client: CoreClient, execution_id: str, generation: int, stop: threading.Event) -> None:
    while not stop.wait(60):
        try:
            client.renew_lease(execution_id, generation)
        except Exception:
            logger.exception("lease renew failed execution_id=%s", execution_id)


def run_once(client: CoreClient, mock: bool, allowed_roots: list[Path]) -> bool:
    task = client.claim_next()
    if not task:
        return False
    execution_id = str(task.get("execution_id") or "")
    generation = int(task.get("assignment_generation") or 1)
    task_id = str(task.get("task_id") or "")
    logger.info(
        "claimed task_id=%s execution_id=%s agent=%s runtime=%s",
        task_id,
        execution_id,
        task.get("agent_id"),
        task.get("runtime"),
    )
    try:
        client.delivery_ack(execution_id, "received", generation)
    except Exception:
        logger.exception("delivery_ack received failed")
    stop = threading.Event()
    if execution_id:
        threading.Thread(
            target=_lease_loop,
            args=(client, execution_id, generation, stop),
            daemon=True,
        ).start()
    started = time.time()
    try:
        client.delivery_ack(execution_id, "applied", generation)
    except Exception:
        logger.exception("delivery_ack applied failed")
    status, output, error = execute_task(task, mock=mock, allowed_roots=allowed_roots)
    stop.set()
    duration_ms = int((time.time() - started) * 1000)
    try:
        client.finish(
            {
                "protocol_version": 2,
                "task_id": task_id,
                "execution_id": execution_id,
                "status": status,
                "output": output,
                "error": error,
                "duration_ms": duration_ms,
                "assignment_generation": generation,
            }
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            logger.error("finish rejected stale/closed task_id=%s code=409", task_id)
        raise
    logger.info("finished task_id=%s status=%s duration_ms=%s", task_id, status, duration_ms)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentCenter Node Agent (v2)")
    parser.add_argument("--base-url", default=_env("AGENTCENTER_URL", "http://127.0.0.1:8013"))
    parser.add_argument("--token-file", default="")
    parser.add_argument("--mock", action="store_true", default=_env("FLEET_MOCK") in {"1", "true", "yes"})
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--allow-root",
        action="append",
        default=[],
        help="允许访问的目录根；可重复。默认含 HOME 与 AGENTCENTER_DATA_DIR",
    )
    args = parser.parse_args(argv)

    log_dir = Path.home() / ".agentcenter" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "node-agent.log", encoding="utf-8"),
        ],
    )

    node_id = _load_identity_node_id()
    token = ""
    if args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if not token:
        token = _read_token()
    if not token:
        logger.error("缺少 node_agent.token（Core 启动后应已写入）或 NODE_AGENT_TOKEN")
        return 2

    allowed = [Path(p) for p in args.allow_root]
    if not allowed:
        allowed = [Path.home(), _data_dir()]
    client = CoreClient(args.base_url, token)
    logger.info(
        "node-agent start base=%s node_id=%s mock=%s",
        args.base_url,
        node_id or "(pending)",
        args.mock,
    )

    def beat() -> None:
        while True:
            try:
                client.heartbeat()
            except Exception:
                logger.exception("heartbeat failed")
            time.sleep(15)

    threading.Thread(target=beat, name="node-heartbeat", daemon=True).start()

    while True:
        try:
            did = run_once(client, mock=args.mock, allowed_roots=allowed)
        except Exception:
            logger.exception("run_once failed")
            did = False
        if args.once:
            return 0 if did else 1
        time.sleep(2 if not did else 0.2)


if __name__ == "__main__":
    raise SystemExit(main())
