"""Agent 发现 API。"""

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.schemas import AgentInfo, AgentStats

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/stats", response_model=list[AgentStats])
async def agent_stats(request: Request) -> list[AgentStats]:
    tm = request.app.state.task_manager
    rows = await tm.get_agent_stats()
    return [AgentStats(**r) for r in rows]


@router.get("", response_model=list[AgentInfo])
async def list_agents(
    request: Request,
    refresh: bool = False,
    runtime: str | None = Query(None, description="按运行时过滤 openclaw|hermes"),
) -> list[AgentInfo]:
    registry = request.app.state.registry
    agents = await registry.list_agents(force_refresh=refresh)
    if runtime:
        agents = [a for a in agents if a.runtime == runtime]
    return agents


@router.get("/{agent_id}", response_model=AgentInfo)
async def get_agent(
    agent_id: str,
    request: Request,
    runtime: str | None = Query(None),
) -> AgentInfo:
    registry = request.app.state.registry
    agent = await registry.get_agent(agent_id, runtime=runtime)
    if not agent:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return agent
