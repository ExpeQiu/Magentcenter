"""系统状态 / Sessions / Settings API。"""

import logging

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel

from app.core.cron_repair import dispatch_cron_repair
from app.core.openclaw_monitor import SessionDetail, SessionInfo, SystemStatus
from app.models.schemas import TaskInfo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


class CronRepairRequest(BaseModel):
    note: str = ""
    workspace_id: str = ""


# ── Alert Settings ─────────────────────────────────────────────────────────


class AlertSettingsResponse(BaseModel):
    webhook_url_set: bool
    webhook_url_masked: str
    cron_alert_interval: int
    cron_alert_enabled: bool
    gateway_alert_enabled: bool
    disk_alert_threshold: int
    persisted: bool = False
    profile: str = "default"
    profiles: list[str] = []


class AlertSettingsUpdate(BaseModel):
    feishu_webhook_url: str | None = None
    cron_alert_interval: int | None = None
    cron_alert_enabled: bool | None = None
    gateway_alert_enabled: bool | None = None
    disk_alert_threshold: int | None = None
    profile: str | None = None
    activate: bool = True


class AlertProfileCreate(BaseModel):
    name: str
    from_current: bool = True
    activate: bool = False


def _alert_response(settings) -> AlertSettingsResponse:
    from app.core.alert_settings_store import list_profiles, profiles_path

    meta = list_profiles()
    url = settings.feishu_webhook_url
    masked = f"{url[:8]}...{url[-4:]}" if url and len(url) > 12 else ("" if not url else url)
    return AlertSettingsResponse(
        webhook_url_set=bool(url),
        webhook_url_masked=masked,
        cron_alert_interval=settings.cron_alert_interval,
        cron_alert_enabled=settings.cron_alert_enabled,
        gateway_alert_enabled=settings.gateway_alert_enabled,
        disk_alert_threshold=settings.disk_alert_threshold,
        persisted=profiles_path().is_file() or True,
        profile=getattr(settings, "alert_profile", None) or meta.get("active") or "default",
        profiles=list(meta.get("profiles") or []),
    )


@router.get("/settings/alert", response_model=AlertSettingsResponse)
async def get_alert_settings(
    request: Request,
    profile: str | None = Query(None),
):
    from app.core.alert_settings_store import apply_alert_settings, load_alert_settings

    settings = request.app.state.settings
    if profile:
        data = load_alert_settings(profile=profile)
        if not data:
            raise HTTPException(status_code=404, detail=f"profile not found: {profile}")
        # 仅返回该 profile 视图，不切换运行时 Settings
        tmp = settings.model_copy()
        apply_alert_settings(tmp, data)
        tmp.alert_profile = profile
        resp = _alert_response(tmp)
        resp.profile = profile
        return resp
    return _alert_response(settings)


@router.get("/settings/alert/profiles")
async def get_alert_profiles():
    from app.core.alert_settings_store import list_profiles

    return list_profiles()


@router.post("/settings/alert/profiles")
async def create_alert_profile(req: AlertProfileCreate, request: Request):
    from app.core.alert_settings_store import activate_profile, ensure_profile

    settings = request.app.state.settings
    try:
        meta = ensure_profile(settings, req.name, from_current=req.from_current)
        if req.activate:
            activate_profile(settings, req.name)
            meta = {**meta, "active": req.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info("alert profile created name=%s activate=%s", req.name, req.activate)
    return {"status": "ok", **meta, "settings": _alert_response(settings)}


@router.post("/settings/alert/profiles/{name}/activate")
async def activate_alert_profile(name: str, request: Request):
    from app.core.alert_settings_store import activate_profile

    try:
        result = activate_profile(request.app.state.settings, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {
        "status": "ok",
        **result,
        "settings": _alert_response(request.app.state.settings),
    }


@router.patch("/settings/alert")
async def update_alert_settings(req: AlertSettingsUpdate, request: Request):
    from app.core.alert_settings_store import save_alert_settings

    settings = request.app.state.settings
    updates = []
    if req.feishu_webhook_url is not None:
        settings.feishu_webhook_url = req.feishu_webhook_url
        updates.append("feishu_webhook_url")
    if req.cron_alert_interval is not None:
        if req.cron_alert_interval < 60:
            raise HTTPException(status_code=400, detail="cron_alert_interval must be >= 60 seconds")
        settings.cron_alert_interval = req.cron_alert_interval
        updates.append("cron_alert_interval")
    if req.cron_alert_enabled is not None:
        settings.cron_alert_enabled = req.cron_alert_enabled
        updates.append("cron_alert_enabled")
    if req.gateway_alert_enabled is not None:
        settings.gateway_alert_enabled = req.gateway_alert_enabled
        updates.append("gateway_alert_enabled")
    if req.disk_alert_threshold is not None:
        if req.disk_alert_threshold < 0 or req.disk_alert_threshold > 100:
            raise HTTPException(
                status_code=400, detail="disk_alert_threshold must be 0-100 (0=off)"
            )
        settings.disk_alert_threshold = req.disk_alert_threshold
        updates.append("disk_alert_threshold")
    profile = req.profile or settings.alert_profile or "default"
    try:
        path = save_alert_settings(
            settings, profile=profile, activate=req.activate
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    logger.info(
        "alert settings updated: %s profile=%s path=%s", updates, profile, path
    )
    return {
        "updated": updates,
        "status": "ok",
        "persisted": True,
        "profile": profile,
        "path": str(path),
        "settings": _alert_response(settings),
    }


@router.get("/system-status", response_model=SystemStatus)
async def system_status(request: Request, refresh: bool = False) -> SystemStatus:
    monitor = request.app.state.monitor
    return await monitor.get_system_status(force_refresh=refresh)


@router.get("/sessions", response_model=list[SessionInfo])
async def list_sessions(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
) -> list[SessionInfo]:
    monitor = request.app.state.monitor
    sessions, _ = await monitor.get_sessions(limit=limit)
    return sessions


@router.get("/sessions/{session_id}", response_model=SessionDetail)
async def session_detail(
    request: Request,
    session_id: str = Path(..., description="Session ID"),
) -> SessionDetail:
    """获取 Session 详情（最近消息记录）。"""
    monitor = request.app.state.monitor
    detail = await monitor.get_session_detail(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return detail


@router.get("/cron-alerts")
async def cron_alerts(request: Request):
    """兼容旧路径：返回 Cron 错误 + 近期告警（含 gateway；启动时从 DB 加载，新告警同步落库）。"""
    watcher = request.app.state.alert_watcher
    errors = await watcher.check_once()
    gateway_alerts = [
        a for a in watcher.recent_alerts if a.get("kind") == "gateway"
    ]
    return {
        "errors": [e.model_dump() for e in errors],
        "recent_alerts": watcher.recent_alerts,
        "gateway_alerts": gateway_alerts,
        "persisted": True,
    }


@router.post("/cron/{cron_id}/repair", response_model=TaskInfo, status_code=201)
async def repair_cron(
    request: Request,
    cron_id: str = Path(..., description="Cron job id（Hermes 为 hermes:<id>）"),
    body: CronRepairRequest | None = None,
) -> TaskInfo:
    """将异常 Cron 派单给 ops-agent 进行诊断/修复（创建 AgentCenter 任务）。"""
    monitor = request.app.state.monitor
    jobs = await monitor.get_cron_jobs()
    job = next((j for j in jobs if j.id == cron_id), None)
    if not job:
        raise HTTPException(status_code=404, detail=f"cron job not found: {cron_id}")

    req = body or CronRepairRequest()
    try:
        return await dispatch_cron_repair(
            job=job,
            settings=request.app.state.settings,
            registry=request.app.state.registry,
            task_manager=request.app.state.task_manager,
            note=req.note,
            workspace_id=req.workspace_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
