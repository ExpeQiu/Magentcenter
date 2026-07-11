"""SQLAlchemy 数据库模型。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


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


_engine = None
_session_factory = None

_MIGRATIONS: list[tuple[str, str, str]] = [
    ("tasks", "project_id", "VARCHAR(64) DEFAULT ''"),
    ("tasks", "workspace_id", "VARCHAR(64) DEFAULT ''"),
    ("tasks", "start_date", "VARCHAR(16) DEFAULT ''"),
    ("tasks", "due_date", "VARCHAR(16) DEFAULT ''"),
    ("projects", "workspace_id", "VARCHAR(64) DEFAULT ''"),
    ("projects", "lead_type", "VARCHAR(32) DEFAULT ''"),
    ("projects", "lead_id", "VARCHAR(128) DEFAULT ''"),
    ("projects", "resource_count", "INTEGER DEFAULT 0"),
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


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized")
    return _session_factory
