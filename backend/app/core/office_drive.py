"""办公室外部驱动：内存队列，供工作流推角色状态。"""

from __future__ import annotations

import threading
import time
from collections import deque

from pydantic import BaseModel, Field


class OfficeBeat(BaseModel):
    agent: str = ""
    to: str = ""
    pose: str = ""
    say: str = ""
    board: str = ""
    task_id: str = ""
    task_status: str = ""
    hold_ms: int = 1200


class OfficeDriveIn(BaseModel):
    script: str = ""
    beats: list[OfficeBeat] = Field(default_factory=list)
    source: str = "external"


class OfficeDriveEvent(BaseModel):
    id: int
    at: float
    source: str
    script: str
    beats: list[OfficeBeat]


class OfficeDrive:
    def __init__(self, limit: int = 100) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._events: deque[OfficeDriveEvent] = deque(maxlen=limit)

    def push(self, payload: OfficeDriveIn) -> OfficeDriveEvent:
        with self._lock:
            self._seq += 1
            event = OfficeDriveEvent(
                id=self._seq,
                at=time.time(),
                source=(payload.source or "external").strip() or "external",
                script=payload.script,
                beats=list(payload.beats),
            )
            self._events.append(event)
            return event

    def since(self, after: int) -> tuple[list[OfficeDriveEvent], int]:
        with self._lock:
            events = [event for event in self._events if event.id > after]
            latest = self._seq
        return events, latest


office_drive = OfficeDrive()
