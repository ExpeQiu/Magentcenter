"""Cron 异常派单修复：封装 ops-agent 任务创建。"""

from __future__ import annotations

import logging
import uuid

from app.config import Settings
from app.core.agent_registry import AgentRegistry
from app.core.openclaw_monitor import CronJobInfo
from app.core.task_manager import TaskManager
from app.models.schemas import CreateTaskRequest, TaskInfo

logger = logging.getLogger(__name__)

FALLBACK_AGENTS = ("ops-agent", "ops", "main")


def build_repair_prompt(job: CronJobInfo, note: str = "") -> str:
    lines = [
        f"你是运维修复 Agent。请诊断并修复以下 {job.runtime or job.source or 'openclaw'} Cron 任务异常。",
        "",
        "## 异常 Cron",
        f"- id: `{job.id}`",
        f"- runtime: {job.runtime or job.source or 'openclaw'}",
        f"- name: {job.name}",
        f"- agent_id: {job.agent_id or '—'}",
        f"- schedule: {job.schedule or '—'}",
        f"- status: {job.status or '—'}",
        f"- last_status: {job.last_status or '—'}",
        f"- last_run: {job.last_run or '—'}",
        f"- enabled: {job.enabled}",
        "",
        "## 要求",
        "1. 查清失败原因（日志 / session / gateway / 依赖）。",
        "2. 在授权范围内给出可执行修复步骤并尽量落地。",
        "3. 无法自动修复时，输出明确阻塞点与人工操作清单。",
        "4. 最后给出：根因、已做操作、验证建议、是否建议重跑该 cron。",
    ]
    if note.strip():
        lines.extend(["", "## 附加说明", note.strip()])
    return "\n".join(lines)


async def resolve_repair_agent(
    registry: AgentRegistry, preferred: str, runtime: str = "openclaw"
) -> str | None:
    candidates: list[str] = []
    for a in (preferred, *FALLBACK_AGENTS):
        if a and a not in candidates:
            candidates.append(a)
    for agent_id in candidates:
        if await registry.get_agent(agent_id, runtime=runtime):
            return agent_id
    # Hermes 侧常只有 default
    if runtime == "hermes" and await registry.get_agent("default", runtime="hermes"):
        return "default"
    return None


async def dispatch_cron_repair(
    *,
    job: CronJobInfo,
    settings: Settings,
    registry: AgentRegistry,
    task_manager: TaskManager,
    note: str = "",
    workspace_id: str = "",
) -> TaskInfo:
    run_id = uuid.uuid4().hex[:12]
    runtime = job.runtime or job.source or "openclaw"
    # 修复任务默认走 OpenClaw ops-agent；Hermes cron 也可派到 hermes/default
    repair_runtime = "hermes" if runtime == "hermes" else "openclaw"
    agent_id = await resolve_repair_agent(
        registry, settings.ops_repair_agent_id, runtime=repair_runtime
    )
    if not agent_id:
        raise ValueError(
            f"repair agent not found (tried {settings.ops_repair_agent_id} and fallbacks)"
        )

    prompt = build_repair_prompt(job, note=note)
    # 将本次症状写入故障百科，供后续 ops 检索
    try:
        from app.core.knowledge import upsert_incident_from_alert

        await upsert_incident_from_alert(
            alert_key=f"cron:{job.id}:{run_id}",
            title=f"Cron 异常 · {job.name or job.id}",
            symptom=f"{job.name or job.id} last_status={job.last_status or job.status or 'error'}",
            root_cause=note.strip() or "cron alert",
            fix="派单 ops 诊断；查日志 / session / gateway / 依赖",
            cron_id=job.id,
            runtime=repair_runtime,
            workspace_id=workspace_id,
        )
    except Exception as e:
        logger.warning("cron repair incident upsert failed cron_id=%s: %s", job.id, e)

    logger.info(
        "cron repair dispatch run_id=%s cron_id=%s cron_name=%s runtime=%s agent_id=%s",
        run_id,
        job.id,
        job.name,
        repair_runtime,
        agent_id,
    )
    task = await task_manager.create_task(
        CreateTaskRequest(
            agent_id=agent_id,
            runtime=repair_runtime,  # type: ignore[arg-type]
            prompt=prompt,
            system_prompt=(
                f"[AgentCenter cron-repair run_id={run_id} cron_id={job.id}] "
                "优先诊断与安全修复，重大变更前确认授权。"
            ),
            workspace_id=workspace_id,
            inject_knowledge=True,
        )
    )
    logger.info(
        "cron repair task created run_id=%s cron_id=%s task_id=%s agent_id=%s",
        run_id,
        job.id,
        task.id,
        agent_id,
    )
    return task
