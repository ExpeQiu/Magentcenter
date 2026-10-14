"""任务、执行、投递三套状态，以及 v1 兼容映射。

内部状态和对外旧状态分开。无法用旧枚举表达的恢复细节走附加字段。
"""

from __future__ import annotations

TASK_STATES = frozenset(
    {"queued", "running", "succeeded", "failed", "cancelled", "needs_attention"}
)
EXECUTION_STATES = frozenset(
    {
        "accepted",
        "starting",
        "running",
        "succeeded",
        "failed",
        "stopped",
        "interrupted",
        "unknown",
    }
)
DELIVERY_STATES = frozenset({"pending", "acknowledged", "retry_wait", "blocked"})
TERMINAL_EXECUTION = frozenset({"succeeded", "failed", "stopped"})
V1_TASK_STATUS = {
    "queued": "queued",
    "running": "running",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
    "needs_attention": "running",
    "completed": "completed",
    "timeout": "timeout",
}
PROTOCOL_VERSION = 2
MAX_DELEGATION_DEPTH = 3


class ProtocolError(ValueError):
    pass


def accept_protocol(version: int) -> None:
    """未知主协议版本拒绝派单。小版本差异留给能力协商。"""
    try:
        major = int(version)
    except (TypeError, ValueError) as exc:
        raise ProtocolError("protocol_version required") from exc
    if major != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol {version}")


def task_status_v1(status: str) -> str:
    return V1_TASK_STATUS.get(status or "", status or "queued")


def execution_status_for_v1(v1_status: str) -> str:
    return {
        "queued": "accepted",
        "running": "running",
        "completed": "succeeded",
        "failed": "failed",
        "cancelled": "stopped",
        "timeout": "interrupted",
    }.get(v1_status, "unknown")


def reduce_outcome(task: str, execution: str, event: str) -> dict[str, str]:
    """取消和完成交错时保留已经发生的事实，不把终态改回去。"""
    task = task or "running"
    execution = execution or "running"
    if event == "completed":
        if execution == "stopped" or task == "cancelled":
            return {
                "task": "cancelled",
                "execution": "stopped",
                "outcome": "kept_stopped",
            }
        return {"task": "succeeded", "execution": "succeeded", "outcome": "finished"}
    if event == "cancel_requested":
        if execution in {"succeeded", "failed"} or task in {"succeeded", "failed", "cancelled"}:
            kept_task = "succeeded" if execution == "succeeded" or task == "succeeded" else task
            kept_exec = execution if execution in TERMINAL_EXECUTION else "succeeded"
            return {
                "task": kept_task,
                "execution": kept_exec,
                "outcome": "already_finished",
            }
        return {"task": task, "execution": execution, "outcome": "cancel_requested"}
    if event == "cancel_ack":
        if execution in TERMINAL_EXECUTION:
            return reduce_outcome(task, execution, "cancel_requested")
        return {"task": task, "execution": "running", "outcome": "stopping"}
    if event == "stopped":
        if execution == "succeeded" or task == "succeeded":
            return {
                "task": "succeeded",
                "execution": "succeeded",
                "outcome": "already_finished",
            }
        return {"task": "cancelled", "execution": "stopped", "outcome": "stopped"}
    if event == "unknown":
        return {"task": "needs_attention", "execution": "unknown", "outcome": "needs_attention"}
    raise ValueError(f"unknown outcome event: {event}")


def cancel_phase(task_status: str, execution_status: str, requested: bool) -> str:
    if execution_status == "stopped" or task_status in {"cancelled"}:
        return "stopped"
    if execution_status == "running" and requested:
        return "stopping"
    if requested:
        return "requested"
    return ""


def ancestor_has_cycle(ancestors: list[str], next_node: str) -> bool:
    return next_node in ancestors


def depth_allowed(depth: int, limit: int = MAX_DELEGATION_DEPTH) -> bool:
    return 1 <= depth <= limit
