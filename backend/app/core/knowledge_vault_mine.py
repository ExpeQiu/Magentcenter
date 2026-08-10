"""从 Outputs vault（默认 openclaw/）挖掘知识卡片。

策略：全量建 ArtifactRef（路径+摘要）；高价值文档额外蒸馏
Playbook / Incident / SharedFact。不把整库原文灌进检索。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings
from app.core.knowledge import (
    create_entry,
    KnowledgeEntryCreate,
    redact_secrets,
    upsert_artifact_ref,
    upsert_incident_from_alert,
)
from app.core.outputs_vault import IGNORE_NAMES, infer_source, resolve_path

logger = logging.getLogger(__name__)

TEXT_EXTS = {".md", ".markdown", ".html", ".htm", ".txt"}
SKIP_DIR_PARTS = frozenset(
    {
        "node_modules",
        ".git",
        ".obsidian",
        ".clawhub",
        ".openclaw",
        ".openclaw-ops",
        "__pycache__",
        ".trash",
        "svg-convert",
    }
)

# 相对 vault 的优先子树（分数越高越先入库）
PRIORITY_PREFIXES: list[tuple[str, int]] = [
    ("openclaw/0团队通用规则", 100),
    ("openclaw/fangfa/自主进化虚拟组织/高难度案例库", 95),
    ("openclaw/fangfa", 80),
    ("openclaw/知识库", 85),
    ("openclaw/情报中心", 70),
    ("openclaw/skills", 65),
    ("openclaw/HermesCenter/技术推广", 60),
    ("openclaw/千岛湖团队", 50),
    ("openclaw/小二团队", 50),
    ("openclaw", 10),
]

HIGH_VALUE_NAME_RE = re.compile(
    r"(CASE[-_]|SOP|_SOP|约定|规则|总纲|原理|手册|健康维护|故障排查|SKILL\.md$)",
    re.IGNORECASE,
)


@dataclass
class MineResult:
    scanned: int = 0
    artifact_refs: int = 0
    playbooks: int = 0
    incidents: int = 0
    shared_facts: int = 0
    skipped: int = 0
    errors: int = 0


def _priority(rel: str) -> int:
    rel_n = rel.replace("\\", "/")
    score = 0
    for prefix, pts in PRIORITY_PREFIXES:
        if rel_n == prefix or rel_n.startswith(prefix + "/"):
            score = max(score, pts)
    name = Path(rel_n).name
    if HIGH_VALUE_NAME_RE.search(name) or HIGH_VALUE_NAME_RE.search(rel_n):
        score += 25
    if name.upper() == "SKILL.MD":
        score += 15
    if "node_modules" in rel_n:
        score = -999
    return score


def _should_skip(rel: str) -> bool:
    parts = rel.replace("\\", "/").split("/")
    if any(p in SKIP_DIR_PARTS or p in IGNORE_NAMES for p in parts):
        return True
    if any(p.startswith(".") for p in parts[1:]):  # 隐藏目录
        return True
    return False


def _summary_from_text(text: str, limit: int = 360) -> str:
    text = redact_secrets(text or "")
    # 去 frontmatter
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            text = text[end + 4 :]
    lines: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            if lines:
                break
            continue
        if s.startswith("#"):
            s = s.lstrip("#").strip()
        if s.startswith("```") or s.startswith("|---"):
            continue
        lines.append(s)
        if sum(len(x) for x in lines) >= limit:
            break
    out = " ".join(lines)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:limit]


def _title_from_file(path: Path, text: str) -> str:
    for ln in (text or "").splitlines()[:30]:
        s = ln.strip()
        if s.startswith("# "):
            return s[2:].strip()[:120]
        if s.startswith("name:") and path.name.upper() == "SKILL.MD":
            return s.split(":", 1)[1].strip().strip("\"'")[:120]
    return path.stem[:120]


def _tags_for(rel: str, name: str) -> list[str]:
    tags = ["vault", "openclaw-doc"]
    parts = rel.replace("\\", "/").split("/")
    if len(parts) >= 2:
        tags.append(parts[1][:40])
    if "CASE" in name.upper() or "/高难度案例库/" in rel:
        tags.append("case")
    if "SOP" in name.upper() or "/SOP/" in rel:
        tags.append("sop")
    if name.upper() == "SKILL.MD":
        tags.append("skill")
    if "HermesCenter" in parts:
        tags.append("hermes")
    if "0团队通用规则" in parts:
        tags.append("governance")
    return tags


def _collect_candidates(scope: str, limit: int) -> list[tuple[int, str, Path]]:
    scope = (scope or "openclaw").strip().strip("/")
    root = resolve_path(scope, expect="dir")
    settings_root = resolve_path("", expect="dir")
    cands: list[tuple[int, str, Path]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            rel = p.resolve().relative_to(settings_root.resolve()).as_posix()
        except ValueError:
            continue
        if _should_skip(rel):
            continue
        score = _priority(rel)
        if score < 0:
            continue
        # mtime 微调：越新略优先
        try:
            score += min(10, int(p.stat().st_mtime) % 10)
        except OSError:
            pass
        cands.append((score, rel, p))
    cands.sort(key=lambda x: (-x[0], x[1]))
    return cands[: max(1, min(limit, 2000))]


def _is_case(rel: str, name: str) -> bool:
    return "CASE-" in name.upper() or "/高难度案例库/" in rel.replace("\\", "/")


def _is_sop(rel: str, name: str) -> bool:
    u = name.upper()
    return "SOP" in u or "/SOP/" in rel.replace("\\", "/")


def _is_governance(rel: str) -> bool:
    return "0团队通用规则" in rel.replace("\\", "/")


async def mine_vault_docs(
    *,
    scope: str = "openclaw",
    limit: int = 300,
    distill_high_value: bool = True,
    workspace_id: str = "",
) -> dict:
    """扫描 vault 并写入知识库。"""
    settings = get_settings()
    from app.core.outputs_vault import vault_status

    st = vault_status(settings)
    if not st.get("readable"):
        raise RuntimeError(st.get("message") or "vault 不可读")

    result = MineResult()
    cands = _collect_candidates(scope, limit)
    result.scanned = len(cands)
    logger.info(
        "knowledge vault mine start scope=%s candidates=%d distill=%s",
        scope,
        len(cands),
        distill_high_value,
    )

    for score, rel, path in cands:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")[:12000]
        except OSError as e:
            logger.warning("vault mine read fail path=%s err=%s", rel, e)
            result.errors += 1
            continue

        summary = _summary_from_text(raw)
        if len(summary) < 12:
            result.skipped += 1
            continue

        title = _title_from_file(path, raw)
        tags = _tags_for(rel, path.name)
        runtime = "hermes" if infer_source(rel) == "hermes" else "openclaw"
        structure = f"priority={score}; vault={rel}"

        try:
            await upsert_artifact_ref(
                path=rel,
                title=title,
                summary=summary,
                runtime=runtime,
                workspace_id=workspace_id,
                tags=tags,
                structure_notes=structure,
            )
            result.artifact_refs += 1
        except Exception as e:
            logger.warning("artifact_ref fail path=%s: %s", rel, e)
            result.errors += 1
            continue

        if not distill_high_value:
            continue

        try:
            if _is_case(rel, path.name):
                await upsert_incident_from_alert(
                    alert_key=f"vault-case:{rel}",
                    title=f"Incident · {title}",
                    symptom=summary[:200],
                    root_cause=summary[:400],
                    fix=f"详见文档 {rel}",
                    cron_id="",
                    runtime=runtime,
                    workspace_id=workspace_id,
                )
                result.incidents += 1
            elif _is_sop(rel, path.name) or path.name.upper() == "SKILL.MD":
                steps = [
                    ln.lstrip("#*- ").strip()
                    for ln in raw.splitlines()
                    if ln.strip().startswith(("- ", "* ", "1.", "2.", "3."))
                ][:8]
                if not steps:
                    steps = [summary[:120]]
                await create_entry(
                    KnowledgeEntryCreate(
                        kind="playbook",
                        title=f"Playbook · {title}"[:120],
                        summary=summary,
                        workspace_id=workspace_id,
                        runtime=runtime,
                        source_type="outputs",
                        source_id=f"vault-playbook:{rel}",
                        tags=tags + ["playbook"],
                        payload={
                            "problem": title,
                            "steps": steps,
                            "outcome": summary[:200],
                            "pitfalls": [],
                            "source_refs": {"path": rel},
                        },
                    )
                )
                result.playbooks += 1
            elif _is_governance(rel) and path.name.endswith(".md"):
                # 总纲/原理 → 共享事实
                if any(
                    k in path.name or k in title
                    for k in ("总纲", "原理", "规范", "约定", "README")
                ) or path.name in ("0总纲.md",):
                    await create_entry(
                        KnowledgeEntryCreate(
                            kind="shared_fact",
                            title=title,
                            summary=summary,
                            workspace_id=workspace_id,
                            runtime=runtime,
                            source_type="outputs",
                            source_id=f"vault-fact:{rel}",
                            tags=tags + ["shared_fact"],
                            payload={"body": summary, "path": rel},
                        )
                    )
                    result.shared_facts += 1
        except Exception as e:
            logger.warning("vault distill fail path=%s: %s", rel, e)
            result.errors += 1

    out = {
        "status": "ok",
        "scope": scope,
        "scanned": result.scanned,
        "artifact_refs": result.artifact_refs,
        "playbooks": result.playbooks,
        "incidents": result.incidents,
        "shared_facts": result.shared_facts,
        "skipped": result.skipped,
        "errors": result.errors,
    }
    logger.info("knowledge vault mine done %s", out)
    return out
