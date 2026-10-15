"""自治升级：状态机、迁移、执行、委托、确认和轻量端去重。"""

import asyncio
import sqlite3

import pytest
from sqlalchemy import select

from app.core.autonomy_state import (
    ProtocolError,
    accept_protocol,
    ancestor_has_cycle,
    depth_allowed,
    reduce_outcome,
    task_status_v1,
)
from app.config import Settings
from app.core.agent_registry import AgentRegistry
from app.core.capabilities import catalog_for_profile
from app.core import content_roots
from app.core.capabilities import choose_node as choose_capability_node
from app.core.confirmations import attach_task, bind_device_task, confirm, device_can_read, issue_confirmation
from app.core.delegations import (
    DelegationError,
    authorize_workspace,
    create_delegation,
    link_workspaces,
)
from app.core.execution import accept_remote, mark, open_local, reconcile_handle, recover, request_cancel
from app.core.identity import load_or_create_identity, remember_alias
from app.core.privacy import leaks_private, redact_for_sync
from app.core.sync_bus import SyncConflict, ingest
from app.models.db import (
    ExecutionRecord,
    TaskRecord,
    backfill_task_owners,
    create_tables,
    get_session_factory,
    init_db,
)
from app.api.v2 import ClaimRequest, claim_command, create_enrollment, enroll_node
from app.models.db import NodeCredentialRecord


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    init_db(f"sqlite+aiosqlite:///{tmp_path}/auto.db")
    return tmp_path


def test_v1_mapping_and_cancel_race():
    assert task_status_v1("succeeded") == "completed"
    assert task_status_v1("needs_attention") == "running"
    finished = reduce_outcome("running", "succeeded", "cancel_requested")
    assert finished["outcome"] == "already_finished"
    stopped = reduce_outcome("running", "running", "stopped")
    assert stopped["task"] == "cancelled"
    late = reduce_outcome("cancelled", "stopped", "completed")
    assert late["outcome"] == "kept_stopped"
    assert reconcile_handle("starting", False) == "unknown"
    assert reconcile_handle("starting", True) == "running"
    with pytest.raises(ProtocolError):
        accept_protocol(1)


def test_identity_is_stable_and_alias_does_not_replace_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    first = load_or_create_identity("full")
    second = load_or_create_identity("edge")
    assert first.node_id == second.node_id
    assert first.center_id == second.center_id
    aliased = remember_alias("old-host")
    assert aliased.node_id == first.node_id
    assert "old-host" in aliased.aliases


def test_cloud_profile_has_no_executors_or_personal_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(content_roots, "_load", lambda: {})
    monkeypatch.setattr(content_roots, "_personal_defaults", lambda: False)
    assert content_roots.wiki_dir() == ""
    assert content_roots.skills_dir() == ""
    assert content_roots.outputs_dir() == ""
    snap = content_roots.snapshot()
    assert snap["knowledge_wiki_dir"] == ""
    assert snap["knowledge_default"] == ""
    settings = Settings(deploy_profile="cloud", local_executor_scan="auto", ai_mock_mode=True)
    registry = AgentRegistry(settings)
    assert settings.execution_slots() == 0
    assert registry._providers == {}


def test_profile_catalog_and_node_choice():
    cloud = catalog_for_profile("cloud", ["openclaw"])
    assert cloud[0]["capability_id"] == "conversation.text"
    full = catalog_for_profile("full", ["openclaw"], browser=False)
    assert "tool.browser" not in {item["capability_id"] for item in full}
    chosen = choose_capability_node(
        "mac-a",
        [
            {"node_id": "mac-b", "capabilities": ["agent.openclaw"], "free_slots": 2, "healthy": True},
        ],
        "agent.openclaw",
    )
    assert chosen is None
    auto = choose_capability_node(
        "",
        [
            {"node_id": "far", "capabilities": ["agent.openclaw"], "free_slots": 3, "data_local": False, "healthy": True},
            {"node_id": "near", "capabilities": ["agent.openclaw"], "free_slots": 1, "data_local": True, "healthy": True},
        ],
        "agent.openclaw",
    )
    assert auto["node_id"] == "near"


def test_private_payload_stays_local():
    secret = "sk-live-secret"
    body = "这是私有正文"
    hidden = redact_for_sync(
        {"task_id": "t1", "prompt": body, "api_key": secret, "path": "/Users/me/notes"},
        "private",
    )
    assert hidden["shared"] is False
    assert not leaks_private(hidden, secret, body)


def test_workspace_slug_is_not_implicit_link():
    assert authorize_workspace("local-ws", "center-b", "same-slug", []) is False
    assert depth_allowed(3) is True
    assert depth_allowed(4) is False
    assert ancestor_has_cycle(["mac-a", "mac-b"], "mac-a") is True


def test_history_migration_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCENTER_DATA_DIR", str(tmp_path))
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE tasks (
                id VARCHAR(36) PRIMARY KEY,
                workspace_id VARCHAR(64) DEFAULT '',
                project_id VARCHAR(64) DEFAULT '',
                agent_id VARCHAR(128),
                runtime VARCHAR(32) DEFAULT 'openclaw',
                prompt TEXT,
                system_prompt TEXT DEFAULT '',
                status VARCHAR(32),
                session_id VARCHAR(128) DEFAULT '',
                output TEXT DEFAULT '',
                error TEXT DEFAULT '',
                usage_json TEXT DEFAULT '',
                duration_ms INTEGER DEFAULT 0,
                start_date VARCHAR(16) DEFAULT '',
                due_date VARCHAR(16) DEFAULT '',
                node_id VARCHAR(64) DEFAULT '',
                created_at DATETIME,
                updated_at DATETIME
            )
            """
        )
        conn.execute(
            "INSERT INTO tasks (id, agent_id, prompt, status) VALUES ('keep-me', 'a', 'hello', 'completed')"
        )
    init_db(f"sqlite+aiosqlite:///{db_path}")

    async def scenario():
        await create_tables()
        await create_tables()
        ident = load_or_create_identity()
        await backfill_task_owners(ident.center_id)
        await backfill_task_owners(ident.center_id)
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(select(TaskRecord))).scalars().all()
            assert len(rows) == 1
            assert rows[0].id == "keep-me"
            assert rows[0].owner_center_id == ident.center_id
            assert rows[0].visibility == "private"

    asyncio.run(scenario())


def test_execution_dedupe_recover_and_two_cursors(db):
    async def scenario():
        await create_tables()
        first = await open_local("task-1", "openclaw", "main")
        second = await open_local("task-1", "openclaw", "main")
        assert first == second
        fresh = await accept_remote("task-9", "node-a", attempt=1, delegation_id="del-1")
        again = await accept_remote("task-9", "node-a", attempt=1, delegation_id="del-1")
        assert fresh is True
        assert again is False
        await mark(first, "running", handle_kind="async", handle_token="sess")
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                TaskRecord(
                    id="task-1",
                    agent_id="main",
                    prompt="stay",
                    status="running",
                    owner_center_id="center",
                )
            )
            await session.commit()
        changed = await recover()
        assert changed >= 1
        async with factory() as session:
            row = await session.get(ExecutionRecord, first)
            task = await session.get(TaskRecord, "task-1")
            assert row.status == "unknown"
            assert task.lifecycle_status == "needs_attention"
            count = (await session.execute(select(ExecutionRecord).where(ExecutionRecord.task_id == "task-1"))).scalars().all()
            assert len(count) == 1
        from app.core.task_manager import TaskManager
        from app.models.schemas import TaskEvent

        class _Registry:
            pass

        from app.config import Settings

        manager = TaskManager(Settings(local_auth_enabled=False), _Registry())
        await manager._save_event("task-1", TaskEvent(type="status", content="one"))
        await manager._save_event("task-1", TaskEvent(type="result", content="completed"))
        left = await manager.get_events("task-1", after_id=0)
        right = await manager.get_events("task-1", after_id=0)
        assert [item.id for item in left] == [item.id for item in right]
        assert len(left) == 2
        tail = await manager.get_events("task-1", after_id=left[0].id)
        assert len(tail) == 1

    asyncio.run(scenario())


def test_cancel_keeps_finished_fact(db):
    async def scenario():
        await create_tables()
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                TaskRecord(id="done", agent_id="a", prompt="p", status="completed", lifecycle_status="succeeded")
            )
            await session.commit()
        assert await request_cancel("done") == "already_finished"

    asyncio.run(scenario())


def test_delegation_cycle_depth_and_conflict(db):
    async def scenario():
        await create_tables()
        created = await create_delegation(
            owner_center_id="center-a",
            task_id="task-1",
            target_node_id="mac-b",
            idempotency_key="step-1",
            payload={"prompt": "do", "visibility": "shared"},
            source_node_id="mac-a",
            target_center_id="cloud",
            ancestors=["mac-a"],
            depth=1,
            visibility="shared",
        )
        assert created["delegation_id"]
        again = await create_delegation(
            owner_center_id="center-a",
            task_id="task-1",
            target_node_id="mac-b",
            idempotency_key="step-1",
            payload={"prompt": "do", "visibility": "shared"},
            source_node_id="mac-a",
            target_center_id="cloud",
            ancestors=["mac-a"],
            depth=1,
            visibility="shared",
        )
        assert again["delegation_id"] == created["delegation_id"]
        with pytest.raises(DelegationError):
            await create_delegation(
                owner_center_id="center-a",
                task_id="task-1",
                target_node_id="mac-b",
                idempotency_key="step-1",
                payload={"prompt": "other", "visibility": "shared"},
                source_node_id="mac-a",
                target_center_id="cloud",
                visibility="shared",
            )
        with pytest.raises(DelegationError):
            await create_delegation(
                owner_center_id="center-a",
                task_id="task-2",
                target_node_id="mac-a",
                idempotency_key="loop",
                payload={"prompt": "back"},
                source_node_id="mac-b",
                target_center_id="cloud",
                ancestors=["mac-a", "mac-b"],
                visibility="shared",
            )
        with pytest.raises(DelegationError):
            await create_delegation(
                owner_center_id="center-a",
                task_id="task-3",
                target_node_id="mac-c",
                idempotency_key="deep",
                payload={"prompt": "too deep"},
                source_node_id="mac-a",
                target_center_id="cloud",
                depth=4,
                visibility="shared",
            )
        assert authorize_workspace("ws-a", "center-b", "ws-b", []) is False
        await link_workspaces("ws-a", "center-b", "ws-b")
        from app.core.delegations import list_links

        assert authorize_workspace("ws-a", "center-b", "ws-b", await list_links()) is True

    asyncio.run(scenario())


def test_confirmation_returns_same_task(db):
    async def scenario():
        await create_tables()
        confirmation_id = await issue_confirmation(
            subject_id="user",
            session_id="sess",
            summary="整理",
            target={"agent_id": "a1", "prompt": "整理", "runtime": "openclaw"},
        )
        opened = await confirm(confirmation_id, subject_id="user", session_id="sess")
        assert opened["created"] is True
        await attach_task(confirmation_id, "task-7")
        again = await confirm(confirmation_id, subject_id="user", session_id="sess")
        assert again["task_id"] == "task-7"
        assert again["created"] is False
        with pytest.raises(Exception):
            await confirm(confirmation_id, subject_id="user", session_id="other")

    asyncio.run(scenario())


def test_device_cannot_read_unlinked_task_and_ingest_rejects_forged_source(db):
    async def scenario():
        await create_tables()
        await bind_device_task("esp", "task-ok", "sess")
        assert await device_can_read("esp", "task-ok") is True
        assert await device_can_read("esp", "task-other") is False
        with pytest.raises(SyncConflict):
            await ingest(
                {
                    "protocol_version": 2,
                    "message_id": "m1",
                    "type": "execution.completed",
                    "source_node_id": "attacker",
                    "payload": {"visibility": "private", "prompt": "secret"},
                },
                authenticated_node_id="node-a",
            )
        hidden = redact_for_sync({"prompt": "secret", "task_id": "t"}, "private")
        acked = await ingest(
            {
                "protocol_version": 2,
                "message_id": "m2",
                "type": "execution.completed",
                "source_node_id": "node-a",
                "payload": {"visibility": "private", "prompt": "secret", "task_id": "t"},
            },
            authenticated_node_id="node-a",
        )
        assert acked["status"] == "acked"
        duplicate = await ingest(
            {
                "protocol_version": 2,
                "message_id": "m2",
                "type": "execution.completed",
                "source_node_id": "node-a",
                "payload": {"visibility": "private"},
            },
            authenticated_node_id="node-a",
        )
        assert duplicate["status"] == "duplicate"
        assert hidden["shared"] is False

    asyncio.run(scenario())


def test_conversation_role_cannot_claim(db):
    async def scenario():
        await create_tables()
        voucher = await create_enrollment(type("Req", (), {"role": "conversation", "uses": 1, "ttl_seconds": 60})())
        enrolled = await enroll_node(
            type("Enroll", (), {"voucher": voucher["voucher"], "node_id": "esp-1", "protocol_version": 2})()
        )
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            await claim_command(
                ClaimRequest(task_id="t", attempt=1),
                x_node_token=enrolled["node_token"],
            )
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(NodeCredentialRecord, "esp-1")
            row.revoked = 1
            await session.commit()
        with pytest.raises(HTTPException):
            await claim_command(
                ClaimRequest(task_id="t", attempt=1),
                x_node_token=enrolled["node_token"],
            )

    asyncio.run(scenario())


def test_openapi_lists_contract():
    from app.api.v2 import openapi_document

    doc = openapi_document()
    assert doc["x-protocol-version"] == 2
    for path in (
        "/api/v2/delegations",
        "/api/v2/commands/claim",
        "/api/v2/events/batch",
        "/api/v2/confirmations/{id}/confirm",
    ):
        assert path in doc["paths"]
