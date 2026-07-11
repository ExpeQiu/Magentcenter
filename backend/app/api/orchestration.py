"""Squads / Skills / Autopilot API。"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.core.skills import scan_skills
from app.core.squads import get_squad, load_squads
from app.models.schemas import CreateTaskRequest, TaskInfo

router = APIRouter(tags=["orchestration"])


class CreateSquadTaskRequest(BaseModel):
    squad_id: str
    prompt: str
    timeout: int | None = None


class CreateAutopilotRequest(BaseModel):
    name: str
    agent_id: str
    prompt: str
    cron: str = "3600"
    enabled: bool = True


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
async def list_skills():
    return scan_skills()


@router.get("/api/autopilots")
async def list_autopilots(request: Request):
    ap: "AutopilotManager" = request.app.state.autopilot_manager
    return ap.list_autopilots()


@router.post("/api/autopilots", status_code=201)
async def create_autopilot(req: CreateAutopilotRequest, request: Request):
    ap = request.app.state.autopilot_manager
    return ap.create_autopilot(req.name, req.agent_id, req.prompt, req.cron, req.enabled)


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
    if not ap.delete_autopilot(autopilot_id):
        raise HTTPException(status_code=404, detail=f"autopilot not found: {autopilot_id}")
    return {"ok": True}
