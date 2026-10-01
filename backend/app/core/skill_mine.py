"""技能自挖掘：捕获、规则提炼、验证、检索。正文在技能目录，账本在 SQLite。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.core.knowledge import _upsert_entry, redact_secrets
from app.core.skills import (
    _default_skills_root,
    _hermes_skills_root,
    archive_skill,
)
from app.core.text_embed import cosine, embed_text, hash_embed
from app.core.wiki_layers import (
    explicit_skill_request,
    layer_weight,
    namespaced_tags,
    positive_feedback,
)
from app.models.db import SkillRecord, get_session_factory

logger = logging.getLogger(__name__)

CAPTURED_DIR = "_captured"
SKILL_MARK = re.compile(r"<!--\s*skills:\s*([^>]+)\s*-->")
_CLASS_LAYER = {"decision": "L2", "flow": "L3", "data": "L1"}


def _root(runtime: str, skills_dir: str | None, hermes_dir: str | None) -> Path:
    if runtime == "hermes":
        return _hermes_skills_root(hermes_dir or skills_dir)
    return _default_skills_root(skills_dir)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slug(summary: str, capture_id: str) -> str:
    words = re.findall(r"[A-Za-z0-9]{3,}", summary or "")
    base = "-".join(w.lower() for w in words[:4]) or "mined"
    digest = hashlib.sha1(capture_id.encode()).hexdigest()[:8]
    return f"{base}-{digest}"[:64]


def _skill_class(text: str) -> str:
    if re.search(r"决策|原则|拍板", text or ""):
        return "decision"
    if re.search(r"事实|数据|偏好", text or ""):
        return "data"
    return "flow"


def _steps_from_output(output: str) -> list[str]:
    lines = [ln.strip(" -*\t") for ln in (output or "").splitlines() if ln.strip()]
    steps = [ln for ln in lines if len(ln) >= 8][:8]
    if not steps and (output or "").strip():
        steps = [re.sub(r"\s+", " ", output.strip())[:200]]
    return steps


def _confidence(steps: list[str], prompt: str, result: str) -> float:
    if len(steps) >= 2 and prompt.strip() and result.strip():
        return 0.85
    if steps and prompt.strip():
        return 0.6
    return 0.4


def _set_status(skill_md: Path, status: str) -> None:
    text = skill_md.read_text(encoding="utf-8")
    if re.search(r"(?m)^status:", text):
        text = re.sub(r"(?m)^status:.*$", f"status: {status}", text, count=1)
    elif text.startswith("---"):
        text = text.replace("---\n", f"---\nstatus: {status}\n", 1)
    skill_md.write_text(text, encoding="utf-8")


def _write_skill_md(
    directory: Path,
    *,
    name: str,
    description: str,
    skill_class: str,
    manifest: dict[str, Any],
    steps: list[str],
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    step_lines = "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1)) or "1. 按来源会话重做"
    body = f"""---
name: {name}
description: "{description.replace('"', "'")[:180]}"
status: draft
metadata:
  agentcenter:
    class: {skill_class}
    source_task: {manifest.get("task_id") or ""}
    source_session: {manifest.get("session_id") or ""}
---

# Skill: {name}

## 触发场景
{manifest.get("task_summary") or description}

## 输入
{manifest.get("user_prompt") or "与来源任务相同的问题"}

## 执行步骤
{step_lines}

## 输出
{(manifest.get("result") or "")[:400]}

## 来源
- 原始会话：{manifest.get("session_id") or ""}
- 任务：{manifest.get("task_id") or ""}
- 提炼日期：{_now()[:10]}
- 验证次数：0
"""
    (directory / "SKILL.md").write_text(body, encoding="utf-8")
    examples = directory / "examples"
    examples.mkdir(exist_ok=True)
    prompt = manifest.get("user_prompt") or ""
    (examples / "source.md").write_text(f"# 来源\n\n{prompt}\n", encoding="utf-8")


async def _upsert_record(**fields: Any) -> SkillRecord:
    factory = get_session_factory()
    async with factory() as session:
        existing = (
            await session.execute(
                select(SkillRecord).where(
                    SkillRecord.name == fields["name"],
                    SkillRecord.runtime == fields["runtime"],
                )
            )
        ).scalar_one_or_none()
        if existing:
            for key, value in fields.items():
                if key in {"name", "runtime"}:
                    continue
                setattr(existing, key, value)
            existing.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(existing)
            return existing
        rec = SkillRecord(id=str(uuid.uuid4()), **fields)
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
        return rec


def _record_dict(rec: SkillRecord) -> dict[str, Any]:
    return {
        "id": rec.id,
        "name": rec.name,
        "runtime": rec.runtime,
        "description": rec.description or "",
        "status": rec.status,
        "skill_class": rec.skill_class or "flow",
        "source_task": rec.source_task or "",
        "source_session": rec.source_session or "",
        "wiki_ref": rec.wiki_ref or "",
        "capture_id": rec.capture_id or "",
        "usage_count": rec.usage_count or 0,
        "success_rate": rec.success_rate or 0.0,
        "fail_count": rec.fail_count or 0,
    }


async def capture_task(
    *,
    task_id: str,
    prompt: str,
    output: str,
    error: str = "",
    agent_id: str = "",
    runtime: str = "openclaw",
    session_id: str = "",
    status: str = "",
    workspace_id: str = "",
    tools_used: list[str] | None = None,
    duration_ms: int = 0,
    skills_dir: str | None = None,
    hermes_skills_dir: str | None = None,
) -> dict[str, Any]:
    """任务收尾写快照。只有显式「做成技能」才提炼。"""
    if status not in ("completed", "failed", "timeout"):
        return {}
    runtime = runtime if runtime in ("openclaw", "hermes") else "openclaw"
    root = _root(runtime, skills_dir, hermes_skills_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    digest = hashlib.sha1(f"{task_id}:{stamp}".encode()).hexdigest()[:8]
    capture_id = f"cap_{stamp}_{digest}"
    feedback_src = f"{prompt}\n{output}"
    explicit = explicit_skill_request(feedback_src)
    manifest = {
        "capture_id": capture_id,
        "timestamp": _now(),
        "session_id": session_id,
        "agent": agent_id,
        "task_id": task_id,
        "runtime": runtime,
        "workspace_id": workspace_id,
        "status": status,
        "task_summary": redact_secrets(re.sub(r"\s+", " ", prompt or "")[:160]),
        "user_prompt": redact_secrets(prompt or "")[:4000],
        "tools_used": tools_used or [],
        "steps": _steps_from_output(output or error),
        "result": redact_secrets((output or error or "")[:4000]),
        "user_feedback": positive_feedback(feedback_src),
        "explicit": explicit,
        "refined": False,
        "duration_sec": int((duration_ms or 0) / 1000),
    }
    folder = root / CAPTURED_DIR / f"{stamp}-{digest}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "skill captured id=%s task=%s runtime=%s explicit=%s path=%s",
        capture_id,
        task_id,
        runtime,
        explicit,
        path,
    )
    refined = None
    if explicit:
        refined = await refine_capture(
            capture_id,
            skills_dir=skills_dir,
            hermes_skills_dir=hermes_skills_dir,
        )
    return {"capture_id": capture_id, "explicit": explicit, "refined": refined, "path": str(path)}


def list_captured(
    *,
    skills_dir: str | None = None,
    hermes_skills_dir: str | None = None,
    runtime: str | None = None,
) -> list[dict[str, Any]]:
    runtimes = [runtime] if runtime in ("openclaw", "hermes") else ["openclaw", "hermes"]
    found: list[dict[str, Any]] = []
    for rt in runtimes:
        root = _root(rt, skills_dir, hermes_skills_dir) / CAPTURED_DIR
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir(), reverse=True):
            manifest_path = folder / "manifest.json"
            if not manifest_path.is_file():
                continue
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("skill capture read failed path=%s err=%s", manifest_path, exc)
                continue
            if not isinstance(data, dict):
                continue
            data["path"] = str(manifest_path)
            data.setdefault("runtime", rt)
            found.append(data)
    logger.info("skill captured list count=%d runtime=%s", len(found), runtime or "all")
    return found


def _load_manifest(
    capture_id: str,
    *,
    skills_dir: str | None,
    hermes_skills_dir: str | None,
) -> tuple[dict[str, Any], Path]:
    for item in list_captured(skills_dir=skills_dir, hermes_skills_dir=hermes_skills_dir):
        if item.get("capture_id") == capture_id:
            path = Path(item["path"])
            return item, path
    raise FileNotFoundError(f"capture not found: {capture_id}")


async def refine_capture(
    capture_id: str,
    *,
    skills_dir: str | None = None,
    hermes_skills_dir: str | None = None,
) -> dict[str, Any]:
    """用规则模板把快照写成 draft。置信度不够也留在 draft，不进入可调用列表。"""
    manifest, manifest_path = _load_manifest(
        capture_id, skills_dir=skills_dir, hermes_skills_dir=hermes_skills_dir
    )
    runtime = manifest.get("runtime") or "openclaw"
    steps = list(manifest.get("steps") or [])
    summary = manifest.get("task_summary") or capture_id
    confidence = _confidence(steps, manifest.get("user_prompt") or "", manifest.get("result") or "")
    name = _slug(summary, capture_id)
    skill_class = _skill_class(summary)
    description = re.sub(r"\s+", " ", summary)[:160]
    root = _root(runtime, skills_dir, hermes_skills_dir)
    directory = root / name
    _write_skill_md(
        directory,
        name=name,
        description=description,
        skill_class=skill_class,
        manifest=manifest,
        steps=steps,
    )
    tags = namespaced_tags(src="skill", facet="tools", topic=name)
    wiki_id = await _upsert_entry(
        kind="playbook",
        layer="L3",
        facet="tools",
        source_type="skill",
        source_id=f"skill:{runtime}:{name}",
        title=f"技能 · {name}",
        content=redact_secrets(description),
        runtime=runtime,
        session_id=manifest.get("session_id") or "",
        status="active",
        workspace_id=manifest.get("workspace_id") or "",
        tags=tags,
        payload={
            "skill": name,
            "runtime": runtime,
            "pointer": True,
            "summary": description,
            "task_id": manifest.get("task_id") or "",
        },
    )
    blob = json.dumps(await embed_text(f"{name}\n{description}"), separators=(",", ":"))
    rec = await _upsert_record(
        name=name,
        runtime=runtime,
        description=description,
        trigger_keywords=description,
        status="draft",
        skill_class=skill_class,
        source_task=manifest.get("task_id") or "",
        source_session=manifest.get("session_id") or "",
        wiki_ref=wiki_id,
        capture_id=capture_id,
        usage_count=0,
        success_rate=0.0,
        success_count=0,
        fail_count=0,
        embedding_json=blob,
    )
    manifest["refined"] = True
    manifest["skill_name"] = name
    manifest["confidence"] = confidence
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "skill refined capture=%s name=%s confidence=%.2f wiki=%s status=draft",
        capture_id,
        name,
        confidence,
        wiki_id,
    )
    out = _record_dict(rec)
    out["confidence"] = confidence
    out["path"] = str(directory / "SKILL.md")
    return out


async def verify_skill(
    name: str,
    *,
    runtime: str = "openclaw",
    skills_dir: str | None = None,
    hermes_skills_dir: str | None = None,
) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        rec = (
            await session.execute(
                select(SkillRecord).where(SkillRecord.name == name, SkillRecord.runtime == runtime)
            )
        ).scalar_one_or_none()
        if rec is None:
            raise FileNotFoundError(f"skill record not found: {name}")
        rec.status = "verified"
        rec.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(rec)
        data = _record_dict(rec)
    skill_md = _root(runtime, skills_dir, hermes_skills_dir) / name / "SKILL.md"
    if skill_md.is_file():
        _set_status(skill_md, "verified")
    logger.info("skill verified name=%s runtime=%s", name, runtime)
    return data


async def reject_skill(
    name: str,
    *,
    runtime: str = "openclaw",
    skills_dir: str | None = None,
    hermes_skills_dir: str | None = None,
) -> dict[str, Any]:
    """失败加一。满 3 次移入 _archive。"""
    factory = get_session_factory()
    async with factory() as session:
        rec = (
            await session.execute(
                select(SkillRecord).where(SkillRecord.name == name, SkillRecord.runtime == runtime)
            )
        ).scalar_one_or_none()
        if rec is None:
            raise FileNotFoundError(f"skill record not found: {name}")
        rec.fail_count = int(rec.fail_count or 0) + 1
        archived = rec.fail_count >= 3
        if archived:
            rec.status = "archived"
        rec.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(rec)
        data = _record_dict(rec)
    if data["fail_count"] >= 3:
        try:
            archive_skill(
                name,
                skills_dir,
                runtime=runtime,
                hermes_skills_dir=hermes_skills_dir,
            )
        except FileNotFoundError:
            logger.warning("skill archive missing on disk name=%s", name)
        except FileExistsError:
            logger.warning("skill archive already exists name=%s", name)
        logger.info("skill archived after 3 failures name=%s runtime=%s", name, runtime)
    else:
        logger.info(
            "skill verify failed name=%s runtime=%s fail_count=%s",
            name,
            runtime,
            data["fail_count"],
        )
    data["archived"] = data["status"] == "archived"
    return data


def _parse_embed(raw: str) -> list[float]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [float(x) for x in data]
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return []


async def search_verified_skills(
    query: str,
    *,
    runtime: str = "openclaw",
    top_k: int = 2,
) -> list[dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    q_vec = await embed_text(q)
    tokens = [t for t in re.split(r"\s+", q.lower()) if t]
    if not tokens:
        tokens = [q.lower()]
    weights = get_settings().knowledge_layer_weights
    factory = get_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(SkillRecord).where(
                    SkillRecord.status == "verified",
                    SkillRecord.runtime == runtime,
                )
            )
        ).scalars().all()
    scored: list[tuple[float, SkillRecord]] = []
    for rec in rows:
        hay = f"{rec.name}\n{rec.description}\n{rec.trigger_keywords}".lower()
        kw = sum(1 for token in tokens if token in hay)
        if any(token in (rec.name or "").lower() for token in tokens):
            kw += 2
        emb = _parse_embed(rec.embedding_json or "")
        if emb and len(emb) == len(q_vec):
            vec = cosine(q_vec, emb)
        else:
            vec = cosine(hash_embed(q), hash_embed(hay))
        if kw <= 0 and vec <= 0:
            continue
        layer = _CLASS_LAYER.get(rec.skill_class or "flow", "L3")
        score = (kw + vec * 8.0) * layer_weight(layer, weights)
        scored.append((score, rec))
    scored.sort(key=lambda item: -item[0])
    hits = []
    for score, rec in scored[: max(1, top_k)]:
        item = _record_dict(rec)
        item["score"] = round(score, 4)
        hits.append(item)
    logger.info("skill search q=%r runtime=%s hits=%d", q[:80], runtime, len(hits))
    return hits


async def build_skill_inject_block(
    query: str,
    *,
    runtime: str,
    top_k: int = 2,
    openclaw_dir: str | None = None,
    hermes_dir: str | None = None,
) -> str:
    del openclaw_dir, hermes_dir
    hits = await search_verified_skills(query, runtime=runtime, top_k=top_k)
    if not hits:
        return ""
    names = ",".join(hit["name"] for hit in hits)
    lines = [
        "## 已验证技能（自动注入）",
        f"<!-- skills: {names} -->",
        "以下技能已通过验证，可沿用步骤。草稿技能不会出现在这里。",
        "",
    ]
    for hit in hits:
        lines.append(f"### [{hit['skill_class']}] {hit['name']}")
        if hit.get("description"):
            lines.append(str(hit["description"])[:240])
        lines.append("")
    return "\n".join(lines).strip()


async def record_skill_outcomes(system_prompt: str, *, success: bool, runtime: str) -> None:
    match = SKILL_MARK.search(system_prompt or "")
    if not match:
        return
    names = [part.strip() for part in match.group(1).split(",") if part.strip()]
    if not names:
        return
    factory = get_session_factory()
    async with factory() as session:
        for name in names:
            rec = (
                await session.execute(
                    select(SkillRecord).where(
                        SkillRecord.name == name,
                        SkillRecord.runtime == runtime,
                    )
                )
            ).scalar_one_or_none()
            if rec is None or rec.status != "verified":
                continue
            rec.usage_count = int(rec.usage_count or 0) + 1
            if success:
                rec.success_count = int(rec.success_count or 0) + 1
            total = rec.usage_count or 1
            rec.success_rate = (rec.success_count or 0) / total
            rec.updated_at = datetime.utcnow()
        await session.commit()
    logger.info(
        "skill outcomes runtime=%s success=%s names=%s",
        runtime,
        success,
        names,
    )
