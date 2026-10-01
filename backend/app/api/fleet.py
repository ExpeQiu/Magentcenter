"""多端连接器 API。插件用令牌领取；webhook 由协调器签名推送。"""

import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.core import fleet as fleet_service
from app.core.fleet import FleetAuthError, FleetError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


class AgentPick(BaseModel):
    id: str
    runtime: str
    name: str = ""
    model: str = ""


class EnrollRequest(BaseModel):
    enroll_token: str
    node_id: str
    name: str = ""
    runtimes: list[str] = Field(default_factory=list)
    agents: list[AgentPick] = Field(default_factory=list)
    hostname: str = ""
    platform: str = ""
    mode: str = "plugin"
    webhook_url: str = ""


class HeartbeatRequest(BaseModel):
    runtimes: list[str] = Field(default_factory=list)
    agents: list[AgentPick] | None = None
    hostname: str = ""
    platform: str = ""
    load: float | None = None


class BindRequest(BaseModel):
    node_id: str = ""
    name: str = ""
    workspace_id: str = ""
    agents: list[AgentPick] = Field(default_factory=list)


class FinishRequest(BaseModel):
    status: str
    output: str = ""
    error: str = ""
    session_id: str = ""
    duration_ms: int = 0


def _auth_error(exc: FleetAuthError) -> HTTPException:
    return HTTPException(status_code=401, detail=str(exc))


def _fleet_error(exc: FleetError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/nodes")
async def list_nodes(workspace_id: str = Query(default="")):
    return await fleet_service.list_nodes(workspace_id)


@router.get("/scan")
async def scan_local(request: Request):
    registry = request.app.state.registry
    return await fleet_service.scan_host(registry)


@router.post("/bind")
async def bind(req: BindRequest, request: Request):
    try:
        return await fleet_service.bind_selection(
            node_id=req.node_id,
            name=req.name,
            picks=[a.model_dump() for a in req.agents],
            registry=request.app.state.registry,
            workspace_id=req.workspace_id,
        )
    except FleetError as e:
        raise _fleet_error(e)


@router.delete("/nodes/{node_id}")
async def unbind(node_id: str):
    try:
        return await fleet_service.unbind_node(node_id)
    except FleetError as e:
        raise _fleet_error(e)


@router.post("/enroll")
async def enroll(req: EnrollRequest, request: Request):
    settings = request.app.state.settings
    try:
        return await fleet_service.enroll(
            enroll_token=req.enroll_token,
            expected_token=settings.fleet_enroll_token,
            node_id=req.node_id,
            name=req.name,
            runtimes=req.runtimes,
            agents=[a.model_dump() for a in req.agents],
            hostname=req.hostname,
            platform=req.platform,
            mode=req.mode,
            webhook_url=req.webhook_url,
        )
    except FleetAuthError as e:
        raise _auth_error(e)
    except FleetError as e:
        raise _fleet_error(e)


@router.post("/heartbeat")
async def heartbeat(
    req: HeartbeatRequest,
    x_node_token: str = Header(default=""),
):
    try:
        return await fleet_service.heartbeat(
            x_node_token,
            runtimes=req.runtimes,
            agents=None if req.agents is None else [a.model_dump() for a in req.agents],
            hostname=req.hostname,
            platform=req.platform,
            load=req.load,
        )
    except FleetAuthError as e:
        raise _auth_error(e)


@router.post("/claim")
async def claim(x_node_token: str = Header(default="")):
    try:
        task = await fleet_service.claim(x_node_token)
    except FleetAuthError as e:
        raise _auth_error(e)
    return {"task": task}


@router.post("/tasks/{task_id}/finish")
async def finish(
    task_id: str,
    req: FinishRequest,
    x_node_token: str = Header(default=""),
):
    try:
        result = await fleet_service.finish(
            x_node_token,
            task_id,
            status=req.status,
            output=req.output,
            error=req.error,
            session_id=req.session_id,
            duration_ms=req.duration_ms,
        )
    except FleetAuthError as e:
        raise _auth_error(e)
    except FleetError as e:
        raise _fleet_error(e)

    try:
        from app.core.knowledge import distill_from_task

        await distill_from_task(
            task_id=result["id"],
            prompt=result["prompt"],
            output=result["output"],
            agent_id=result["agent_id"],
            runtime=result["runtime"],
            session_id=result["session_id"],
            status=result["status"],
            workspace_id=result["workspace_id"],
            error=result["error"],
        )
    except Exception as e:
        logger.warning("fleet distill failed task=%s: %s", task_id, e)

    try:
        from app.config import get_settings
        from app.core.skill_mine import capture_task, record_skill_outcomes

        settings = get_settings()
        if settings.skill_mine_enabled:
            await capture_task(
                task_id=result["id"],
                prompt=result["prompt"],
                output=result["output"],
                error=result["error"],
                agent_id=result["agent_id"],
                runtime=result["runtime"],
                session_id=result["session_id"],
                status=result["status"],
                workspace_id=result["workspace_id"],
                duration_ms=int(result.get("duration_ms") or 0),
                skills_dir=settings.skills_dir or None,
                hermes_skills_dir=settings.hermes_skills_dir or None,
            )
            await record_skill_outcomes(
                result.get("system_prompt") or "",
                success=result["status"] == "completed",
                runtime=result["runtime"] or "openclaw",
            )
    except Exception as e:
        logger.warning("fleet skill capture failed task=%s: %s", task_id, e)
    return result
