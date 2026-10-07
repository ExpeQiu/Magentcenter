"""信息链查询。"""

from fastapi import APIRouter, HTTPException, Query

from app.core.chain import list_chain
from app.models.schemas import ChainEvent

router = APIRouter(prefix="/api/chain", tags=["chain"])


@router.get("", response_model=list[ChainEvent])
async def read_chain(
    task_id: str = "",
    run_id: str = "",
    actor_id: str = "",
    limit: int = Query(default=200, ge=1, le=500),
) -> list[ChainEvent]:
    if not (task_id or run_id or actor_id):
        raise HTTPException(status_code=400, detail="需要 task_id、run_id 或 actor_id")
    return await list_chain(task_id=task_id, run_id=run_id, actor_id=actor_id, limit=limit)
