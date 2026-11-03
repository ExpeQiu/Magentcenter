"""常驻 Router：只输出结构化建议，不持工具。"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

RouteAction = Literal[
    "reply",
    "accept",
    "attach",
    "revise",
    "status",
    "stop",
    "ignore",
    "ask_target",
]


class RouteSuggestion(BaseModel):
    action: RouteAction
    reason: str = ""
    work_item_id: str = ""
    reply: str = ""
    evidence: list[str] = Field(default_factory=list)


async def evaluate(
    *,
    text: str,
    work_item_id: str = "",
    roster_hits: list[str] | None = None,
    policy_version: int = 1,
) -> RouteSuggestion:
    """规则版 Router（Mock / 无模型时）。模型路径由 workers 注入。"""
    text = (text or "").strip()
    lower = text.lower()
    roster_hits = roster_hits or []
    if any(k in text for k in ("停止", "取消任务", "别做了")) or "stop" in lower:
        return RouteSuggestion(
            action="stop",
            reason="user_stop",
            work_item_id=work_item_id,
            evidence=["keyword:stop"],
        )
    if work_item_id and any(k in text for k in ("改成", "修改", "再加上")):
        return RouteSuggestion(
            action="revise",
            reason="followup_revise",
            work_item_id=work_item_id,
            evidence=["keyword:revise"],
        )
    if roster_hits:
        return RouteSuggestion(
            action="accept",
            reason="roster_dispatch",
            work_item_id=work_item_id,
            evidence=[f"roster:{h}" for h in roster_hits[:3]],
        )
    if len(text) < 2:
        return RouteSuggestion(action="ignore", reason="empty")
    logger.info(
        "router evaluate action=reply policy_version=%s text_len=%s",
        policy_version,
        len(text),
    )
    return RouteSuggestion(action="reply", reason="chat", reply="")


def controller_accept(suggestion: RouteSuggestion, *, expected_policy: int, actual_policy: int) -> bool:
    """Controller：策略版本过期则作废。"""
    if expected_policy != actual_policy:
        logger.info(
            "router decision stale expected_policy=%s actual=%s action=%s",
            expected_policy,
            actual_policy,
            suggestion.action,
        )
        return False
    return True
