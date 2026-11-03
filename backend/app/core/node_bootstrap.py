"""为本机 Node Agent 写入 v2 凭证（data/node_agent.token）。"""

from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path

from app.core.identity import load_or_create_identity
from app.models.db import NodeCredentialRecord, get_session_factory
from app.paths import data_dir

logger = logging.getLogger(__name__)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_path() -> Path:
    return data_dir() / "node_agent.token"


async def ensure_local_node_credential(role: str = "full") -> str:
    """确保本机 node_id 有可 claim 的凭证，明文只写在数据目录。"""
    ident = load_or_create_identity()
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_raw = ""
    if path.is_file():
        existing_raw = path.read_text(encoding="utf-8").strip()
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(NodeCredentialRecord, ident.node_id)
        if row is not None and not row.revoked and existing_raw:
            if row.token_hash == _hash(existing_raw):
                return existing_raw
        raw = secrets.token_urlsafe(32)
        if row is None:
            session.add(
                NodeCredentialRecord(
                    node_id=ident.node_id,
                    token_hash=_hash(raw),
                    role=role if role in {"full", "edge"} else "full",
                    revoked=0,
                )
            )
        else:
            row.token_hash = _hash(raw)
            row.role = role if role in {"full", "edge"} else "full"
            row.revoked = 0
        await session.commit()
    path.write_text(raw, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    logger.info("node-agent credential ready node_id=%s path=%s", ident.node_id, path)
    return raw


async def revoke_local_node_credential() -> None:
    ident = load_or_create_identity()
    factory = get_session_factory()
    async with factory() as session:
        row = await session.get(NodeCredentialRecord, ident.node_id)
        if row is not None:
            row.revoked = 1
            await session.commit()
    path = token_path()
    if path.is_file():
        path.unlink(missing_ok=True)
    logger.info("node-agent credential revoked node_id=%s", ident.node_id)
