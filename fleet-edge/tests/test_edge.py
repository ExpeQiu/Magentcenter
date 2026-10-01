"""连接器包：节点标识与扫描解析，不连云端。"""

import json

from agentcenter_fleet.edge import (
    _agents_from_openclaw_text,
    gateway_blocks_local,
    openclaw_command,
    slug_node_id,
)


def test_slug_node_id():
    assert slug_node_id("Mac-Studio.local") == "mac-studio"
    assert slug_node_id("") == "device"
    assert slug_node_id("树莓派") == "device"


def test_openclaw_command_skips_local_when_gateway_up():
    task = {"id": "abc12345-rest", "agent_id": "main", "session_id": ""}
    local = openclaw_command(task, "pong", local=True)
    remote = openclaw_command(task, "pong", local=False)
    assert "--local" in local
    assert "--local" not in remote
    assert local[local.index("--agent") + 1] == "main"
    assert gateway_blocks_local("A Gateway is running for this state directory. Run without --local")


def test_openclaw_json_entries():
    raw = json.dumps({"agents": [{"id": "main", "name": "指挥", "model": "gpt"}]})
    found = _agents_from_openclaw_text(raw)
    assert found == [
        {"id": "main", "name": "指挥", "runtime": "openclaw", "model": "gpt"},
    ]
