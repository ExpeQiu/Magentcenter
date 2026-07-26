"""运行时常量与工具。"""

from typing import Literal

RuntimeName = Literal["openclaw", "hermes"]
VALID_RUNTIMES: tuple[str, ...] = ("openclaw", "hermes")


def normalize_runtime(value: str | None, default: str = "openclaw") -> str:
    raw = (value or default).strip().lower()
    if raw not in VALID_RUNTIMES:
        raise ValueError(f"unsupported runtime: {value!r} (expected {VALID_RUNTIMES})")
    return raw


def parse_enabled_runtimes(raw: str) -> list[str]:
    items = [x.strip().lower() for x in (raw or "").split(",") if x.strip()]
    out: list[str] = []
    for item in items:
        if item in VALID_RUNTIMES and item not in out:
            out.append(item)
    return out or ["openclaw"]


def agent_lock_key(runtime: str, agent_id: str) -> str:
    return f"{runtime}:{agent_id}"
