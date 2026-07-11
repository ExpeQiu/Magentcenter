"""Agent 发现 API。"""

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import AgentInfo

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("", response_model=list[AgentInfo])
async def list_agents(request: Request, refresh: bool = False) -> list[AgentInfo]:
    registry = request.app.state.registry
    return await registry.list_agents(force_refresh=refresh)


@router.get("/{agent_id}", response_model=AgentInfo)
async def get_agent(agent_id: str, request: Request) -> AgentInfo:
    registry = request.app.state.registry
    agent = await registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"agent not found: {agent_id}")
    return agent
