"""技能扫描解析单测。"""

from pathlib import Path

from app.core.skills import (
    _parse_skill_file,
    _short_description,
    archive_skill,
    scan_skills,
)


def test_short_description_strips_when_to_use():
    raw = (
        'Route requests into ACP sessions. | When to use: user asks to run code. '
        "| NOT for: general coding."
    )
    assert _short_description(raw) == "Route requests into ACP sessions."
    zh = "工具集（Python 实现）。| When to use: 需要执行 Shell"
    assert _short_description(zh) == "工具集（Python 实现）。"


def test_parse_frontmatter(tmp_path: Path):
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(
        """---
name: demo-skill
description: "Do useful work. | When to use: always."
version: "1.2.0"
owner: "coder"
disable-model-invocation: true
allowed-tools:
  - read
  - exec
metadata:
  openclaw:
    emoji: "🧩"
---

# Demo

Body here.
""",
        encoding="utf-8",
    )
    parsed = _parse_skill_file(skill_md, "demo-skill")
    assert parsed["name"] == "demo-skill"
    assert parsed["description"] == "Do useful work."
    assert "When to use" in parsed["description_full"]
    assert parsed["version"] == "1.2.0"
    assert parsed["owner"] == "coder"
    assert parsed["disable_model_invocation"] is True
    assert parsed["allowed_tools"] == ["read", "exec"]
    assert parsed["emoji"] == "🧩"
    assert parsed["body"].startswith("# Demo")


def test_scan_hides_underscore_dirs(tmp_path: Path):
    (tmp_path / "_templates").mkdir()
    (tmp_path / "_templates" / "SKILL.md").write_text(
        "---\nname: tpl\ndescription: x\n---\n", encoding="utf-8"
    )
    active = tmp_path / "real-skill"
    active.mkdir()
    (active / "SKILL.md").write_text(
        "---\nname: Real\ndescription: hello world\n---\n# Hi\n",
        encoding="utf-8",
    )
    skills = scan_skills(str(tmp_path))
    assert [s.id for s in skills] == ["real-skill"]
    assert skills[0].name == "Real"
    assert skills[0].description == "hello world"


def test_archive_hermes_nested(tmp_path: Path):
    skill = tmp_path / "research" / "demo-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: Demo\ndescription: nested hermes skill\n---\n# Demo\n",
        encoding="utf-8",
    )
    detail = archive_skill(
        "research/demo-skill",
        runtime="hermes",
        hermes_skills_dir=str(tmp_path),
    )
    assert detail.archived is True
    assert detail.runtime == "hermes"
    assert not skill.exists()
    archived = tmp_path / "_archive" / "research" / "demo-skill" / "SKILL.md"
    assert archived.is_file()
    active = scan_skills(str(tmp_path), runtime="hermes")
    assert all(s.id != "research/demo-skill" for s in active)
    all_skills = scan_skills(str(tmp_path), runtime="hermes", include_archived=True)
    assert any(s.id == "research/demo-skill" and s.archived for s in all_skills)
