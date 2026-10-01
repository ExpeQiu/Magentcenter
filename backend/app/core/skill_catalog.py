"""WaytoAI 技能仓：分类真源，并作为控制台的初始技能。"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from app.core.content_roots import DEFAULT_SKILLS_DIR as DEFAULT_CATALOG_DIR
from app.core.skills import SkillInfo, _entry_to_info

logger = logging.getLogger(__name__)

# 与 catalog/skills.yaml 的 category 注释一致。前五项是初始技能。
ACTIVE_CATEGORIES = (
    "engineering",
    "productivity",
    "research",
    "domain",
    "misc",
)
LIFECYCLE_CATEGORIES = ("in-progress", "deprecated")
ALL_CATEGORIES = ACTIVE_CATEGORIES + LIFECYCLE_CATEGORIES


def load_catalog_index(catalog_dir: Path) -> dict[str, dict]:
    """skills.yaml 是分类真源。缺文件时退回目录名。"""
    path = catalog_dir / "catalog" / "skills.yaml"
    if not path.is_file():
        logger.info("skill catalog index missing path=%s", path)
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("skill catalog index unreadable path=%s err=%s", path, exc)
        return {}
    skills = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(skills, dict):
        return {}
    index: dict[str, dict] = {}
    for name, meta in skills.items():
        if not isinstance(meta, dict):
            continue
        category = str(meta.get("category") or "").strip()
        if category not in ALL_CATEGORIES:
            continue
        index[str(name)] = {
            "category": category,
            "owner": str(meta.get("owner") or ""),
            "summary": str(meta.get("summary") or ""),
            "trigger": str(meta.get("trigger") or ""),
        }
    logger.info("skill catalog index loaded count=%d path=%s", len(index), path)
    return index


def scan_catalog(
    catalog_dir: str | None,
    *,
    include_archived: bool = False,
) -> list[SkillInfo]:
    """扫描 <category>/<name>/SKILL.md，绑定为初始技能。"""
    if not catalog_dir:
        return []
    root = Path(catalog_dir).expanduser()
    if not root.is_dir():
        logger.warning("skill catalog dir missing path=%s", root)
        return []
    index = load_catalog_index(root)
    categories = list(ACTIVE_CATEGORIES)
    if include_archived:
        categories.append("deprecated")
    categories.append("in-progress")

    found: list[SkillInfo] = []
    seen: set[str] = set()
    for category in categories:
        bucket = root / category
        if not bucket.is_dir():
            continue
        for entry in sorted(bucket.iterdir()):
            if not entry.is_dir() or not (entry / "SKILL.md").is_file():
                continue
            meta = index.get(entry.name) or {}
            if str(meta.get("category") or "") == "deprecated" and not include_archived:
                continue
            if entry.name in seen:
                continue
            skill_id = f"{category}/{entry.name}"
            info = _entry_to_info(
                entry, skill_id=skill_id, archived=category == "deprecated", runtime="catalog"
            )
            if not info:
                continue
            info.category = category
            info.bound = True
            if meta.get("owner") and not info.owner:
                info.owner = meta["owner"]
            if meta.get("summary") and not info.description:
                info.description = meta["summary"]
            if meta.get("trigger") == "user":
                info.disable_model_invocation = True
            seen.add(entry.name)
            found.append(info)
    order = {name: i for i, name in enumerate(ALL_CATEGORIES)}
    found.sort(key=lambda item: (order.get(item.category, 99), item.name.lower()))
    logger.info(
        "skill catalog scanned count=%d categories=%s root=%s",
        len(found),
        ",".join(categories),
        root,
    )
    return found


def apply_catalog_categories(skills: list[SkillInfo], index: dict[str, dict]) -> list[SkillInfo]:
    """运行时目录里的同名技能沿用仓内分类，避免和初始技能各分一套。"""
    if not index:
        return skills
    for skill in skills:
        meta = index.get(skill.name) or index.get(skill.id.rsplit("/", 1)[-1])
        if not meta:
            continue
        skill.category = meta["category"]
        skill.bound = True
    return skills
