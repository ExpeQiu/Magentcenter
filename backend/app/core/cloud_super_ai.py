"""PC/full 端：联网协同时把超级AI turn 转到云端 Client Session。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings
from app.core import client_session as client_svc
from app.core import fleet as fleet_service
from app.core.identity import load_or_create_identity

logger = logging.getLogger(__name__)


class CloudSuperAiError(Exception):
    def __init__(self, detail: str, status_code: int = 503):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


async def remote_cloud_target(settings: Settings, workspace_id: str = "") -> dict[str, Any] | None:
    """返回需转发的云端地址；本机即云端或未绑定则 None。"""
    try:
        link = await fleet_service.link_status(
            workspace_id or "",
            env_cloud_url=settings.fleet_cloud_url or "",
        )
    except Exception:
        logger.exception("cloud super_ai link_status failed")
        return None
    cloud_url = str(link.get("cloud_url") or "").rstrip("/")
    if not cloud_url:
        return None
    if link.get("local_cloud"):
        return None
    return {"cloud_url": cloud_url, "link": link}


async def ensure_client_session(settings: Settings, *, cloud_url: str, workspace_id: str = "") -> dict:
    """确保本机持有对云端的 Client Session；必要时用 enroll_token 注册。"""
    saved = client_svc.load_local_client_session() or {}
    token = str(saved.get("client_token") or "")
    same_cloud = str(saved.get("cloud_url") or "").rstrip("/") == cloud_url.rstrip("/")
    if token and same_cloud:
        return saved
    enroll_token = (settings.fleet_enroll_token or "").strip()
    if not enroll_token:
        raise CloudSuperAiError("未配置 FLEET_ENROLL_TOKEN，无法向云端注册 Client Session", 503)
    ident = load_or_create_identity(settings.normalized_profile())
    payload = {
        "enroll_token": enroll_token,
        "center_id": ident.center_id,
        "client_id": ident.center_id,
        "workspace_id": workspace_id or "cyber",
        "device_id": ident.node_id,
        "protocol_version": 2,
    }
    url = cloud_url.rstrip("/") + "/api/v2/clients/enroll"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        logger.warning("client enroll transport failed cloud=%s err=%s", cloud_url, exc)
        raise CloudSuperAiError(f"云端不可达：{exc}", 503) from exc
    if resp.status_code >= 400:
        logger.warning(
            "client enroll rejected cloud=%s status=%s body=%s",
            cloud_url,
            resp.status_code,
            (resp.text or "")[:200],
        )
        raise CloudSuperAiError(
            f"云端 Client Session 注册失败（{resp.status_code}）",
            503 if resp.status_code >= 500 else resp.status_code,
        )
    data = resp.json()
    stored = {
        "cloud_url": cloud_url,
        "client_token": data.get("client_token") or "",
        "client_id": data.get("client_id") or ident.center_id,
        "session_id": data.get("session_id") or "",
        "center_id": data.get("center_id") or ident.center_id,
        "workspace_id": data.get("workspace_id") or workspace_id or "cyber",
        "expires_at": data.get("expires_at") or "",
    }
    if not stored["client_token"]:
        raise CloudSuperAiError("云端未返回 client_token", 503)
    client_svc.save_local_client_session(stored)
    return stored


async def forward_turn(
    settings: Settings,
    body: dict[str, Any],
    *,
    workspace_id: str = "",
) -> dict[str, Any]:
    target = await remote_cloud_target(settings, workspace_id=workspace_id)
    if target is None:
        raise CloudSuperAiError("not_remote", 404)
    cloud_url = target["cloud_url"]
    session = await ensure_client_session(
        settings, cloud_url=cloud_url, workspace_id=workspace_id or body.get("workspace_slug") or "cyber"
    )
    url = cloud_url.rstrip("/") + "/api/super-ai/client/turn"
    headers = {"X-Client-Token": session["client_token"], "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("cloud turn transport failed cloud=%s err=%s", cloud_url, exc)
        raise CloudSuperAiError(
            "云端超级AI 暂时不可达。本地任务台仍可建单；超级AI 建单需云端在线。",
            503,
        ) from exc
    if resp.status_code == 401:
        # token 失效：清本地再试一次
        client_svc.clear_local_client_session()
        session = await ensure_client_session(
            settings,
            cloud_url=cloud_url,
            workspace_id=workspace_id or body.get("workspace_slug") or "cyber",
        )
        headers["X-Client-Token"] = session["client_token"]
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=body, headers=headers)
    if resp.status_code >= 400:
        detail = (resp.text or "")[:300]
        logger.warning("cloud turn rejected status=%s body=%s", resp.status_code, detail)
        raise CloudSuperAiError(
            "云端超级AI 拒绝请求。请检查 Client Session 或稍后再试。",
            resp.status_code if resp.status_code < 500 else 503,
        )
    data = resp.json()
    logger.info(
        "cloud turn forwarded cloud=%s run_id=%s intent=%s task_id=%s",
        cloud_url,
        data.get("run_id") or "-",
        data.get("intent") or "-",
        data.get("task_id") or "-",
    )
    return data
