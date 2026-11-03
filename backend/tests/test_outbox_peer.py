"""跨中心 outbox peer 投递：正确 events 信封 + 失败重试。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.identity import load_or_create_identity
from app.core.sync_bus import dispatch_pending, enqueue, envelope
from app.models.db import OutboxRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/outbox.db")
    return tmp_path


def _link(tmp_path, center: str = "cloud-center-1"):
    (tmp_path / "fleet_link.json").write_text(
        json.dumps({"cloud_url": "http://peer.test:8080", "remote_center_id": center}),
        encoding="utf-8",
    )
    (tmp_path / "fleet_link.token").write_text("node-token", encoding="utf-8")


async def _put_outbox(message_id: str, target: str) -> None:
    ident = load_or_create_identity()
    msg = envelope(
        message_type="execution.event",
        source_node_id=ident.node_id,
        target_center_id=target,
        owner_center_id=ident.center_id,
        message_id=message_id,
        payload={"hello": 1},
    )
    factory = get_session_factory()
    async with factory() as session:
        await enqueue(session, msg)
        await session.commit()


def test_peer_deliver_uses_events_and_acks(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr("app.core.fleet.link_path", lambda: db / "fleet_link.json")
        monkeypatch.setattr(
            "app.core.fleet.link_token_path", lambda: db / "fleet_link.token"
        )
        _link(db)
        await _put_outbox("m-peer-1", "cloud-center-1")

        captured: dict = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"results":[]}'

        def fake_urlopen(req, timeout=15):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            captured["token"] = req.get_header("X-node-token") or req.get_header(
                "X-Node-Token"
            )
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            result = await dispatch_pending()
        assert result["peer_delivered"] == 1
        assert result["acked"] >= 1
        assert captured["url"].endswith("/api/v2/events/batch")
        assert "events" in captured["body"]
        assert "messages" not in captured["body"]
        assert captured["body"]["events"][0]["message_id"] == "m-peer-1"

        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(OutboxRecord).where(OutboxRecord.message_id == "m-peer-1")
                )
            ).scalar_one()
            assert row.acked == 1

    asyncio.run(scenario())


def test_peer_deliver_failure_bumps_attempts(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr("app.core.fleet.link_path", lambda: db / "fleet_link.json")
        monkeypatch.setattr(
            "app.core.fleet.link_token_path", lambda: db / "fleet_link.token"
        )
        _link(db)
        await _put_outbox("m-fail-1", "cloud-center-1")

        import urllib.error

        def boom(*a, **k):
            raise urllib.error.URLError("down")

        with patch("urllib.request.urlopen", boom):
            result = await dispatch_pending()
        assert result["waiting"] == 1
        assert result.get("peer_delivered", 0) == 0

        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(OutboxRecord).where(OutboxRecord.message_id == "m-fail-1")
                )
            ).scalar_one()
            assert row.acked == 0
            assert int(row.attempts or 0) >= 1

    asyncio.run(scenario())


def test_unknown_peer_center_waits(db, monkeypatch):
    async def scenario():
        await create_tables()
        monkeypatch.setattr("app.core.fleet.link_path", lambda: db / "fleet_link.json")
        monkeypatch.setattr(
            "app.core.fleet.link_token_path", lambda: db / "fleet_link.token"
        )
        _link(db, center="cloud-center-1")
        await _put_outbox("m-other", "other-center")
        with patch("urllib.request.urlopen") as mock_open:
            result = await dispatch_pending()
            mock_open.assert_not_called()
        assert result["waiting"] == 1

    asyncio.run(scenario())
