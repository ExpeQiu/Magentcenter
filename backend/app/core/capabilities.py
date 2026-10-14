"""能力声明。不从「这是一台电脑」推断它什么都能做。"""

from __future__ import annotations


def catalog_for_profile(profile: str, runtimes: list[str], *, browser: bool = False) -> list[dict]:
    profile = profile or "full"
    if profile == "cloud":
        return [
            {
                "capability_id": "conversation.text",
                "runtime": "",
                "needs_internet": True,
                "external_write": False,
                "supports_cancel": False,
                "concurrency": 0,
            }
        ]
    items: list[dict] = []
    for runtime in runtimes:
        if runtime not in {"openclaw", "hermes"}:
            continue
        items.append(
            {
                "capability_id": f"agent.{runtime}",
                "runtime": runtime,
                "needs_internet": True,
                "external_write": True,
                "supports_cancel": True,
                "concurrency": 1 if profile == "edge" else 3,
            }
        )
    if profile == "full":
        items.append(
            {
                "capability_id": "tool.files",
                "runtime": "",
                "needs_internet": False,
                "external_write": False,
                "supports_cancel": True,
                "concurrency": 1,
            }
        )
        if browser:
            items.append(
                {
                    "capability_id": "tool.browser",
                    "runtime": "",
                    "needs_internet": True,
                    "external_write": True,
                    "supports_cancel": True,
                    "concurrency": 1,
                }
            )
    if profile == "edge":
        items.append(
            {
                "capability_id": "sensor.read",
                "runtime": "",
                "needs_internet": False,
                "external_write": False,
                "supports_cancel": False,
                "concurrency": 1,
            }
        )
    return items


def choose_node(
    requested: str,
    candidates: list[dict],
    capability_id: str,
) -> dict | None:
    """指定了节点就只用它。不可用时不换机器。自动选择先看数据位置，再看空闲槽。"""
    usable = [
        item
        for item in candidates
        if capability_id in item.get("capabilities", [])
        and int(item.get("free_slots") or 0) > 0
        and item.get("healthy", True)
    ]
    if requested:
        for item in candidates:
            if item.get("node_id") == requested and item in usable:
                return item
        return None
    usable.sort(key=lambda item: (0 if item.get("data_local") else 1, -int(item.get("free_slots") or 0)))
    return usable[0] if usable else None
