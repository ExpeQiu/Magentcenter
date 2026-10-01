"""Wiki 层权重、旧 kind 映射、技能自挖掘。"""

import asyncio
from pathlib import Path

from app.core.knowledge import (
    _upsert_entry,
    backfill_layers,
    build_task_inject_context,
    search_knowledge,
)
from app.core.skill_mine import (
    build_skill_inject_block,
    capture_task,
    reject_skill,
    verify_skill,
)
from app.core.skills import scan_skills
from app.core.wiki_layers import explicit_skill_request, kind_to_layer
from app.models.db import KnowledgeRecord, create_tables, get_session_factory, init_db


def test_kind_maps_to_layer():
    assert kind_to_layer("playbook") == ("L3", "procedural")
    assert kind_to_layer("precedent") == ("L2", "experiences")
    assert kind_to_layer("incident") == ("L2", "reflections")
    assert kind_to_layer("archive") == ("notes", "notes")
    assert explicit_skill_request("请做成技能")
    assert not explicit_skill_request("好，收到")


def test_layer_weight_and_notes_hidden(tmp_path: Path):
    async def run() -> None:
        init_db(f"sqlite+aiosqlite:///{tmp_path}/wiki.db")
        await create_tables()
        body = "deploy checklist shared phrase"
        await _upsert_entry(
            kind="playbook",
            layer="L3",
            facet="procedural",
            source_type="manual",
            source_id="proc-1",
            title=body,
            content=body,
        )
        await _upsert_entry(
            kind="incident",
            layer="L2",
            facet="reflections",
            source_type="manual",
            source_id="ref-1",
            title=body,
            content=body,
        )
        await _upsert_entry(
            kind="archive",
            layer="notes",
            facet="notes",
            source_type="manual",
            source_id="note-1",
            title=body,
            content=body,
        )
        hits = await search_knowledge("deploy checklist", limit=5, auto_backfill=False)
        assert hits
        assert hits[0].layer == "L2"
        assert all(hit.layer != "notes" for hit in hits)
        block, injected = await build_task_inject_context("deploy checklist", top_k=5)
        assert "notes" not in {hit.layer for hit in injected}
        assert "L2" in block

        factory = get_session_factory()
        async with factory() as session:
            session.add(
                KnowledgeRecord(
                    id="old-1",
                    kind="playbook",
                    layer="",
                    facet="",
                    source_type="manual",
                    source_id="old-playbook",
                    title="legacy",
                    content="legacy body",
                )
            )
            await session.commit()
        filled = await backfill_layers()
        assert filled >= 1
        async with factory() as session:
            rec = await session.get(KnowledgeRecord, "old-1")
            assert rec is not None
            assert rec.layer == "L3"
            assert rec.facet == "procedural"

    asyncio.run(run())


def test_skill_mine_explicit_only_and_archive(tmp_path: Path):
    async def run() -> None:
        init_db(f"sqlite+aiosqlite:///{tmp_path}/skills.db")
        await create_tables()
        skills = tmp_path / "skills"
        skills.mkdir()

        plain = await capture_task(
            task_id="t-plain",
            prompt="好，收到",
            output="done with the report steps here",
            status="completed",
            runtime="openclaw",
            skills_dir=str(skills),
        )
        assert plain["explicit"] is False
        assert plain["refined"] is None
        assert scan_skills(str(skills)) == []

        mined = await capture_task(
            task_id="t-mine",
            prompt="请做成技能 orbit-report-skill",
            output="step one is long enough\nstep two is also long enough",
            status="completed",
            runtime="openclaw",
            skills_dir=str(skills),
        )
        assert mined["explicit"] is True
        refined = mined["refined"]
        assert refined["status"] == "draft"
        name = refined["name"]
        assert scan_skills(str(skills)) == []
        drafts = scan_skills(str(skills), include_draft=True)
        assert any(item.id == name for item in drafts)

        hidden = await build_skill_inject_block(
            "orbit-report-skill",
            runtime="openclaw",
            top_k=2,
        )
        assert hidden == ""

        verified = await verify_skill(name, runtime="openclaw", skills_dir=str(skills))
        assert verified["status"] == "verified"
        block = await build_skill_inject_block(
            "orbit-report-skill",
            runtime="openclaw",
            top_k=2,
        )
        assert name in block
        assert "skills:" in block

        for _ in range(3):
            rejected = await reject_skill(name, runtime="openclaw", skills_dir=str(skills))
        assert rejected["archived"] is True
        assert (skills / "_archive" / name).is_dir()
        assert scan_skills(str(skills)) == []

    asyncio.run(run())
