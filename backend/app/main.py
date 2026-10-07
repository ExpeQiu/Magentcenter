"""AgentCenter FastAPI 入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    agents,
    chain,
    content_roots,
    fleet,
    kanban,
    knowledge,
    orchestration,
    outputs,
    projects,
    super_ai,
    system,
    tasks,
    workspaces,
    ws,
)
from app.api.tasks import live_tasks_router
from app.config import get_settings
from app.core.agent_registry import AgentRegistry
from app.core import projects as project_service
from app.core import workspaces as workspace_service
from app.core.autopilot import AutopilotManager
from app.core.cron_alerts import CronAlertWatcher
from app.core.monitor_hub import MonitorHub
from app.core.task_manager import TaskManager
from app.logging_setup import setup_logging
from app.models.db import create_tables, init_db
from app.models.schemas import HealthResponse
from app.paths import data_dir, log_dir

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, str(log_dir()))

    db_path = data_dir()
    db_path.mkdir(parents=True, exist_ok=True)
    init_db(settings.database_url)
    await create_tables()
    from app.core.alert_settings_store import (
        apply_alert_settings,
        ensure_profile,
        load_alert_settings,
    )
    from app.core.text_embed import configure_embedder

    configure_embedder(
        provider=settings.embedding_provider,
        api_url=settings.embedding_api_url,
        api_key=settings.embedding_api_key,
        model=settings.embedding_model,
        mock=settings.ai_mock_mode,
    )
    # 告警多环境：按 ALERT_PROFILE 加载，并确保 profile 存在
    profile_data = load_alert_settings(profile=settings.alert_profile)
    if profile_data:
        apply_alert_settings(settings, profile_data)
    else:
        ensure_profile(settings, settings.alert_profile or "default")
        apply_alert_settings(settings)
    settings.alert_profile = settings.alert_profile or "default"
    await workspace_service.sync_seed_workspaces()
    await project_service.sync_seed_projects()
    await project_service.refresh_task_counts()

    registry = AgentRegistry(settings)
    task_manager = TaskManager(settings, registry)
    monitor = MonitorHub(settings)
    autopilot_manager = AutopilotManager(settings, task_manager)
    alert_watcher = CronAlertWatcher(settings, monitor)
    await alert_watcher.load_persisted()
    await autopilot_manager.start()
    alert_watcher.start()
    app.state.registry = registry
    app.state.task_manager = task_manager
    app.state.autopilot_manager = autopilot_manager
    app.state.monitor = monitor
    app.state.alert_watcher = alert_watcher
    app.state.settings = settings

    health = await registry.check_all_health()
    logger.info(
        "AgentCenter started mock=%s runtimes=%s health=%s",
        settings.ai_mock_mode,
        settings.enabled_runtimes(),
        [(h.runtime, h.available, h.version) for h in health],
    )
    yield
    alert_watcher.stop()
    autopilot_manager.stop()
    logger.info("AgentCenter shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AgentCenter",
        description="OpenClaw / Hermes 双运行时 Agent 编排中台",
        version="0.2.0",
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
        panes = await registry.check_all_health()
        by_rt = {p.runtime: p for p in panes}
        oc = by_rt.get("openclaw")
        hm = by_rt.get("hermes")
        return HealthResponse(
            status="ok",
            openclaw_available=bool(oc and oc.available),
            openclaw_version=(oc.version if oc else ""),
            hermes_available=bool(hm and hm.available),
            hermes_version=(hm.version if hm else ""),
            runtimes=panes,
            default_runtime=settings.default_runtime,
            mock_mode=settings.ai_mock_mode,
        )

    app.include_router(agents.router)
    app.include_router(workspaces.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(tasks.live_tasks_router)
    app.include_router(orchestration.router)
    app.include_router(kanban.router)
    app.include_router(knowledge.router)
    app.include_router(content_roots.router)
    app.include_router(outputs.router)
    app.include_router(system.router)
    app.include_router(super_ai.router)
    app.include_router(chain.router)
    app.include_router(fleet.router)
    app.include_router(ws.router)
    from app.core.static_ui import mount_static_ui

    mount_static_ui(app)
    return app


app = create_app()
