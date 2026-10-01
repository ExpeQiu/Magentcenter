"""Squads / Skills / Autopilot API。"""

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core import content_roots
from app.core.skills import (
    archive_skill,
    get_skill,
    install_hermes_skill,
    scan_all_skills,
)
from app.core.skill_mine import (
    list_captured,
    refine_capture,
    reject_skill,
    verify_skill,
)
from app.core.squads import get_squad, load_squads
from app.models.schemas import (
    AuditSkillRequest,
    CreateAutopilotRequest,
    CreateTaskRequest,
    InstallSkillRequest,
    InstallSkillResult,
    TaskInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["orchestration"])


class CreateSquadTaskRequest(BaseModel):
    squad_id: str
    prompt: str
    timeout: int | None = None
    runtime: str | None = None


@router.get("/api/squads")
async def list_squads():
    return load_squads()


@router.get("/api/squads/{squad_id}")
async def get_squad_detail(squad_id: str):
    squad = get_squad(squad_id)
    if not squad:
        raise HTTPException(status_code=404, detail=f"squad not found: {squad_id}")
    return squad


@router.post("/api/squads/tasks", response_model=TaskInfo, status_code=201)
async def create_squad_task(req: CreateSquadTaskRequest, request: Request) -> TaskInfo:
    from app.core.squads import build_squad_prompt

    squad = get_squad(req.squad_id)
    if not squad:
        raise HTTPException(status_code=404, detail=f"squad not found: {req.squad_id}")

    leader_id, system_prompt, prompt = build_squad_prompt(squad, req.prompt)
    runtime = req.runtime or squad.runtime
    tm = request.app.state.task_manager
    task_req = CreateTaskRequest(
        agent_id=leader_id,
        runtime=runtime,  # type: ignore[arg-type]
        prompt=prompt,
        system_prompt=system_prompt,
        timeout=req.timeout,
    )
    try:
        task = await tm.create_task(task_req)
        logger.info(
            "squad task created squad=%s runtime=%s leader=%s task_id=%s",
            squad.id,
            runtime,
            leader_id,
            task.id,
        )
        return task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/skills")
async def list_skills(
    request: Request,
    include_hidden: bool = False,
    include_archived: bool = False,
    include_draft: bool = False,
    runtime: str | None = None,
):
    settings = request.app.state.settings
    runtimes = settings.enabled_runtimes()
    if runtime:
        if runtime not in ("openclaw", "hermes", "catalog"):
            raise HTTPException(status_code=400, detail="runtime must be openclaw|hermes|catalog")
        runtimes = [runtime]
    return scan_all_skills(
        openclaw_dir=settings.skills_dir or None,
        hermes_dir=settings.hermes_skills_dir or None,
        catalog_dir=content_roots.skills_dir() or None,
        include_hidden=include_hidden,
        include_archived=include_archived,
        include_draft=include_draft,
        runtimes=runtimes,
    )


@router.get("/api/skills/captured")
async def skills_captured(request: Request, runtime: str | None = None):
    settings = request.app.state.settings
    if runtime and runtime not in ("openclaw", "hermes"):
        raise HTTPException(status_code=400, detail="runtime must be openclaw|hermes")
    return list_captured(
        skills_dir=settings.skills_dir or None,
        hermes_skills_dir=settings.hermes_skills_dir or None,
        runtime=runtime,
    )


@router.post("/api/skills/captured/{capture_id}/refine")
async def skills_refine(capture_id: str, request: Request):
    settings = request.app.state.settings
    try:
        return await refine_capture(
            capture_id,
            skills_dir=settings.skills_dir or None,
            hermes_skills_dir=settings.hermes_skills_dir or None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/api/skills/{skill_id:path}/verify")
async def skills_verify(skill_id: str, request: Request, runtime: str = "openclaw"):
    settings = request.app.state.settings
    if runtime not in ("openclaw", "hermes"):
        raise HTTPException(status_code=400, detail="runtime must be openclaw|hermes")
    try:
        return await verify_skill(
            skill_id,
            runtime=runtime,
            skills_dir=settings.skills_dir or None,
            hermes_skills_dir=settings.hermes_skills_dir or None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/api/skills/{skill_id:path}/reject")
async def skills_reject(skill_id: str, request: Request, runtime: str = "openclaw"):
    settings = request.app.state.settings
    if runtime not in ("openclaw", "hermes"):
        raise HTTPException(status_code=400, detail="runtime must be openclaw|hermes")
    try:
        return await reject_skill(
            skill_id,
            runtime=runtime,
            skills_dir=settings.skills_dir or None,
            hermes_skills_dir=settings.hermes_skills_dir or None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/api/skills/{skill_id:path}")
async def skill_detail(
    skill_id: str,
    request: Request,
    runtime: str = "openclaw",
):
    settings = request.app.state.settings
    if runtime not in ("openclaw", "hermes", "catalog"):
        raise HTTPException(status_code=400, detail="runtime must be openclaw|hermes|catalog")
    detail = get_skill(
        skill_id,
        settings.skills_dir or None,
        include_archived=True,
        runtime=runtime,
        hermes_skills_dir=settings.hermes_skills_dir or None,
        catalog_dir=content_roots.skills_dir() or None,
    )
    if not detail:
        raise HTTPException(status_code=404, detail=f"skill not found: {skill_id}")
    return detail


@router.post("/api/skills/install", response_model=InstallSkillResult, status_code=201)
async def install_skill(req: InstallSkillRequest, request: Request) -> InstallSkillResult:
    """安装分流：openclaw → skill-agent 任务；hermes → `hermes skills install`。"""
    settings = request.app.state.settings
    target = (req.url or req.name or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="url or name required")
    runtime = req.runtime or "openclaw"

    if runtime == "hermes":
        if not settings.is_runtime_enabled("hermes"):
            raise HTTPException(status_code=400, detail="hermes runtime not enabled")
        try:
            ok, message = await install_hermes_skill(
                target,
                executable=settings.hermes_executable,
                hermes_home=settings.hermes_home or "",
                category=req.category or "",
                name=req.name if req.url else "",
                force=req.force,
                mock=settings.ai_mock_mode,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        status = "completed" if ok else "failed"
        logger.info(
            "skills install hermes target=%s status=%s",
            target,
            status,
        )
        return InstallSkillResult(
            runtime="hermes",
            status=status,
            identifier=target,
            message=message[:2000],
        )

    tm = request.app.state.task_manager
    prompt = f"请安装技能：{target}"
    if req.instructions:
        prompt += f"\n\n附加说明：{req.instructions}"
    try:
        task = await tm.create_task(
            CreateTaskRequest(agent_id="skill-agent", prompt=prompt, runtime="openclaw")
        )
        logger.info(
            "skills install task created task_id=%s target=%s agent_id=skill-agent",
            task.id,
            target,
        )
        return InstallSkillResult(
            runtime="openclaw",
            status="queued",
            identifier=target,
            message="已创建 skill-agent 安装任务",
            task_id=task.id,
            task=task,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/skills/audit", response_model=TaskInfo, status_code=201)
async def audit_skill(req: AuditSkillRequest, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    prompt = (
        f"请审核技能 `{req.skill_id}`：检查 SKILL.md 规范、安全性、依赖合理性，"
        "输出审核结论（通过/需修改/拒绝）及理由。"
        "请在结论首行使用固定格式：`结论: 通过` 或 `结论: 需修改` 或 `结论: 拒绝`。"
    )
    try:
        task = await tm.create_task(
            CreateTaskRequest(agent_id="skill-agent", prompt=prompt)
        )
        logger.info(
            "skills audit task created task_id=%s skill_id=%s agent_id=skill-agent",
            task.id,
            req.skill_id,
        )
        return task
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/skills/{skill_id:path}/archive")
async def archive_skill_api(
    skill_id: str,
    request: Request,
    runtime: str = "openclaw",
):
    settings = request.app.state.settings
    if runtime not in ("openclaw", "hermes"):
        raise HTTPException(status_code=400, detail="runtime must be openclaw|hermes")
    try:
        return archive_skill(
            skill_id,
            settings.skills_dir or None,
            runtime=runtime,
            hermes_skills_dir=settings.hermes_skills_dir or None,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/api/autopilots")
async def list_autopilots(
    request: Request,
    include_openclaw: bool = True,
    include_hermes: bool = True,
):
    ap = request.app.state.autopilot_manager
    return await ap.list_autopilots(
        include_openclaw=include_openclaw,
        include_hermes=include_hermes,
    )


@router.post("/api/autopilots/refresh")
async def refresh_autopilots(request: Request):
    """按 OpenClaw / Hermes 现况对账本地库，返回更新后的聚合列表。"""
    ap = request.app.state.autopilot_manager
    try:
        result = await ap.reconcile_external()
        return {
            "pruned_count": result["pruned_count"],
            "pruned": result["pruned"],
            "synced_openclaw": result["synced_openclaw"],
            "synced_hermes": result["synced_hermes"],
            "items": result["items"],
            "count": len(result["items"]),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/autopilots", status_code=201)
async def create_autopilot(req: CreateAutopilotRequest, request: Request):
    ap = request.app.state.autopilot_manager
    try:
        return await ap.create_autopilot(
            req.name,
            req.agent_id,
            req.prompt,
            req.cron,
            req.enabled,
            runtime=req.runtime,
            sync_to_openclaw=req.sync_to_openclaw,
            sync_to_hermes=req.sync_to_hermes,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/autopilots/{autopilot_id}/trigger", response_model=TaskInfo)
async def trigger_autopilot(autopilot_id: str, request: Request) -> TaskInfo:
    ap = request.app.state.autopilot_manager
    try:
        return await ap.trigger_now(autopilot_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/api/autopilots/{autopilot_id}")
async def delete_autopilot(autopilot_id: str, request: Request):
    ap = request.app.state.autopilot_manager
    if not await ap.delete_autopilot(autopilot_id):
        raise HTTPException(status_code=404, detail=f"autopilot not found: {autopilot_id}")
    return {"ok": True}


# ── Cron ↔ Autopilot 双向同步 ──────────────────────────────────────────────


@router.get("/api/autopilots/from-openclaw")
async def sync_from_openclaw(request: Request):
    """Fetch all OpenClaw cron jobs and mirror them as local Autopilot records."""
    ap = request.app.state.autopilot_manager
    try:
        synced = await ap.sync_from_openclaw()
        return {"synced": [c.id for c in synced], "count": len(synced)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/autopilots/to-openclaw/{autopilot_id}")
async def sync_to_openclaw(autopilot_id: str, request: Request):
    """Push a local Autopilot to OpenClaw as a new cron job."""
    ap = request.app.state.autopilot_manager
    try:
        cfg = await ap.sync_to_openclaw(autopilot_id)
        return {"id": cfg.id, "openclaw_id": cfg.openclaw_id, "source": cfg.source}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/autopilots/from-openclaw/{cron_id}")
async def delete_openclaw_cron(cron_id: str, request: Request):
    """Delete a cron directly from OpenClaw (via its cron ID)."""
    ap = request.app.state.autopilot_manager
    try:
        await ap.remove_from_openclaw(cron_id)
        return {"ok": True, "cron_id": cron_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/autopilots/from-hermes")
async def sync_from_hermes(request: Request):
    """拉取 Hermes cron 并镜像为本地 Autopilot。"""
    ap = request.app.state.autopilot_manager
    try:
        synced = await ap.sync_from_hermes()
        return {"synced": [c.id for c in synced], "count": len(synced)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/autopilots/to-hermes/{autopilot_id}")
async def sync_to_hermes(autopilot_id: str, request: Request):
    """将本地 Autopilot 推送到 Hermes cron。"""
    ap = request.app.state.autopilot_manager
    try:
        cfg = await ap.sync_to_hermes(autopilot_id)
        return {"id": cfg.id, "hermes_id": cfg.hermes_id, "source": cfg.source}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/autopilots/from-hermes/{cron_id}")
async def delete_hermes_cron(cron_id: str, request: Request):
    """删除 Hermes cron（支持 hermes:<id> 或裸 id）。"""
    ap = request.app.state.autopilot_manager
    try:
        await ap.remove_from_hermes(cron_id)
        return {"ok": True, "cron_id": cron_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
