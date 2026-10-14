"""WebSocket 事件流。每个连接按游标读取，不和 SSE 抢同一条内存队列。"""

import asyncio
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.models.schemas import TaskEvent

router = APIRouter(tags=["websocket"])
_TERMINAL = {"completed", "failed", "cancelled", "timeout"}


@router.websocket("/ws/tasks/{task_id}")
async def ws_task_events(websocket: WebSocket, task_id: str):
    await websocket.accept()
    tm = websocket.app.state.task_manager
    task = await tm.get_task(task_id)
    if not task:
        await websocket.close(code=4004, reason="task not found")
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
        pass
    finally:
        await websocket.close()


def _event_payload(ev: TaskEvent) -> dict:
    payload = ev.model_dump(mode="json")
    if isinstance(payload.get("timestamp"), datetime):
        payload["timestamp"] = payload["timestamp"].isoformat()
    return payload
