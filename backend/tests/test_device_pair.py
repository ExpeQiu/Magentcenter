"""语音终端短码绑定：短码给人，长期令牌只回到发起的设备。"""

from datetime import datetime, timedelta

import pytest

from app.core.device_channel import (
    DeviceAuthError,
    DevicePairError,
    claim_device_pair,
    poll_device_pair,
    start_device_pair,
)
from app.core.fleet import FleetError, authenticate
from app.main import _session_public
from app.models.db import DevicePairRecord, FleetNodeRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/pair.db")
    return tmp_path


def test_pair_paths_are_public_claim_is_not():
    assert _session_public("/api/super-ai/device/pair")
    assert _session_public("/api/super-ai/device/pair/status")
    assert _session_public("/api/super-ai/device/enroll")
    assert not _session_public("/api/super-ai/device/pair/claim")


def test_short_code_bind_returns_token_only_to_device(db):
    async def scenario():
        await create_tables()
        started = await start_device_pair(device_id="esp32-room", name="客厅", platform="esp32")
        assert started["code"].isdigit() and len(started["code"]) == 6
        assert started["poll_secret"]
        assert "device_token" not in started
        assert started["bind_path"] == "/bind"

        pending = await poll_device_pair(started["device_id"], started["poll_secret"])
        assert pending["status"] == "pending"
        assert pending["device_token"] == ""

        with pytest.raises(DeviceAuthError):
            await poll_device_pair(started["device_id"], "someone-else")
        with pytest.raises(DevicePairError):
            await claim_device_pair("000000")

        claimed = await claim_device_pair(f" {started['code']} ")
        assert claimed == {"device_id": "esp32-room", "name": "客厅", "status": "bound"}
        assert "device_token" not in claimed

        ready = await poll_device_pair(started["device_id"], started["poll_secret"])
        assert ready["status"] == "ready"
        token = ready["device_token"]
        assert token
        again = await poll_device_pair(started["device_id"], started["poll_secret"])
        assert again["device_token"] == token

        with pytest.raises(DevicePairError):
            await claim_device_pair(started["code"])

        node = await authenticate(token)
        assert node is not None
        assert node.mode == "voice"
        assert node.bound == 0

        rebound = await start_device_pair(device_id="esp32-room", name="客厅")
        await claim_device_pair(rebound["code"])
        assert await authenticate(token) is None
        fresh = await poll_device_pair("esp32-room", rebound["poll_secret"])
        assert fresh["status"] == "ready"
        assert fresh["device_token"] != token

    import asyncio

    asyncio.run(scenario())


def test_expired_code_and_occupied_id(db):
    async def scenario():
        await create_tables()
        started = await start_device_pair(device_id="esp32-room", name="客厅")
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(DevicePairRecord, await _pair_id(session))
            rec.expires_at = datetime.utcnow() - timedelta(seconds=1)
            await session.commit()
        with pytest.raises(DevicePairError):
            await claim_device_pair(started["code"])
        expired = await poll_device_pair("esp32-room", started["poll_secret"])
        assert expired["status"] == "expired"
        assert expired["device_token"] == ""

        async with factory() as session:
            session.add(
                FleetNodeRecord(
                    id="desk-1",
                    name="desk",
                    mode="plugin",
                    bound=1,
                    token_hash="x",
                    agents_json="[]",
                    seen_json="[]",
                    runtimes_json="[]",
                )
            )
            await session.commit()
        with pytest.raises(FleetError):
            await start_device_pair(device_id="desk-1", name="桌面")

    import asyncio

    asyncio.run(scenario())


async def _pair_id(session):
    from sqlalchemy import select

    rec = await session.scalar(select(DevicePairRecord).where(DevicePairRecord.device_id == "esp32-room"))
    return rec.id
