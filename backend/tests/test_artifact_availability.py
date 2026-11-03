"""ArtifactRef availability：跨端不把裸本地路径当可下载 URL。"""

from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("AI_MOCK_MODE", "true")

from app.core.knowledge import get_entry, upsert_artifact_ref
from app.models.db import KnowledgeRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/art.db")
    return tmp_path


def test_artifact_ref_local_keeps_path_offline_hides(db):
    async def scenario():
        await create_tables()
        local_path = "/Users/demo/private/report.md"
        entry_id = await upsert_artifact_ref(
            path=local_path,
            title="报告",
            summary="本地产物",
            availability="local",
        )
        row = await get_entry(entry_id)
        assert row is not None
        assert row.payload.get("path") == local_path
        assert row.payload.get("local_path_private") is True
        assert row.payload.get("availability") == "local"

        offline_id = await upsert_artifact_ref(
            path=local_path,
            title="报告-离线",
            summary="不可读",
            availability="offline",
            access_scope="shared",
        )
        offline = await get_entry(offline_id)
        assert offline is not None
        assert offline.payload.get("path") == ""
        assert offline.payload.get("availability") == "offline"
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(KnowledgeRecord, offline_id)
            assert rec is not None
            assert rec.availability == "offline"

    asyncio.run(scenario())


def test_artifact_ref_online_exposes_public_path(db):
    async def scenario():
        await create_tables()
        url = "https://cdn.example.com/a.md"
        entry_id = await upsert_artifact_ref(
            path=url,
            title="在线",
            availability="online",
            access_scope="shared",
        )
        row = await get_entry(entry_id)
        assert row is not None
        assert row.payload.get("path") == url
        assert row.payload.get("availability") == "online"

    asyncio.run(scenario())
