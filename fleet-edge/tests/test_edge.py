"""连接器包：节点标识与扫描解析，不连云端。"""

import json

import hashlib
import hmac

from agentcenter_fleet.edge import (
    Cloud,
    _agents_from_openclaw_text,
    gateway_blocks_local,
    handshake_proof,
    openclaw_command,
    slug_node_id,
)


def test_handshake_proof_matches_cloud():
    material = "nonce.challenge"
    msg = f"fleet.handshake.v1.cloud.{material}".encode()
    expected = hmac.new(b"secret", msg, hashlib.sha256).hexdigest()
    assert handshake_proof("secret", "cloud", material) == expected


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


def test_call_agent_posts_other_endpoint():
    seen = {}

    class Fake(Cloud):
        def _request(self, method, path, payload=None, auth=False):
            seen["method"] = method
            seen["path"] = path
            seen["payload"] = payload
            seen["auth"] = auth
            return {
                "id": "task-1",
                "node_id": "pi",
                "agent_id": "coder",
                "kind": "subagent",
                "status": "queued",
            }

    result = Fake("http://cloud:8013", "secret", "tok").call_agent(
        "pi", "hermes", "coder", "写一段检查"
    )
    assert seen == {
        "method": "POST",
        "path": "/api/fleet/call",
        "payload": {
            "node_id": "pi",
            "runtime": "hermes",
            "agent_id": "coder",
            "prompt": "写一段检查",
        },
        "auth": True,
    }
    assert result["kind"] == "subagent"


def test_openclaw_json_entries():
    raw = json.dumps({"agents": [{"id": "main", "name": "指挥", "model": "gpt"}]})
    found = _agents_from_openclaw_text(raw)
    assert found == [
        {"id": "main", "name": "指挥", "runtime": "openclaw", "model": "gpt"},
    ]
