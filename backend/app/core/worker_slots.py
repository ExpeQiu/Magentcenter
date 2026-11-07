"""Worker 槽位：并发 Ticket 隔离登记（与 TaskManager semaphore 配合）。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SlotLease:
    task_id: str
    work_item_id: str = ""
    session_id: str = ""
    agent_key: str = ""
    acquired_at: float = field(default_factory=time.time)


class WorkerSlotPool:
    """进程内槽位表：每任务一槽，session_id 互不复用。"""

    def __init__(self, capacity: int = 3):
        self._capacity = max(1, int(capacity or 1))
        self._lock = asyncio.Lock()
        self._active: dict[str, SlotLease] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    def resize(self, capacity: int) -> None:
        self._capacity = max(1, int(capacity or 1))

    async def try_acquire(
        self,
        task_id: str,
        *,
        work_item_id: str = "",
        session_id: str = "",
        agent_key: str = "",
    ) -> SlotLease | None:
        async with self._lock:
            if task_id in self._active:
                return self._active[task_id]
            if len(self._active) >= self._capacity:
                logger.info(
                    "worker slot full capacity=%s active=%s task_id=%s",
                    self._capacity,
                    len(self._active),
                    task_id,
                )
                return None
            # 同 agent 可并行不同 task，但 session 不得撞车
            if session_id and any(
                s.session_id == session_id for s in self._active.values()
            ):
                logger.warning(
                    "worker slot session collision session=%s task_id=%s",
                    session_id[:16],
                    task_id,
                )
                return None
            lease = SlotLease(
                task_id=task_id,
                work_item_id=work_item_id,
                session_id=session_id,
                agent_key=agent_key,
            )
            self._active[task_id] = lease
            logger.info(
                "worker slot acquired task_id=%s session=%s active=%s/%s",
                task_id,
                (session_id or "-")[:16],
                len(self._active),
                self._capacity,
            )
            return lease

    async def release(self, task_id: str) -> None:
        async with self._lock:
            gone = self._active.pop(task_id, None)
            if gone:
                logger.info(
                    "worker slot released task_id=%s active=%s/%s",
                    task_id,
                    len(self._active),
                    self._capacity,
                )

    def snapshot(self) -> dict:
        return {
            "capacity": self._capacity,
            "active": len(self._active),
            "free": max(0, self._capacity - len(self._active)),
            "leases": [
                {
                    "task_id": s.task_id,
                    "work_item_id": s.work_item_id,
                    "session_id": s.session_id,
                    "agent_key": s.agent_key,
                    "acquired_at": s.acquired_at,
                }
                for s in self._active.values()
            ],
        }


_pool: WorkerSlotPool | None = None


def get_pool(capacity: int | None = None) -> WorkerSlotPool:
    global _pool
    if _pool is None:
        _pool = WorkerSlotPool(capacity=capacity or 3)
    elif capacity is not None:
        _pool.resize(capacity)
    return _pool
