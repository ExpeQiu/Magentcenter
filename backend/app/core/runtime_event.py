"""跨运行时统一事件结构。"""

from dataclasses import dataclass
from typing import Any


@dataclass
class RuntimeEvent:
    type: str
    content: str = ""
    tool: str = ""
    call_id: str = ""
    input: dict[str, Any] | None = None
    output: str = ""
    status: str = ""
