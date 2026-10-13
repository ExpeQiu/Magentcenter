"""CLI 输出：人类表格走 stdout，日志与说明走 stderr，JSON 契约可落盘。"""

from __future__ import annotations

import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.cli import __version__

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_DATA = 2
EXIT_UPSTREAM = 3
EXIT_INTERRUPTED = 130

EXIT_CODES = {
    "0": "success",
    "1": "error",
    "2": "no_data",
    "3": "upstream",
    "130": "interrupted",
}


def note(message: str) -> None:
    print(message, file=sys.stderr)


def resolve_format(args: Any) -> tuple[str, bool]:
    """返回 (format, raw_json)。

    单独的 --json 保持历史原始载荷，供已有脚本解析。
    --format json 输出带 module / data_source / items 的契约。
    """
    chosen = getattr(args, "format", None)
    if chosen:
        return chosen, False
    if getattr(args, "json", False):
        return "json", True
    return "table", False


def envelope(
    module: str,
    payload: Any,
    *,
    data_source: str,
    request_id: str,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
        count = payload.get("total", len(items))
        meta = {key: value for key, value in payload.items() if key != "items"}
    elif isinstance(payload, list):
        items = payload
        count = len(items)
    else:
        items = payload
        count = 0 if payload is None else 1
    body: dict[str, Any] = {
        "module": module,
        "version": __version__,
        "data_source": data_source,
        "fetched_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "request_id": request_id,
        "count": count,
        "items": items,
    }
    if meta:
        body["meta"] = meta
    if next_actions:
        body["next"] = next_actions
    return body


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _scalar_row(data: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (dict, list)):
            continue
        row[key] = "" if value is None else value
    return row


def render_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "(empty)"
    widths = [
        max(len(header), *(len(str(row.get(key, ""))) for row in rows))
        for key, header in columns
    ]
    lines = [
        "  ".join(header.ljust(width) for (_, header), width in zip(columns, widths)),
        "  ".join("-" * width for width in widths),
    ]
    for row in rows:
        lines.append(
            "  ".join(str(row.get(key, "")).ljust(width) for (key, _), width in zip(columns, widths))
        )
    return "\n".join(lines)


def render_csv(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([header for _, header in columns])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in columns])
    return buffer.getvalue().rstrip("\n")


def render_markdown(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    headers = [header for _, header in columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(row.get(key, "")).replace("|", "\\|") for key, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_record(data: dict[str, Any]) -> str:
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, list):
            shown = len(value)
            lines.append(f"{key}={shown}")
            continue
        if isinstance(value, dict):
            lines.append(f"{key}={len(value)}")
            continue
        text = str(value)
        if len(text) > 160:
            text = text[:157] + "..."
        lines.append(f"{key}={text}")
    return "\n".join(lines) if lines else "(empty)"


def _columns_for(rows: list[dict[str, Any]], columns: list[tuple[str, str]] | None) -> list[tuple[str, str]]:
    if columns:
        return columns
    if not rows:
        return []
    return [(key, key.upper()) for key in rows[0].keys()]


def render_body(
    data: Any,
    *,
    fmt: str,
    raw: bool,
    module: str,
    demo: bool,
    request_id: str,
    columns: list[tuple[str, str]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    human: str | None = None,
) -> str:
    if fmt == "json":
        payload = data if raw else envelope(
            module,
            data,
            data_source="demo" if demo else "live",
            request_id=request_id,
            next_actions=next_actions,
        )
        return dumps(payload)
    if fmt == "table" and human is not None:
        return human
    tabular = rows
    if tabular is None and isinstance(data, list):
        tabular = data
    if tabular is None and isinstance(data, dict) and isinstance(data.get("items"), list):
        tabular = data["items"]
    if fmt in ("csv", "markdown", "table") and tabular is not None:
        cols = _columns_for(tabular, columns)
        if not cols:
            return "(empty)" if fmt == "table" else ""
        if fmt == "csv":
            return render_csv(tabular, cols)
        if fmt == "markdown":
            return render_markdown(tabular, cols)
        return render_table(tabular, cols)
    if isinstance(data, dict):
        if fmt == "table":
            return render_record(data)
        row = _scalar_row(data)
        cols = [(key, key.upper()) for key in row]
        if fmt == "csv":
            return render_csv([row], cols)
        return render_markdown([row], cols)
    return dumps(data)


def emit(
    data: Any,
    *,
    fmt: str,
    raw: bool,
    module: str,
    demo: bool,
    request_id: str,
    columns: list[tuple[str, str]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    human: str | None = None,
    output_path: str | None = None,
) -> None:
    text = render_body(
        data,
        fmt=fmt,
        raw=raw,
        module=module,
        demo=demo,
        request_id=request_id,
        columns=columns,
        rows=rows,
        next_actions=next_actions,
        human=human,
    )
    if output_path:
        path = Path(output_path)
        path.write_text(text + "\n", encoding="utf-8")
        note(f"wrote {path}")
        return
    print(text)


def print_json(data: Any) -> None:
    print(dumps(data))


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    print(render_table(rows, columns))


def format_task_row(task: dict[str, Any]) -> dict[str, str]:
    prompt = task.get("prompt", "")
    if len(prompt) > 40:
        prompt = prompt[:37] + "..."
    return {
        "id": str(task.get("id", ""))[:8],
        "runtime": str(task.get("runtime", "openclaw")),
        "agent": str(task.get("agent_id", "")),
        "status": str(task.get("status", "")),
        "prompt": prompt,
    }


def format_agent_row(agent: dict[str, Any]) -> dict[str, str]:
    return {
        "runtime": str(agent.get("runtime", "openclaw")),
        "id": str(agent.get("id", "")),
        "name": str(agent.get("name", "")),
        "model": str(agent.get("model", "")),
        "default": "yes" if agent.get("is_default") else "",
    }


def clip(value: Any, limit: int = 40) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
