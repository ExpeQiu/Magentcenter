"""系统状态 / Sessions / Settings API。"""

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel

from app.core.openclaw_monitor import SessionDetail, SessionInfo, SystemStatus

router = APIRouter(prefix="/api", tags=["system"])


# ── Alert Settings ─────────────────────────────────────────────────────────


class AlertSettingsResponse(BaseModel):
    webhook_url_set: bool
    webhook_url_masked: str
    cron_alert_interval: int


class AlertSettingsUpdate(BaseModel):
    feishu_webhook_url: str | None = None
    cron_alert_interval: int | None = None


@router.get("/settings/alert", response_model=AlertSettingsResponse)
async def get_alert_settings(request: Request):
    settings = request.app.state.settings
    url = settings.feishu_webhook_url
    masked = f"{url[:8]}...{url[-4:]}" if url and len(url) > 12 else ("" if not url else url)
    return AlertSettingsResponse(
        webhook_url_set=bool(url),
        webhook_url_masked=masked,
        cron_alert_interval=settings.cron_alert_interval,
    )


@router.patch("/settings/alert")
async def update_alert_settings(req: AlertSettingsUpdate, request: Request):
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
    return {"updated": updates, "status": "ok"}


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
    watcher = request.app.state.alert_watcher
    errors = await watcher.check_once()
    return {
        "errors": [e.model_dump() for e in errors],
        "recent_alerts": watcher.recent_alerts,
    }
