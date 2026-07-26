"""输出物 vault 只读 API。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.core.outputs_vault import (
    OutputsVaultError,
    VaultEntry,
    list_dir,
    list_recent,
    read_file,
    vault_status,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/outputs", tags=["outputs"])


class OutputEntryOut(BaseModel):
    name: str
    path: str
    kind: str
    source: str
    mtime: str
    size: int


class OutputFileOut(BaseModel):
    path: str
    name: str
    source: str
    mtime: str
    size: int
    content: str


class OutputStatusOut(BaseModel):
    status: str
    readable: bool
    root_name: str = ""
    message: str = ""


def _fmt_mtime(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _entry_out(e: VaultEntry) -> OutputEntryOut:
    return OutputEntryOut(
        name=e.name,
        path=e.path,
        kind=e.kind,
        source=e.source,
        mtime=_fmt_mtime(e.mtime),
        size=e.size,
    )


def _raise(exc: OutputsVaultError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/status", response_model=OutputStatusOut)
async def outputs_status():
    return OutputStatusOut(**vault_status())


@router.get("/tree", response_model=list[OutputEntryOut])
async def outputs_tree(
    path: str = Query("", description="相对 vault 的目录路径"),
):
    try:
        entries = list_dir(path)
    except OutputsVaultError as exc:
        _raise(exc)
        return []
    return [_entry_out(e) for e in entries]


@router.get("/recent", response_model=list[OutputEntryOut])
async def outputs_recent(
    limit: int = Query(50, ge=1, le=200),
    source: str | None = Query(None, description="openclaw|hermes"),
    q: str | None = Query(None, description="文件名/路径关键词"),
    since_hours: float | None = Query(
        None, ge=0.1, le=24 * 30, description="仅返回该小时数内修改的文档"
    ),
):
    if source and source not in ("openclaw", "hermes"):
        source = None
    try:
        entries = list_recent(
            limit=limit, source=source, q=q, since_hours=since_hours
        )
    except OutputsVaultError as exc:
        _raise(exc)
        return []
    return [_entry_out(e) for e in entries]


@router.get("/file", response_model=OutputFileOut)
async def outputs_file(
    path: str = Query(..., min_length=1, description="相对 vault 的文件路径"),
):
    try:
        f = read_file(path)
    except OutputsVaultError as exc:
        _raise(exc)
        raise
    return OutputFileOut(
        path=f.path,
        name=f.name,
        source=f.source,
        mtime=_fmt_mtime(f.mtime),
        size=f.size,
        content=f.content,
    )
