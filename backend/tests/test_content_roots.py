"""知识库与技能读取目录。"""

import asyncio
from pathlib import Path

import pytest

from app.core import content_roots
from app.core.knowledge import list_entries, search_knowledge
from app.core.outputs_vault import list_dir, vault_status
from app.core.wiki_files import get_wiki_hit
from app.models.db import create_tables, init_db


def test_relative_path_rejected():
    with pytest.raises(ValueError):
        content_roots.clean_dir("personalwiki")


def test_override_then_reset(tmp_path: Path, monkeypatch):
    store = tmp_path / "content_roots.json"
    monkeypatch.setattr(content_roots, "roots_path", lambda: store)
    wiki = tmp_path / "wiki"
    skills = tmp_path / "skills"
    wiki.mkdir()
    skills.mkdir()
    saved = content_roots.update(
        knowledge_wiki_dir=str(wiki),
        skills_catalog_dir=str(skills),
    )
    assert saved["knowledge_wiki_dir"] == str(wiki.resolve())
    assert saved["skills"]["exists"] is True
    reset = content_roots.update(knowledge_wiki_dir="", skills_catalog_dir="")
    assert reset["knowledge_wiki_dir"] == content_roots.wiki_dir()
    assert reset["knowledge_wiki_dir"] != str(wiki.resolve())
    assert "knowledge_wiki_dir" not in store.read_text(encoding="utf-8")


def test_wiki_markdown_is_listed(tmp_path: Path, monkeypatch):
    init_db(f"sqlite+aiosqlite:///{tmp_path}/wiki.db")
    asyncio.run(create_tables())
    root = tmp_path / "personalwiki"
    folder = root / "decisions"
    folder.mkdir(parents=True)
    (folder / "ship.md").write_text("# 发布节奏\n\n先灰度再全量。\n", encoding="utf-8")
    monkeypatch.setattr("app.core.wiki_files.wiki_dir", lambda: str(root))

    hits = asyncio.run(list_entries(limit=20))
    assert any(hit.id == "wiki:decisions/ship.md" and hit.layer == "L2" for hit in hits)

    found = asyncio.run(search_knowledge("灰度", limit=10, auto_backfill=False))
    assert any(hit.source_id == "decisions/ship.md" for hit in found)

    detail = get_wiki_hit("wiki:decisions/ship.md")
    assert detail is not None
    assert "先灰度" in detail.payload["body"]
    assert get_wiki_hit("wiki:../secret.md") is None


def test_outputs_override_is_what_vault_reads(tmp_path: Path, monkeypatch):
    store = tmp_path / "content_roots.json"
    monkeypatch.setattr(content_roots, "roots_path", lambda: store)
    vault = tmp_path / "expe"
    (vault / "openclaw").mkdir(parents=True)
    (vault / "openclaw" / "note.md").write_text("vault note\n", encoding="utf-8")
    content_roots.update(outputs_vault_dir=str(vault))
    status = vault_status()
    assert status["readable"] is True
    assert status["root_name"] == "expe"
    names = {item.name for item in list_dir("")}
    assert "openclaw" in names
    content_roots.update(outputs_vault_dir="")
    assert content_roots.outputs_dir().endswith("Documents/expe")
