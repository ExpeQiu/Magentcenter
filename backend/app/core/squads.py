"""小队（Squads）路由模块。"""

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

logger = logging.getLogger(__name__)

SQUADS_FILE = Path(__file__).resolve().parents[3] / "guide" / "squads.yml"


class SquadInfo(BaseModel):
    id: str
    name: str
    leader: str
    members: list[str]
    description: str = ""
    runtime: Literal["openclaw", "hermes"] = "openclaw"


def load_squads() -> list[SquadInfo]:
    if not SQUADS_FILE.exists():
        logger.warning("squads config not found: %s", SQUADS_FILE)
        return []
    with open(SQUADS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    squads = []
    for s in data.get("squads", []):
        squads.append(SquadInfo(**s))
    logger.info("squads loaded count=%d", len(squads))
    return squads


def get_squad(squad_id: str) -> SquadInfo | None:
    for s in load_squads():
        if s.id == squad_id:
            return s
    return None


def build_squad_prompt(squad: SquadInfo, user_prompt: str) -> tuple[str, str, str]:
    """生成小队路由 prompt，返回 (leader_agent_id, system_prompt, prompt)。"""
    members_desc = ", ".join(squad.members)
    if squad.runtime == "hermes":
        system = (
            f"你是 Hermes 小队「{squad.name}」的执行 profile（{squad.leader}）。"
            f"可用 profile/成员: {members_desc}。"
            f"请直接完成任务；若需多步协作，在回复中明确步骤。"
        )
    else:
        system = (
            f"你是 {squad.name} 的队长（{squad.leader}）。"
            f"小队成员: {members_desc}。"
            f"请分析以下任务，决定由哪位成员执行，或直接回答。"
            f"如需委派，在回复开头注明 [DELEGATE:<agent_id>] 并说明理由。"
        )
    prompt = f"【小队任务 - {squad.name}】\n{user_prompt}"
    return squad.leader, system, prompt
