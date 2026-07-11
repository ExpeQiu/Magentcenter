"""技能目录扫描模块。"""

import logging
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class SkillInfo(BaseModel):
    id: str
    name: str
    path: str
    description: str = ""


def _parse_skill_md(skill_md: Path) -> str:
    try:
        text = skill_md.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line[:200]
        if text:
            return text.splitlines()[0].lstrip("# ").strip()[:200]
    except OSError:
        pass
    return ""


def scan_skills(skills_dir: str | None = None) -> list[SkillInfo]:
    if skills_dir:
        root = Path(skills_dir).expanduser()
    else:
        root = Path.home() / ".openclaw" / "skills"

    if not root.is_dir():
        logger.info("skills directory not found: %s", root)
        return []

    skills: list[SkillInfo] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        skills.append(
            SkillInfo(
                id=entry.name,
                name=entry.name,
                path=str(entry),
                description=_parse_skill_md(skill_md),
            )
        )
    logger.info("scanned %d skills from %s", len(skills), root)
    return skills
