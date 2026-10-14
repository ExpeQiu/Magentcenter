"""轻量端本地收件箱、执行记录和结果发件箱。只使用标准库 SQLite。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class EdgeStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    dedupe_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS outbox (
                    task_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    acked INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def begin(self, task_id: str, attempt: int = 1) -> bool:
        key = f"{task_id}:{attempt}"
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO executions (dedupe_key, task_id, attempt, status) VALUES (?, ?, ?, ?)",
                    (key, task_id, attempt, "accepted"),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def save_result(self, task_id: str, result: dict) -> None:
        raw = json.dumps(result, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outbox (task_id, result_json, acked) VALUES (?, ?, 0)
                ON CONFLICT(task_id) DO UPDATE SET result_json=excluded.result_json, acked=0
                """,
                (task_id, raw),
            )

    def ack(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE outbox SET acked=1 WHERE task_id=?", (task_id,))

    def pending(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id, result_json FROM outbox WHERE acked=0"
            ).fetchall()
        items = []
        for row in rows:
            items.append({"task_id": row["task_id"], "result": json.loads(row["result_json"])})
        return items
