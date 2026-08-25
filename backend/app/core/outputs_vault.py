"""OpenClaw / Hermes 输出物 vault 只读浏览（整库索引）。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
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
        ".venv",
        "venv",
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


def _unescape_fs_path(raw: str) -> str:
    """去掉 shell 转义（如 Mobile\\ Documents、com\\~apple）。"""
    s = (raw or "").strip().strip('"').strip("'")
    return s.replace("\\ ", " ").replace("\\~", "~")


def _vault_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    raw = _unescape_fs_path(s.outputs_vault_root or "")
    if not raw:
        raise OutputsVaultError("OUTPUTS_VAULT_ROOT 未配置", status_code=503)
    root = Path(raw).expanduser()
    if not root.is_dir():
        logger.warning("outputs vault missing path=%s", root)
        raise OutputsVaultError(f"vault 不可读: {root.name}", status_code=503)
    return root.resolve()


def _split_extra_raw(raw: str) -> list[str]:
    text = _unescape_fs_path(raw)
    if not text:
        return []
    chunks: list[str] = []
    for piece in text.replace(";", "\n").replace(",", "\n").splitlines():
        p = _unescape_fs_path(piece)
        if p:
            chunks.append(p)
    return chunks


@lru_cache(maxsize=16)
def _cached_extra_specs(
    primary_raw: str, extra_raw: str
) -> tuple[tuple[str, bool, str, str], ...]:
    """(name, readable, path, message) 缓存；配置变更或进程重启后失效。"""
    primary: Path | None = None
    if primary_raw:
        p = Path(primary_raw).expanduser()
        if p.is_dir():
            primary = p.resolve()

    used_names: set[str] = set(_EXPE_TOP_LEVEL)
    rows: list[tuple[str, bool, str, str]] = []
    for raw in _split_extra_raw(extra_raw):
        path = Path(raw).expanduser()
        readable = path.is_dir()
        resolved = path.resolve() if readable else path
        if primary is not None and readable:
            if resolved == primary:
                logger.warning("outputs extra skipped (same as primary) path=%s", resolved)
                continue
            try:
                resolved.relative_to(primary)
                logger.warning("outputs extra skipped (inside primary) path=%s", resolved)
                continue
            except ValueError:
                pass
            try:
                primary.relative_to(resolved)
                logger.warning("outputs extra skipped (contains primary) path=%s", resolved)
                continue
            except ValueError:
                pass

        base = path.name.strip() or "extra"
        alias = base
        n = 2
        while alias in used_names or (
            primary is not None and (primary / alias).exists()
        ):
            alias = f"{base}_{n}"
            n += 1
        used_names.add(alias)
        msg = "" if readable else f"额外目录不可读: {path.name}"
        rows.append((alias, readable, str(resolved), msg))
        if readable:
            logger.info("outputs extra root alias=%s path=%s", alias, resolved)
        else:
            logger.warning("outputs extra missing alias=%s path=%s", alias, path)
    return tuple(rows)


def extra_vault_specs(settings: Settings | None = None) -> list[dict]:
    """配置里的额外根（含不可读项），供 status 展示。"""
    s = settings or get_settings()
    rows = _cached_extra_specs(
        _unescape_fs_path(s.outputs_vault_root or ""),
        s.outputs_vault_extra or "",
    )
    return [
        {"name": n, "readable": r, "path": p, "message": m}
        for n, r, p, m in rows
    ]


def extra_vault_roots(settings: Settings | None = None) -> dict[str, Path]:
    """可读额外根：alias -> 绝对路径。"""
    out: dict[str, Path] = {}
    for spec in extra_vault_specs(settings):
        if spec["readable"]:
            out[spec["name"]] = Path(spec["path"])
    return out


def vault_status(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    raw = _unescape_fs_path(s.outputs_vault_root or "")
    extras = extra_vault_specs(s)
    extra_public = [
        {"name": x["name"], "readable": x["readable"], "message": x["message"]}
        for x in extras
    ]
    if not raw:
        return {
            "status": "unavailable",
            "readable": False,
            "root_name": "",
            "message": "OUTPUTS_VAULT_ROOT 未配置",
            "extra_roots": extra_public,
        }
    root = Path(raw).expanduser()
    readable = root.is_dir()
    return {
        "status": "ok" if readable else "unavailable",
        "readable": readable,
        "root_name": root.name if raw else "",
        "message": "" if readable else f"vault 路径不存在: {root.name}",
        "extra_roots": extra_public,
    }


def infer_source(rel: str) -> str:
    normalized = rel.replace("\\", "/").lstrip("/")
    parts = normalized.split("/") if normalized else []
    if "HermesCenter" in parts:
        return "hermes"
    return "openclaw"


def resolve_safe(rel: str, settings: Settings | None = None) -> Path:
    """将相对路径解析到主库或额外根内；拒绝逃逸。"""
    cleaned = (rel or "").replace("\\", "/").strip("/")
    if ".." in cleaned.split("/"):
        raise OutputsVaultError("非法路径", status_code=400)
    extras = extra_vault_roots(settings)
    if cleaned and cleaned != ".":
        first, _, rest = cleaned.partition("/")
        extra_root = extras.get(first)
        if extra_root is not None:
            candidate = extra_root if not rest else (extra_root / rest).resolve()
            if not rest:
                return extra_root
            try:
                candidate.relative_to(extra_root)
            except ValueError as exc:
                raise OutputsVaultError("非法路径", status_code=400) from exc
            return candidate
    root = _vault_root(settings)
    if cleaned in ("", "."):
        return root
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


def legacy_openclaw_rel(
    rel: str, settings: Settings | None = None
) -> str | None:
    """若路径仍是旧 openclaw 根下的相对路径，返回加前缀后的路径。"""
    cleaned = _clean_rel(rel)
    if not cleaned:
        return None
    first = cleaned.split("/", 1)[0]
    if first in _EXPE_TOP_LEVEL or first in extra_vault_roots(settings):
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

    alt_rel = legacy_openclaw_rel(cleaned, settings)
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


def _logical_rel(
    path: Path,
    settings: Settings | None = None,
    extras: dict[str, Path] | None = None,
) -> str | None:
    """绝对路径 → 逻辑相对路径。库外符号链接返回 None。"""
    mapping = extras if extras is not None else extra_vault_roots(settings)
    roots: list[tuple[str, Path]] = [(alias, extra) for alias, extra in mapping.items()]
    try:
        primary = _vault_root(settings)
        roots.append(("", primary))
    except OutputsVaultError:
        primary = None

    def _rel_to(candidate: Path) -> str | None:
        for alias, extra_root in roots:
            try:
                rel = candidate.relative_to(extra_root)
            except ValueError:
                continue
            rel_s = rel.as_posix()
            if alias:
                return alias if rel_s in ("", ".") else f"{alias}/{rel_s}"
            return rel_s
        return None

    # 先按展示路径（不跟随 symlink），避免链到库外
    hit = _rel_to(path)
    if hit is not None:
        return hit
    try:
        resolved = path.resolve()
    except OSError:
        return None
    hit = _rel_to(resolved)
    if hit is None:
        logger.warning("outputs skip escaped path=%s resolved=%s", path, resolved)
    return hit


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
    extras = extra_vault_roots(settings)
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
        rel_path = _logical_rel(child, settings, extras=extras)
        if not rel_path:
            continue
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

    cleaned_rel = _clean_rel(rel)
    if not cleaned_rel:
        existing = {e.path for e in entries}
        for alias, extra_root in extras.items():
            if alias in existing:
                continue
            try:
                st = extra_root.stat()
            except OSError:
                continue
            entries.append(
                VaultEntry(
                    name=alias,
                    path=alias,
                    kind="dir",
                    source=infer_source(alias),
                    mtime=st.st_mtime,
                    size=0,
                    ext="",
                )
            )
        entries.sort(key=lambda e: (e.kind != "dir", e.name.lower()))

    ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "outputs list_dir rel=%r entries=%d elapsed_ms=%.1f",
        rel or "/",
        len(entries),
        ms,
    )
    return entries


def normalize_scopes(
    scopes: list[str] | None, settings: Settings | None = None
) -> list[str]:
    """去重、规范化相对路径；保持用户选择顺序。

    旧前端会把额外根误写成 openclaw/<extra>，这里还原。
    """
    if not scopes:
        return []
    extras = extra_vault_roots(settings)
    seen: set[str] = set()
    out: list[str] = []
    for raw in scopes:
        cleaned = (raw or "").replace("\\", "/").strip().strip("/")
        if not cleaned or ".." in cleaned.split("/"):
            continue
        parts = cleaned.split("/")
        if parts[0] == "openclaw" and len(parts) >= 2 and parts[1] in extras:
            cleaned = "/".join(parts[1:])
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
        # 返回逻辑相对路径（额外根带 alias）
        logical = _logical_rel(path, settings)
        if not logical:
            logger.warning("outputs scope escaped skipped scope=%r", rel)
            continue
        resolved.append((logical, path))
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
        extras = extra_vault_roots(settings)
        start_dirs = [("/", root)]
        for alias, extra_root in extras.items():
            start_dirs.append((alias, extra_root))

    found: list[VaultEntry] = []
    scanned = 0
    extras = extra_vault_roots(settings)

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
                    if child.is_symlink():
                        logger.info("outputs skip symlink dir path=%s", child)
                        continue
                    walk(child, depth + 1)
                    continue
                if not child.is_file():
                    continue
                scanned += 1
                rel_path = _logical_rel(child, settings, extras=extras)
                if not rel_path:
                    continue
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
            except (OSError, ValueError, TypeError):
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

    rel_path = _logical_rel(path, settings)
    if not rel_path:
        raise OutputsVaultError("非法路径", status_code=400)
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
