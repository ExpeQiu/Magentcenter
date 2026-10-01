"""知识库与技能的读取目录。文件里的改动优先于环境变量。"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.paths import data_dir

logger = logging.getLogger(__name__)

DEFAULT_WIKI_DIR = (
    "/Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/personalwiki"
)
DEFAULT_SKILLS_DIR = (
    "/Users/qiubin/Library/Mobile Documents/com~apple~CloudDocs/WaytoAI/skills"
)
DEFAULT_OUTPUTS_DIR = (
    "~/Library/Mobile Documents/iCloud~md~obsidian/Documents/expe"
)

_KEYS = ("knowledge_wiki_dir", "skills_catalog_dir", "outputs_vault_dir")


def roots_path() -> Path:
    return data_dir() / "content_roots.json"


def _load() -> dict[str, str]:
    path = roots_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("content roots unreadable path=%s err=%s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in _KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _save(data: dict[str, str]) -> None:
    path = roots_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    logger.info("content roots saved path=%s keys=%s", path, ",".join(sorted(data)))


def clean_dir(raw: str) -> str:
    """展开用户目录，要求绝对路径，拒绝盘根和家目录本身。"""
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise ValueError("路径不能为空")
    path = Path(text).expanduser()
    if not path.is_absolute():
        raise ValueError("路径需要是绝对路径")
    resolved = path.resolve()
    if resolved == Path("/") or resolved == Path.home():
        raise ValueError("路径范围太大")
    return str(resolved)


def _settings_value(field: str, fallback: str) -> str:
    from app.config import get_settings

    raw = str(getattr(get_settings(), field, "") or "").strip()
    return raw or fallback


def wiki_dir() -> str:
    saved = _load().get("knowledge_wiki_dir") or ""
    return saved or _settings_value("knowledge_wiki_dir", DEFAULT_WIKI_DIR)


def skills_dir() -> str:
    saved = _load().get("skills_catalog_dir") or ""
    return saved or _settings_value("skills_catalog_dir", DEFAULT_SKILLS_DIR)


def outputs_dir() -> str:
    saved = _load().get("outputs_vault_dir") or ""
    raw = saved or _settings_value("outputs_vault_root", DEFAULT_OUTPUTS_DIR)
    text = raw.strip().strip('"').strip("'").replace("\\ ", " ").replace("\\~", "~")
    return str(Path(text).expanduser())


_SKIP_WALK = {".git", "node_modules", ".next", ".obsidian", "__pycache__", "dist"}


def _count_files(root: Path, *, suffix: str = "", name: str = "") -> int:
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_WALK and not d.startswith(".")]
        for filename in filenames:
            if name and filename != name:
                continue
            if suffix and not filename.endswith(suffix):
                continue
            count += 1
            if count >= 500:
                return count
        if count >= 500:
            break
    return count


def describe(path: str, *, suffix: str = "", name: str = "") -> dict[str, Any]:
    root = Path(path).expanduser()
    exists = root.is_dir()
    file_count = 0
    if exists:
        try:
            file_count = _count_files(root, suffix=suffix, name=name)
        except OSError as exc:
            logger.warning("content root unreadable path=%s err=%s", root, exc)
            exists = False
    if not exists:
        logger.info("content root missing path=%s", root)
    return {"path": str(root), "exists": exists, "file_count": file_count}


def snapshot() -> dict[str, Any]:
    wiki = wiki_dir()
    skills = skills_dir()
    outputs = outputs_dir()
    return {
        "knowledge_wiki_dir": wiki,
        "skills_catalog_dir": skills,
        "outputs_vault_dir": outputs,
        "knowledge_default": DEFAULT_WIKI_DIR,
        "skills_default": DEFAULT_SKILLS_DIR,
        "outputs_default": str(Path(DEFAULT_OUTPUTS_DIR).expanduser()),
        "knowledge": describe(wiki, suffix=".md"),
        "skills": describe(skills, name="SKILL.md"),
        "outputs": describe(outputs, suffix=".md"),
    }


def update(
    *,
    knowledge_wiki_dir: str | None = None,
    skills_catalog_dir: str | None = None,
    outputs_vault_dir: str | None = None,
) -> dict[str, Any]:
    """None 表示不改。空字符串恢复默认。"""
    data = _load()
    if knowledge_wiki_dir is not None:
        text = knowledge_wiki_dir.strip()
        if text:
            data["knowledge_wiki_dir"] = clean_dir(text)
        else:
            data.pop("knowledge_wiki_dir", None)
        logger.info("knowledge wiki dir set path=%s", data.get("knowledge_wiki_dir") or DEFAULT_WIKI_DIR)
    if skills_catalog_dir is not None:
        text = skills_catalog_dir.strip()
        if text:
            data["skills_catalog_dir"] = clean_dir(text)
        else:
            data.pop("skills_catalog_dir", None)
        logger.info("skills catalog dir set path=%s", data.get("skills_catalog_dir") or DEFAULT_SKILLS_DIR)
    if outputs_vault_dir is not None:
        text = outputs_vault_dir.strip()
        if text:
            data["outputs_vault_dir"] = clean_dir(text)
        else:
            data.pop("outputs_vault_dir", None)
        logger.info(
            "outputs vault dir set path=%s",
            data.get("outputs_vault_dir") or DEFAULT_OUTPUTS_DIR,
        )
    _save(data)
    return snapshot()
