"""OpenClaw / Hermes 输出物 vault 只读浏览（整库索引）。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# 仅跳过系统/工具目录；业务目录（含 skills、各战队、文档中心等）全部纳入索引
IGNORE_NAMES = frozenset(
    {
        ".obsidian",
        ".openclaw",
        ".openclaw-ops",
        ".git",
        ".clawhub",
        ".DS_Store",
        "__pycache__",
        "node_modules",
        ".trash",
    }
)

TEXT_PREVIEW_EXTS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".json",
        ".yml",
        ".yaml",
        ".csv",
        ".tsv",
        ".log",
        ".xml",
        ".html",
        ".htm",
        ".css",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".py",
        ".sh",
        ".bash",
        ".zsh",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".gitignore",
        ".mdc",
        ".sql",
        ".r",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".swift",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".vue",
        ".svelte",
    }
)

MAX_SCAN_FILES = 20000
MAX_DEPTH = 16
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
    ext: str = ""


@dataclass
class VaultFile:
    path: str
    name: str
    source: str
    mtime: float
    size: int
    content: str
    ext: str = ""
    previewable: bool = True


def _vault_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    raw = (s.outputs_vault_root or "").strip().strip('"').strip("'")
    if not raw:
        raise OutputsVaultError("OUTPUTS_VAULT_ROOT 未配置", status_code=503)
    root = Path(raw).expanduser()
    if not root.is_dir():
        logger.warning("outputs vault missing path=%s", root)
        raise OutputsVaultError(f"vault 不可读: {root.name}", status_code=503)
    return root.resolve()


def vault_status(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    raw = (s.outputs_vault_root or "").strip().strip('"').strip("'")
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
    parts = normalized.split("/") if normalized else []
    if "HermesCenter" in parts:
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


# vault 根从 …/openclaw 上移到 …/expe 后，旧相对路径缺 openclaw/ 前缀
_EXPE_TOP_LEVEL = frozenset(
    {"Document", "Github", "myKW", "openclaw", "综合附件区"}
)


def _clean_rel(rel: str) -> str:
    return (rel or "").replace("\\", "/").strip().strip("/")


def legacy_openclaw_rel(rel: str) -> str | None:
    """若路径仍是旧 openclaw 根下的相对路径，返回加前缀后的路径。"""
    cleaned = _clean_rel(rel)
    if not cleaned:
        return None
    first = cleaned.split("/", 1)[0]
    if first in _EXPE_TOP_LEVEL:
        return None
    return f"openclaw/{cleaned}"


def resolve_path(
    rel: str,
    settings: Settings | None = None,
    *,
    expect: str | None = None,
) -> Path:
    """解析路径；不存在时尝试 openclaw/ 遗留前缀。

    expect: None | 'file' | 'dir' — 用于判定是否需要遗留回退。
    """
    cleaned = _clean_rel(rel)
    primary = resolve_safe(cleaned, settings)
    ok = (
        primary.is_file()
        if expect == "file"
        else primary.is_dir()
        if expect == "dir"
        else primary.exists()
    )
    if ok:
        return primary

    alt_rel = legacy_openclaw_rel(cleaned)
    if not alt_rel:
        return primary
    try:
        alt = resolve_safe(alt_rel, settings)
    except OutputsVaultError:
        return primary
    alt_ok = (
        alt.is_file()
        if expect == "file"
        else alt.is_dir()
        if expect == "dir"
        else alt.exists()
    )
    if alt_ok:
        logger.info(
            "outputs legacy path rewrite from=%r to=%r expect=%s",
            cleaned,
            alt_rel,
            expect or "any",
        )
        return alt
    return primary


def _rel_str(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _should_ignore(name: str) -> bool:
    return name in IGNORE_NAMES


def _is_previewable(path: Path) -> bool:
    ext = path.suffix.lower()
    if ext in TEXT_PREVIEW_EXTS:
        return True
    # 无扩展名：尝试按文本探测
    if not ext:
        return True
    return False


def _looks_binary(sample: bytes) -> bool:
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    # 高比例非文本字节则视为二进制
    textish = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126 or b >= 0x80)
    return textish / max(len(sample), 1) < 0.85


def list_dir(rel: str = "", settings: Settings | None = None) -> list[VaultEntry]:
    t0 = time.perf_counter()
    root = _vault_root(settings)
    target = resolve_path(rel, settings, expect="dir")
    if not target.is_dir():
        logger.warning("outputs list_dir missing rel=%r", _clean_rel(rel))
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
                    ext="",
                )
            )
        elif child.is_file():
            entries.append(
                VaultEntry(
                    name=child.name,
                    path=rel_path,
                    kind="file",
                    source=infer_source(rel_path),
                    mtime=st.st_mtime,
                    size=st.st_size,
                    ext=child.suffix.lower().lstrip("."),
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


def normalize_scopes(scopes: list[str] | None) -> list[str]:
    """去重、规范化相对路径；保持用户选择顺序。"""
    if not scopes:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in scopes:
        cleaned = (raw or "").replace("\\", "/").strip().strip("/")
        if not cleaned or ".." in cleaned.split("/"):
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def resolve_scope_dirs(
    scopes: list[str], settings: Settings | None = None
) -> list[tuple[str, Path]]:
    """将范围路径解析为存在的目录；(rel, abs)。无效项跳过并打日志。"""
    resolved: list[tuple[str, Path]] = []
    for rel in normalize_scopes(scopes):
        try:
            path = resolve_path(rel, settings, expect="dir")
        except OutputsVaultError:
            logger.warning("outputs invalid scope skipped scope=%r", rel)
            continue
        if not path.is_dir():
            logger.warning("outputs scope not a dir skipped scope=%r", rel)
            continue
        # 返回实际相对路径（可能已加 openclaw/）
        root = _vault_root(settings)
        resolved.append((_rel_str(root, path), path))
    return resolved


def path_in_scopes(rel: str, scopes: list[str]) -> bool:
    """文件/目录相对路径是否落在任一范围前缀下。"""
    if not scopes:
        return True
    normalized = (rel or "").replace("\\", "/").strip("/")
    for scope in scopes:
        if normalized == scope or normalized.startswith(scope + "/"):
            return True
    return False


def list_recent(
    limit: int = 50,
    source: str | None = None,
    q: str | None = None,
    since_hours: float | None = None,
    scopes: list[str] | None = None,
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

    scope_list = normalize_scopes(scopes)
    if scope_list:
        start_dirs = resolve_scope_dirs(scope_list, settings)
        if not start_dirs:
            logger.info(
                "outputs list_recent scopes=%s no_valid_dirs elapsed_ms=%.1f",
                scope_list,
                (time.perf_counter() - t0) * 1000,
            )
            return []
    else:
        start_dirs = [("/", root)]

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
                if not child.is_file():
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
                        ext=child.suffix.lower().lstrip("."),
                    )
                )
            except OSError:
                continue

    for _rel, start in start_dirs:
        walk(start, 0)

    found.sort(key=lambda e: e.mtime, reverse=True)
    result = found[:limit]
    ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "outputs list_recent source=%s q=%r since_hours=%s scopes=%s scanned=%d hits=%d elapsed_ms=%.1f",
        source_filter or "all",
        needle,
        since_hours,
        scope_list or "all",
        scanned,
        len(result),
        ms,
    )
    return result


def read_file(rel: str, settings: Settings | None = None) -> VaultFile:
    t0 = time.perf_counter()
    root = _vault_root(settings)
    path = resolve_path(rel, settings, expect="file")
    if not path.is_file():
        logger.warning("outputs read_file missing rel=%r", _clean_rel(rel))
        raise OutputsVaultError("文件不存在", status_code=404)
    try:
        st = path.stat()
    except OSError as exc:
        raise OutputsVaultError(f"无法读取文件: {exc}", status_code=500) from exc
    if st.st_size > MAX_FILE_BYTES:
        raise OutputsVaultError("文件过大", status_code=413)

    rel_path = _rel_str(root, path)
    src = infer_source(rel_path)
    ext = path.suffix.lower().lstrip(".")
    content = ""
    previewable = False

    if _is_previewable(path):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise OutputsVaultError(f"无法读取文件: {exc}", status_code=500) from exc
        sample = raw[:8192]
        if _looks_binary(sample):
            previewable = False
            content = ""
        else:
            previewable = True
            content = raw.decode("utf-8", errors="replace")
    else:
        previewable = False

    ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "outputs read_file path=%r source=%s size=%d previewable=%s elapsed_ms=%.1f",
        rel_path,
        src,
        st.st_size,
        previewable,
        ms,
    )
    return VaultFile(
        path=rel_path,
        name=path.name,
        source=src,
        mtime=st.st_mtime,
        size=st.st_size,
        content=content,
        ext=ext,
        previewable=previewable,
    )
