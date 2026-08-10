"""Autopilot 定时任务：本地调度 + OpenClaw / Hermes Cron 镜像。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings
from app.core.hermes_monitor import HermesMonitor
from app.core.task_manager import TaskManager
from app.models.db import AutopilotRecord, get_session_factory
from app.models.schemas import CreateTaskRequest, TaskInfo

logger = logging.getLogger(__name__)

HERMES_JOB_ID_RE = re.compile(r"\b([a-f0-9]{10,})\b")


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
    hermes_id: str = ""
    runtime: str = "openclaw"
    status: str = ""
    schedule: str = ""


class AutopilotManager:
    def __init__(self, settings: Settings, task_manager: TaskManager):
        self.settings = settings
        self.task_manager = task_manager
        self.executable = settings.openclaw_executable
        self.hermes_executable = settings.hermes_executable
        self._configs: dict[str, AutopilotConfig] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._hermes_monitor = HermesMonitor(settings)

    def _hermes_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.settings.hermes_home:
            env["HERMES_HOME"] = os.path.expanduser(self.settings.hermes_home)
        return env

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

    async def _run_hermes(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        if not shutil.which(self.hermes_executable):
            return 127, "", "hermes not found"
        logger.info("hermes autopilot cmd: %s", " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            self.hermes_executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._hermes_env(),
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
                    hermes_id=getattr(rec, "hermes_id", "") or "",
                    runtime=getattr(rec, "runtime", None) or "openclaw",
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
                    hermes_id=cfg.hermes_id or "",
                    runtime=cfg.runtime or "openclaw",
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
                rec.hermes_id = cfg.hermes_id or ""
                rec.runtime = cfg.runtime or "openclaw"
                rec.last_run = cfg.last_run
            await session.commit()

    async def _delete_db(self, autopilot_id: str) -> None:
        factory = get_session_factory()
        async with factory() as session:
            rec = await session.get(AutopilotRecord, autopilot_id)
            if rec:
                await session.delete(rec)
                await session.commit()

    async def _fetch_openclaw_cron(self, *, strict: bool = False) -> list[AutopilotConfig]:
        if self.settings.ai_mock_mode:
            return [
                AutopilotConfig(
                    id="openclaw:mock-cron-ok-1",
                    name="【Mock】OpenClaw 正常定时",
                    agent_id="ops",
                    prompt="mock openclaw cron",
                    cron="0 9 * * *",
                    enabled=True,
                    source="openclaw",
                    openclaw_id="mock-cron-ok-1",
                    runtime="openclaw",
                    status="ok",
                    schedule="0 9 * * *",
                )
            ]
        if "openclaw" not in self.settings.enabled_runtimes():
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
                        runtime="openclaw",
                        status=j.get("status", state.get("lastStatus", "")),
                        schedule=schedule_str,
                    )
                )
            return items
        except Exception as e:
            logger.error("fetch openclaw cron failed: %s", e)
            if strict:
                raise
            return []

    async def _fetch_hermes_cron(self, *, strict: bool = False) -> list[AutopilotConfig]:
        if "hermes" not in self.settings.enabled_runtimes():
            return []
        try:
            jobs = await self._hermes_monitor.get_cron_jobs()
        except Exception as e:
            logger.error("fetch hermes cron failed: %s", e)
            if strict:
                raise
            return []
        items: list[AutopilotConfig] = []
        for j in jobs:
            hid = j.id.replace("hermes:", "", 1) if j.id.startswith("hermes:") else j.id
            items.append(
                AutopilotConfig(
                    id=j.id if j.id.startswith("hermes:") else f"hermes:{j.id}",
                    name=j.name,
                    agent_id=j.agent_id or "default",
                    prompt="",
                    cron=j.schedule,
                    enabled=j.enabled,
                    source="hermes",
                    hermes_id=hid,
                    runtime="hermes",
                    status=j.status or j.last_status,
                    schedule=j.schedule,
                    last_run=None,
                )
            )
        return items
    async def sync_from_openclaw(self) -> list[AutopilotConfig]:
        jobs = await self._fetch_openclaw_cron()
        synced = []
        for job in jobs:
            existing = next(
                (c for c in self._configs.values() if c.openclaw_id == job.openclaw_id),
                None,
            )
            if existing:
                existing.name = job.name
                existing.agent_id = job.agent_id
                existing.prompt = job.prompt
                existing.cron = job.cron
                existing.enabled = job.enabled
                existing.status = job.status
                existing.runtime = "openclaw"
                await self._save(existing)
                synced.append(existing)
            else:
                new_cfg = AutopilotConfig(
                    id=str(uuid.uuid4()),
                    name=job.name,
                    agent_id=job.agent_id,
                    prompt=job.prompt,
                    cron=job.cron,
                    enabled=job.enabled,
                    source="openclaw",
                    openclaw_id=job.openclaw_id,
                    runtime="openclaw",
                    status=job.status,
                )
                self._configs[new_cfg.id] = new_cfg
                await self._save(new_cfg)
                synced.append(new_cfg)
        logger.info("sync_from_openclaw: %d jobs synced", len(synced))
        return synced

    async def sync_from_hermes(self) -> list[AutopilotConfig]:
        jobs = await self._fetch_hermes_cron()
        synced = []
        for job in jobs:
            existing = next(
                (c for c in self._configs.values() if c.hermes_id == job.hermes_id),
                None,
            )
            if existing:
                existing.name = job.name
                existing.agent_id = job.agent_id
                existing.cron = job.cron
                existing.enabled = job.enabled
                existing.status = job.status
                existing.runtime = "hermes"
                await self._save(existing)
                synced.append(existing)
            else:
                new_cfg = AutopilotConfig(
                    id=str(uuid.uuid4()),
                    name=job.name,
                    agent_id=job.agent_id,
                    prompt=job.prompt,
                    cron=job.cron,
                    enabled=job.enabled,
                    source="hermes",
                    hermes_id=job.hermes_id,
                    runtime="hermes",
                    status=job.status,
                )
                self._configs[new_cfg.id] = new_cfg
                await self._save(new_cfg)
                synced.append(new_cfg)
        logger.info("sync_from_hermes: %d jobs synced", len(synced))
        return synced

    async def sync_to_openclaw(self, autopilot_id: str) -> AutopilotConfig:
        cfg = self._configs.get(autopilot_id)
        if not cfg:
            raise ValueError(f"autopilot not found: {autopilot_id}")
        if autopilot_id.startswith("openclaw:") or autopilot_id.startswith("hermes:"):
            raise ValueError("Cannot sync an external-sourced autopilot")
        oc_id = await self._sync_to_openclaw(cfg)
        if not oc_id:
            raise ValueError("openclaw cron add did not return a job id")
        cfg.openclaw_id = oc_id
        cfg.source = "bidirectional"
        cfg.runtime = "openclaw"
        await self._save(cfg)
        logger.info("sync_to_openclaw: %s -> %s", autopilot_id, oc_id)
        return cfg

    async def sync_to_hermes(self, autopilot_id: str) -> AutopilotConfig:
        cfg = self._configs.get(autopilot_id)
        if not cfg:
            raise ValueError(f"autopilot not found: {autopilot_id}")
        if autopilot_id.startswith("openclaw:") or autopilot_id.startswith("hermes:"):
            raise ValueError("Cannot sync an external-sourced autopilot")
        hid = await self._sync_to_hermes(cfg)
        if not hid:
            raise ValueError("hermes cron create did not return a job id")
        cfg.hermes_id = hid
        cfg.source = "bidirectional"
        cfg.runtime = "hermes"
        await self._save(cfg)
        logger.info("sync_to_hermes: %s -> %s", autopilot_id, hid)
        return cfg

    async def remove_from_openclaw(self, cron_id: str) -> bool:
        code, out, err = await self._run_cmd("cron", "remove", cron_id, timeout=30)
        if code != 0:
            logger.error("openclaw cron remove failed: %s", err or out)
            raise ValueError(f"openclaw cron remove failed: {err or out}")
        logger.info("remove_from_openclaw: %s deleted", cron_id)
        return True

    async def remove_from_hermes(self, cron_id: str) -> bool:
        hid = cron_id.replace("hermes:", "", 1)
        if self.settings.ai_mock_mode:
            logger.info("remove_from_hermes mock: %s", hid)
            return True
        code, out, err = await self._run_hermes("cron", "remove", hid, timeout=30)
        if code != 0:
            logger.error("hermes cron remove failed: %s", err or out)
            raise ValueError(f"hermes cron remove failed: {err or out}")
        logger.info("remove_from_hermes: %s deleted", hid)
        return True

    async def list_autopilots(
        self,
        include_openclaw: bool = True,
        include_hermes: bool = True,
    ) -> list[AutopilotConfig]:
        local = list(self._configs.values())
        merged = list(local)
        local_oc = {c.openclaw_id for c in local if c.openclaw_id}
        local_hm = {c.hermes_id for c in local if c.hermes_id}

        if include_openclaw:
            for j in await self._fetch_openclaw_cron():
                if j.openclaw_id not in local_oc:
                    merged.append(j)
        if include_hermes:
            for j in await self._fetch_hermes_cron():
                if j.hermes_id not in local_hm:
                    merged.append(j)
        return merged

    async def _drop_local(self, autopilot_id: str, reason: str) -> None:
        """删除本地记录（不触碰外部 cron；用于对账清孤儿）。"""
        if autopilot_id in self._tasks:
            self._tasks[autopilot_id].cancel()
            del self._tasks[autopilot_id]
        cfg = self._configs.pop(autopilot_id, None)
        await self._delete_db(autopilot_id)
        logger.info(
            "autopilot reconcile drop id=%s name=%s reason=%s",
            autopilot_id,
            cfg.name if cfg else "-",
            reason,
        )

    async def reconcile_external(self) -> dict:
        """以 OpenClaw / Hermes 现况为准，更新本地库后返回聚合列表。

        - 外部已删除的镜像本地行 → 删除
        - 外部仍存在的 → 同步字段到本地
        - 外部新增未镜像的 → 写入本地
        - 纯本地（无 openclaw_id/hermes_id）→ 保留
        拉取失败时跳过该侧清理，避免误删。
        """
        pruned: list[str] = []
        oc_ok = False
        hm_ok = False
        live_oc: set[str] = set()
        live_hm: set[str] = set()

        if "openclaw" in self.settings.enabled_runtimes():
            try:
                oc_jobs = await self._fetch_openclaw_cron(strict=True)
                live_oc = {j.openclaw_id for j in oc_jobs if j.openclaw_id}
                oc_ok = True
            except Exception as e:
                logger.warning("reconcile skip openclaw prune: %s", e)

        if "hermes" in self.settings.enabled_runtimes():
            try:
                hm_jobs = await self._fetch_hermes_cron(strict=True)
                live_hm = {j.hermes_id for j in hm_jobs if j.hermes_id}
                hm_ok = True
            except Exception as e:
                logger.warning("reconcile skip hermes prune: %s", e)

        for cfg in list(self._configs.values()):
            oc_id = (cfg.openclaw_id or "").strip()
            hm_id = (cfg.hermes_id or "").strip()
            if not oc_id and not hm_id:
                continue  # 纯本地调度

            changed = False
            if oc_id and oc_ok and oc_id not in live_oc:
                cfg.openclaw_id = ""
                changed = True
                logger.info(
                    "autopilot reconcile clear stale openclaw_id id=%s oc=%s",
                    cfg.id,
                    oc_id,
                )
            if hm_id and hm_ok and hm_id not in live_hm:
                cfg.hermes_id = ""
                changed = True
                logger.info(
                    "autopilot reconcile clear stale hermes_id id=%s hm=%s",
                    cfg.id,
                    hm_id,
                )

            if not (cfg.openclaw_id or "").strip() and not (cfg.hermes_id or "").strip():
                # 曾绑定外部 cron，现两侧均已不存在 → 删除本地镜像
                await self._drop_local(
                    cfg.id,
                    f"external_gone oc={oc_id or '-'} hm={hm_id or '-'}",
                )
                pruned.append(cfg.id)
                continue

            if changed:
                if cfg.openclaw_id and cfg.hermes_id:
                    cfg.source = "bidirectional"
                elif cfg.hermes_id:
                    cfg.source = "hermes"
                    cfg.runtime = "hermes"
                else:
                    cfg.source = "openclaw"
                    cfg.runtime = "openclaw"
                await self._save(cfg)

        synced_oc: list[AutopilotConfig] = []
        synced_hm: list[AutopilotConfig] = []
        if oc_ok:
            synced_oc = await self.sync_from_openclaw()
        if hm_ok:
            synced_hm = await self.sync_from_hermes()

        items = await self.list_autopilots(include_openclaw=True, include_hermes=True)
        logger.info(
            "autopilot reconcile done pruned=%d synced_oc=%d synced_hm=%d list=%d",
            len(pruned),
            len(synced_oc),
            len(synced_hm),
            len(items),
        )
        return {
            "pruned": pruned,
            "pruned_count": len(pruned),
            "synced_openclaw": len(synced_oc),
            "synced_hermes": len(synced_hm),
            "items": items,
        }
    def get_autopilot(self, autopilot_id: str) -> AutopilotConfig | None:
        return self._configs.get(autopilot_id)

    async def _sync_to_openclaw(self, cfg: AutopilotConfig) -> str:
        if self.settings.ai_mock_mode:
            return f"mock-oc-{uuid.uuid4().hex[:8]}"
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

    @staticmethod
    def _to_hermes_schedule(cron: str) -> str:
        if cron.isdigit():
            secs = max(60, int(cron))
            if secs % 3600 == 0:
                return f"every {max(1, secs // 3600)}h"
            if secs % 60 == 0:
                return f"every {max(1, secs // 60)}m"
            return f"every {secs}s"
        if cron == "hourly":
            return "every 1h"
        if cron == "daily":
            return "every 24h"
        return cron

    async def _sync_to_hermes(self, cfg: AutopilotConfig) -> str:
        if self.settings.ai_mock_mode:
            return f"mockhm{uuid.uuid4().hex[:10]}"
        schedule = self._to_hermes_schedule(cfg.cron)
        args = [
            "cron",
            "create",
            schedule,
            cfg.prompt,
            "--name",
            cfg.name,
            "--deliver",
            "local",
        ]
        code, out, err = await self._run_hermes(*args, timeout=60)
        text = out or err
        if code != 0:
            raise ValueError(f"hermes cron create failed: {err or out}")
        m = HERMES_JOB_ID_RE.search(text)
        return m.group(1) if m else ""

    async def create_autopilot(
        self,
        name: str,
        agent_id: str,
        prompt: str,
        cron: str = "3600",
        enabled: bool = True,
        runtime: str = "openclaw",
        sync_to_openclaw: bool = False,
        sync_to_hermes: bool = False,
    ) -> AutopilotConfig:
        runtime = runtime or "openclaw"
        if runtime not in ("openclaw", "hermes"):
            raise ValueError(f"unsupported runtime: {runtime}")
        if not self.settings.is_runtime_enabled(runtime):
            raise ValueError(f"runtime not enabled: {runtime}")

        cfg = AutopilotConfig(
            id=str(uuid.uuid4()),
            name=name,
            agent_id=agent_id,
            prompt=prompt,
            cron=cron,
            enabled=enabled,
            runtime=runtime,
        )
        if sync_to_openclaw and runtime == "openclaw":
            cfg.openclaw_id = await self._sync_to_openclaw(cfg)
            if cfg.openclaw_id:
                cfg.source = "bidirectional"
        if sync_to_hermes and runtime == "hermes":
            cfg.hermes_id = await self._sync_to_hermes(cfg)
            if cfg.hermes_id:
                cfg.source = "bidirectional"

        self._configs[cfg.id] = cfg
        await self._save(cfg)
        if enabled and not cfg.openclaw_id and not cfg.hermes_id:
            # 仅本地调度；已镜像到外部 cron 的不再双跑
            self._schedule(cfg)
        logger.info(
            "autopilot created id=%s runtime=%s agent=%s cron=%s oc=%s hm=%s",
            cfg.id,
            runtime,
            agent_id,
            cron,
            cfg.openclaw_id or "-",
            cfg.hermes_id or "-",
        )
        return cfg

    async def delete_autopilot(self, autopilot_id: str) -> bool:
        if autopilot_id.startswith("openclaw:") or autopilot_id.startswith("hermes:"):
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
        logger.info(
            "autopilot trigger id=%s runtime=%s agent=%s",
            cfg.id,
            cfg.runtime,
            cfg.agent_id,
        )
        req = CreateTaskRequest(
            agent_id=cfg.agent_id,
            runtime=cfg.runtime if cfg.runtime in ("openclaw", "hermes") else "openclaw",  # type: ignore[arg-type]
            prompt=f"[Autopilot: {cfg.name}] {cfg.prompt}",
        )
        task = await self.task_manager.create_task(req)
        cfg.last_run = datetime.utcnow()
        await self._save(cfg)
        return task

    async def trigger_now(self, autopilot_id: str) -> TaskInfo:
        if autopilot_id.startswith("openclaw:"):
            oc_id = autopilot_id.replace("openclaw:", "", 1)
            if self.settings.ai_mock_mode:
                return TaskInfo(
                    id=f"openclaw-run-{oc_id[:8]}",
                    agent_id="openclaw",
                    runtime="openclaw",
                    prompt=f"[OpenClaw Cron Run] {oc_id}",
                    status="completed",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            code, out, err = await self._run_cmd("cron", "run", oc_id, timeout=60)
            if code != 0:
                raise ValueError(f"openclaw cron run failed: {err or out}")
            return TaskInfo(
                id=f"openclaw-run-{oc_id[:8]}",
                agent_id="openclaw",
                runtime="openclaw",
                prompt=f"[OpenClaw Cron Run] {oc_id}",
                status="completed",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )

        if autopilot_id.startswith("hermes:"):
            hid = autopilot_id.replace("hermes:", "", 1)
            if self.settings.ai_mock_mode:
                return TaskInfo(
                    id=f"hermes-run-{hid[:8]}",
                    agent_id="default",
                    runtime="hermes",
                    prompt=f"[Hermes Cron Run] {hid}",
                    status="completed",
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            code, out, err = await self._run_hermes("cron", "run", hid, timeout=60)
            if code != 0:
                raise ValueError(f"hermes cron run failed: {err or out}")
            return TaskInfo(
                id=f"hermes-run-{hid[:8]}",
                agent_id="default",
                runtime="hermes",
                prompt=f"[Hermes Cron Run] {hid}",
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
            if cfg.enabled and not cfg.openclaw_id and not cfg.hermes_id:
                self._schedule(cfg)
        logger.info("autopilot manager started, %d active", len(self._tasks))

    def stop(self) -> None:
        self._running = False
        for t in self._tasks.values():
            t.cancel()
        self._tasks.clear()
