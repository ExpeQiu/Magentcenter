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


def data_dir() -> Path:
    override = os.environ.get("AGENTCENTER_DATA_DIR")
    if override:
        path = Path(override)
    else:
        path = repo_root() / "backend" / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    override = os.environ.get("AGENTCENTER_LOG_DIR")
    if override:
        path = Path(override)
    else:
        path = repo_root() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path
