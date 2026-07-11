"""AgentCenter FastAPI 入口。"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import agents, orchestration, projects, tasks, workspaces, ws
from app.config import get_settings
from app.core.agent_registry import AgentRegistry
from app.core import projects as project_service
from app.core import workspaces as workspace_service
from app.core.autopilot import AutopilotManager
from app.core.task_manager import TaskManager
from app.logging_setup import setup_logging
from app.models.db import create_tables, init_db
from app.models.schemas import HealthResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log_dir = str(Path(__file__).resolve().parents[2] / "logs")
    setup_logging(settings.log_level, log_dir)

    db_path = Path("data")
    db_path.mkdir(parents=True, exist_ok=True)
    init_db(settings.database_url)
    await create_tables()
    await workspace_service.sync_seed_workspaces()
    await project_service.sync_seed_projects()
    await project_service.refresh_task_counts()

    registry = AgentRegistry(settings)
    task_manager = TaskManager(settings, registry)
    autopilot_manager = AutopilotManager(task_manager)
    autopilot_manager.start()
    app.state.registry = registry
    app.state.task_manager = task_manager
    app.state.autopilot_manager = autopilot_manager
    app.state.settings = settings

    ok, version = await registry.check_health()
    logger.info(
        "AgentCenter started mock=%s openclaw=%s version=%s",
        settings.ai_mock_mode,
        ok,
        version,
    )
    yield
    autopilot_manager.stop()
    logger.info("AgentCenter shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AgentCenter",
        description="OpenClaw Agent 编排中台",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        registry: AgentRegistry = app.state.registry
        ok, version = await registry.check_health()
        return HealthResponse(
            status="ok",
            openclaw_available=ok,
            openclaw_version=version,
            mock_mode=settings.ai_mock_mode,
        )

    app.include_router(agents.router)
    app.include_router(workspaces.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(orchestration.router)
    app.include_router(ws.router)
    return app


app = create_app()
