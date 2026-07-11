"""Squads / Skills / Autopilot API。"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.skills import scan_skills
from app.core.squads import get_squad, load_squads
from app.models.schemas import (
    AuditSkillRequest,
    CreateAutopilotRequest,
    CreateTaskRequest,
    InstallSkillRequest,
    TaskInfo,
)

router = APIRouter(tags=["orchestration"])


class CreateSquadTaskRequest(BaseModel):
    squad_id: str
    prompt: str
    timeout: int | None = None


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
    tm = request.app.state.task_manager
    task_req = CreateTaskRequest(
        agent_id=leader_id,
        prompt=prompt,
        system_prompt=system_prompt,
        timeout=req.timeout,
    )
    try:
        return await tm.create_task(task_req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/skills")
async def list_skills(request: Request):
    settings = request.app.state.settings
    return scan_skills(settings.skills_dir or None)


@router.post("/api/skills/install", response_model=TaskInfo, status_code=201)
async def install_skill(req: InstallSkillRequest, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    target = req.url or req.name
    if not target:
        raise HTTPException(status_code=400, detail="url or name required")
    prompt = f"请安装技能：{target}"
    if req.instructions:
        prompt += f"\n\n附加说明：{req.instructions}"
    try:
        return await tm.create_task(
            CreateTaskRequest(agent_id="skill-agent", prompt=prompt)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/skills/audit", response_model=TaskInfo, status_code=201)
async def audit_skill(req: AuditSkillRequest, request: Request) -> TaskInfo:
    tm = request.app.state.task_manager
    prompt = (
        f"请审核技能 `{req.skill_id}`：检查 SKILL.md 规范、安全性、依赖合理性，"
        "输出审核结论（通过/需修改/拒绝）及理由。"
    )
    try:
        return await tm.create_task(
            CreateTaskRequest(agent_id="skill-agent", prompt=prompt)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/autopilots")
async def list_autopilots(request: Request, include_openclaw: bool = True):
    ap = request.app.state.autopilot_manager
    return await ap.list_autopilots(include_openclaw=include_openclaw)


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
            req.sync_to_openclaw,
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
