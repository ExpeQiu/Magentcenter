"""多端连接器：本机扫描智能体并绑定，远程设备上报扫描结果后在控制台绑定。

已绑定的设备才能接单。插件在 NAT 后领取任务；本机绑定由协调器直接执行。
设备有可达地址时登记 webhook_url，协调器 POST 签名任务包。
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import platform
import re
import secrets
import socket
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select

from app.config import get_settings
from app.models.db import FleetNodeRecord, TaskEventRecord, TaskRecord, get_session_factory
from app.paths import data_dir

logger = logging.getLogger(__name__)

NODE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MODES = ("plugin", "webhook", "local")
_claim_lock = asyncio.Lock()


class FleetAuthError(Exception):
    pass


class FleetError(Exception):
    pass


class FleetLegacyCloud(FleetError):
    """云端还是旧协调器，没有握手接口，改走注册和设备列表。"""


def _now() -> datetime:
    return datetime.utcnow()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


_RUNTIME_CAPS = {
    "openclaw": ("openclaw.agent",),
    "hermes": ("hermes.chat",),
}
_HANDSHAKE_TTL = 120


def handshake_proof(secret: str, role: str, material: str) -> str:
    msg = f"fleet.handshake.v1.{role}.{material}".encode()
    mac = hmac.new(secret.encode(), msg, hashlib.sha256)
    return mac.hexdigest()


def _eq(left: str, right: str) -> bool:
    if not left or not right or len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def capabilities_of(agents: list[dict[str, str]]) -> list[str]:
    caps: list[str] = []
    for agent in agents:
        for cap in _RUNTIME_CAPS.get(agent.get("runtime") or "", ()):
            if cap not in caps:
                caps.append(cap)
    if agents and "task.execute" not in caps:
        caps.append("task.execute")
    return caps


def sign_body(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256)
    return mac.hexdigest()


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str, skew_sec: int = 300) -> bool:
    if not secret or not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    # utcnow() 是 naive 时间，.timestamp() 会按本地时区解释，东八区会偏 8 小时
    if abs(int(time.time()) - ts) > skew_sec:
        return False
    expected = sign_body(secret, timestamp, body)
    return hmac.compare_digest(expected, signature)


def slug_node_id(hostname: str) -> str:
    base = (hostname or "").split(".")[0].lower()
    base = re.sub(r"[^a-z0-9_-]", "-", base).strip("-")
    return (base or "device")[:64]


def _clean_agents(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    items = raw if isinstance(raw, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        runtime = str(item.get("runtime") or "").strip()
        agent_id = str(item.get("id") or "").strip()
        if runtime not in ("openclaw", "hermes") or not agent_id:
            continue
        key = (runtime, agent_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": agent_id,
                "name": str(item.get("name") or agent_id),
                "runtime": runtime,
                "model": str(item.get("model") or ""),
            }
        )
    return out


def _load_agents(raw: str) -> list[dict[str, str]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return _clean_agents(data)


def _dump_agents(agents: list[dict[str, str]]) -> str:
    return json.dumps(_clean_agents(agents), ensure_ascii=False)


def _has_agent(agents: list[dict[str, str]], runtime: str, agent_id: str) -> bool:
    return any(a["runtime"] == runtime and a["id"] == agent_id for a in agents)


def _runtimes(raw: Any) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        name = str(item).strip()
        if name in ("openclaw", "hermes") and name not in out:
            out.append(name)
    return out


def _dump_runtimes(runtimes: list[str]) -> str:
    return json.dumps(_runtimes(runtimes), ensure_ascii=False)


def _online(rec: FleetNodeRecord, ttl: int | None = None) -> bool:
    if (rec.mode or "") == "local" and bool(getattr(rec, "bound", 0)):
        return True
    if not rec.last_seen:
        return False
    limit = ttl if ttl is not None else get_settings().fleet_heartbeat_ttl
    return _now() - rec.last_seen <= timedelta(seconds=max(5, limit))


async def _counts() -> dict[str, dict[str, int]]:
    factory = get_session_factory()
    stats: dict[str, dict[str, int]] = {}
    async with factory() as session:
        q = (
            select(TaskRecord.node_id, TaskRecord.status, func.count())
            .where(TaskRecord.node_id != "")
            .where(TaskRecord.status.in_(("queued", "running")))
            .group_by(TaskRecord.node_id, TaskRecord.status)
        )
        for node_id, status, count in (await session.execute(q)).all():
            bucket = stats.setdefault(node_id, {"queued": 0, "running": 0})
            bucket[status] = int(count)
    return stats


def to_info(rec: FleetNodeRecord, counts: dict[str, dict[str, int]] | None = None) -> dict[str, Any]:
    bucket = (counts or {}).get(rec.id, {})
    agents = _load_agents(getattr(rec, "agents_json", "") or "[]")
    seen = _load_agents(getattr(rec, "seen_json", "") or "[]")
    runtimes = _runtimes([a["runtime"] for a in (agents or seen)])
    bound = bool(getattr(rec, "bound", 0))
    shown = agents if bound else seen
    return {
        "id": rec.id,
        "name": rec.name,
        "runtimes": runtimes,
        "agents": agents,
        "seen": seen,
        "hostname": rec.hostname or "",
        "platform": rec.platform or "",
        "mode": rec.mode or "plugin",
        "webhook_url": rec.webhook_url or "",
        "online": _online(rec),
        "enrolled": bool(rec.token_hash) or (rec.mode == "local" and bound),
        "bound": bound,
        "workspace_id": getattr(rec, "workspace_id", "") or "",
        "last_seen": rec.last_seen,
        "load": rec.load,
        "running_count": int(bucket.get("running", 0)),
        "queued_count": int(bucket.get("queued", 0)),
        "capabilities": capabilities_of(shown),
        "handshake": getattr(rec, "handshake_state", "") or "",
        "handshake_at": getattr(rec, "handshake_at", None),
    }


def _visible_to_workspace(info: dict[str, Any], workspace_id: str) -> bool:
    """未归属的终端每个团队都能看到；绑定后只属于该团队。"""
    if not workspace_id:
        return True
    owner = info.get("workspace_id") or ""
    if not owner:
        return True
    return owner == workspace_id


async def list_nodes(workspace_id: str = "") -> list[dict[str, Any]]:
    factory = get_session_factory()
    counts = await _counts()
    async with factory() as session:
        rows = (
            await session.execute(select(FleetNodeRecord).order_by(FleetNodeRecord.name))
        ).scalars().all()
        infos = [to_info(r, counts) for r in rows]
    visible = [n for n in infos if _visible_to_workspace(n, workspace_id)]
    logger.debug(
        "fleet nodes listed workspace=%s total=%d visible=%d",
        workspace_id or "-",
        len(infos),
        len(visible),
    )
    return visible


async def get_node(node_id: str) -> FleetNodeRecord | None:
    factory = get_session_factory()
    async with factory() as session:
        return await session.get(FleetNodeRecord, node_id)


async def enroll(
    *,
    enroll_token: str,
    expected_token: str,
    node_id: str,
    name: str = "",
    runtimes: list[str] | None = None,
    agents: list[dict[str, Any]] | None = None,
    hostname: str = "",
    platform: str = "",
    mode: str = "plugin",
    webhook_url: str = "",
) -> dict[str, Any]:
    """设备上报扫描结果并领取令牌。绑定要在控制台确认，这里不会直接接单。"""
    if not expected_token:
        raise FleetAuthError("fleet enroll token is not configured")
    if not hmac.compare_digest(enroll_token or "", expected_token):
        logger.warning("fleet enroll rejected node=%s", node_id)
        raise FleetAuthError("invalid enroll token")
    node_id = (node_id or "").strip().lower()
    if not NODE_ID_RE.match(node_id):
        raise FleetError("invalid node id")
    mode = mode if mode in ("plugin", "webhook") else "plugin"
    seen = _clean_agents(agents)
    rts = _runtimes([a["runtime"] for a in seen] or (runtimes or []))
    if not rts and not seen:
        raise FleetError("没有扫到 openclaw 或 hermes 智能体")
    if mode == "webhook" and not (webhook_url or "").strip():
        raise FleetError("webhook mode requires webhook_url")

    token = secrets.token_urlsafe(32)
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(FleetNodeRecord, node_id)
        if rec is None:
            rec = FleetNodeRecord(id=node_id, name=name or node_id, bound=0, agents_json="[]")
            session.add(rec)
        rec.name = name or rec.name or node_id
        rec.token_hash = hash_token(token)
        if seen:
            rec.seen_json = _dump_agents(seen)
        if not rec.bound:
            rec.runtimes_json = _dump_runtimes(rts)
            rec.agents_json = "[]"
        elif seen:
            rec.runtimes_json = _dump_runtimes([a["runtime"] for a in _load_agents(rec.agents_json)])
        rec.hostname = hostname or rec.hostname or ""
        rec.platform = platform or rec.platform or ""
        if rec.mode != "local":
            rec.mode = mode
            rec.webhook_url = webhook_url.strip() if mode == "webhook" else ""
        rec.last_seen = _now()
        rec.updated_at = _now()
        await session.commit()
        await session.refresh(rec)
        info = to_info(rec)
    logger.info(
        "fleet reported node=%s mode=%s seen=%d bound=%s hostname=%s",
        node_id,
        info["mode"],
        len(seen),
        info["bound"],
        hostname or "-",
    )
    from app.core.chain import append_chain

    await append_chain(
        kind="enroll",
        actor_id=node_id,
        channel=info["mode"],
        status="connector",
        summary=name or node_id,
        detail={"platform": platform or "", "agents": len(seen)},
    )
    return {**info, "node_id": node_id, "node_token": token}


async def enroll_voice(
    *,
    enroll_token: str,
    expected_token: str,
    device_id: str,
    name: str = "",
    hostname: str = "",
    platform: str = "esp32",
) -> dict[str, str]:
    """在场终端注册。不扫描智能体，也不领任务，只换一张设备令牌。"""
    if not expected_token:
        raise FleetAuthError("fleet enroll token is not configured")
    if not hmac.compare_digest(enroll_token or "", expected_token):
        logger.warning("voice enroll rejected device=%s", device_id)
        raise FleetAuthError("invalid enroll token")
    device_id = (device_id or "").strip().lower()
    if not NODE_ID_RE.match(device_id):
        raise FleetError("invalid device id")

    token = secrets.token_urlsafe(32)
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(FleetNodeRecord, device_id)
        if rec is not None and (rec.mode or "plugin") != "voice":
            raise FleetError("device id already registered")
        if rec is None:
            rec = FleetNodeRecord(
                id=device_id,
                name=name or device_id,
                bound=0,
                agents_json="[]",
                seen_json="[]",
            )
            session.add(rec)
        rec.name = name or rec.name or device_id
        rec.token_hash = hash_token(token)
        rec.runtimes_json = "[]"
        rec.agents_json = "[]"
        rec.seen_json = "[]"
        rec.mode = "voice"
        rec.webhook_url = ""
        rec.bound = 0
        rec.platform = platform if platform in ("esp32", "desktop") else "esp32"
        rec.hostname = hostname or rec.hostname or ""
        rec.last_seen = _now()
        rec.updated_at = _now()
        await session.commit()
    logger.info("voice device enrolled device=%s name=%s", device_id, name or device_id)
    from app.core.chain import append_chain

    await append_chain(
        kind="enroll",
        actor_id=device_id,
        channel=platform if platform in ("esp32", "desktop") else "esp32",
        status="voice",
        summary=name or device_id,
    )
    return {
        "device_id": device_id,
        "device_token": token,
        "name": name or device_id,
    }


def _peer_view(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": info["id"],
        "name": info["name"],
        "hostname": info.get("hostname") or "",
        "platform": info.get("platform") or "",
        "mode": info.get("mode") or "plugin",
        "online": bool(info.get("online")),
        "runtimes": info.get("runtimes") or [],
        "agents": info.get("agents") or [],
        "capabilities": info.get("capabilities") or [],
    }


async def peer_catalog(exclude: str = "", workspace_id: str = "") -> list[dict[str, Any]]:
    """已绑定到云端的其他端：智能体是资源，运行时映射成能力。"""
    nodes = await list_nodes(workspace_id)
    peers = [
        _peer_view(n)
        for n in nodes
        if n.get("bound") and (not exclude or n["id"] != exclude)
    ]
    logger.info(
        "fleet catalog workspace=%s exclude=%s peers=%d",
        workspace_id or "-",
        exclude or "-",
        len(peers),
    )
    return peers


async def begin_handshake(
    *,
    enroll_token: str,
    expected_token: str,
    node_id: str,
    nonce: str,
    name: str = "",
    runtimes: list[str] | None = None,
    agents: list[dict[str, Any]] | None = None,
    hostname: str = "",
    platform: str = "",
    mode: str = "plugin",
    webhook_url: str = "",
    local_self: bool = False,
) -> dict[str, Any]:
    """云端核对注册令牌，记下本机资源，并回一段只有持有同一令牌的云端才能给出的证明。"""
    if not expected_token:
        raise FleetAuthError("fleet enroll token is not configured")
    if not _eq(enroll_token or "", expected_token):
        logger.warning("fleet handshake rejected node=%s reason=bad-token", node_id)
        raise FleetAuthError("invalid enroll token")
    node_id = (node_id or "").strip().lower()
    if not NODE_ID_RE.match(node_id):
        raise FleetError("invalid node id")
    client_nonce = (nonce or "").strip()
    if len(client_nonce) < 8 or len(client_nonce) > 128:
        raise FleetError("invalid handshake nonce")
    seen = _clean_agents(agents)
    if not seen:
        raise FleetError("没有可绑定的智能体")
    if local_self:
        mode = "local"
    else:
        mode = mode if mode in ("plugin", "webhook") else "plugin"
    if mode == "webhook" and not (webhook_url or "").strip():
        raise FleetError("webhook mode requires webhook_url")

    challenge = secrets.token_hex(16)
    expires = _now() + timedelta(seconds=_HANDSHAKE_TTL)
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(FleetNodeRecord, node_id)
        if rec is None:
            rec = FleetNodeRecord(id=node_id, name=name or node_id, bound=0, agents_json="[]")
            session.add(rec)
        rec.name = name or rec.name or node_id
        rec.seen_json = _dump_agents(seen)
        if not rec.bound:
            rec.runtimes_json = _dump_runtimes([a["runtime"] for a in seen] or (runtimes or []))
            rec.agents_json = "[]"
        rec.hostname = hostname or rec.hostname or ""
        rec.platform = platform or rec.platform or ""
        if local_self or rec.mode != "local":
            rec.mode = mode
            rec.webhook_url = webhook_url.strip() if mode == "webhook" else ""
        rec.handshake_state = "pending"
        rec.handshake_challenge = challenge
        rec.handshake_expires = expires
        rec.updated_at = _now()
        await session.commit()
    proof = handshake_proof(expected_token, "cloud", f"{client_nonce}.{challenge}")
    logger.info(
        "fleet handshake offered node=%s mode=%s agents=%d",
        node_id,
        mode,
        len(seen),
    )
    return {
        "node_id": node_id,
        "challenge": challenge,
        "cloud_proof": proof,
        "expires_in": _HANDSHAKE_TTL,
    }


async def complete_handshake(
    *,
    enroll_token: str,
    expected_token: str,
    node_id: str,
    proof: str,
    workspace_id: str = "",
) -> dict[str, Any]:
    """本地回证后，云端绑定它上报的资源，并给出其他端的资源与能力。"""
    if not expected_token:
        raise FleetAuthError("fleet enroll token is not configured")
    if not _eq(enroll_token or "", expected_token):
        logger.warning("fleet handshake rejected node=%s reason=bad-token", node_id)
        raise FleetAuthError("invalid enroll token")
    node_id = (node_id or "").strip().lower()
    if not NODE_ID_RE.match(node_id):
        raise FleetError("invalid node id")

    token = secrets.token_urlsafe(32)
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(FleetNodeRecord, node_id)
        if rec is None or not (rec.handshake_challenge or ""):
            logger.warning("fleet handshake rejected node=%s reason=no-challenge", node_id)
            raise FleetError("handshake has not started")
        if rec.handshake_expires is None or _now() > rec.handshake_expires:
            rec.handshake_state = "failed"
            rec.handshake_challenge = ""
            rec.updated_at = _now()
            await session.commit()
            logger.warning("fleet handshake rejected node=%s reason=expired", node_id)
            raise FleetError("handshake expired")
        expected = handshake_proof(expected_token, "client", rec.handshake_challenge)
        if not _eq(proof or "", expected):
            logger.warning("fleet handshake rejected node=%s reason=bad-proof", node_id)
            raise FleetAuthError("invalid handshake proof")
        seen = _load_agents(rec.seen_json)
        if not seen:
            raise FleetError("没有可绑定的智能体")
        rec.token_hash = hash_token(token)
        rec.bound = 1
        rec.agents_json = _dump_agents(seen)
        rec.runtimes_json = _dump_runtimes([a["runtime"] for a in seen])
        if workspace_id:
            rec.workspace_id = workspace_id
        rec.handshake_state = "ok"
        rec.handshake_at = _now()
        rec.handshake_challenge = ""
        rec.handshake_expires = None
        rec.last_seen = _now()
        rec.updated_at = _now()
        await session.commit()
        await session.refresh(rec)
        info = to_info(rec)
        owner = info.get("workspace_id") or ""
    peers = await peer_catalog(exclude=node_id, workspace_id=owner)
    logger.info(
        "fleet handshake bound node=%s mode=%s agents=%d peers=%d workspace=%s",
        node_id,
        info["mode"],
        len(info["agents"]),
        len(peers),
        owner or "-",
    )
    return {**info, "node_id": node_id, "node_token": token, "peers": peers}


async def authenticate(token: str) -> FleetNodeRecord | None:
    if not token:
        return None
    digest = hash_token(token)
    factory = get_session_factory()
    async with factory() as session:
        q = select(FleetNodeRecord).where(FleetNodeRecord.token_hash == digest)
        return (await session.execute(q)).scalar_one_or_none()


async def heartbeat(
    token: str,
    *,
    runtimes: list[str] | None = None,
    agents: list[dict[str, Any]] | None = None,
    hostname: str = "",
    platform: str = "",
    load: float | None = None,
) -> dict[str, Any]:
    rec = await authenticate(token)
    if rec is None:
        raise FleetAuthError("invalid node token")
    was_online = _online(rec)
    seen = _clean_agents(agents) if agents is not None else None
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(FleetNodeRecord, rec.id)
        if row is None:
            raise FleetAuthError("invalid node token")
        row.last_seen = _now()
        if seen is not None:
            row.seen_json = _dump_agents(seen)
            logger.debug("fleet heartbeat scan node=%s seen=%d", row.id, len(seen))
        if row.bound:
            row.runtimes_json = _dump_runtimes(
                [a["runtime"] for a in _load_agents(row.agents_json)]
            )
        elif seen is not None:
            row.runtimes_json = _dump_runtimes([a["runtime"] for a in seen])
        elif runtimes:
            row.runtimes_json = _dump_runtimes(runtimes)
        if hostname:
            row.hostname = hostname
        if platform:
            row.platform = platform
        if load is not None:
            row.load = float(load)
        row.updated_at = _now()
        await session.commit()
        await session.refresh(row)
        info = to_info(row)
    if not was_online:
        logger.info("fleet node online id=%s mode=%s", info["id"], info["mode"])
    else:
        logger.debug("fleet heartbeat id=%s", info["id"])
    return info


def _same_team(rec: FleetNodeRecord, workspace_id: str) -> bool:
    owner = getattr(rec, "workspace_id", "") or ""
    if not workspace_id or not owner:
        return True
    return owner == workspace_id


async def plan_dispatch(
    target: str, runtime: str, agent_id: str, workspace_id: str = ""
) -> dict[str, Any]:
    """选定已绑定设备。local=True 时由协调器本机执行，任务仍记下 node_id。"""
    target = (target or "").strip().lower()
    agent_id = (agent_id or "").strip()
    if not agent_id:
        raise FleetError("需要指定智能体")
    if target == "auto":
        chosen = await _pick_online_agent(runtime, agent_id, workspace_id)
        if not chosen:
            raise FleetError(f"没有在线设备绑定了 {runtime}/{agent_id}")
        rec = await get_node(chosen)
        local = bool(rec and rec.mode == "local")
        logger.info(
            "fleet auto picked node=%s runtime=%s agent=%s local=%s",
            chosen,
            runtime,
            agent_id,
            local,
        )
        return {"node_id": chosen, "local": local}
    if not NODE_ID_RE.match(target):
        raise FleetError(f"invalid node id: {target}")
    rec = await get_node(target)
    if rec is None:
        raise FleetError(f"设备不存在: {target}")
    if not rec.bound:
        raise FleetError(f"设备未绑定: {target}")
    if not _same_team(rec, workspace_id):
        raise FleetError(f"终端 {target} 不属于当前团队")
    agents = _load_agents(rec.agents_json)
    if not _has_agent(agents, runtime, agent_id):
        raise FleetError(f"设备 {target} 未绑定 {runtime}/{agent_id}")
    if not _online(rec):
        logger.info(
            "fleet queue offline node=%s runtime=%s agent=%s mode=%s",
            target,
            runtime,
            agent_id,
            rec.mode,
        )
    return {"node_id": target, "local": rec.mode == "local"}


async def resolve_dispatch_node(target: str, runtime: str, agent_id: str = "") -> str:
    plan = await plan_dispatch(target, runtime, agent_id or "default")
    return plan["node_id"]


def _agent_kind(agents: list[dict[str, str]], agent_id: str) -> str:
    """绑定列表里的第一个是主智能体，其余是子智能体。"""
    if agents and agents[0].get("id") != agent_id:
        return "subagent"
    return "agent"


async def _bound_caller(caller_id: str) -> FleetNodeRecord:
    caller_id = (caller_id or "").strip().lower()
    caller = await get_node(caller_id)
    if caller is None or not caller.bound:
        raise FleetError("这台终端还没有绑定，不能调用其他端")
    if (caller.mode or "") == "voice":
        raise FleetError("语音终端不直接调用其他端的智能体")
    return caller


async def call_peer(
    *,
    caller_id: str,
    target: str,
    runtime: str,
    agent_id: str,
    prompt: str,
    task_manager: Any,
    workspace_id: str = "",
) -> dict[str, Any]:
    """已绑定的任意端（含云端本机）让另一端上的智能体或子智能体执行任务。"""
    caller = await _bound_caller(caller_id)
    target_id = (target or "").strip().lower()
    prompt = (prompt or "").strip()
    runtime = (runtime or "").strip()
    if runtime not in ("openclaw", "hermes"):
        raise FleetError("runtime must be openclaw or hermes")
    if not prompt:
        raise FleetError("需要任务内容")
    if not target_id or target_id == caller.id:
        raise FleetError("只能调用其他端上的智能体")
    owner = (caller.workspace_id or "").strip()
    if workspace_id and owner and workspace_id != owner:
        raise FleetError("终端不属于当前团队")
    if not owner:
        owner = (workspace_id or "").strip()
    plan = await plan_dispatch(target_id, runtime, agent_id, workspace_id=owner)
    from app.models.schemas import CreateTaskRequest

    info = await task_manager.create_task(
        CreateTaskRequest(
            agent_id=agent_id,
            prompt=prompt,
            runtime=runtime,  # type: ignore[arg-type]
            workspace_id=owner,
            node_id=plan["node_id"],
        )
    )
    target_rec = await get_node(plan["node_id"])
    agents = _load_agents(target_rec.agents_json) if target_rec is not None else []
    kind = _agent_kind(agents, agent_id)
    logger.info(
        "fleet call caller=%s target=%s kind=%s runtime=%s agent=%s task=%s local=%s",
        caller.id,
        plan["node_id"],
        kind,
        runtime,
        agent_id,
        info.id,
        plan["local"],
    )
    from app.core.chain import append_chain

    await append_chain(
        kind="call",
        task_id=info.id,
        actor_id=caller.id,
        target_id=plan["node_id"],
        intent=kind,
        status="queued",
        summary=prompt,
        detail={"runtime": runtime, "agent_id": agent_id, "local": bool(plan["local"])},
    )
    return {
        "id": info.id,
        "caller": caller.id,
        "node_id": plan["node_id"],
        "local": bool(plan["local"]),
        "runtime": runtime,
        "agent_id": agent_id,
        "kind": kind,
        "status": info.status,
    }


async def call_peer_from_token(
    token: str,
    *,
    target: str,
    runtime: str,
    agent_id: str,
    prompt: str,
    task_manager: Any,
    workspace_id: str = "",
) -> dict[str, Any]:
    rec = await authenticate(token)
    if rec is None:
        raise FleetAuthError("invalid node token")
    return await call_peer(
        caller_id=rec.id,
        target=target,
        runtime=runtime,
        agent_id=agent_id,
        prompt=prompt,
        task_manager=task_manager,
        workspace_id=workspace_id,
    )


async def call_peer_as_cloud(
    *,
    target: str,
    runtime: str,
    agent_id: str,
    prompt: str,
    task_manager: Any,
    workspace_id: str = "",
) -> dict[str, Any]:
    """云端协调器自己作为调用方，使用已绑定的本机节点。"""
    nodes = await list_nodes(workspace_id)
    local = [n for n in nodes if n.get("bound") and n.get("mode") == "local"]
    if not local:
        raise FleetError("云端还没有绑定本机智能体")
    if len(local) > 1:
        raise FleetError("云端本机节点不唯一")
    return await call_peer(
        caller_id=local[0]["id"],
        target=target,
        runtime=runtime,
        agent_id=agent_id,
        prompt=prompt,
        task_manager=task_manager,
        workspace_id=workspace_id or local[0].get("workspace_id") or "",
    )


async def _pick_online_agent(runtime: str, agent_id: str, workspace_id: str = "") -> str:
    nodes = await list_nodes(workspace_id)
    candidates = [
        n
        for n in nodes
        if n["online"] and n["bound"] and _has_agent(n["agents"], runtime, agent_id)
        and _visible_to_workspace(n, workspace_id)
        and (not workspace_id or not n.get("workspace_id") or n["workspace_id"] == workspace_id)
    ]
    if not candidates:
        return ""
    candidates.sort(key=lambda n: (n["running_count"], n["queued_count"], n["id"]))
    return candidates[0]["id"]


async def scan_host(registry: Any) -> dict[str, Any]:
    """扫描协调器本机上的 OpenClaw / Hermes 智能体。"""
    started = time.perf_counter()
    raw = await registry.list_agents(force_refresh=True)
    agents = _clean_agents(
        [
            item if isinstance(item, dict) else item.model_dump()
            for item in raw
        ]
    )
    hostname = socket.gethostname()
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "fleet scan host=%s node=%s agents=%d elapsed_ms=%.0f",
        hostname,
        slug_node_id(hostname),
        len(agents),
        elapsed_ms,
    )
    return {
        "node_id": slug_node_id(hostname),
        "hostname": hostname,
        "platform": platform.system().lower(),
        "name": hostname.split(".")[0] or hostname,
        "agents": agents,
    }


async def bind_selection(
    *,
    node_id: str,
    name: str,
    picks: list[dict[str, Any]],
    registry: Any,
    workspace_id: str = "",
) -> dict[str, Any]:
    """把扫描到的智能体绑定到设备。本机尚无记录时，用本次扫描结果建成本地节点。"""
    requested = (node_id or "").strip().lower()
    rec = await get_node(requested) if requested else None
    remote = rec is not None and bool(rec.token_hash) and rec.mode != "local"
    if (
        rec is not None
        and rec.bound
        and workspace_id
        and (rec.workspace_id or "")
        and rec.workspace_id != workspace_id
    ):
        raise FleetError("该终端已属于其他团队")
    if remote:
        allowed = _load_agents(rec.seen_json)
        if not allowed:
            raise FleetError("这台设备还没有上报扫描结果")
        hostname = rec.hostname or ""
        plat = rec.platform or ""
        mode = rec.mode or "plugin"
        node_id = rec.id
    else:
        scan = await scan_host(registry)
        node_id = requested or scan["node_id"]
        if rec is None and requested and requested != scan["node_id"]:
            raise FleetError(f"设备不存在: {requested}")
        if requested and requested != scan["node_id"] and (rec is None or rec.mode == "local"):
            raise FleetError("本机扫描结果与设备标识不一致")
        if not requested:
            node_id = scan["node_id"]
        allowed = scan["agents"]
        hostname = scan["hostname"]
        plat = scan["platform"]
        mode = "local"
        name = name or scan["name"]
    if not NODE_ID_RE.match(node_id):
        raise FleetError("invalid node id")

    allowed_map = {(a["runtime"], a["id"]): a for a in allowed}
    selected: list[dict[str, str]] = []
    for pick in _clean_agents(picks):
        src = allowed_map.get((pick["runtime"], pick["id"]))
        if src:
            selected.append(src)
    if not selected:
        raise FleetError("没有可绑定的智能体，请先扫描并勾选")

    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(FleetNodeRecord, node_id)
        if row is None:
            row = FleetNodeRecord(id=node_id, name=name or node_id)
            session.add(row)
        row.name = name or row.name or node_id
        row.bound = 1
        if workspace_id:
            row.workspace_id = workspace_id
        row.agents_json = _dump_agents(selected)
        row.seen_json = _dump_agents(allowed)
        row.runtimes_json = _dump_runtimes([a["runtime"] for a in selected])
        row.hostname = hostname or row.hostname or ""
        row.platform = plat or row.platform or ""
        if not remote:
            row.mode = "local"
            row.webhook_url = ""
        else:
            row.mode = mode
        row.last_seen = _now()
        row.updated_at = _now()
        await session.commit()
        await session.refresh(row)
        info = to_info(row)
    logger.info(
        "fleet bind node=%s mode=%s workspace=%s agents=%d",
        node_id,
        info["mode"],
        info.get("workspace_id") or "-",
        len(selected),
    )
    return info


async def unbind_node(node_id: str) -> dict[str, Any]:
    node_id = (node_id or "").strip().lower()
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(FleetNodeRecord, node_id)
        if row is None:
            raise FleetError(f"设备不存在: {node_id}")
        if row.mode == "local" and not row.token_hash:
            await session.delete(row)
            await session.commit()
            logger.info("fleet unbound local node=%s", node_id)
            return {"id": node_id, "removed": True, "bound": False}
        row.bound = 0
        row.workspace_id = ""
        row.agents_json = "[]"
        seen = _load_agents(row.seen_json)
        row.runtimes_json = _dump_runtimes([a["runtime"] for a in seen])
        row.updated_at = _now()
        await session.commit()
        await session.refresh(row)
        info = to_info(row)
    logger.info("fleet unbound node=%s", node_id)
    return info


async def claim(token: str) -> dict[str, Any] | None:
    rec = await authenticate(token)
    if not rec:
        raise FleetAuthError("invalid node token")
    if not rec.bound:
        logger.info("fleet claim skipped unbound node=%s", rec.id)
        return None
    async with _claim_lock:
        factory = get_session_factory()
        async with factory() as session:
            q = (
                select(TaskRecord)
                .where(TaskRecord.node_id == rec.id)
                .where(TaskRecord.status == "queued")
                .order_by(TaskRecord.created_at)
                .limit(1)
            )
            task = (await session.execute(q)).scalar_one_or_none()
            if task is None:
                return None
            task.status = "running"
            task.updated_at = _now()
            session.add(
                TaskEventRecord(
                    task_id=task.id,
                    event_type="status",
                    content=f"claimed by {rec.id}",
                    event_json="{}",
                )
            )
            await session.commit()
            payload = {
                "id": task.id,
                "agent_id": task.agent_id,
                "runtime": task.runtime,
                "prompt": task.prompt,
                "system_prompt": task.system_prompt or "",
                "session_id": task.session_id or "",
            }
    logger.info(
        "fleet claimed task=%s node=%s runtime=%s agent=%s",
        payload["id"],
        rec.id,
        payload["runtime"],
        payload["agent_id"],
    )
    from app.core.chain import append_chain

    await append_chain(
        kind="claim",
        task_id=payload["id"],
        actor_id=rec.id,
        target_id=rec.id,
        status="running",
        summary=payload["prompt"],
        detail={"runtime": payload["runtime"], "agent_id": payload["agent_id"]},
    )
    return payload


async def finish(
    token: str,
    task_id: str,
    *,
    status: str,
    output: str = "",
    error: str = "",
    session_id: str = "",
    duration_ms: int = 0,
) -> dict[str, Any]:
    rec = await authenticate(token)
    if rec is None:
        raise FleetAuthError("invalid node token")
    if status not in ("completed", "failed", "cancelled", "timeout"):
        raise FleetError("status must be completed|failed|cancelled|timeout")
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(TaskRecord, task_id)
        if task is None:
            raise FleetError(f"task not found: {task_id}")
        if task.node_id != rec.id:
            raise FleetAuthError("task belongs to another node")
        if task.status not in ("queued", "running"):
            raise FleetError(f"task already finished: {task.status}")
        task.status = status
        task.output = output or ""
        task.error = error or ""
        if session_id:
            task.session_id = session_id
        task.duration_ms = int(duration_ms or 0)
        task.updated_at = _now()
        session.add(
            TaskEventRecord(
                task_id=task.id,
                event_type="result",
                content=status,
                event_json=json.dumps({"node_id": rec.id}, ensure_ascii=False),
            )
        )
        await session.commit()
        result = {
            "id": task.id,
            "node_id": task.node_id,
            "status": task.status,
            "agent_id": task.agent_id,
            "runtime": task.runtime,
            "prompt": task.prompt or "",
            "output": task.output or "",
            "error": task.error or "",
            "session_id": task.session_id or "",
            "workspace_id": task.workspace_id or "",
            "system_prompt": task.system_prompt or "",
            "duration_ms": int(task.duration_ms or 0),
        }
    logger.info(
        "fleet finished task=%s node=%s status=%s duration_ms=%s",
        task_id,
        rec.id,
        status,
        duration_ms,
    )
    from app.core.chain import append_chain

    await append_chain(
        kind="finish",
        task_id=task_id,
        actor_id=rec.id,
        target_id=rec.id,
        status=status,
        summary=output or error,
        detail={"duration_ms": int(duration_ms or 0)},
    )
    return result


async def _mark_running(task_id: str, node_id: str) -> None:
    if not task_id:
        return
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(TaskRecord, task_id)
        if row is None or row.node_id != node_id or row.status != "queued":
            return
        row.status = "running"
        row.updated_at = _now()
        await session.commit()


async def notify_connector(node_id: str, task: dict[str, Any]) -> bool:
    """webhook 模式按飞书签名把任务推到设备。失败则保留 queued，插件仍可领取。"""
    from app.core.chain import append_chain

    task_id = str(task.get("id") or "")
    summary = str(task.get("prompt") or "")
    rec = await get_node(node_id)
    if rec is None or rec.mode != "webhook" or not (rec.webhook_url or "").strip():
        logger.info("fleet plugin queued node=%s task=%s", node_id, task_id or "-")
        await append_chain(
            kind="webhook",
            task_id=task_id,
            target_id=node_id,
            status="queued",
            summary=summary,
        )
        return False
    secret = get_settings().fleet_enroll_token
    if not secret:
        logger.error("fleet webhook skipped, enroll token empty node=%s", node_id)
        await append_chain(
            kind="webhook",
            task_id=task_id,
            target_id=node_id,
            status="failed",
            summary=summary,
        )
        return False
    body = json.dumps({"type": "task.dispatch", "task": task}, ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Fleet-Timestamp": timestamp,
        "X-Fleet-Signature": sign_body(secret, timestamp, body),
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(rec.webhook_url, content=body, headers=headers)
        ok = 200 <= resp.status_code < 300
        if ok:
            await _mark_running(task_id, node_id)
            logger.info(
                "fleet webhook pushed node=%s task=%s status=%s",
                node_id,
                task_id or "-",
                resp.status_code,
            )
        else:
            logger.error(
                "fleet webhook rejected node=%s task=%s status=%s",
                node_id,
                task_id or "-",
                resp.status_code,
            )
        await append_chain(
            kind="webhook",
            task_id=task_id,
            target_id=node_id,
            status="pushed" if ok else "failed",
            summary=summary,
            detail={"http_status": resp.status_code},
        )
        return ok
    except Exception as e:
        logger.error("fleet webhook failed node=%s task=%s err=%s", node_id, task_id or "-", e)
        await append_chain(
            kind="webhook",
            task_id=task_id,
            target_id=node_id,
            status="failed",
            summary=summary,
        )
        return False


def link_path():
    return data_dir() / "fleet_link.json"


def link_token_path():
    return data_dir() / "fleet_link.token"


def normalize_cloud_url(url: str) -> str:
    text = (url or "").strip().rstrip("/")
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.username or parsed.password:
        raise FleetError("云端地址不要带账号密码")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FleetError("云端地址需要是 http 或 https")
    return text


def is_self_cloud(url: str) -> bool:
    if not (url or "").strip():
        return True
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return False
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return port == int(get_settings().port)


def displayed_cloud_url(env_value: str) -> str:
    """已有链接文件时以文件为准，空字符串也不回落到环境变量。"""
    path = link_path()
    if path.is_file():
        saved = _read_link_file()
        return str(saved.get("cloud_url") or "")
    return (env_value or "").strip()


def _read_link_file() -> dict[str, Any]:
    path = link_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("fleet link unreadable path=%s err=%s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _save_link(data: dict[str, Any]) -> None:
    path = link_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in data.items() if k != "node_token"}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(public, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info(
        "fleet link saved state=%s node=%s peers=%d",
        public.get("state") or "-",
        public.get("node_id") or "-",
        len(public.get("peers") or []),
    )


def _write_link_token(token: str) -> None:
    path = link_token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        logger.warning("fleet link token chmod failed path=%s", path)


def _empty_link(cloud_url: str, *, enroll_configured: bool) -> dict[str, Any]:
    return {
        "cloud_url": cloud_url,
        "state": "",
        "detail": "",
        "at": "",
        "node_id": "",
        "bound": False,
        "local_cloud": is_self_cloud(cloud_url),
        "agents": [],
        "capabilities": [],
        "peers": [],
        "enroll_configured": enroll_configured,
    }


def _link_view(saved: dict[str, Any], *, enroll_configured: bool) -> dict[str, Any]:
    cloud_url = str(saved.get("cloud_url") or "")
    return {
        "cloud_url": cloud_url,
        "state": str(saved.get("state") or ""),
        "detail": str(saved.get("detail") or ""),
        "at": str(saved.get("at") or ""),
        "node_id": str(saved.get("node_id") or ""),
        "bound": bool(saved.get("bound")),
        "local_cloud": is_self_cloud(cloud_url),
        "agents": saved.get("agents") if isinstance(saved.get("agents"), list) else [],
        "capabilities": saved.get("capabilities") if isinstance(saved.get("capabilities"), list) else [],
        "peers": saved.get("peers") if isinstance(saved.get("peers"), list) else [],
        "enroll_configured": enroll_configured,
    }


async def link_status(workspace_id: str = "", env_cloud_url: str = "") -> dict[str, Any]:
    enroll_configured = bool(get_settings().fleet_enroll_token)
    if not link_path().is_file():
        return _empty_link(displayed_cloud_url(env_cloud_url), enroll_configured=enroll_configured)
    saved = _read_link_file()
    view = _link_view(saved, enroll_configured=enroll_configured)
    if view["state"] != "ok" or not view["node_id"]:
        return view
    if view["local_cloud"]:
        view["peers"] = await peer_catalog(exclude=view["node_id"], workspace_id=workspace_id)
        return view
    refreshed = await _pull_remote_peers(view["cloud_url"], exclude=view["node_id"])
    if refreshed is not None:
        view["peers"] = refreshed
        saved["peers"] = refreshed
        _save_link(saved)
    return view


async def _pull_remote_peers(cloud_url: str, exclude: str = "") -> list[dict[str, Any]] | None:
    path = link_token_path()
    token = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    if token:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    cloud_url.rstrip("/") + "/api/fleet/catalog",
                    headers={"X-Node-Token": token},
                )
        except Exception as exc:
            logger.warning("fleet catalog refresh failed cloud=%s err=%s", cloud_url, exc)
            resp = None
        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
            except json.JSONDecodeError:
                data = None
            peers = data.get("peers") if isinstance(data, dict) else None
            if isinstance(peers, list):
                logger.info("fleet catalog refreshed cloud=%s peers=%d", cloud_url, len(peers))
                return peers
    try:
        listed = await _get_cloud(cloud_url, "/api/fleet/nodes")
    except FleetError as exc:
        logger.warning("fleet nodes refresh failed cloud=%s err=%s", cloud_url, exc)
        return None
    if not isinstance(listed, list):
        return None
    peers = peers_from_nodes(listed, exclude=exclude)
    logger.info("fleet nodes refreshed cloud=%s peers=%d", cloud_url, len(peers))
    return peers


def peers_from_nodes(nodes: list[Any], exclude: str = "") -> list[dict[str, Any]]:
    """把云端设备列表收成其他端的资源与能力。旧协调器没有 capabilities 字段。"""
    peers: list[dict[str, Any]] = []
    for item in nodes:
        if not isinstance(item, dict) or not item.get("bound"):
            continue
        node_id = str(item.get("id") or "")
        if exclude and node_id == exclude:
            continue
        agents = _clean_agents(item.get("agents"))
        peers.append(
            {
                "id": node_id,
                "name": str(item.get("name") or node_id),
                "hostname": str(item.get("hostname") or ""),
                "platform": str(item.get("platform") or ""),
                "mode": str(item.get("mode") or "plugin"),
                "online": bool(item.get("online")),
                "runtimes": item.get("runtimes") if isinstance(item.get("runtimes"), list) else [],
                "agents": agents,
                "capabilities": item.get("capabilities")
                if isinstance(item.get("capabilities"), list) and item.get("capabilities")
                else capabilities_of(agents),
            }
        )
    return peers


async def _request_cloud(
    method: str,
    cloud_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    legacy_on_404: bool = False,
) -> Any:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, cloud_url.rstrip("/") + path, json=payload)
    except Exception as exc:
        logger.error("fleet link %s failed path=%s err=%s", method, path, exc)
        raise FleetError(f"连不上云端：{exc}") from exc
    if legacy_on_404 and resp.status_code in (404, 405):
        logger.info("fleet link legacy path missing path=%s status=%s", path, resp.status_code)
        raise FleetLegacyCloud(path)
    if resp.status_code == 401:
        detail = _http_detail(resp) or "云端拒绝了注册令牌"
        raise FleetAuthError(detail)
    if resp.status_code >= 400:
        raise FleetError(_http_detail(resp) or f"云端返回 {resp.status_code}")
    if resp.status_code == 204 or not resp.content:
        return {}
    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise FleetError("云端返回的不是 JSON") from exc
    if not isinstance(data, (dict, list)):
        raise FleetError("云端返回的不是 JSON")
    return data


async def _post_cloud(
    cloud_url: str,
    path: str,
    payload: dict[str, Any],
    *,
    legacy_on_404: bool = False,
) -> dict[str, Any]:
    data = await _request_cloud(
        "POST", cloud_url, path, payload, legacy_on_404=legacy_on_404
    )
    if not isinstance(data, dict):
        raise FleetError("云端返回的不是 JSON")
    return data


async def _get_cloud(cloud_url: str, path: str) -> Any:
    return await _request_cloud("GET", cloud_url, path)


async def _link_legacy_cloud(
    url: str,
    secret: str,
    identity: dict[str, Any],
    workspace_id: str,
) -> dict[str, Any]:
    """旧云端只有注册和设备列表。注册后立刻绑定，再取回其他端。"""
    enrolled = await _post_cloud(
        url,
        "/api/fleet/enroll",
        {
            "enroll_token": secret,
            "node_id": identity["node_id"],
            "name": identity["name"],
            "hostname": identity["hostname"],
            "platform": identity["platform"],
            "agents": identity["agents"],
            "mode": "plugin",
        },
    )
    remote_token = str(enrolled.get("node_token") or "")
    if remote_token:
        _write_link_token(remote_token)
    bound = await _post_cloud(
        url,
        "/api/fleet/bind",
        {
            "node_id": identity["node_id"],
            "name": identity["name"],
            "workspace_id": workspace_id,
            "agents": identity["agents"],
        },
    )
    listed = await _get_cloud(url, "/api/fleet/nodes")
    nodes = listed if isinstance(listed, list) else []
    node_id = str(bound.get("id") or enrolled.get("node_id") or identity["node_id"])
    agents = bound.get("agents") if isinstance(bound.get("agents"), list) else identity["agents"]
    peers = peers_from_nodes(nodes, exclude=node_id)
    logger.info(
        "fleet link legacy bound cloud=%s node=%s agents=%d peers=%d",
        url,
        node_id,
        len(agents),
        len(peers),
    )
    return {
        "node_id": node_id,
        "id": node_id,
        "agents": agents,
        "capabilities": capabilities_of(_clean_agents(agents)),
        "peers": peers,
    }


def _http_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except json.JSONDecodeError:
        return (resp.text or "")[:200]
    detail = data.get("detail") if isinstance(data, dict) else ""
    return str(detail or "")[:200]


async def open_link(
    *,
    cloud_url: str,
    workspace_id: str,
    registry: Any,
    enroll_token: str,
) -> dict[str, Any]:
    """把本机扫到的智能体绑定到云端，并取回其他端的资源与能力。"""
    started = time.perf_counter()
    url = normalize_cloud_url(cloud_url)
    previous = _read_link_file() if link_path().is_file() else {}
    same_cloud = str(previous.get("cloud_url") or "") == url
    local = is_self_cloud(url)
    secret = enroll_token
    if not secret:
        if not local:
            raise FleetAuthError("fleet enroll token is not configured")
        secret = secrets.token_urlsafe(32)
        logger.info("fleet link self handshake without enroll token")
    scan = await scan_host(registry)
    if not scan["agents"]:
        raise FleetError("本机没有可绑定的智能体")
    nonce = secrets.token_hex(16)
    identity = {
        "node_id": scan["node_id"],
        "name": scan["name"],
        "hostname": scan["hostname"],
        "platform": scan["platform"],
        "agents": scan["agents"],
        "nonce": nonce,
    }
    try:
        if local:
            offered = await begin_handshake(
                enroll_token=secret,
                expected_token=secret,
                local_self=True,
                **identity,
            )
            material = f"{nonce}.{offered['challenge']}"
            if not _eq(offered.get("cloud_proof") or "", handshake_proof(secret, "cloud", material)):
                raise FleetError("云端握手证明不一致")
            accepted = await complete_handshake(
                enroll_token=secret,
                expected_token=secret,
                node_id=scan["node_id"],
                proof=handshake_proof(secret, "client", offered["challenge"]),
                workspace_id=workspace_id,
            )
        else:
            try:
                offered = await _post_cloud(
                    url,
                    "/api/fleet/handshake",
                    {**identity, "enroll_token": secret, "mode": "plugin"},
                    legacy_on_404=True,
                )
            except FleetLegacyCloud:
                accepted = await _link_legacy_cloud(url, secret, identity, workspace_id)
            else:
                challenge = str(offered.get("challenge") or "")
                material = f"{nonce}.{challenge}"
                if not _eq(str(offered.get("cloud_proof") or ""), handshake_proof(secret, "cloud", material)):
                    logger.warning("fleet link rejected cloud=%s reason=bad-cloud-proof", url)
                    raise FleetError("云端握手证明不一致")
                accepted = await _post_cloud(
                    url,
                    "/api/fleet/handshake/accept",
                    {
                        "enroll_token": secret,
                        "node_id": scan["node_id"],
                        "proof": handshake_proof(secret, "client", challenge),
                        "workspace_id": workspace_id,
                    },
                )
                remote_token = str(accepted.get("node_token") or "")
                if remote_token:
                    _write_link_token(remote_token)
        view = _link_view(
            {
                "cloud_url": url,
                "state": "ok",
                "detail": "",
                "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "node_id": accepted.get("node_id") or accepted.get("id") or scan["node_id"],
                "bound": True,
                "agents": accepted.get("agents") or [],
                "capabilities": accepted.get("capabilities") or capabilities_of(accepted.get("agents") or []),
                "peers": accepted.get("peers") or [],
            },
            enroll_configured=bool(enroll_token),
        )
    except (FleetError, FleetAuthError) as exc:
        failed = _link_view(
            {
                "cloud_url": url,
                "state": "failed",
                "detail": str(exc),
                "at": str(previous.get("at") or ""),
                "node_id": str(previous.get("node_id") or "") if same_cloud else "",
                "bound": bool(previous.get("bound")) if same_cloud else False,
                "agents": previous.get("agents") if same_cloud else [],
                "capabilities": previous.get("capabilities") if same_cloud else [],
                "peers": previous.get("peers") if same_cloud else [],
            },
            enroll_configured=bool(enroll_token),
        )
        _save_link(failed)
        logger.warning("fleet link failed cloud=%s err=%s", url or "self", exc)
        raise
    _save_link(view)
    logger.info(
        "fleet link opened cloud=%s node=%s agents=%d peers=%d elapsed_ms=%.0f",
        url or "self",
        view["node_id"],
        len(view["agents"]),
        len(view["peers"]),
        (time.perf_counter() - started) * 1000,
    )
    return view
