"""CLI 输出格式化。"""

from __future__ import annotations

import json
from typing import Any


def print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    """columns: [(key, header), ...]"""
    if not rows:
        print("(empty)")
        return
    widths = [
        max(len(header), *(len(str(row.get(key, ""))) for row in rows))
        for key, header in columns
    ]
    header_line = "  ".join(header.ljust(w) for (_, header), w in zip(columns, widths))
    print(header_line)
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(
            "  ".join(
                str(row.get(key, "")).ljust(w) for (key, _), w in zip(columns, widths)
            )
        )


def format_task_row(task: dict[str, Any]) -> dict[str, str]:
    prompt = task.get("prompt", "")
    if len(prompt) > 40:
        prompt = prompt[:37] + "..."
    return {
        "id": task.get("id", "")[:8],
        "runtime": task.get("runtime", "openclaw"),
        "agent": task.get("agent_id", ""),
        "status": task.get("status", ""),
        "prompt": prompt,
    }


def format_agent_row(agent: dict[str, Any]) -> dict[str, str]:
    return {
        "runtime": agent.get("runtime", "openclaw"),
        "id": agent.get("id", ""),
        "name": agent.get("name", ""),
        "model": agent.get("model", ""),
        "default": "yes" if agent.get("is_default") else "",
    }
