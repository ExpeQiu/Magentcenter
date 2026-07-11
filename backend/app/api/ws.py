"""WebSocket 事件流 API。"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models.schemas import TaskEvent

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/tasks/{task_id}")
async def ws_task_events(websocket: WebSocket, task_id: str):
    await websocket.accept()
    tm = websocket.app.state.task_manager
    task = await tm.get_task(task_id)
    if not task:
        await websocket.close(code=4004, reason="task not found")
        return

    history = await tm.get_events(task_id)
    for ev in history:
        await websocket.send_json(_event_payload(ev))

    queue = tm.subscribe(task_id)
    try:
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=30)
            except asyncio.TimeoutError:
                task = await tm.get_task(task_id)
                if task and task.status in (
                    "completed",
                    "failed",
                    "cancelled",
                    "timeout",
                ):
                    break
                await websocket.send_json({"type": "heartbeat", "content": "ping"})
                continue

            await websocket.send_json(_event_payload(ev))
            if ev.type == "result":
                break
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


def _event_payload(ev: TaskEvent) -> dict:
    payload = ev.model_dump(mode="json")
    if isinstance(payload.get("timestamp"), datetime):
        payload["timestamp"] = payload["timestamp"].isoformat()
    return payload
