"""SOP 工作流：有序步骤，运行时按步派发任务。"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select

from app.core import workspaces as workspace_service
from app.models.db import SopRecord, SopStepRecord, get_session_factory
from app.models.schemas import (
    CreateSopRequest,
    CreateSopStepRequest,
    CreateTaskRequest,
    ReorderSopStepsRequest,
    RunSopRequest,
    SopInfo,
    SopRunResult,
    SopStepInfo,
    UpdateSopRequest,
    UpdateSopStepRequest,
)

logger = logging.getLogger(__name__)


def _step_to_info(rec: SopStepRecord) -> SopStepInfo:
    return SopStepInfo(
        id=rec.id,
        sop_id=rec.sop_id,
        position=rec.position or 0,
        title=rec.title,
        instruction=rec.instruction or "",
        skill_name=rec.skill_name or "",
    )


def _sop_to_info(rec: SopRecord, steps: list[SopStepRecord] | None = None) -> SopInfo:
    ordered = sorted(steps or [], key=lambda s: (s.position or 0, s.created_at))
    return SopInfo(
        id=rec.id,
        workspace_id=rec.workspace_id or "",
        name=rec.name,
        description=rec.description or "",
        step_count=rec.step_count or 0,
        run_count=rec.run_count or 0,
        steps=[_step_to_info(s) for s in ordered],
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


async def _require_workspace(workspace_id: str) -> str:
    resolved = await workspace_service.resolve_workspace_id(workspace_id)
    if not resolved:
        raise ValueError(f"workspace not found: {workspace_id}")
    return resolved


async def list_sops(workspace_id: str | None = None) -> list[SopInfo]:
    factory = get_session_factory()
    async with factory() as session:
        q = select(SopRecord).order_by(SopRecord.updated_at.desc())
        if workspace_id:
            q = q.where(SopRecord.workspace_id == workspace_id)
        rows = (await session.execute(q)).scalars().all()
        return [_sop_to_info(r) for r in rows]


async def get_sop(sop_id: str) -> SopInfo | None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        if not rec:
            return None
        steps = (
            await session.execute(
                select(SopStepRecord)
                .where(SopStepRecord.sop_id == sop_id)
                .order_by(SopStepRecord.position)
            )
        ).scalars().all()
        return _sop_to_info(rec, list(steps))


async def create_sop(req: CreateSopRequest) -> SopInfo:
    name = req.name.strip()
    if not name:
        raise ValueError("name is required")
    workspace_id = await _require_workspace(req.workspace_id)
    rec = SopRecord(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name=name,
        description=(req.description or "").strip(),
    )
    factory = get_session_factory()
    async with factory() as session:
        session.add(rec)
        await session.commit()
        await session.refresh(rec)
    logger.info("sop created sop_id=%s workspace_id=%s name=%s", rec.id, workspace_id, name)
    return _sop_to_info(rec)


async def update_sop(sop_id: str, req: UpdateSopRequest) -> SopInfo:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        if not rec:
            raise ValueError(f"sop not found: {sop_id}")
        if req.name is not None:
            name = req.name.strip()
            if not name:
                raise ValueError("name is required")
            rec.name = name
        if req.description is not None:
            rec.description = req.description.strip()
        rec.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(rec)
        steps = (
            await session.execute(
                select(SopStepRecord)
                .where(SopStepRecord.sop_id == sop_id)
                .order_by(SopStepRecord.position)
            )
        ).scalars().all()
        logger.info("sop updated sop_id=%s", sop_id)
        return _sop_to_info(rec, list(steps))


async def delete_sop(sop_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        if not rec:
            raise ValueError(f"sop not found: {sop_id}")
        steps = (
            await session.execute(select(SopStepRecord).where(SopStepRecord.sop_id == sop_id))
        ).scalars().all()
        for step in steps:
            await session.delete(step)
        await session.delete(rec)
        await session.commit()
    logger.info("sop deleted sop_id=%s", sop_id)


async def add_step(sop_id: str, req: CreateSopStepRequest) -> SopInfo:
    title = req.title.strip()
    if not title:
        raise ValueError("title is required")
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        if not rec:
            raise ValueError(f"sop not found: {sop_id}")
        step = SopStepRecord(
            id=str(uuid.uuid4()),
            workspace_id=rec.workspace_id,
            sop_id=sop_id,
            position=rec.step_count or 0,
            title=title,
            instruction=(req.instruction or "").strip(),
            skill_name=(req.skill_name or "").strip(),
        )
        session.add(step)
        rec.step_count = (rec.step_count or 0) + 1
        rec.updated_at = datetime.utcnow()
        await session.commit()
    logger.info("sop step added sop_id=%s title=%s", sop_id, title)
    sop = await get_sop(sop_id)
    if not sop:
        raise ValueError(f"sop not found: {sop_id}")
    return sop


async def update_step(sop_id: str, step_id: str, req: UpdateSopStepRequest) -> SopInfo:
    factory = get_session_factory()
    async with factory() as session:
        step = await session.get(SopStepRecord, step_id)
        if not step or step.sop_id != sop_id:
            raise ValueError(f"step not found: {step_id}")
        if req.title is not None:
            title = req.title.strip()
            if not title:
                raise ValueError("title is required")
            step.title = title
        if req.instruction is not None:
            step.instruction = req.instruction.strip()
        if req.skill_name is not None:
            step.skill_name = req.skill_name.strip()
        step.updated_at = datetime.utcnow()
        rec = await session.get(SopRecord, sop_id)
        if rec:
            rec.updated_at = datetime.utcnow()
        await session.commit()
    logger.info("sop step updated sop_id=%s step_id=%s", sop_id, step_id)
    sop = await get_sop(sop_id)
    if not sop:
        raise ValueError(f"sop not found: {sop_id}")
    return sop


async def delete_step(sop_id: str, step_id: str) -> SopInfo:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        step = await session.get(SopStepRecord, step_id)
        if not rec or not step or step.sop_id != sop_id:
            raise ValueError(f"step not found: {step_id}")
        await session.delete(step)
        await session.flush()
        remaining = (
            await session.execute(
                select(SopStepRecord)
                .where(SopStepRecord.sop_id == sop_id)
                .order_by(SopStepRecord.position)
            )
        ).scalars().all()
        for idx, item in enumerate(remaining):
            item.position = idx
        rec.step_count = len(remaining)
        rec.updated_at = datetime.utcnow()
        await session.commit()
    logger.info("sop step deleted sop_id=%s step_id=%s", sop_id, step_id)
    sop = await get_sop(sop_id)
    if not sop:
        raise ValueError(f"sop not found: {sop_id}")
    return sop


async def reorder_steps(sop_id: str, req: ReorderSopStepsRequest) -> SopInfo:
    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        if not rec:
            raise ValueError(f"sop not found: {sop_id}")
        rows = (
            await session.execute(select(SopStepRecord).where(SopStepRecord.sop_id == sop_id))
        ).scalars().all()
        by_id = {row.id: row for row in rows}
        if set(req.step_ids) != set(by_id):
            raise ValueError("step_ids must match existing steps")
        for idx, step_id in enumerate(req.step_ids):
            by_id[step_id].position = idx
            by_id[step_id].updated_at = datetime.utcnow()
        rec.updated_at = datetime.utcnow()
        await session.commit()
    logger.info("sop steps reordered sop_id=%s count=%d", sop_id, len(req.step_ids))
    sop = await get_sop(sop_id)
    if not sop:
        raise ValueError(f"sop not found: {sop_id}")
    return sop


async def run_sop(sop_id: str, req: RunSopRequest, task_manager) -> SopRunResult:
    sop = await get_sop(sop_id)
    if not sop:
        raise ValueError(f"sop not found: {sop_id}")
    if not sop.steps:
        raise ValueError("sop has no steps")
    agent_id = req.agent_id.strip()
    if not agent_id:
        raise ValueError("agent_id is required")

    total = len(sop.steps)
    task_ids: list[str] = []
    for index, step in enumerate(sop.steps, start=1):
        prompt = step.instruction.strip() or step.title
        system = (
            f"你正在执行 SOP「{sop.name}」第 {index}/{total} 步：{step.title}。\n"
            "只完成本步，给出可核对的结果。不要提前做后续步骤。"
        )
        if step.skill_name:
            system += f"\n优先使用技能：{step.skill_name}"
        task = await task_manager.create_task(
            CreateTaskRequest(
                agent_id=agent_id,
                runtime=req.runtime,
                prompt=prompt,
                system_prompt=system,
                workspace_id=sop.workspace_id,
            )
        )
        task_ids.append(task.id)

    factory = get_session_factory()
    async with factory() as session:
        rec = await session.get(SopRecord, sop_id)
        if rec:
            rec.run_count = (rec.run_count or 0) + 1
            rec.updated_at = datetime.utcnow()
            await session.commit()
    logger.info(
        "sop run sop_id=%s workspace_id=%s agent_id=%s steps=%d task_ids=%s",
        sop_id,
        sop.workspace_id,
        agent_id,
        total,
        ",".join(task_ids),
    )
    return SopRunResult(sop_id=sop_id, task_ids=task_ids)
