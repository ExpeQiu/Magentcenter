"""AgentCenter FastAPI 入口。"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
    sops,
    super_ai,
    system,
    tasks,
    v2,
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
from app.models.db import backfill_task_owners, create_tables, init_db
from app.models.schemas import HealthResponse
from app.paths import data_dir, log_dir, resolve_database_url

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, str(log_dir()))

    from app.core.execution import recover
    from app.core.identity import load_or_create_identity
    from app.core.local_auth import ensure_local_session

    ident = load_or_create_identity(settings.normalized_profile())
    ensure_local_session()
    db_path = data_dir()
    db_path.mkdir(parents=True, exist_ok=True)
    database_url = resolve_database_url(settings.database_url)
    init_db(database_url)
    await create_tables()
    await backfill_task_owners(ident.center_id)
    recovered = await recover()
    logger.info(
        "autonomy ready profile=%s center_id=%s node_id=%s recovered=%s slots=%s",
        settings.normalized_profile(),
        ident.center_id,
        ident.node_id,
        recovered,
        settings.execution_slots(),
    )
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
    app.state.center_id = ident.center_id
    app.state.node_id = ident.node_id

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

    @app.middleware("http")
    async def local_session_guard(request: Request, call_next):
        if not settings.local_auth_enabled:
            return await call_next(request)
        path = request.url.path
        if request.method == "OPTIONS" or _session_public(path):
            return await call_next(request)
        if request.headers.get("x-node-token") or request.headers.get("x-device-token"):
            return await call_next(request)
        from app.core.local_auth import session_matches

        presented_header = request.headers.get("x-agentcenter-session") or ""
        presented_cookie = request.cookies.get("ac_session") or ""
        if session_matches(presented_header) or session_matches(presented_cookie):
            return await call_next(request)
        admin = (settings.admin_token or "").strip()
        if admin and request.headers.get("x-admin-token") == admin:
            return await call_next(request)
        return JSONResponse({"detail": "local session required"}, status_code=401)

    @app.get("/api/session/status")
    async def session_status(request: Request):
        from app.core.local_auth import session_matches

        header = request.headers.get("x-agentcenter-session") or ""
        cookie = request.cookies.get("ac_session") or ""
        unlocked = session_matches(header) or session_matches(cookie)
        return {"unlocked": unlocked}

    @app.post("/api/session/unlock")
    async def unlock_session(request: Request):
        host = request.client.host if request.client else ""
        from app.core.local_auth import (
            clear_failures,
            code_matches,
            cooldown_remaining,
            ensure_local_session,
            register_failure,
        )

        remaining = cooldown_remaining(host)
        if remaining > 0:
            logger.warning("entry unlock cooled host=%s remaining_s=%.0f", host, remaining)
            return JSONResponse({"detail": "尝试过多，请稍后再试"}, status_code=429)
        try:
            body = await request.json()
        except Exception:
            body = {}
        code = str(body.get("code") or "") if isinstance(body, dict) else ""
        expected = (settings.entry_code or "").strip() or "Qb123!456"
        if not code_matches(code, expected):
            count = register_failure(host)
            logger.info("entry unlock rejected host=%s failures=%s", host, count)
            return JSONResponse({"detail": "鉴权码不正确"}, status_code=401)
        clear_failures(host)
        token = ensure_local_session()
        logger.info("entry unlock ok host=%s", host)
        response = JSONResponse({"ok": True, "token": token})
        response.set_cookie(
            "ac_session",
            token,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 60 * 60,
            path="/",
        )
        return response

    @app.get("/api/session/bootstrap")
    async def bootstrap_session(request: Request):
        host = request.client.host if request.client else ""
        if host not in {"127.0.0.1", "::1"}:
            return JSONResponse({"detail": "bootstrap is loopback only"}, status_code=403)
        from app.core.local_auth import session_matches

        header = request.headers.get("x-agentcenter-session") or ""
        cookie = request.cookies.get("ac_session") or ""
        return JSONResponse({"unlocked": session_matches(header) or session_matches(cookie)})

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
            deploy_profile=settings.normalized_profile(),
            protocol_version=2,
            center_id=app.state.center_id if hasattr(app.state, "center_id") else "",
        )

    app.include_router(agents.router)
    app.include_router(workspaces.router)
    app.include_router(projects.router)
    app.include_router(sops.router)
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
    app.include_router(v2.router)
    app.include_router(ws.router)
    from app.core.static_ui import mount_static_ui

    mount_static_ui(app)
    return app


app = create_app()


def _session_public(path: str) -> bool:
    if path in {
        "/api/health",
        "/api/session/bootstrap",
        "/api/session/status",
        "/api/session/unlock",
        "/api/v2/openapi.json",
        "/api/v2/nodes/enroll",
        "/api/super-ai/device/enroll",
        "/api/super-ai/device/pair",
        "/api/super-ai/device/pair/status",
    }:
        return True
    if not path.startswith("/api") and not path.startswith("/ws"):
        return True
    return False
