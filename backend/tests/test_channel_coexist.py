"""同一 device_id：执行 Node 与语音 Channel 可并存。"""

import asyncio

import pytest

from app.core import fleet
from app.core.channels import authenticate_channel, issue_voice_channel
from app.core.device_channel import start_device_pair
from app.models.db import ChannelRecord, FleetNodeRecord, create_tables, get_session_factory, init_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_GUIDE_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/coexist.db")
    return tmp_path


def test_voice_channel_alongside_exec_node(db):
    async def scenario():
        await create_tables()
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                FleetNodeRecord(
                    id="desk-pc",
                    name="本地PC",
                    mode="plugin",
                    bound=1,
                    token_hash=fleet.hash_token("node-secret"),
                    agents_json='[{"id":"coder","runtime":"openclaw"}]',
                    seen_json="[]",
                    runtimes_json='["openclaw"]',
                )
            )
            await session.commit()

        # 旧逻辑会抛 device id already registered；现应成功
        token = await issue_voice_channel("desk-pc", name="桌面语音", platform="desktop")
        assert token
        ch = await authenticate_channel(token)
        assert ch is not None
        assert ch.device_id == "desk-pc"

        async with factory() as session:
            node = await session.get(FleetNodeRecord, "desk-pc")
            assert node is not None
            assert node.mode == "plugin"
            assert node.bound == 1
            assert node.token_hash == fleet.hash_token("node-secret")
            channel = await session.get(ChannelRecord, "desk-pc:desktop")
            assert channel is not None

        started = await start_device_pair(device_id="desk-pc", name="桌面语音", platform="desktop")
        assert started["code"]

    asyncio.run(scenario())
