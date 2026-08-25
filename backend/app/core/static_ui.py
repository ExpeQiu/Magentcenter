"""打包后由 FastAPI 直接提供 Next 静态页（运行时无 Node）。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.requests import Request

from app.paths import DEFAULT_WORKSPACE_SLUG, LEGACY_PREFIXES

logger = logging.getLogger(__name__)

_API_PREFIXES = ("api/", "ws/", "docs", "redoc", "openapi.json")
_DETAIL_KINDS = frozenset({"tasks", "projects", "sessions"})
_ASSET_SUFFIXES = frozenset(
    {".txt", ".js", ".css", ".map", ".json", ".woff", ".woff2", ".svg", ".ico", ".png", ".jpg"}
)
_SKIP_SLUG_DIRS = frozenset({"_next", "404"})


def static_dir() -> Path | None:
    raw = (os.environ.get("AGENTCENTER_STATIC_DIR") or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_dir():
        logger.warning("static ui missing path=%s", path)
        return None
    return path.resolve()


def _is_api(path: str) -> bool:
    cleaned = path.lstrip("/")
    return any(cleaned == p.rstrip("/") or cleaned.startswith(p) for p in _API_PREFIXES)


def _known_slugs(root: Path) -> set[str]:
    try:
        return {
            p.name
            for p in root.iterdir()
            if p.is_dir() and p.name not in _SKIP_SLUG_DIRS and not p.name.startswith(".")
        }
    except OSError:
        return {DEFAULT_WORKSPACE_SLUG}


def _looks_asset(cleaned: str) -> bool:
    lower = cleaned.lower()
    return any(lower.endswith(suf) for suf in _ASSET_SUFFIXES)


@dataclass(frozen=True)
class StaticResolve:
    kind: str  # file | redirect | missing
    path: Path | None = None
    location: str | None = None


def resolve_static(root: Path, full_path: str, query: str = "") -> StaticResolve:
    """把 URL 路径解析成静态文件或跳转。

    Next 静态导出的客户端导航会请求 /{slug}/{page}.txt，
    实际文件在 /{slug}/{page}/index.txt；绝不能回落到首页 HTML。
    """
    cleaned = full_path.strip("/")
    parts = [p for p in cleaned.split("/") if p]
    slugs = _known_slugs(root)

    if parts and parts[0] in LEGACY_PREFIXES:
        dest = f"/{DEFAULT_WORKSPACE_SLUG}/{cleaned}"
        if query:
            dest = f"{dest}?{query}"
        return StaticResolve(kind="redirect", location=dest)

    if (
        len(parts) == 3
        and parts[0] in slugs
        and parts[1] in _DETAIL_KINDS
        and parts[2] != "detail"
        and not _looks_asset(parts[2])
    ):
        dest = f"/{parts[0]}/{parts[1]}/detail?id={quote(parts[2])}"
        return StaticResolve(kind="redirect", location=dest)

    # 未知工作区 slug（如 cookie=expe）改写到默认工作区，避免首页死循环
    if parts and parts[0] not in slugs and parts[0] not in _SKIP_SLUG_DIRS:
        rest = parts[1:]
        dest = (
            f"/{DEFAULT_WORKSPACE_SLUG}/{'/'.join(rest)}"
            if rest
            else f"/{DEFAULT_WORKSPACE_SLUG}/tasks"
        )
        if query:
            dest = f"{dest}?{query}"
        return StaticResolve(kind="redirect", location=dest)

    file_path = _file_for(root, cleaned)
    if file_path is not None:
        return StaticResolve(kind="file", path=file_path)
    return StaticResolve(kind="missing")


def _file_for(root: Path, cleaned: str) -> Path | None:
    if not cleaned:
        index = root / "index.html"
        return index if index.is_file() else None

    candidate = root / cleaned
    try:
        candidate.relative_to(root)
    except ValueError:
        return None

    if candidate.is_file():
        return candidate

    # Next 静态导出：/cyber/outputs.txt → cyber/outputs/index.txt
    if cleaned.endswith(".txt"):
        stem = cleaned[: -len(".txt")].strip("/")
        if stem:
            rsc = root / stem / "index.txt"
            if rsc.is_file():
                return rsc

    as_index = candidate / "index.html"
    if as_index.is_file():
        return as_index
    html_file = root / f"{cleaned}.html"
    if html_file.is_file():
        return html_file
    return None


def mount_static_ui(app: FastAPI) -> None:
    root = static_dir()
    if root is None:
        logger.info("static ui skipped (AGENTCENTER_STATIC_DIR unset)")
        return

    index = root / "index.html"
    if not index.is_file():
        logger.warning("static ui index.html missing path=%s", index)
        return
    not_found = root / "404.html"
    if not not_found.is_file():
        not_found = index

    logger.info("static ui mounted root=%s", root)

    @app.get("/", include_in_schema=False)
    async def serve_static_home():
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_static_ui(full_path: str, request: Request):
        if _is_api(full_path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        result = resolve_static(root, full_path, request.url.query)
        if result.kind == "redirect" and result.location:
            logger.info("static ui redirect from=%s to=%s", full_path, result.location)
            return RedirectResponse(result.location)
        if result.kind == "file" and result.path is not None:
            headers = {}
            suffix = result.path.suffix.lower()
            if suffix in {".js", ".css", ".txt", ".html"}:
                headers["Cache-Control"] = "no-store"
            return FileResponse(result.path, headers=headers)

        logger.warning("static ui miss path=%s", full_path)
        if _looks_asset(full_path):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(not_found, status_code=404)
