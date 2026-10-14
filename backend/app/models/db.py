"""SQLAlchemy 数据库模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProjectRecord(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    color: Mapped[str] = mapped_column(String(32), default="slate")
    lead_type: Mapped[str] = mapped_column(String(32), default="")
    lead_id: Mapped[str] = mapped_column(String(128), default="")
    task_count: Mapped[int] = mapped_column(Integer, default=0)
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SopRecord(Base):
    __tablename__ = "sops"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SopStepRecord(Base):
    __tablename__ = "sop_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    sop_id: Mapped[str] = mapped_column(String(36), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(256))
    instruction: Mapped[str] = mapped_column(Text, default="")
    skill_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProjectResourceRecord(Base):
    __tablename__ = "project_resources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(128), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    ref_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    project_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    runtime: Mapped[str] = mapped_column(String(32), index=True, default="openclaw")
    prompt: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    session_id: Mapped[str] = mapped_column(String(128), default="")
    output: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    usage_json: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[str] = mapped_column(String(16), default="")
    due_date: Mapped[str] = mapped_column(String(16), default="")
    node_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    owner_center_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    origin: Mapped[str] = mapped_column(String(32), default="local")
    visibility: Mapped[str] = mapped_column(String(32), default="private")
    lifecycle_status: Mapped[str] = mapped_column(String(32), default="")
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ChainRecord(Base):
    """跨设备信息链。一条任务从开口到回写的经过都在这里。"""

    __tablename__ = "chain_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), index=True, default="")
    run_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    task_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    actor_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    target_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    channel: Mapped[str] = mapped_column(String(16), default="")
    intent: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TaskEventRecord(Base):
    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")
    tool: Mapped[str] = mapped_column(String(128), default="")
    call_id: Mapped[str] = mapped_column(String(128), default="")
    event_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AutopilotRecord(Base):
    __tablename__ = "autopilots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    agent_id: Mapped[str] = mapped_column(String(128), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    cron: Mapped[str] = mapped_column(String(64), default="3600")
    enabled: Mapped[bool] = mapped_column(Integer, default=1)
    openclaw_id: Mapped[str] = mapped_column(String(64), default="")
    hermes_id: Mapped[str] = mapped_column(String(64), default="")
    runtime: Mapped[str] = mapped_column(String(32), default="openclaw")
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AlertRecord(Base):
    """持久化告警历史（Cron / Gateway / Disk）。"""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(String(64), index=True, default="")
    kind: Mapped[str] = mapped_column(String(32), index=True, default="cron")
    count: Mapped[int] = mapped_column(Integer, default=0)
    sent: Mapped[int] = mapped_column(Integer, default=0)
    jobs_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FleetNodeRecord(Base):
    """云端协调器上的设备连接器。令牌只存哈希。"""

    __tablename__ = "fleet_nodes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    token_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    runtimes_json: Mapped[str] = mapped_column(Text, default="[]")
    hostname: Mapped[str] = mapped_column(String(128), default="")
    platform: Mapped[str] = mapped_column(String(64), default="")
    mode: Mapped[str] = mapped_column(String(16), default="plugin")
    webhook_url: Mapped[str] = mapped_column(Text, default="")
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    bound: Mapped[int] = mapped_column(Integer, default=0)
    agents_json: Mapped[str] = mapped_column(Text, default="[]")
    seen_json: Mapped[str] = mapped_column(Text, default="[]")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    load: Mapped[float | None] = mapped_column(Float, nullable=True)
    handshake_state: Mapped[str] = mapped_column(String(16), default="")
    handshake_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handshake_challenge: Mapped[str] = mapped_column(String(64), default="")
    handshake_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class KnowledgeRecord(Base):
    """知识条目。kind 保留旧卡片；layer/facet 是 Personal Wiki 坐标。"""

    __tablename__ = "knowledge_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True, default="archive")
    layer: Mapped[str] = mapped_column(String(16), index=True, default="")
    facet: Mapped[str] = mapped_column(String(32), index=True, default="")
    source_type: Mapped[str] = mapped_column(String(32), index=True, default="task")
    source_id: Mapped[str] = mapped_column(String(256), index=True, default="")
    runtime: Mapped[str] = mapped_column(String(32), index=True, default="")
    agent_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    session_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    embedding_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class SkillRecord(Base):
    """自挖掘技能账本。正文在运行时 SKILL.md，这里只存状态和用量。"""

    __tablename__ = "skill_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    runtime: Mapped[str] = mapped_column(String(32), index=True, default="openclaw")
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_keywords: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), index=True, default="draft")
    skill_class: Mapped[str] = mapped_column(String(16), default="flow")
    source_task: Mapped[str] = mapped_column(String(64), default="")
    source_session: Mapped[str] = mapped_column(String(128), default="")
    wiki_ref: Mapped[str] = mapped_column(String(64), default="")
    capture_id: Mapped[str] = mapped_column(String(64), default="")
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ExecutionRecord(Base):
    """某次运行尝试。本地任务和跨端委托各写一行，断网补传不增加 attempt。"""

    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_executions_dedupe"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    owner_center_id: Mapped[str] = mapped_column(String(64), default="")
    delegation_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    node_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    dedupe_key: Mapped[str] = mapped_column(String(96), default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="accepted")
    runtime: Mapped[str] = mapped_column(String(32), default="")
    agent_id: Mapped[str] = mapped_column(String(128), default="")
    handle_kind: Mapped[str] = mapped_column(String(32), default="")
    handle_token: Mapped[str] = mapped_column(String(128), default="")
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    external_write: Mapped[int] = mapped_column(Integer, default=0)
    cancel_ack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DelegationRecord(Base):
    """路由中心上的一次子步骤委托。重投不改变 delegation_id。"""

    __tablename__ = "delegations"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_delegations_idem"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_center_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    task_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    target_node_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    idempotency_key: Mapped[str] = mapped_column(String(128), default="")
    payload_hash: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    auth_snapshot_json: Mapped[str] = mapped_column(Text, default="{}")
    delivery_status: Mapped[str] = mapped_column(String(32), default="pending")
    parent_task_ref: Mapped[str] = mapped_column(String(80), default="")
    root_task_ref: Mapped[str] = mapped_column(String(80), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="")
    depth: Mapped[int] = mapped_column(Integer, default=1)
    ancestor_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class InboxRecord(Base):
    __tablename__ = "inbox"
    __table_args__ = (UniqueConstraint("message_id", name="uq_inbox_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), default="")
    source_node_id: Mapped[str] = mapped_column(String(64), default="")
    message_type: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    acked: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OutboxRecord(Base):
    __tablename__ = "outbox"
    __table_args__ = (UniqueConstraint("message_id", name="uq_outbox_message"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(64), default="")
    target_center_id: Mapped[str] = mapped_column(String(64), default="")
    message_type: Mapped[str] = mapped_column(String(64), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    acked: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EnrollmentVoucherRecord(Base):
    __tablename__ = "enrollment_vouchers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    role: Mapped[str] = mapped_column(String(32), default="edge")
    uses_left: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NodeCredentialRecord(Base):
    __tablename__ = "node_credentials"

    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    role: Mapped[str] = mapped_column(String(32), default="full")
    revoked: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WorkspaceLinkRecord(Base):
    __tablename__ = "workspace_links"
    __table_args__ = (
        UniqueConstraint(
            "local_workspace_id",
            "remote_center_id",
            "remote_workspace_id",
            name="uq_workspace_link",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    local_workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    remote_center_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    remote_workspace_id: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ConfirmationRecord(Base):
    __tablename__ = "confirmations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    session_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    target_json: Mapped[str] = mapped_column(Text, default="{}")
    scope: Mapped[str] = mapped_column(String(64), default="local")
    task_id: Mapped[str] = mapped_column(String(36), default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DeviceTaskLinkRecord(Base):
    """对话设备只能读取自己会话里产生的任务。"""

    __tablename__ = "device_task_links"
    __table_args__ = (UniqueConstraint("device_id", "task_id", name="uq_device_task"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    session_id: Mapped[str] = mapped_column(String(64), default="")
    task_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


_engine = None
_session_factory = None

_MIGRATIONS: list[tuple[str, str, str]] = [
    ("tasks", "project_id", "VARCHAR(64) DEFAULT ''"),
    ("tasks", "workspace_id", "VARCHAR(64) DEFAULT ''"),
    ("tasks", "start_date", "VARCHAR(16) DEFAULT ''"),
    ("tasks", "due_date", "VARCHAR(16) DEFAULT ''"),
    ("tasks", "runtime", "VARCHAR(32) DEFAULT 'openclaw'"),
    ("projects", "workspace_id", "VARCHAR(64) DEFAULT ''"),
    ("projects", "lead_type", "VARCHAR(32) DEFAULT ''"),
    ("projects", "lead_id", "VARCHAR(128) DEFAULT ''"),
    ("projects", "resource_count", "INTEGER DEFAULT 0"),
    ("autopilots", "hermes_id", "VARCHAR(64) DEFAULT ''"),
    ("autopilots", "runtime", "VARCHAR(32) DEFAULT 'openclaw'"),
    ("knowledge_entries", "embedding_json", "TEXT DEFAULT ''"),
    ("knowledge_entries", "kind", "VARCHAR(32) DEFAULT 'archive'"),
    ("knowledge_entries", "workspace_id", "VARCHAR(64) DEFAULT ''"),
    ("knowledge_entries", "tags_json", "TEXT DEFAULT '[]'"),
    ("knowledge_entries", "payload_json", "TEXT DEFAULT '{}'"),
    ("tasks", "node_id", "VARCHAR(64) DEFAULT ''"),
    ("fleet_nodes", "bound", "INTEGER DEFAULT 0"),
    ("fleet_nodes", "agents_json", "TEXT DEFAULT '[]'"),
    ("fleet_nodes", "seen_json", "TEXT DEFAULT '[]'"),
    ("fleet_nodes", "workspace_id", "VARCHAR(64) DEFAULT ''"),
    ("fleet_nodes", "handshake_state", "VARCHAR(16) DEFAULT ''"),
    ("fleet_nodes", "handshake_at", "DATETIME"),
    ("fleet_nodes", "handshake_challenge", "VARCHAR(64) DEFAULT ''"),
    ("fleet_nodes", "handshake_expires", "DATETIME"),
    ("knowledge_entries", "layer", "VARCHAR(16) DEFAULT ''"),
    ("knowledge_entries", "facet", "VARCHAR(32) DEFAULT ''"),
    ("tasks", "owner_center_id", "VARCHAR(64) DEFAULT ''"),
    ("tasks", "origin", "VARCHAR(32) DEFAULT 'local'"),
    ("tasks", "visibility", "VARCHAR(32) DEFAULT 'private'"),
    ("tasks", "lifecycle_status", "VARCHAR(32) DEFAULT ''"),
    ("tasks", "cancel_requested_at", "DATETIME"),
    ("tasks", "revision", "INTEGER DEFAULT 0"),
]


def init_db(database_url: str) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(database_url, echo=False)
    _session_factory = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


async def _migrate_columns(conn) -> None:
    """轻量迁移：为已有 SQLite 库补列。"""
    from sqlalchemy import text

    async def has_column(table: str, column: str) -> bool:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result.fetchall())

    for table, column, ddl in _MIGRATIONS:
        if not await has_column(table, column):
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def create_tables() -> None:
    if _engine is None:
        raise RuntimeError("Database not initialized")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_columns(conn)


async def backfill_task_owners(center_id: str) -> int:
    """历史任务归到当前这个库所在的中心。可重复执行。"""
    from sqlalchemy import text

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "UPDATE tasks SET owner_center_id = :center "
                "WHERE owner_center_id IS NULL OR owner_center_id = ''"
            ),
            {"center": center_id},
        )
        await session.commit()
        return int(result.rowcount or 0)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    return _session_factory
