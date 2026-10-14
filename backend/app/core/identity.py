"""本机稳定身份。node_id / center_id 在首次安装时生成，不使用主机名。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.paths import data_dir

_FILENAME = "node_identity.json"


@dataclass
class NodeIdentity:
    node_id: str
    center_id: str
    profile: str = "full"
    aliases: list[str] | None = None

    def as_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "center_id": self.center_id,
            "profile": self.profile,
            "aliases": list(self.aliases or []),
            "schema_version": 1,
            "protocol_version": 2,
        }


def identity_path() -> Path:
    return data_dir() / _FILENAME


def load_or_create_identity(profile: str = "full", path: Path | None = None) -> NodeIdentity:
    target = path or identity_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        raw = json.loads(target.read_text(encoding="utf-8"))
        node_id = str(raw.get("node_id") or "")
        center_id = str(raw.get("center_id") or "")
        if node_id and center_id:
            return NodeIdentity(
                node_id=node_id,
                center_id=center_id,
                profile=str(raw.get("profile") or profile or "full"),
                aliases=list(raw.get("aliases") or []),
            )
    created = NodeIdentity(
        node_id=str(uuid.uuid4()),
        center_id=str(uuid.uuid4()),
        profile=profile or "full",
        aliases=[],
    )
    target.write_text(json.dumps(created.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return created


def remember_alias(alias: str, path: Path | None = None) -> NodeIdentity:
    """保留旧节点 ID 别名。不按主机名把历史任务并到另一台机器。"""
    alias = (alias or "").strip()
    ident = load_or_create_identity(path=path)
    if not alias or alias in {ident.node_id, ident.center_id}:
        return ident
    aliases = list(ident.aliases or [])
    if alias not in aliases:
        aliases.append(alias)
        ident.aliases = aliases
        target = path or identity_path()
        target.write_text(json.dumps(ident.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return ident
