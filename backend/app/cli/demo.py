"""离线示例数据。--demo 不访问协调器。"""

from __future__ import annotations

from typing import Any


def demo_payload(key: str) -> Any:
    samples: dict[str, Any] = {
        "health": {
            "status": "ok",
            "mock_mode": True,
            "openclaw_available": True,
            "openclaw_version": "demo",
            "hermes_available": True,
            "hermes_version": "demo",
            "default_runtime": "openclaw",
        },
        "agents": [
            {
                "id": "coder",
                "name": "Coder",
                "runtime": "openclaw",
                "model": "demo",
                "is_default": True,
            },
            {
                "id": "default",
                "name": "Default",
                "runtime": "hermes",
                "model": "demo",
                "is_default": False,
            },
        ],
        "agent": {
            "id": "coder",
            "name": "Coder",
            "runtime": "openclaw",
            "model": "demo",
            "is_default": True,
        },
        "agent-stats": [
            {
                "agent_id": "coder",
                "runtime": "openclaw",
                "task_count": 1,
                "running_count": 0,
            }
        ],
        "tasks": {
            "items": [
                {
                    "id": "task_demo",
                    "runtime": "openclaw",
                    "agent_id": "coder",
                    "status": "completed",
                    "prompt": "demo prompt",
                    "output": "demo output",
                }
            ],
            "total": 1,
            "page": 1,
        },
        "task": {
            "id": "task_demo",
            "runtime": "openclaw",
            "agent_id": "coder",
            "status": "completed",
            "prompt": "demo prompt",
            "output": "demo output",
        },
        "squads": [
            {"id": "core", "name": "Core", "leader_id": "coder", "runtime": "openclaw"}
        ],
        "skills": [{"name": "demo-skill", "path": "skills/demo-skill", "runtime": "openclaw"}],
        "autopilots": [
            {
                "id": "ap_demo",
                "name": "daily",
                "agent_id": "coder",
                "enabled": True,
            }
        ],
        "workspaces": [{"id": "ws_demo", "slug": "cyber", "name": "Cyber"}],
        "projects": [{"id": "proj_demo", "name": "Demo", "task_count": 1}],
        "knowledge-status": {
            "status": "ok",
            "embedding": {"provider": "hash"},
            "kinds": ["playbook", "precedent"],
        },
        "knowledge-hits": [
            {
                "id": "hit_demo",
                "kind": "playbook",
                "title": "demo playbook",
                "score": 1.0,
                "snippet": "offline fixture",
            }
        ],
        "outputs-status": {
            "status": "ok",
            "readable": True,
            "root_name": "demo",
            "message": "",
        },
        "outputs": [
            {
                "name": "note.md",
                "path": "demo/note.md",
                "source": "openclaw",
                "kind": "file",
                "size": 12,
            }
        ],
        "system": {
            "gateway": {"running": True, "port": 18789, "probe_ok": True},
            "runtimes": [
                {"runtime": "openclaw", "available": True, "version": "demo"},
                {"runtime": "hermes", "available": True, "version": "demo"},
            ],
            "sessions_count": 1,
            "cron_errors": [],
        },
        "alerts": {"errors": [], "recent_alerts": [], "gateway_alerts": [], "persisted": True},
        "sessions": [
            {
                "session_id": "sess_demo",
                "runtime": "openclaw",
                "agent_id": "coder",
                "model": "demo",
            }
        ],
        "session": {
            "session_id": "sess_demo",
            "runtime": "openclaw",
            "agent_id": "coder",
            "model": "demo",
            "messages": [{"role": "user", "content": "hello"}],
        },
        "fleet": [
            {
                "id": "macpro",
                "name": "Mac Pro",
                "mode": "plugin",
                "online": True,
                "bound": True,
                "hostname": "macpro.local",
            }
        ],
        "chain": [
            {
                "id": 1,
                "kind": "task",
                "status": "completed",
                "task_id": "task_demo",
                "summary": "demo chain",
            }
        ],
        "sops": [
            {"id": "sop_demo", "name": "Demo SOP", "step_count": 2, "run_count": 0}
        ],
        "sop": {
            "id": "sop_demo",
            "name": "Demo SOP",
            "description": "offline fixture",
            "step_count": 2,
            "run_count": 0,
            "steps": [],
        },
    }
    if key not in samples:
        raise KeyError(key)
    return samples[key]
