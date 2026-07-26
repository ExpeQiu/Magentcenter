"""技能目录扫描与管理模块。"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

HIDDEN_DIR_PREFIX = "_"
ARCHIVE_DIR_NAME = "_archive"
BODY_PREVIEW_CHARS = 4000
SHORT_DESC_LIMIT = 160


class SkillInfo(BaseModel):
    id: str
    name: str
    path: str
    description: str = ""
    description_full: str = ""
    version: str = ""
    owner: str = ""
    disable_model_invocation: bool = False
    allowed_tools: list[str] = Field(default_factory=list)
    emoji: str = ""
    archived: bool = False
    runtime: str = "openclaw"


class SkillDetail(SkillInfo):
    body_preview: str = ""
    skill_md_path: str = ""


def _default_skills_root(skills_dir: str | None = None) -> Path:
    if skills_dir:
        return Path(skills_dir).expanduser()
    return Path.home() / ".openclaw" / "skills"


def _hermes_skills_root(skills_dir: str | None = None) -> Path:
    if skills_dir:
        return Path(skills_dir).expanduser()
    hermes_home = Path.home() / ".hermes"
    return hermes_home / "skills"


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw_fm, body = parts[1], parts[2]
    try:
        data = yaml.safe_load(raw_fm) or {}
        if not isinstance(data, dict):
            return {}, body.lstrip("\n")
        return data, body.lstrip("\n")
    except yaml.YAMLError as exc:
        logger.warning("skill frontmatter yaml parse failed: %s", exc)
        return {}, body.lstrip("\n")


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            s = _as_str(item)
            if s:
                out.append(s)
        return out
    return []


def _short_description(desc: str, limit: int = SHORT_DESC_LIMIT) -> str:
    text = desc.strip().strip("\"'")
    # 兼容 " | When to use" / "。| When to use" / 无空格变体
    cut = re.search(
        r"\s*\|?\s*(When to use|NOT for|When:)\b|\.\s*Use when\b|\sUse when:",
        text,
        flags=re.IGNORECASE,
    )
    if cut:
        text = text[: cut.start()].strip()
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _extract_emoji(meta: Any) -> str:
    if not isinstance(meta, dict):
        return ""
    openclaw = meta.get("openclaw")
    if isinstance(openclaw, dict):
        return _as_str(openclaw.get("emoji"))
    return _as_str(meta.get("emoji"))


def _parse_skill_file(skill_md: Path, skill_id: str) -> dict[str, Any]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("read skill md failed id=%s err=%s", skill_id, exc)
        return {
            "name": skill_id,
            "description": "",
            "description_full": "",
            "version": "",
            "owner": "",
            "disable_model_invocation": False,
            "allowed_tools": [],
            "emoji": "",
            "body": "",
        }

    fm, body = _split_frontmatter(text)
    full_desc = _as_str(fm.get("description"))
    name = _as_str(fm.get("name")) or skill_id
    return {
        "name": name,
        "description": _short_description(full_desc) if full_desc else "",
        "description_full": full_desc,
        "version": _as_str(fm.get("version")),
        "owner": _as_str(fm.get("owner")),
        "disable_model_invocation": _as_bool(fm.get("disable-model-invocation")),
        "allowed_tools": _as_str_list(fm.get("allowed-tools")),
        "emoji": _extract_emoji(fm.get("metadata")),
        "body": body,
    }


def _entry_to_info(
    entry: Path,
    *,
    skill_id: str,
    archived: bool = False,
    runtime: str = "openclaw",
) -> SkillInfo | None:
    skill_md = entry / "SKILL.md"
    if not skill_md.is_file():
        return None
    parsed = _parse_skill_file(skill_md, entry.name)
    return SkillInfo(
        id=skill_id,
        name=parsed["name"],
        path=str(entry),
        description=parsed["description"],
        description_full=parsed["description_full"],
        version=parsed["version"],
        owner=parsed["owner"],
        disable_model_invocation=parsed["disable_model_invocation"],
        allowed_tools=parsed["allowed_tools"],
        emoji=parsed["emoji"],
        archived=archived,
        runtime=runtime,
    )


def _scan_flat_root(
    root: Path,
    *,
    runtime: str,
    include_hidden: bool,
    include_archived: bool,
) -> list[SkillInfo]:
    skills: list[SkillInfo] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if name == ARCHIVE_DIR_NAME:
            continue
        if name.startswith(HIDDEN_DIR_PREFIX) and not include_hidden:
            continue
        info = _entry_to_info(entry, skill_id=name, archived=False, runtime=runtime)
        if info:
            skills.append(info)

    if include_archived:
        archive_root = root / ARCHIVE_DIR_NAME
        if archive_root.is_dir():
            for entry in sorted(archive_root.iterdir()):
                if not entry.is_dir():
                    continue
                info = _entry_to_info(
                    entry, skill_id=entry.name, archived=True, runtime=runtime
                )
                if info:
                    skills.append(info)
    return skills


def _scan_nested_root(
    root: Path,
    *,
    runtime: str,
    include_hidden: bool,
    include_archived: bool,
) -> list[SkillInfo]:
    """Hermes 技能常为 category/skill/SKILL.md 嵌套结构。"""
    skills: list[SkillInfo] = []
    skip_names = {".git", "node_modules", "__pycache__"}
    for skill_md in sorted(root.rglob("SKILL.md")):
        entry = skill_md.parent
        rel = entry.relative_to(root)
        parts = rel.parts
        if any(p in skip_names for p in parts):
            continue
        archived = (
            ARCHIVE_DIR_NAME in parts
            or any(p.startswith(".archive") or p == ".archive" for p in parts)
        )
        if archived and not include_archived:
            continue
        if any(p.startswith(HIDDEN_DIR_PREFIX) for p in parts) and not include_hidden:
            # 允许 .archive 走 archived 分支；其它隐藏目录按开关
            if not archived:
                continue
        skill_id = rel.as_posix()
        # archived 路径去掉 archive 前缀，便于展示
        if archived:
            cleaned = [p for p in parts if p not in {ARCHIVE_DIR_NAME, ".archive"}]
            skill_id = "/".join(cleaned) if cleaned else entry.name
        info = _entry_to_info(
            entry, skill_id=skill_id, archived=archived, runtime=runtime
        )
        if info:
            skills.append(info)
    return skills


def scan_skills(
    skills_dir: str | None = None,
    *,
    include_hidden: bool = False,
    include_archived: bool = False,
    runtime: str = "openclaw",
) -> list[SkillInfo]:
    run_id = uuid.uuid4().hex[:8]
    t0 = time.perf_counter()
    root = (
        _hermes_skills_root(skills_dir)
        if runtime == "hermes"
        else _default_skills_root(skills_dir)
    )

    if not root.is_dir():
        logger.info(
            "skills scan skip run_id=%s runtime=%s reason=dir_missing root=%s",
            run_id,
            runtime,
            root,
        )
        return []

    if runtime == "hermes":
        skills = _scan_nested_root(
            root,
            runtime=runtime,
            include_hidden=include_hidden,
            include_archived=include_archived,
        )
    else:
        skills = _scan_flat_root(
            root,
            runtime=runtime,
            include_hidden=include_hidden,
            include_archived=include_archived,
        )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "skills scanned run_id=%s runtime=%s count=%d include_hidden=%s "
        "include_archived=%s elapsed_ms=%d root=%s",
        run_id,
        runtime,
        len(skills),
        include_hidden,
        include_archived,
        elapsed_ms,
        root,
    )
    return skills


def scan_all_skills(
    *,
    openclaw_dir: str | None = None,
    hermes_dir: str | None = None,
    include_hidden: bool = False,
    include_archived: bool = False,
    runtimes: list[str] | None = None,
) -> list[SkillInfo]:
    enabled = runtimes or ["openclaw", "hermes"]
    out: list[SkillInfo] = []
    if "openclaw" in enabled:
        out.extend(
            scan_skills(
                openclaw_dir,
                include_hidden=include_hidden,
                include_archived=include_archived,
                runtime="openclaw",
            )
        )
    if "hermes" in enabled:
        out.extend(
            scan_skills(
                hermes_dir,
                include_hidden=include_hidden,
                include_archived=include_archived,
                runtime="hermes",
            )
        )
    return out


def get_skill(
    skill_id: str,
    skills_dir: str | None = None,
    *,
    include_archived: bool = True,
    runtime: str = "openclaw",
    hermes_skills_dir: str | None = None,
) -> SkillDetail | None:
    root = (
        _hermes_skills_root(hermes_skills_dir or skills_dir)
        if runtime == "hermes"
        else _default_skills_root(skills_dir)
    )
    # 禁止路径穿越
    if ".." in skill_id.split("/"):
        return None

    candidates = [root / skill_id]
    if include_archived:
        candidates.append(root / ARCHIVE_DIR_NAME / skill_id)
        candidates.append(root / ".archive" / skill_id)

    for entry in candidates:
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        parsed = _parse_skill_file(skill_md, entry.name)
        archived = ARCHIVE_DIR_NAME in entry.parts or ".archive" in entry.parts
        return SkillDetail(
            id=skill_id,
            name=parsed["name"],
            path=str(entry),
            description=parsed["description"],
            description_full=parsed["description_full"],
            version=parsed["version"],
            owner=parsed["owner"],
            disable_model_invocation=parsed["disable_model_invocation"],
            allowed_tools=parsed["allowed_tools"],
            emoji=parsed["emoji"],
            archived=archived,
            runtime=runtime,
            body_preview=parsed["body"][:BODY_PREVIEW_CHARS],
            skill_md_path=str(skill_md),
        )
    return None


def archive_skill(
    skill_id: str,
    skills_dir: str | None = None,
    *,
    runtime: str = "openclaw",
    hermes_skills_dir: str | None = None,
) -> SkillDetail:
    """将技能目录移动到 `_archive/`（下线）。支持 OpenClaw 扁平与 Hermes 嵌套路径。"""
    run_id = uuid.uuid4().hex[:8]
    if not skill_id or skill_id.startswith(HIDDEN_DIR_PREFIX) or ".." in skill_id.split("/"):
        raise ValueError(f"invalid skill_id: {skill_id}")
    if runtime not in ("openclaw", "hermes"):
        raise ValueError("runtime must be openclaw|hermes")

    root = (
        _hermes_skills_root(hermes_skills_dir or skills_dir)
        if runtime == "hermes"
        else _default_skills_root(skills_dir)
    )
    src = root / skill_id
    if not src.is_dir() or not (src / "SKILL.md").is_file():
        raise FileNotFoundError(f"skill not found: {skill_id}")

    archive_root = root / ARCHIVE_DIR_NAME
    dest = archive_root / skill_id
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"archive already exists: {dest}")

    logger.info(
        "skills archive start run_id=%s runtime=%s skill_id=%s src=%s dest=%s",
        run_id,
        runtime,
        skill_id,
        src,
        dest,
    )
    shutil.move(str(src), str(dest))
    # 清理 Hermes 空 category 目录
    if runtime == "hermes":
        parent = src.parent
        try:
            if parent != root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass

    detail = get_skill(
        skill_id,
        skills_dir,
        include_archived=True,
        runtime=runtime,
        hermes_skills_dir=hermes_skills_dir,
    )
    if not detail:
        raise RuntimeError(f"archive moved but skill unreadable: {skill_id}")
    logger.info(
        "skills archive done run_id=%s runtime=%s skill_id=%s path=%s",
        run_id,
        runtime,
        skill_id,
        detail.path,
    )
    return detail


async def install_hermes_skill(
    identifier: str,
    *,
    executable: str = "hermes",
    hermes_home: str = "",
    category: str = "",
    name: str = "",
    force: bool = False,
    mock: bool = False,
) -> tuple[bool, str]:
    """调用 `hermes skills install`。返回 (ok, message)。"""
    run_id = uuid.uuid4().hex[:8]
    ident = (identifier or "").strip()
    if not ident:
        raise ValueError("identifier required")

    if mock:
        msg = f"[mock] hermes skills install {ident}"
        logger.info("skills hermes install mock run_id=%s %s", run_id, msg)
        return True, msg

    if not shutil.which(executable):
        return False, f"hermes executable not found: {executable}"

    args = [executable, "skills", "install", ident, "-y"]
    if category:
        args.extend(["--category", category])
    if name:
        args.extend(["--name", name])
    if force:
        args.append("--force")

    env = os.environ.copy()
    if hermes_home:
        env["HERMES_HOME"] = os.path.expanduser(hermes_home)

    logger.info("skills hermes install start run_id=%s cmd=%s", run_id, " ".join(args))
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        logger.error("skills hermes install timeout run_id=%s", run_id)
        return False, "hermes skills install timed out"

    out = stdout.decode("utf-8", errors="replace").strip()
    err = stderr.decode("utf-8", errors="replace").strip()
    text = out or err
    ok = (proc.returncode or 0) == 0
    logger.info(
        "skills hermes install done run_id=%s ok=%s exit=%s",
        run_id,
        ok,
        proc.returncode,
    )
    return ok, text or ("ok" if ok else "install failed")
