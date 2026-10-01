"""Personal Wiki 三层路由。写入和召回都走这里。"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

LAYER_L2 = "L2"
LAYER_L3 = "L3"
LAYER_L1 = "L1"
LAYER_NOTES = "notes"

RECALL_LAYERS = (LAYER_L2, LAYER_L3, LAYER_L1)

FACETS: dict[str, tuple[str, ...]] = {
    LAYER_L2: (
        "mental-models",
        "patterns",
        "principles",
        "decisions",
        "reflections",
        "experiences",
    ),
    LAYER_L3: ("procedural", "templates", "tools"),
    LAYER_L1: ("profile", "state", "preferences", "semantic"),
    LAYER_NOTES: ("notes",),
}

# 旧卡片 kind → (layer, facet)。正文不改，只补坐标。
KIND_TO_LAYER: dict[str, tuple[str, str]] = {
    "playbook": (LAYER_L3, "procedural"),
    "precedent": (LAYER_L2, "experiences"),
    "incident": (LAYER_L2, "reflections"),
    "shared_fact": (LAYER_L1, "semantic"),
    "artifact_ref": (LAYER_L1, "semantic"),
    "archive": (LAYER_NOTES, "notes"),
}

_DEFAULT_WEIGHTS = {LAYER_L2: 3.0, LAYER_L3: 1.2, LAYER_L1: 1.0, LAYER_NOTES: 0.0}

_HIGH_STAKES = re.compile(r"发布|凭证|生产")
_PREFERENCE = re.compile(r"偏好|以后都|不要再")
_EXPLICIT_SKILL = re.compile(r"记住这个|做个技能|做成技能|固化下来|固化")
_POSITIVE = re.compile(r"收到|可以|👍|✅|🎯|(?:^|[\s，。！])好(?:[\s，。！]|$)|(?<![不])干")


def parse_layer_weights(raw: str | None = None) -> dict[str, float]:
    """`KNOWLEDGE_LAYER_WEIGHTS=3.0,1.2,1.0` → L2, L3, L1。"""
    weights = dict(_DEFAULT_WEIGHTS)
    text = (raw or "").strip()
    if not text:
        return weights
    parts = [p.strip() for p in text.split(",") if p.strip()]
    keys = (LAYER_L2, LAYER_L3, LAYER_L1)
    try:
        for key, part in zip(keys, parts):
            weights[key] = float(part)
    except ValueError:
        logger.warning("invalid KNOWLEDGE_LAYER_WEIGHTS=%r, using defaults", raw)
        return dict(_DEFAULT_WEIGHTS)
    return weights


def layer_weight(layer: str, raw: str | None = None) -> float:
    return parse_layer_weights(raw).get(layer or "", 1.0)


def kind_to_layer(kind: str) -> tuple[str, str]:
    return KIND_TO_LAYER.get((kind or "").strip(), (LAYER_NOTES, "notes"))


def normalize_facet(layer: str, facet: str) -> str:
    allowed = FACETS.get(layer) or ()
    facet = (facet or "").strip()
    if facet in allowed:
        return facet
    if allowed:
        return allowed[-1]
    return "notes"


def resolve_placement(
    kind: str,
    *,
    layer: str = "",
    facet: str = "",
) -> tuple[str, str]:
    """显式 layer 优先，否则按旧 kind 映射。"""
    layer = (layer or "").strip()
    if layer in FACETS:
        return layer, normalize_facet(layer, facet)
    return kind_to_layer(kind)


def effective_placement(layer: str, facet: str, kind: str) -> tuple[str, str]:
    """读库时：已写入的层优先，空层回退到 kind。"""
    if (layer or "").strip() in FACETS:
        return resolve_placement(kind, layer=layer, facet=facet)
    return kind_to_layer(kind)


def kinds_for_layers(layers: list[str]) -> list[str]:
    want = set(layers)
    return [kind for kind, (layer, _) in KIND_TO_LAYER.items() if layer in want]


def namespaced_tags(
    *,
    src: str,
    facet: str,
    topic: str = "",
    status: str = "active",
    extra: list[str] | None = None,
) -> list[str]:
    tags = [f"src:{src}", f"type:{facet}", f"status:{status}"]
    topic = re.sub(r"\s+", "-", (topic or "").strip())[:40]
    if topic:
        tags.append(f"topic:{topic}")
    for item in extra or []:
        text = (item or "").strip()
        if text and text not in tags:
            tags.append(text)
    return tags


def is_high_stakes(text: str) -> bool:
    return bool(_HIGH_STAKES.search(text or ""))


def find_preference(text: str) -> str:
    """命中偏好说法时返回摘句，否则空。"""
    raw = text or ""
    match = _PREFERENCE.search(raw)
    if not match:
        return ""
    start = max(0, match.start() - 20)
    end = min(len(raw), match.end() + 80)
    return re.sub(r"\s+", " ", raw[start:end]).strip()


def explicit_skill_request(text: str) -> bool:
    return bool(_EXPLICIT_SKILL.search(text or ""))


def positive_feedback(text: str) -> str:
    match = _POSITIVE.search(text or "")
    return match.group(0).strip() if match else ""
