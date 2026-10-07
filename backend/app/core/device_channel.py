"""ESP32 等语音终端：登记、对话、取回任务结果。"""

from __future__ import annotations

import logging

from app.core import fleet as fleet_service
from app.core.fleet import FleetAuthError
from app.core.super_ai import handle_turn, task_spoken
from app.models.schemas import SuperAiPending, SuperAiTurnResponse

logger = logging.getLogger(__name__)


class DeviceAuthError(Exception):
    pass


def _clip_reply(text: str, limit: int = 480) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


async def enroll_device(
    *,
    enroll_token: str,
    expected_token: str,
    device_id: str,
    name: str = "",
) -> dict[str, str]:
    return await fleet_service.enroll_voice(
        enroll_token=enroll_token,
        expected_token=expected_token,
        device_id=device_id,
        name=name,
        hostname=device_id,
    )


async def _require_voice(token: str):
    rec = await fleet_service.authenticate(token)
    if rec is None or (rec.mode or "") != "voice":
        raise DeviceAuthError("invalid device token")
    await fleet_service.heartbeat(token)
    return rec


async def device_turn(
    token: str,
    text: str,
    *,
    workspace_slug: str,
    pending: SuperAiPending | None,
    registry,
    task_manager,
    monitor,
) -> SuperAiTurnResponse:
    rec = await _require_voice(token)
    result = await handle_turn(
        text,
        workspace_slug=workspace_slug,
        pending=pending,
        last_href="",
        registry=registry,
        task_manager=task_manager,
        monitor=monitor,
    )
    result.reply = _clip_reply(result.reply)
    logger.info(
        "super_ai device turn run_id=%s device=%s intent=%s task_id=%s",
        result.run_id,
        rec.id,
        result.intent,
        result.task_id or "-",
    )
    return result


async def device_task(token: str, task_id: str, task_manager) -> dict:
    rec = await _require_voice(token)
    task = await task_manager.get_task(task_id)
    if task is None:
        logger.info("super_ai device task missing device=%s task_id=%s", rec.id, task_id)
        return {}
    spoken = task_spoken(task)
    logger.info(
        "super_ai device task device=%s task_id=%s status=%s done=%s",
        rec.id,
        task_id,
        spoken["status"],
        spoken["done"],
    )
    return spoken
