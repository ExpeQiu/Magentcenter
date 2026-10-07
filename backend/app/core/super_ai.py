"""超级AI 首页：语音/文字共用的意图路由。只认白名单服务。"""

from __future__ import annotations

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
_SYSTEM = ("系统是否正常", "系统状态", "健康检查", "服务是否正常", "系统正常")
_FLEET = ("哪台设备", "设备在线", "在线设备", "多端状态", "有哪些设备")
_OPEN_AGAIN = ("打开刚才那个", "打开刚才", "打开它")
_HELP = ("你好", "嗨", "在吗", "帮助", "你是谁", "你能做什么", "你会什么")

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
    "也可以看系统与设备是否在线。建任务会先说一遍，你回复「确认」后才执行。"
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
    started: float,
    workspace: str,
) -> SuperAiTurnResponse:
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
            return await _prepare_create(
                run_id, parsed.query, registry, started=started, workspace=slug
            )
        if parsed.intent == "confirm_create" and pending:
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

    return _finish(
        run_id,
        "unknown",
        "",
        "我没对上可调用的服务。可以问进行中的任务、技能、知识库、最近产出，或系统是否正常。",
        started=started,
        workspace=slug,
    )


async def _prepare_create(run_id, prompt, registry, *, started, workspace):
    body = (prompt or "").strip(" ：:，,。")
    if not body:
        return _finish(
            run_id,
            "create_task",
            "tasks",
            "要我做什么？例如：帮我建一个任务：整理本周输出。",
            started=started,
            workspace=workspace,
        )
    agent = await _pick_agent(registry)
    if not agent:
        return _finish(
            run_id,
            "create_task",
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
    return _finish(
        run_id,
        "create_task",
        "tasks",
        f"将用「{pending.agent_name}」新建任务：{body}。回复「确认」后执行。",
        pending=pending,
        started=started,
        workspace=workspace,
    )


async def _commit_create(run_id, pending: SuperAiPending, slug, task_manager, *, started, workspace):
    wid = await workspace_service.resolve_workspace_id(slug) or ""
    task = await task_manager.create_task(
        CreateTaskRequest(
            agent_id=pending.agent_id,
            prompt=pending.prompt,
            runtime=pending.runtime,
            workspace_id=wid,
        )
    )
    label = _STATUS.get(task.status, task.status)
    return _finish(
        run_id,
        "confirm_create",
        "tasks",
        f"已交给 AgentCenter 执行，当前{label}。完成后把结果发回。",
        href=_href(slug, "tasks/detail", f"id={task.id}"),
        task_id=task.id,
        task_status=task.status,
        started=started,
        workspace=workspace,
    )


def task_spoken(task) -> dict[str, str | bool]:
    """把任务状态收成设备能播的一句。未结束时只报进度。"""
    status = task.status or ""
    done = status in ("completed", "failed", "cancelled")
    if status == "completed":
        text = (task.output or "").strip() or "任务已完成。"
    elif status == "failed":
        text = (task.error or "").strip() or "任务失败。"
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
