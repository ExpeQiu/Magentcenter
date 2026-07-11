"""Autopilot 定时任务模块：SQLite 持久化 + OpenClaw Cron 镜像。"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.core.task_manager import TaskManager
from app.models.db import AutopilotRecord, get_session_factory
from app.models.schemas import CreateTaskRequest, TaskInfo

logger = logging.getLogger(__name__)


class AutopilotConfig(BaseModel):
    id: str
    name: str
    agent_id: str
    prompt: str
    cron: str = "3600"
    enabled: bool = True
    last_run: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "local"
    openclaw_id: str = ""
    status: str = ""
    schedule: str = ""


class AutopilotManager:
    def __init__(self, settings: Settings, task_manager: TaskManager):
        self.settings = settings
        self.task_manager = task_manager
        self.executable = settings.openclaw_executable
        self._configs: dict[str, AutopilotConfig] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    async def _run_cmd(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def load_from_db(self) -> None:
        factory = get_session_factory()
        async with factory() as session:
            rows = (await session.execute(select(AutopilotRecord))).scalars().all()
            for rec in rows:
                cfg = AutopilotConfig(
                    id=rec.id,
                    name=rec.name,
                    agent_id=rec.agent_id,
                    prompt=rec.prompt,
                    cron=rec.cron,
                    enabled=bool(rec.enabled),
                    last_run=rec.last_run,
                    created_at=rec.created_at,
                    openclaw_id=rec.openclaw_id or "",
                )
                self._configs[cfg.id] = cfg
        logger.info("autopilot loaded %d from db", len(self._configs))

    async def _save(self, cfg: AutopilotConfig) -> None:
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(AutopilotRecord, cfg.id)
            if not rec:
                rec = AutopilotRecord(
                    id=cfg.id,
                    name=cfg.name,
                    agent_id=cfg.agent_id,
                    prompt=cfg.prompt,
                    cron=cfg.cron,
                    enabled=1 if cfg.enabled else 0,
                    openclaw_id=cfg.openclaw_id or "",
                    last_run=cfg.last_run,
                )
                session.add(rec)
            else:
                rec.name = cfg.name
                rec.agent_id = cfg.agent_id
                rec.prompt = cfg.prompt
                rec.cron = cfg.cron
                rec.enabled = 1 if cfg.enabled else 0
                rec.openclaw_id = cfg.openclaw_id or ""
                rec.last_run = cfg.last_run
            await session.commit()

    async def _delete_db(self, autopilot_id: str) -> None:
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(AutopilotRecord, autopilot_id)
            if rec:
                await session.delete(rec)
                await session.commit()

    async def _fetch_openclaw_cron(self) -> list[AutopilotConfig]:
        if self.settings.ai_mock_mode:
            return []
        try:
            _, out, _ = await self._run_cmd("cron", "list", "--json", timeout=30)
            data = json.loads(out)
            items: list[AutopilotConfig] = []
            for j in data.get("jobs", []):
                state = j.get("state", {}) or {}
                sched = j.get("schedule", {}) or {}
                schedule_str = sched.get("expr", "") or str(sched.get("everyMs", ""))
                items.append(
                    AutopilotConfig(
                        id=f"openclaw:{j.get('id', '')}",
                        name=j.get("name", ""),
                        agent_id=j.get("agentId", ""),
                        prompt=(j.get("payload") or {}).get("message", "")[:200],
                        cron=schedule_str,
                        enabled=bool(j.get("enabled", True)),
                        source="openclaw",
                        openclaw_id=j.get("id", ""),
                        status=j.get("status", state.get("lastStatus", "")),
                        schedule=schedule_str,
                    )
                )
            return items
        except Exception as e:
            logger.error("fetch openclaw cron failed: %s", e)
            return []

    async def sync_from_openclaw(self) -> list[AutopilotConfig]:
        """Fetch all OpenClaw cron jobs and save them as local autopilots."""
        jobs = await self._fetch_openclaw_cron()
        synced = []
        for job in jobs:
            # Check if already linked
            existing = None
            for cfg in self._configs.values():
                if cfg.openclaw_id == job.openclaw_id:
                    existing = cfg
                    break
            if existing:
                # Update in-place
                existing.name = job.name
                existing.agent_id = job.agent_id
                existing.prompt = job.prompt
                existing.cron = job.cron
                existing.enabled = job.enabled
                existing.status = job.status
                await self._save(existing)
                synced.append(existing)
            else:
                # Create new local record linked to this OpenClaw cron
                new_cfg = AutopilotConfig(
                    id=str(uuid.uuid4()),
                    name=job.name,
                    agent_id=job.agent_id,
                    prompt=job.prompt,
                    cron=job.cron,
                    enabled=job.enabled,
                    source="openclaw",
                    openclaw_id=job.openclaw_id,
                    status=job.status,
                )
                self._configs[new_cfg.id] = new_cfg
                await self._save(new_cfg)
                synced.append(new_cfg)
        logger.info("sync_from_openclaw: %d jobs synced", len(synced))
        return synced

    async def sync_to_openclaw(self, autopilot_id: str) -> AutopilotConfig:
        """Push a local Autopilot to OpenClaw as a new cron job."""
        cfg = self._configs.get(autopilot_id)
        if not cfg:
            raise ValueError(f"autopilot not found: {autopilot_id}")
        if autopilot_id.startswith("openclaw:"):
            raise ValueError("Cannot sync an OpenClaw-sourced autopilot back to OpenClaw")
        oc_id = await self._sync_to_openclaw(cfg)
        if not oc_id:
            raise ValueError("openclaw cron add did not return a job id")
        cfg.openclaw_id = oc_id
        cfg.source = "bidirectional"
        await self._save(cfg)
        logger.info("sync_to_openclaw: %s -> %s", autopilot_id, oc_id)
        return cfg

    async def remove_from_openclaw(self, cron_id: str) -> bool:
        """Delete a cron from OpenClaw by its cron ID."""
        code, out, err = await self._run_cmd("cron", "remove", cron_id, timeout=30)
        if code != 0:
            logger.error("openclaw cron remove failed: %s", err or out)
            raise ValueError(f"openclaw cron remove failed: {err or out}")
        logger.info("remove_from_openclaw: %s deleted", cron_id)
        return True

    async def list_autopilots(self, include_openclaw: bool = True) -> list[AutopilotConfig]:
        local = list(self._configs.values())
        if not include_openclaw:
            return local
        openclaw_jobs = await self._fetch_openclaw_cron()
        local_oc_ids = {c.openclaw_id for c in local if c.openclaw_id}
        merged = local + [j for j in openclaw_jobs if j.openclaw_id not in local_oc_ids]
        return merged

    def get_autopilot(self, autopilot_id: str) -> AutopilotConfig | None:
        return self._configs.get(autopilot_id)

    async def _sync_to_openclaw(self, cfg: AutopilotConfig) -> str:
        args = ["cron", "add", "--name", cfg.name, "--agent", cfg.agent_id]
        if cfg.cron.isdigit():
            secs = max(60, int(cfg.cron))
            args.extend(["--every", f"{secs}s"])
        elif cfg.cron in ("hourly", "daily"):
            args.extend(["--every", "1h" if cfg.cron == "hourly" else "24h"])
        else:
            args.extend(["--cron", cfg.cron])
        args.append(cfg.prompt)
        code, out, err = await self._run_cmd(*args, timeout=30)
        if code != 0:
            raise ValueError(f"openclaw cron add failed: {err or out}")
        try:
            data = json.loads(out)
            return data.get("id", "") or data.get("job", {}).get("id", "")
        except json.JSONDecodeError:
            return ""

    async def create_autopilot(
        self,
        name: str,
        agent_id: str,
        prompt: str,
        cron: str = "3600",
        enabled: bool = True,
        sync_to_openclaw: bool = False,
    ) -> AutopilotConfig:
        cfg = AutopilotConfig(
            id=str(uuid.uuid4()),
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            cron=cron,
            enabled=enabled,
        )
        if sync_to_openclaw and not self.settings.ai_mock_mode:
            cfg.openclaw_id = await self._sync_to_openclaw(cfg)
        self._configs[cfg.id] = cfg
        await self._save(cfg)
        if enabled:
            self._schedule(cfg)
        logger.info(
            "autopilot created id=%s agent=%s cron=%s openclaw=%s",
            cfg.id,
            agent_id,
            cron,
            cfg.openclaw_id or "-",
        )
        return cfg

    async def delete_autopilot(self, autopilot_id: str) -> bool:
        if autopilot_id.startswith("openclaw:"):
            return False
        if autopilot_id not in self._configs:
            return False
        if autopilot_id in self._tasks:
            self._tasks[autopilot_id].cancel()
            del self._tasks[autopilot_id]
        del self._configs[autopilot_id]
        await self._delete_db(autopilot_id)
        return True

    def _parse_interval(self, cron: str) -> int:
        if cron == "hourly":
            return 3600
        if cron == "daily":
            return 86400
        try:
            return max(60, int(cron))
        except ValueError:
            return 3600

    def _schedule(self, cfg: AutopilotConfig) -> None:
        if cfg.id in self._tasks:
            self._tasks[cfg.id].cancel()

        interval = self._parse_interval(cfg.cron)

        async def _loop():
            while cfg.id in self._configs and self._configs[cfg.id].enabled:
                try:
                    await asyncio.sleep(interval)
                    await self._trigger(cfg)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("autopilot %s error: %s", cfg.id, e)

        self._tasks[cfg.id] = asyncio.create_task(_loop())

    async def _trigger(self, cfg: AutopilotConfig) -> TaskInfo:
        logger.info("autopilot trigger id=%s agent=%s", cfg.id, cfg.agent_id)
        req = CreateTaskRequest(
            agent_id=cfg.agent_id,
            prompt=f"[Autopilot: {cfg.name}] {cfg.prompt}",
        )
        task = await self.task_manager.create_task(req)
        cfg.last_run = datetime.utcnow()
        await self._save(cfg)
        return task

    async def trigger_now(self, autopilot_id: str) -> TaskInfo:
        if autopilot_id.startswith("openclaw:"):
            oc_id = autopilot_id.replace("openclaw:", "", 1)
            code, out, err = await self._run_cmd("cron", "run", oc_id, timeout=60)
            if code != 0:
                raise ValueError(f"openclaw cron run failed: {err or out}")
            return TaskInfo(
                id=f"openclaw-run-{oc_id[:8]}",
                agent_id="openclaw",
                prompt=f"[OpenClaw Cron Run] {oc_id}",
                status="completed",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        cfg = self._configs.get(autopilot_id)
        if not cfg:
            raise ValueError(f"autopilot not found: {autopilot_id}")
        return await self._trigger(cfg)

    async def start(self) -> None:
        self._running = True
        await self.load_from_db()
        for cfg in self._configs.values():
            if cfg.enabled:
                self._schedule(cfg)
        logger.info("autopilot manager started, %d active", len(self._tasks))

    def stop(self) -> None:
        self._running = False
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()
