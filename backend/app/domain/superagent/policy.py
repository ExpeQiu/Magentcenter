"""Policy：准入 Gate、accept 模式、策略版本。"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.paths import data_dir

logger = logging.getLogger(__name__)

AcceptMode = Literal["off", "observe", "auto"]
GateStrength = Literal["deny", "explicit", "inferred"]


@dataclass
class PolicyState:
    version: int = 1
    mode: AcceptMode = "observe"
    allowed_sources: list[str] = field(
        default_factory=lambda: [
            "web",
            "client",
            "device",
            "conversation",
            "voice",
            "desktop",
            "feishu",
        ]
    )
    # 空列表 = 不按 actor 限制；非空则 actor 须命中
    allowed_actors: list[str] = field(default_factory=list)


def _path() -> Path:
    return data_dir() / "superagent_policy.json"


def load_policy() -> PolicyState:
    path = _path()
    if not path.is_file():
        return PolicyState()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("policy load failed err=%s", exc)
        return PolicyState()
    mode = str(raw.get("mode") or "observe")
    if mode not in ("off", "observe", "auto"):
        mode = "observe"
    return PolicyState(
        version=max(1, int(raw.get("version") or 1)),
        mode=mode,  # type: ignore[arg-type]
        allowed_sources=list(raw.get("allowed_sources") or PolicyState().allowed_sources),
        allowed_actors=list(raw.get("allowed_actors") or []),
    )


def save_policy(state: PolicyState) -> PolicyState:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": int(state.version),
        "mode": state.mode,
        "allowed_sources": list(state.allowed_sources),
        "allowed_actors": list(state.allowed_actors),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "policy saved version=%s mode=%s sources=%d",
        state.version,
        state.mode,
        len(state.allowed_sources),
    )
    return state


def bump_policy(**updates) -> PolicyState:
    state = load_policy()
    if "mode" in updates and updates["mode"] in ("off", "observe", "auto"):
        state.mode = updates["mode"]
    if "allowed_sources" in updates and isinstance(updates["allowed_sources"], list):
        state.allowed_sources = [str(s) for s in updates["allowed_sources"]]
    if "allowed_actors" in updates and isinstance(updates["allowed_actors"], list):
        state.allowed_actors = [str(s) for s in updates["allowed_actors"]]
    state.version = int(state.version) + 1
    return save_policy(state)


@dataclass
class GateDecision:
    strength: GateStrength
    reason: str
    policy_version: int
    would_accept: bool = False


def gate(
    *,
    source: str,
    actor_id: str = "",
    addressed: bool = True,
    policy: PolicyState | None = None,
) -> GateDecision:
    """
    addressed=True：用户明确向超级AI 提需求（默认 turn 路径）。
    addressed=False：推断/主动候选，受 mode 约束。
    """
    pol = policy or load_policy()
    source = (source or "").strip() or "web"
    actor = (actor_id or "").strip()
    if source not in pol.allowed_sources:
        return GateDecision(
            strength="deny",
            reason=f"source_not_allowed:{source}",
            policy_version=pol.version,
        )
    if pol.allowed_actors and actor and actor not in pol.allowed_actors:
        return GateDecision(
            strength="deny",
            reason="actor_not_allowed",
            policy_version=pol.version,
        )
    if addressed:
        return GateDecision(
            strength="explicit",
            reason="addressed",
            policy_version=pol.version,
            would_accept=True,
        )
    # 推断路径
    if pol.mode == "off":
        return GateDecision(
            strength="deny",
            reason="mode_off",
            policy_version=pol.version,
        )
    if pol.mode == "observe":
        return GateDecision(
            strength="inferred",
            reason="would_accept",
            policy_version=pol.version,
            would_accept=False,
        )
    return GateDecision(
        strength="inferred",
        reason="auto_accept",
        policy_version=pol.version,
        would_accept=True,
    )


def allows_dispatch(decision: GateDecision) -> bool:
    if decision.strength == "deny":
        return False
    if decision.strength == "explicit":
        return True
    return bool(decision.would_accept)
