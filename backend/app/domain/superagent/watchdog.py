"""语义 Watchdog：只提醒 / 建议暂停，不扩权、不改需求。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WatchdogAdvice:
    kind: str  # remind | suggest_pause | none
    summary: str = ""


def inspect_attempts(*, fail_streak: int, same_error_count: int) -> WatchdogAdvice:
    if fail_streak >= 3 or same_error_count >= 3:
        logger.info(
            "watchdog suggest_pause fail_streak=%s same_error=%s",
            fail_streak,
            same_error_count,
        )
        return WatchdogAdvice(
            kind="suggest_pause",
            summary="反复失败，建议暂停并人工核实，不自动扩权或重做。",
        )
    if fail_streak >= 1:
        return WatchdogAdvice(kind="remind", summary="最近一次执行失败，可检查输入或节点状态。")
    return WatchdogAdvice(kind="none")
