"""OpenClaw / Hermes 输出物 vault 只读浏览。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

IGNORE_NAMES = frozenset(
    {
        ".obsidian",
        ".openclaw",
        ".openclaw-ops",
        ".git",
        ".clawhub",
        ".DS_Store",
        "skills",
        "__pycache__",
        "node_modules",
    }
)

MAX_SCAN_FILES = 8000
MAX_DEPTH = 12
MAX_FILE_BYTES = 2_000_000


class OutputsVaultError(Exception):
    """vault 配置或路径错误。"""

    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class VaultEntry:
    name: str
    path: str
    kind: str  # dir | file
    source: str  # openclaw | hermes
    mtime: float
    size: int


@dataclass
class VaultFile:
    path: str
    name: str
    source: str
    mtime: float
    size: int
    content: str


def _vault_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    raw = (s.outputs_vault_root or "").strip()
    if not raw:
        raise OutputsVaultError("OUTPUTS_VAULT_ROOT 未配置", status_code=503)
    root = Path(raw).expanduser()
    if not root.is_dir():
        logger.warning("outputs vault missing path=%s", root)
        raise OutputsVaultError(f"vault 不可读: {root.name}", status_code=503)
    return root.resolve()


def vault_status(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    raw = (s.outputs_vault_root or "").strip()
    if not raw:
        return {
            "status": "unavailable",
            "readable": False,
            "root_name": "",
            "message": "OUTPUTS_VAULT_ROOT 未配置",
        }
    root = Path(raw).expanduser()
    readable = root.is_dir()
    return {
        "status": "ok" if readable else "unavailable",
        "readable": readable,
        "root_name": root.name if raw else "",
        "message": "" if readable else f"vault 路径不存在: {root.name}",
    }


def infer_source(rel: str) -> str:
    normalized = rel.replace("\\", "/").lstrip("/")
    if normalized == "HermesCenter" or normalized.startswith("HermesCenter/"):
        return "hermes"
    return "openclaw"


def resolve_safe(rel: str, settings: Settings | None = None) -> Path:
    """将相对路径解析到 vault 内；拒绝逃逸。"""
    root = _vault_root(settings)
    cleaned = (rel or "").replace("\\", "/").strip("/")
    if cleaned in ("", "."):
        return root
    if ".." in cleaned.split("/"):
        raise OutputsVaultError("非法路径", status_code=400)
    candidate = (root / cleaned).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise OutputsVaultError("非法路径", status_code=400) from exc
    return candidate


def _rel_str(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _should_ignore(name: str) -> bool:
    if name in IGNORE_NAMES:
        return True
    if name.startswith(".") and name not in (".", ".."):
        # 隐藏目录/文件默认跳过（业务文档不靠隐藏名）
        return True
    return False


def list_dir(rel: str = "", settings: Settings | None = None) -> list[VaultEntry]:
    t0 = time.perf_counter()
    root = _vault_root(settings)
    target = resolve_safe(rel, settings)
    if not target.is_dir():
        raise OutputsVaultError("不是目录", status_code=404)

    entries: list[VaultEntry] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        logger.exception("outputs list_dir failed rel=%s", rel)
        raise OutputsVaultError(f"无法读取目录: {exc}", status_code=500) from exc

    for child in children:
        if _should_ignore(child.name):
            continue
        try:
            st = child.stat()
        except OSError:
            continue
        rel_path = _rel_str(root, child)
        if child.is_dir():
            entries.append(
                VaultEntry(
                    name=child.name,
                    path=rel_path,
                    kind="dir",
                    source=infer_source(rel_path),
                    mtime=st.st_mtime,
                    size=0,
                )
            )
        elif child.is_file() and child.suffix.lower() == ".md":
            entries.append(
                VaultEntry(
                    name=child.name,
                    path=rel_path,
                    kind="file",
                    source=infer_source(rel_path),
                    mtime=st.st_mtime,
                    size=st.st_size,
                )
            )

    ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "outputs list_dir rel=%r entries=%d elapsed_ms=%.1f",
        rel or "/",
        len(entries),
        ms,
    )
    return entries


def list_recent(
    limit: int = 50,
    source: str | None = None,
    q: str | None = None,
    since_hours: float | None = None,
    settings: Settings | None = None,
) -> list[VaultEntry]:
    t0 = time.perf_counter()
    root = _vault_root(settings)
    limit = max(1, min(limit, 200))
    needle = (q or "").strip().lower()
    source_filter = source if source in ("openclaw", "hermes") else None
    min_mtime: float | None = None
    if since_hours is not None and since_hours > 0:
        min_mtime = time.time() - float(since_hours) * 3600

    found: list[VaultEntry] = []
    scanned = 0

    def walk(dir_path: Path, depth: int) -> None:
        nonlocal scanned
        if depth > MAX_DEPTH or scanned >= MAX_SCAN_FILES:
            return
        try:
            children = list(dir_path.iterdir())
        except OSError:
            return
        for child in children:
            if scanned >= MAX_SCAN_FILES:
                return
            if _should_ignore(child.name):
                continue
            try:
                if child.is_dir():
                    walk(child, depth + 1)
                    continue
                if not child.is_file() or child.suffix.lower() != ".md":
                    continue
                scanned += 1
                rel_path = _rel_str(root, child)
                src = infer_source(rel_path)
                if source_filter and src != source_filter:
                    continue
                if needle and needle not in child.name.lower() and needle not in rel_path.lower():
                    continue
                st = child.stat()
                if min_mtime is not None and st.st_mtime < min_mtime:
                    continue
                found.append(
                    VaultEntry(
                        name=child.name,
                        path=rel_path,
                        kind="file",
                        source=src,
                        mtime=st.st_mtime,
                        size=st.st_size,
                    )
                )
            except OSError:
                continue

    walk(root, 0)
    found.sort(key=lambda e: e.mtime, reverse=True)
    result = found[:limit]
    ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "outputs list_recent source=%s q=%r since_hours=%s scanned=%d hits=%d elapsed_ms=%.1f",
        source_filter or "all",
        needle,
        since_hours,
        scanned,
        len(result),
        ms,
    )
    return result


def read_file(rel: str, settings: Settings | None = None) -> VaultFile:
    t0 = time.perf_counter()
    root = _vault_root(settings)
    path = resolve_safe(rel, settings)
    if not path.is_file():
        raise OutputsVaultError("文件不存在", status_code=404)
    if path.suffix.lower() not in (".md", ".txt", ".markdown"):
        raise OutputsVaultError("仅支持 Markdown/文本", status_code=400)
    try:
        st = path.stat()
    except OSError as exc:
        raise OutputsVaultError(f"无法读取文件: {exc}", status_code=500) from exc
    if st.st_size > MAX_FILE_BYTES:
        raise OutputsVaultError("文件过大", status_code=413)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OutputsVaultError(f"无法读取文件: {exc}", status_code=500) from exc

    rel_path = _rel_str(root, path)
    src = infer_source(rel_path)
    ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "outputs read_file path=%r source=%s size=%d elapsed_ms=%.1f",
        rel_path,
        src,
        st.st_size,
        ms,
    )
    return VaultFile(
        path=rel_path,
        name=path.name,
        source=src,
        mtime=st.st_mtime,
        size=st.st_size,
        content=content,
    )
