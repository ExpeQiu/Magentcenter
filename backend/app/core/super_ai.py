"""超级AI 首页：语音/文字共用的意图路由。只认白名单服务。"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass

from app.core import fleet as fleet_service
from app.core import knowledge as knowledge_service
from app.core import workspaces as workspace_service
from app.core.outputs_vault import list_recent
from app.core.skills import scan_all_skills
from app.models.schemas import (
    CreateTaskRequest,
    SuperAiPending,
    SuperAiTurnResponse,
)

logger = logging.getLogger(__name__)

_SLUG = re.compile(r"^[a-z0-9-]{1,32}$")
_CREATE = re.compile(
    r"(?:请)?(?:帮我)?(?:新建|创建|建一个|建)(?:一个)?任务\s*[:：]?\s*(.*)$"
)
_DO = re.compile(r"^(?:请)?帮我(?:做|处理|完成)\s*[:：]?\s*(.*)$")
_OPEN = re.compile(r"^打开\s*(.+)$")
_KNOW = re.compile(
    r"^(?:请)?(?:查一下|查资料|问一下|搜一下|知识库里|知识库|什么是)\s*[:：]?\s*(.*)$"
)

_CONFIRM = ("确认", "执行", "做吧", "把它做了")
_CANCEL = ("取消", "算了", "不用了", "不要")
_TASK_LIST = (
    "进行中",
    "有哪些任务",
    "任务列表",
    "任务进度",
    "在跑的",
    "执行中的任务",
    "我的任务",
)
_SKILLS = ("有哪些技能", "技能列表", "有什么技能", "技能目录", "能用的技能")
_OUTPUTS = ("最近产出", "输出物", "最近的文件", "最近输出")
_SYSTEM = (
    "系统是否正常",
    "系统状态",
    "健康检查",
    "服务是否正常",
    "系统正常",
    "连接状态",
    "连上了吗",
    "连上没有",
    "通不通",
    "通了吗",
)
_PROFESSIONAL = (
    "分析",
    "排查",
    "审计",
    "自检",
    "调研",
    "复盘",
    "部署",
    "修复",
    "重构",
    "实现",
    "编写",
    "写代码",
    "开发",
    "持仓",
    "回测",
    "策略",
    "诊断",
    "深入",
    "专业",
    "优化",
    "设计方案",
    "写报告",
    "出报告",
    "评估",
    "对比方案",
)
_ROLE_CUE = ("让", "交给", "叫", "请", "用", "找", "指定")
_FLEET = ("哪台设备", "设备在线", "在线设备", "多端状态", "有哪些设备")
_OPEN_AGAIN = ("打开刚才那个", "打开刚才", "打开它")
_HELP = ("帮助", "你是谁", "你能做什么", "你会什么")

_NAV = {
    "任务": "tasks",
    "任务台": "tasks",
    "控制台": "tasks",
    "项目": "projects",
    "知识库": "knowledge",
    "技能": "skills",
    "输出": "outputs",
    "输出物": "outputs",
    "多端": "fleet",
    "设备": "fleet",
    "系统": "system",
    "会话": "sessions",
    "看板": "kanban",
}

_STATUS = {
    "queued": "排队",
    "running": "执行中",
    "completed": "完成",
    "failed": "失败",
    "cancelled": "已取消",
}

_HELP_REPLY = (
    "我可以查进行中的任务、帮你建任务、查知识库、看技能和最近产出，"
    "也可以看系统与设备是否在线。分配任务会直接交给已绑定的智能体。"
)


@dataclass
class Parsed:
    intent: str
    service: str = ""
    query: str = ""
    href: str = ""
    active_only: bool = False


def _slug(raw: str) -> str:
    slug = (raw or "").strip().lower()
    return slug if _SLUG.match(slug) else "cyber"


def _href(slug: str, page: str, query: str = "") -> str:
    path = f"/{slug}/{page}"
    return f"{path}?{query}" if query else path


def _safe_href(raw: str) -> str:
    path = (raw or "").strip()
    if not path.startswith("/") or path.startswith("//") or ".." in path:
        return ""
    return path


def _clip(text: str, limit: int = 36) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text or "（无标题）"
    return text[: limit - 1] + "…"


def parse_turn(
    text: str,
    pending: SuperAiPending | None,
    last_href: str,
    slug: str,
) -> Parsed:
    """把一句话收成白名单意图。认不出就追问，不猜测着去调接口。"""
    raw = (text or "").strip()
    if pending and raw in _CONFIRM:
        return Parsed("confirm_create", "tasks")
    if pending and raw in _CANCEL:
        return Parsed("cancel", "")
    if raw in _OPEN_AGAIN:
        href = _safe_href(last_href)
        if href:
            return Parsed("navigate", "navigate", href=href)
        return Parsed("clarify", "")
    opened = _OPEN.match(raw)
    if opened:
        target = opened.group(1).strip()
        page = _NAV.get(target)
        if page:
            return Parsed("navigate", "navigate", href=_href(slug, page))
        return Parsed("clarify", "", query=target)
    if raw in _HELP or raw.startswith("你能做"):
        return Parsed("help", "")
    created = _CREATE.match(raw)
    if created:
        return Parsed("create_task", "tasks", query=created.group(1).strip())
    doing = _DO.match(raw)
    if doing:
        return Parsed("create_task", "tasks", query=doing.group(1).strip())
    if any(k in raw for k in _TASK_LIST):
        active = any(k in raw for k in ("进行中", "在跑", "执行中"))
        return Parsed("list_tasks", "tasks", active_only=active)
    known = _KNOW.match(raw)
    if known:
        return Parsed("knowledge", "knowledge", query=known.group(1).strip())
    if any(k in raw for k in _SKILLS):
        return Parsed("skills", "skills")
    if any(k in raw for k in _OUTPUTS):
        return Parsed("outputs", "outputs")
    if any(k in raw for k in _FLEET):
        return Parsed("fleet", "fleet")
    if any(k in raw for k in _SYSTEM):
        return Parsed("system", "system")
    return Parsed("unknown", "")


def _finish(
    run_id: str,
    intent: str,
    service: str,
    reply: str,
    *,
    href: str = "",
    pending: SuperAiPending | None = None,
    task_id: str = "",
    task_status: str = "",
    dispatch: bool = False,
    started: float,
    workspace: str,
) -> SuperAiTurnResponse:
    if not (reply or "").strip():
        reply = "我在。"
    logger.info(
        "super_ai turn run_id=%s intent=%s service=%s workspace=%s task_id=%s elapsed_ms=%d",
        run_id,
        intent,
        service or "-",
        workspace,
        task_id or "-",
        int((time.perf_counter() - started) * 1000),
    )
    return SuperAiTurnResponse(
        run_id=run_id,
        reply=reply,
        intent=intent,
        service=service,
        href=href,
        pending=pending,
        task_id=task_id,
        task_status=task_status,
        dispatch=dispatch,
    )


async def _pick_agent(registry):
    agents = await registry.list_agents()
    if not agents:
        return None
    for agent in agents:
        if agent.is_default:
            return agent
    return agents[0]


async def handle_turn(
    text: str,
    *,
    workspace_slug: str,
    pending: SuperAiPending | None,
    last_href: str,
    registry,
    task_manager,
    monitor,
    confirmation_id: str = "",
    session_id: str = "",
    subject_id: str = "local",
) -> SuperAiTurnResponse:
    from app.core import super_ai_session as sessions

    result = await _route_turn(
        text,
        workspace_slug=workspace_slug,
        pending=pending,
        last_href=last_href,
        registry=registry,
        task_manager=task_manager,
        monitor=monitor,
        confirmation_id=confirmation_id,
        session_id=session_id,
        subject_id=subject_id,
    )
    raw = (text or "").strip()
    if raw and (session_id or "").strip() and result.intent != "empty":
        try:
            await sessions.remember(session_id, raw, result.reply)
        except Exception:
            logger.exception("super_ai session write failed session=%s", (session_id or "")[:12])
    return result


async def _route_turn(
    text: str,
    *,
    workspace_slug: str,
    pending: SuperAiPending | None,
    last_href: str,
    registry,
    task_manager,
    monitor,
    confirmation_id: str = "",
    session_id: str = "",
    subject_id: str = "local",
) -> SuperAiTurnResponse:
    started = time.perf_counter()
    run_id = uuid.uuid4().hex[:12]
    slug = _slug(workspace_slug)
    raw = (text or "").strip()
    if not raw:
        return _finish(
            run_id, "empty", "", "说一句，或按住说话。", started=started, workspace=slug
        )

    parsed = parse_turn(raw, pending, last_href, slug)
    try:
        if confirmation_id and raw in _CONFIRM:
            return await _commit_confirmation(
                run_id,
                confirmation_id,
                slug,
                task_manager,
                started=started,
                workspace=slug,
                session_id=session_id,
                subject_id=subject_id,
            )
        if parsed.intent == "help":
            return _finish(run_id, "help", "", _HELP_REPLY, started=started, workspace=slug)
        if parsed.intent == "cancel":
            return _finish(
                run_id, "cancel", "", "已取消，没有创建任务。", started=started, workspace=slug
            )
        if parsed.intent == "clarify":
            if parsed.query:
                reply = f"还不能打开「{parsed.query}」。可以说：打开任务台、知识库、技能、输出物、多端或系统。"
            else:
                reply = "还没有可打开的上一页。"
            return _finish(run_id, "clarify", "", reply, started=started, workspace=slug)
        if parsed.intent == "navigate":
            return _finish(
                run_id,
                "navigate",
                "navigate",
                "可以，从这里进入。",
                href=parsed.href,
                started=started,
                workspace=slug,
            )
        if parsed.intent == "create_task":
            return await _dispatch_local(
                run_id,
                parsed.query,
                registry,
                task_manager,
                started=started,
                workspace=slug,
            )
        if confirmation_id and parsed.intent == "confirm_create":
            return await _commit_confirmation(
                run_id,
                confirmation_id,
                slug,
                task_manager,
                started=started,
                workspace=slug,
                session_id=session_id,
                subject_id=subject_id,
            )
        if parsed.intent == "confirm_create" and pending:
            if pending.action == "call_peer":
                return await _commit_peer(
                    run_id, pending, slug, task_manager, started=started, workspace=slug
                )
            return await _commit_create(
                run_id, pending, slug, task_manager, started=started, workspace=slug
            )
        if parsed.intent == "list_tasks":
            return await _list_tasks(
                run_id,
                slug,
                parsed.active_only,
                task_manager,
                started=started,
                workspace=slug,
            )
        if parsed.intent == "knowledge":
            return await _search_knowledge(
                run_id, parsed.query, slug, started=started, workspace=slug
            )
        if parsed.intent == "skills":
            return await _list_skills(run_id, slug, started=started, workspace=slug)
        if parsed.intent == "outputs":
            return await _list_outputs(run_id, slug, started=started, workspace=slug)
        if parsed.intent == "system":
            return await _system(run_id, slug, monitor, started=started, workspace=slug)
        if parsed.intent == "fleet":
            return await _fleet(run_id, slug, started=started, workspace=slug)
    except Exception:
        logger.exception("super_ai failed run_id=%s intent=%s", run_id, parsed.intent)
        return _finish(
            run_id,
            parsed.intent,
            parsed.service,
            "这项服务暂时不可用，稍后再试。",
            started=started,
            workspace=slug,
        )

    try:
        return await _ask_model(
            run_id,
            raw,
            registry,
            task_manager,
            started=started,
            workspace=slug,
            session_id=session_id,
            subject_id=subject_id,
        )
    except Exception:
        logger.exception("super_ai model failed run_id=%s", run_id)
        return _finish(run_id, "unknown", "", _UNKNOWN, started=started, workspace=slug)


_UNKNOWN = "我没对上可调用的服务。可以问进行中的任务、技能、知识库、最近产出，或系统是否正常。"


def _role_labels(roster: list[dict]) -> list[str]:
    labels: list[str] = []
    for item in roster:
        for key in ("name", "agent_id"):
            label = str(item.get(key) or "").strip()
            if len(label) >= 2 and label not in labels:
                labels.append(label)
    return labels


def names_role(text: str, roster: list[dict]) -> bool:
    """用户点名了名册里的角色。"""
    raw = text or ""
    folded = raw.lower()
    for label in _role_labels(roster):
        hit = label if label in raw else ""
        if not hit and label.lower() in folded:
            hit = label
        if not hit:
            continue
        idx = raw.lower().find(hit.lower())
        window = raw[max(0, idx - 6) : idx]
        if any(cue in window for cue in _ROLE_CUE):
            return True
    return False


def needs_agent(text: str, roster: list[dict]) -> bool:
    """复杂、专业，或指定了角色，才交给多端智能体。"""
    raw = (text or "").strip()
    if not raw:
        return False
    if names_role(raw, roster):
        return True
    return any(word in raw for word in _PROFESSIONAL)


def _match_roster(roster: list[dict], node_id: str, runtime: str, agent_id: str) -> dict | None:
    for item in roster:
        if (
            str(item.get("node_id") or "") == node_id
            and item.get("runtime") == runtime
            and item.get("agent_id") == agent_id
        ):
            return item
    return None


async def list_roster(registry, workspace_slug: str) -> list[dict]:
    """已绑定且在线的智能体，加上本机注册表。语音端不进可派发名单。"""
    slug = _slug(workspace_slug)
    wid = ""
    try:
        wid = await workspace_service.resolve_workspace_id(slug) or ""
    except Exception:
        logger.info("super_ai roster workspace skipped slug=%s", slug)
    nodes: list[dict] = []
    try:
        nodes = await fleet_service.list_nodes(wid)
    except Exception:
        logger.exception("super_ai roster nodes failed workspace=%s", slug)
    entries: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    self_id = ""
    for node in nodes:
        if (node.get("mode") or "") == "voice":
            continue
        if not node.get("bound") or not node.get("online"):
            continue
        local = bool(node.get("self") or (node.get("mode") or "") == "local")
        node_id = str(node.get("id") or "")
        if local and node_id:
            self_id = node_id
        for agent in node.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            runtime = str(agent.get("runtime") or "")
            agent_id = str(agent.get("id") or "")
            if runtime not in ("openclaw", "hermes") or not agent_id:
                continue
            key = (node_id, runtime, agent_id)
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                {
                    "node_id": node_id,
                    "runtime": runtime,
                    "agent_id": agent_id,
                    "name": str(agent.get("name") or agent_id),
                    "local": local,
                }
            )
    try:
        agents = await registry.list_agents()
    except Exception:
        logger.exception("super_ai roster registry failed")
        agents = []
    for agent in agents or []:
        runtime = getattr(agent, "runtime", "") or "openclaw"
        agent_id = getattr(agent, "id", "") or ""
        if runtime not in ("openclaw", "hermes") or not agent_id:
            continue
        if any(
            item["local"] and item["runtime"] == runtime and item["agent_id"] == agent_id
            for item in entries
        ):
            continue
        key = (self_id, runtime, agent_id)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "node_id": self_id,
                "runtime": runtime,
                "agent_id": agent_id,
                "name": getattr(agent, "name", "") or agent_id,
                "local": True,
            }
        )
    logger.info("super_ai roster count=%d workspace=%s", len(entries), slug)
    return entries


async def _ask_model(
    run_id,
    raw,
    registry,
    task_manager,
    *,
    started,
    workspace,
    session_id: str,
    subject_id: str,
):
    from app.core import super_ai_llm as llm
    from app.core import super_ai_session as sessions

    if not llm.configured():
        return _finish(run_id, "unknown", "", _UNKNOWN, started=started, workspace=workspace)
    try:
        roster = await list_roster(registry, workspace)
    except Exception:
        logger.exception("super_ai roster failed run_id=%s", run_id)
        roster = []
    history: list[dict[str, str]] = []
    if session_id:
        try:
            history = await sessions.recent(session_id)
        except Exception:
            logger.exception("super_ai session read failed run_id=%s", run_id)
    decision = await llm.complete(
        run_id=run_id, user_text=raw, history=history, roster=roster
    )
    if decision is not None and decision.action == "dispatch" and not needs_agent(raw, roster):
        reply = (decision.text or "").strip() or "这个问题我直接回答，不派给其他智能体。"
        logger.info("super_ai dispatch blocked run_id=%s reason=simple", run_id)
        return _finish(run_id, "chat", "", reply, started=started, workspace=workspace)
    if decision is None or decision.action != "dispatch":
        if decision is None:
            reply = _UNKNOWN
            intent = "unknown"
        else:
            reply = decision.text or "我在。"
            intent = "chat"
        return _finish(run_id, intent, "", reply, started=started, workspace=workspace)
    if not decision.prompt or decision.runtime not in ("openclaw", "hermes"):
        return _finish(
            run_id,
            "chat",
            "",
            decision.text or "要交给哪台已绑定的智能体、做什么？",
            started=started,
            workspace=workspace,
        )
    hit = _match_roster(roster, decision.node_id, decision.runtime, decision.agent_id)
    if hit is None:
        return _finish(
            run_id,
            "chat",
            "",
            decision.text or "这个智能体不在已绑定名册里，我没有派发。",
            started=started,
            workspace=workspace,
        )
    return await _dispatch_hit(
        run_id,
        hit,
        decision.prompt,
        task_manager,
        started=started,
        workspace=workspace,
    )


async def _dispatch_hit(
    run_id,
    hit: dict,
    prompt: str,
    task_manager,
    *,
    started,
    workspace,
):
    """名册命中后直接派发，不再等「确认」。"""
    local = bool(hit.get("local"))
    runtime = hit.get("runtime") if hit.get("runtime") in ("openclaw", "hermes") else "openclaw"
    pending = SuperAiPending(
        action="create_task" if local else "call_peer",
        prompt=prompt,
        agent_id=str(hit.get("agent_id") or ""),
        agent_name=str(hit.get("name") or hit.get("agent_id") or ""),
        runtime=runtime,
        node_id=str(hit.get("node_id") or ""),
    )
    if local:
        result = await _commit_create(
            run_id, pending, workspace, task_manager, started=started, workspace=workspace
        )
    else:
        result = await _commit_peer(
            run_id, pending, workspace, task_manager, started=started, workspace=workspace
        )
    result.intent = "dispatch"
    result.dispatch = True
    result.pending = None
    logger.info(
        "super_ai assign run_id=%s node=%s agent=%s task_id=%s local=%s",
        run_id,
        pending.node_id or "-",
        pending.agent_id or "-",
        result.task_id or "-",
        local,
    )
    return result


async def _commit_peer(run_id, pending: SuperAiPending, slug, task_manager, *, started, workspace):
    wid = await workspace_service.resolve_workspace_id(slug) or ""
    try:
        info = await fleet_service.call_peer_as_cloud(
            target=pending.node_id,
            runtime=pending.runtime,
            agent_id=pending.agent_id,
            prompt=pending.prompt,
            task_manager=task_manager,
            workspace_id=wid,
        )
    except fleet_service.FleetError:
        logger.exception(
            "super_ai dispatch failed run_id=%s node=%s agent=%s",
            run_id,
            pending.node_id,
            pending.agent_id,
        )
        return _finish(
            run_id,
            "confirm_create",
            "fleet",
            "暂时不能派到那台设备。",
            dispatch=True,
            started=started,
            workspace=workspace,
        )
    status = str(info.get("status") or "queued")
    label = _STATUS.get(status, status)
    name = pending.agent_name or pending.agent_id
    return _finish(
        run_id,
        "confirm_create",
        "fleet",
        f"已交给「{name}」，当前{label}。做完后把结果收成短话发回。",
        href=_href(slug, "tasks/detail", f"id={info['id']}"),
        task_id=str(info.get("id") or ""),
        task_status=status,
        dispatch=True,
        started=started,
        workspace=workspace,
    )


async def _dispatch_local(run_id, prompt, registry, task_manager, *, started, workspace):
    """固定说法的建任务也直接执行。"""
    body = (prompt or "").strip(" ：:，,。")
    if not body:
        return _finish(
            run_id,
            "dispatch",
            "tasks",
            "要我做什么？例如：帮我建一个任务：整理本周输出。",
            started=started,
            workspace=workspace,
        )
    agent = await _pick_agent(registry)
    if not agent:
        return _finish(
            run_id,
            "dispatch",
            "tasks",
            "还没有可用的智能体，暂时不能建任务。",
            started=started,
            workspace=workspace,
        )
    pending = SuperAiPending(
        action="create_task",
        prompt=body,
        agent_id=agent.id,
        agent_name=agent.name or agent.id,
        runtime=agent.runtime,
    )
    result = await _commit_create(
        run_id, pending, workspace, task_manager, started=started, workspace=workspace
    )
    result.intent = "dispatch"
    result.dispatch = True
    result.pending = None
    logger.info(
        "super_ai assign run_id=%s node=- agent=%s task_id=%s local=True",
        run_id,
        pending.agent_id,
        result.task_id or "-",
    )
    return result


async def _commit_confirmation(
    run_id,
    confirmation_id,
    slug,
    task_manager,
    *,
    started,
    workspace,
    session_id: str,
    subject_id: str,
):
    from app.core.confirmations import ConfirmationError, attach_task, confirm

    try:
        opened = await confirm(
            confirmation_id,
            subject_id=subject_id,
            session_id=session_id,
        )
    except ConfirmationError as exc:
        return _finish(run_id, "confirm_create", "tasks", str(exc), started=started, workspace=workspace)
    if opened.get("task_id"):
        return _finish(
            run_id,
            "confirm_create",
            "tasks",
            "确认过了，还是原来的任务。",
            task_id=opened["task_id"],
            task_status="queued",
            started=started,
            workspace=workspace,
        )
    target = opened.get("target") or {}
    action = target.get("action") if target.get("action") in ("create_task", "call_peer") else "create_task"
    runtime = target.get("runtime") if target.get("runtime") in ("openclaw", "hermes") else "openclaw"
    pending = SuperAiPending(
        action=action,
        prompt=target.get("prompt") or opened.get("summary") or "",
        agent_id=target.get("agent_id") or "",
        agent_name=target.get("agent_name") or "",
        runtime=runtime,
        node_id=str(target.get("node_id") or ""),
    )
    if action == "call_peer":
        result = await _commit_peer(
            run_id, pending, slug, task_manager, started=started, workspace=workspace
        )
    else:
        result = await _commit_create(
            run_id, pending, slug, task_manager, started=started, workspace=workspace
        )
    if target.get("source") == "model":
        result.dispatch = True
    if result.task_id:
        await attach_task(confirmation_id, result.task_id)
    result.confirmation_id = confirmation_id
    return result


async def _commit_create(run_id, pending: SuperAiPending, slug, task_manager, *, started, workspace):
    wid = await workspace_service.resolve_workspace_id(slug) or ""
    task = await task_manager.create_task(
        CreateTaskRequest(
            agent_id=pending.agent_id,
            prompt=pending.prompt,
            runtime=pending.runtime,
            workspace_id=wid,
            node_id=pending.node_id or "",
        )
    )
    label = _STATUS.get(task.status, task.status)
    return _finish(
        run_id,
        "confirm_create",
        "tasks",
        f"已交给「{pending.agent_name or pending.agent_id}」执行，当前{label}。做完后把结果收成短话发回。",
        href=_href(slug, "tasks/detail", f"id={task.id}"),
        task_id=task.id,
        task_status=task.status,
        started=started,
        workspace=workspace,
    )


def extract_result_text(raw: str) -> str:
    """从执行器 JSON 里取出给人看的正文。普通文本原样返回。"""
    text = (raw or "").strip()
    if not text.startswith("{"):
        return text
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    inner = data.get("result") if isinstance(data.get("result"), dict) else data
    if not isinstance(inner, dict):
        return text
    parts = [
        str(item.get("text") or "").strip()
        for item in inner.get("payloads") or []
        if isinstance(item, dict) and str(item.get("text") or "").strip()
    ]
    return "\n".join(parts).strip() or text


def task_spoken(task) -> dict[str, str | bool]:
    """把任务状态收成设备能播的一句。未结束时只报进度。"""
    status = task.status or ""
    done = status in ("completed", "failed", "cancelled")
    if status == "completed":
        text = extract_result_text(task.output or "") or "任务已完成。"
    elif status == "failed":
        text = extract_result_text(task.error or "") or "任务失败。"
    elif status == "cancelled":
        text = "任务已取消。"
    else:
        text = f"任务仍在{_STATUS.get(status, status)}。"
    if len(text) > 480:
        text = text[:479] + "…"
    return {
        "task_id": task.id,
        "status": status,
        "done": done,
        "reply": text,
    }


async def brief_for_device(task, *, actor_id: str = "") -> str:
    """完成结果先转成短话。同一任务只转译一次，写进信息链。"""
    from app.core import super_ai_llm as llm
    from app.core.chain import append_chain, list_chain

    source = extract_result_text(task.output or "") or "任务已完成。"
    rows = await list_chain(task_id=task.id)
    for row in rows:
        if row.kind == "translate" and row.summary:
            logger.info("super_ai brief reuse task_id=%s", task.id)
            return row.summary
    spoken = await llm.summarize_spoken(run_id=(task.id or "")[:12], source=source)
    fallback = spoken is None
    if fallback:
        spoken = source if len(source) <= 480 else source[:479] + "…"
        logger.info("super_ai brief fallback task_id=%s", task.id)
    elif len(spoken) > 480:
        spoken = spoken[:479] + "…"
    await append_chain(
        kind="translate",
        task_id=task.id,
        actor_id="super-ai",
        target_id=actor_id,
        channel="voice",
        status=task.status or "",
        summary=spoken,
        detail={"fallback": fallback},
    )
    return spoken


async def _list_tasks(run_id, slug, active_only, task_manager, *, started, workspace):
    wid = await workspace_service.resolve_workspace_id(slug) or None
    if active_only:
        running, _ = await task_manager.list_tasks(
            1, 20, "running", None, None, wid
        )
        queued, _ = await task_manager.list_tasks(1, 20, "queued", None, None, wid)
        items = list(running) + [t for t in queued if t.id not in {x.id for x in running}]
        title = "进行中"
    else:
        items, _ = await task_manager.list_tasks(1, 8, None, None, None, wid)
        title = "最近"
    if not items:
        reply = f"没有{title}的任务。"
    else:
        lines = [
            f"{i}. {_STATUS.get(t.status, t.status)} · {_clip(t.prompt)}"
            for i, t in enumerate(items[:6], 1)
        ]
        reply = f"{title} {len(items)} 条：\n" + "\n".join(lines)
    return _finish(
        run_id,
        "list_tasks",
        "tasks",
        reply,
        href=_href(slug, "tasks"),
        started=started,
        workspace=workspace,
    )


async def _search_knowledge(run_id, query, slug, *, started, workspace):
    q = (query or "").strip()
    if not q:
        return _finish(
            run_id,
            "knowledge",
            "knowledge",
            "要查哪一句？例如：什么是多端绑定。",
            href=_href(slug, "knowledge"),
            started=started,
            workspace=workspace,
        )
    wid = await workspace_service.resolve_workspace_id(slug) or None
    hits = await knowledge_service.search_knowledge(
        q, limit=3, workspace_id=wid, auto_backfill=False
    )
    if not hits:
        reply = f"知识库里没有和「{q}」相关的条目。"
    else:
        lines = [f"{i}. {_clip(h.title, 28)}：{_clip(h.snippet, 42)}" for i, h in enumerate(hits, 1)]
        reply = f"关于「{q}」：\n" + "\n".join(lines)
    return _finish(
        run_id,
        "knowledge",
        "knowledge",
        reply,
        href=_href(slug, "knowledge"),
        started=started,
        workspace=workspace,
    )


async def _list_skills(run_id, slug, *, started, workspace):
    skills = [s for s in scan_all_skills() if not s.archived][:6]
    if not skills:
        reply = "技能目录是空的。"
    else:
        lines = [f"{i}. {s.name}" + (f"：{_clip(s.description, 28)}" if s.description else "") for i, s in enumerate(skills, 1)]
        reply = "可用技能：\n" + "\n".join(lines)
    return _finish(
        run_id,
        "skills",
        "skills",
        reply,
        href=_href(slug, "skills"),
        started=started,
        workspace=workspace,
    )


async def _list_outputs(run_id, slug, *, started, workspace):
    rows = list_recent(limit=5)
    files = [r for r in rows if r.kind == "file"][:5]
    if not files:
        reply = "最近没有输出物。"
    else:
        lines = [f"{i}. {_clip(r.name, 40)}" for i, r in enumerate(files, 1)]
        reply = "最近产出：\n" + "\n".join(lines)
    return _finish(
        run_id,
        "outputs",
        "outputs",
        reply,
        href=_href(slug, "outputs"),
        started=started,
        workspace=workspace,
    )


async def _system(run_id, slug, monitor, *, started, workspace):
    if not monitor.settings.executors_enabled():
        return _finish(
            run_id,
            "system",
            "system",
            "协调器正常，本机没有执行器。",
            href=_href(slug, "system"),
            started=started,
            workspace=workspace,
        )
    status = await monitor.get_system_status(force_refresh=False)
    parts = []
    for pane in status.runtimes or []:
        flag = "可用" if pane.available else "不可用"
        ver = f" {pane.version}" if pane.version else ""
        parts.append(f"{pane.runtime} {flag}{ver}")
    if not parts:
        gate = "可用" if status.gateway.running or status.gateway.probe_ok else "不可用"
        parts.append(f"gateway {gate}")
    err_n = len(status.cron_errors or [])
    reply = "；".join(parts) + f"。会话 {status.sessions_count}，定时异常 {err_n}。"
    return _finish(
        run_id,
        "system",
        "system",
        reply,
        href=_href(slug, "system"),
        started=started,
        workspace=workspace,
    )


async def _fleet(run_id, slug, *, started, workspace):
    wid = await workspace_service.resolve_workspace_id(slug) or ""
    nodes = await fleet_service.list_nodes(wid)
    if not nodes:
        reply = "还没有设备。"
    else:
        lines = [
            f"{i}. {n.get('name') or n.get('id')} · {'在线' if n.get('online') else '离线'}"
            for i, n in enumerate(nodes[:6], 1)
        ]
        reply = f"设备 {len(nodes)} 台：\n" + "\n".join(lines)
    return _finish(
        run_id,
        "fleet",
        "fleet",
        reply,
        href=_href(slug, "fleet"),
        started=started,
        workspace=workspace,
    )
