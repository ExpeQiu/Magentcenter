"""WebSocket 事件流。连接前校验身份、来源和任务归属，再按游标读取。"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException

from app.config import get_settings
from app.core.access import AuthError, authenticate_websocket, task_visible
from app.models.schemas import TaskEvent

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])
_TERMINAL = {"completed", "failed", "cancelled", "timeout"}


@router.websocket("/ws/tasks/{task_id}")
async def ws_task_events(websocket: WebSocket, task_id: str):
    settings = getattr(websocket.app.state, "settings", None) or get_settings()
    try:
        principal = await authenticate_websocket(websocket, settings)
    except AuthError as exc:
        logger.info("ws denied task_id=%s status=%s detail=%s", task_id, exc.status_code, exc.detail)
        raise WebSocketException(code=1008, reason=exc.detail) from exc
    await websocket.accept()
    tm = websocket.app.state.task_manager
    task = await tm.get_task(task_id)
    if not task:
        logger.info("ws task missing task_id=%s kind=%s", task_id, principal.kind)
        await websocket.close(code=4004, reason="task not found")
        return
    if not await task_visible(principal, task):
        logger.info(
            "ws task forbidden task_id=%s kind=%s node_id=%s",
            task_id,
            principal.kind,
            principal.node_id,
        )
        await websocket.close(code=4403, reason="task forbidden")
        return

    last = 0
    try:
        query = websocket.query_params.get("after") or "0"
        last = int(query)
    except ValueError:
        last = 0
    idle = 0
    try:
        while True:
            batch = await tm.get_events(task_id, after_id=last)
            if batch:
                idle = 0
                for ev in batch:
                    last = ev.id or last
                    await websocket.send_json(_event_payload(ev))
                    if ev.type == "result":
                        return
                continue
            task = await tm.get_task(task_id)
            if task and task.status in _TERMINAL and not task.attention_required:
                return
            await asyncio.sleep(0.4)
            idle += 1
            if idle >= 75:
                await websocket.send_json({"type": "heartbeat", "content": "ping"})
                idle = 0
    except WebSocketDisconnect:
        logger.info("ws disconnected task_id=%s", task_id)
    finally:
        await websocket.close()


def _event_payload(ev: TaskEvent) -> dict:
    payload = ev.model_dump(mode="json")
    if isinstance(payload.get("timestamp"), datetime):
        payload["timestamp"] = payload["timestamp"].isoformat()
    return payload
