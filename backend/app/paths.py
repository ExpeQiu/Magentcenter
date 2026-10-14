"""Repo vs packaged-app path resolution.

Packaged Tauri sets AGENTCENTER_* env vars; local scripts leave them unset
so paths stay relative to the git checkout.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_WORKSPACE_SLUG = "cyber"
LEGACY_PREFIXES = frozenset(
    {
        "tasks",
        "projects",
        "agents",
        "squads",
        "autopilots",
        "skills",
        "kanban",
        "system",
        "sessions",
        "knowledge",
        "outputs",
        "fleet",
    }
)


def repo_root() -> Path:
    override = os.environ.get("AGENTCENTER_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2]


def guide_dir() -> Path:
    override = os.environ.get("AGENTCENTER_GUIDE_DIR")
    if override:
        return Path(override)
    return repo_root() / "guide"


def _default_data_dir() -> Path:
    root = repo_root()
    text = str(root)
    # 正在使用的数据库不放进 iCloud 或外置盘仓库目录。
    if "Mobile Documents" in text or text.startswith("/Volumes/"):
        return Path.home() / "Library" / "Application Support" / "AgentCenter" / "data"
    return root / "backend" / "data"


def data_dir() -> Path:
    override = os.environ.get("AGENTCENTER_DATA_DIR")
    if override:
        path = Path(override)
    else:
        path = _default_data_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_database_url(configured: str) -> str:
    """相对 SQLite 路径跟数据目录走，避免库文件留在仓库里。"""
    if ":///./" in (configured or ""):
        return "sqlite+aiosqlite:///" + str(data_dir() / "agentcenter.db")
    return configured


def log_dir() -> Path:
    override = os.environ.get("AGENTCENTER_LOG_DIR")
    if override:
        path = Path(override)
    else:
        path = repo_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
