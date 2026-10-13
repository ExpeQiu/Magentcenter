"""AgentCenter CLI 入口。"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from typing import Any

from app.cli import __version__
from app.cli.catalog import capabilities_payload
from app.cli.client import AgentCenterClient, ApiError
from app.cli.demo import demo_payload
from app.cli.output import (
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_NO_DATA,
    EXIT_OK,
    EXIT_UPSTREAM,
    clip,
    emit,
    format_agent_row,
    format_task_row,
    note,
    resolve_format,
)

logger = logging.getLogger("agentcenter.cli")

TASK_COLUMNS = [
    ("id", "ID"),
    ("runtime", "RUNTIME"),
    ("agent", "AGENT"),
    ("status", "STATUS"),
    ("prompt", "PROMPT"),
]
AGENT_COLUMNS = [
    ("runtime", "RUNTIME"),
    ("id", "ID"),
    ("name", "NAME"),
    ("model", "MODEL"),
    ("default", "DEFAULT"),
]


class AcParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        note(f"error: {message}")
        raise SystemExit(EXIT_ERROR)


def _setup_logging(verbose: bool, quiet: bool) -> None:
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _present(
    args: argparse.Namespace,
    data: Any,
    *,
    module: str,
    columns: list[tuple[str, str]] | None = None,
    rows: list[dict[str, Any]] | None = None,
    next_actions: list[str] | None = None,
    human: str | None = None,
) -> None:
    fmt, raw = resolve_format(args)
    emit(
        data,
        fmt=fmt,
        raw=raw,
        module=module,
        demo=bool(args.demo),
        request_id=args.request_id,
        columns=columns,
        rows=rows,
        next_actions=next_actions,
        human=human,
        output_path=args.output,
    )


def _load(args: argparse.Namespace, key: str, live: Any) -> Any:
    if args.demo:
        return demo_payload(key)
    return live()


def _task_next(task: dict[str, Any]) -> list[str]:
    task_id = task.get("id", "")
    if task.get("status") in ("queued", "running"):
        return [f"ac tasks get {task_id}", f"ac tasks watch {task_id}"]
    return [f"ac tasks get {task_id}"]


def _finish_task(task: dict[str, Any]) -> int:
    return EXIT_OK if task.get("status") != "failed" else EXIT_ERROR


def _task_human(task: dict[str, Any]) -> str:
    lines = [f"task_id={task.get('id')} status={task.get('status')}"]
    if task.get("output"):
        lines.extend(["", "--- output ---", str(task["output"])])
    return "\n".join(lines)


def _show_task(args: argparse.Namespace, task: dict[str, Any], module: str) -> int:
    if task.get("error"):
        note("--- error ---")
        note(str(task["error"]))
    _present(args, task, module=module, human=_task_human(task), next_actions=_task_next(task))
    return _finish_task(task)


def cmd_capabilities(args: argparse.Namespace) -> int:
    _present(args, capabilities_payload(), module="capabilities")
    return EXIT_OK


def cmd_health(args: argparse.Namespace) -> int:
    data = _load(args, "health", lambda: AgentCenterClient(args.base_url).health())
    mock = "mock" if data.get("mock_mode") else "live"
    oc = "ok" if data.get("openclaw_available") else "unavailable"
    hm = "ok" if data.get("hermes_available") else "unavailable"
    human = (
        f"status={data.get('status')} mode={mock} "
        f"openclaw={oc}/{data.get('openclaw_version') or '-'} "
        f"hermes={hm}/{data.get('hermes_version') or '-'} "
        f"default={data.get('default_runtime', 'openclaw')}"
    )
    _present(args, data, module="health", human=human)
    return EXIT_OK


def cmd_agents(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.agents_cmd == "list":
        data = _load(args, "agents", lambda: client.list_agents(refresh=args.refresh))
        rows = [format_agent_row(item) for item in data]
        _present(args, data, module="agents-list", columns=AGENT_COLUMNS, rows=rows)
        return EXIT_OK
    if args.agents_cmd == "stats":
        data = _load(args, "agent-stats", client.agent_stats)
        rows = [
            {
                "runtime": item.get("runtime", ""),
                "agent": item.get("agent_id", ""),
                "tasks": item.get("task_count", 0),
                "running": item.get("running_count", 0),
            }
            for item in data
        ]
        _present(
            args,
            data,
            module="agents-stats",
            columns=[
                ("runtime", "RUNTIME"),
                ("agent", "AGENT"),
                ("tasks", "TASKS"),
                ("running", "RUNNING"),
            ],
            rows=rows,
        )
        return EXIT_OK
    data = _load(args, "agent", lambda: client.get_agent(args.agent_id))
    _present(args, data, module="agents-get")
    return EXIT_OK


def cmd_tasks(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)

    if args.tasks_cmd == "list":
        data = _load(
            args,
            "tasks",
            lambda: client.list_tasks(
                page=args.page,
                page_size=args.page_size,
                status=args.status,
                agent_id=args.agent,
                project_id=args.project,
                workspace_id=args.workspace,
            ),
        )
        rows = [format_task_row(item) for item in data.get("items", [])]
        _present(args, data, module="tasks-list", columns=TASK_COLUMNS, rows=rows)
        fmt, _raw = resolve_format(args)
        if fmt == "table" and not args.output:
            note(f"total={data.get('total', len(rows))} page={data.get('page', 1)}")
        return EXIT_OK

    if args.tasks_cmd == "get":
        task = _load(args, "task", lambda: client.get_task(args.task_id))
        _present(args, task, module="tasks-get", next_actions=_task_next(task))
        return EXIT_OK

    if args.tasks_cmd == "run":
        if args.demo:
            task = demo_payload("task")
        else:
            body: dict[str, Any] = {"agent_id": args.agent_id, "prompt": args.prompt}
            if args.runtime:
                body["runtime"] = args.runtime
            if args.system_prompt:
                body["system_prompt"] = args.system_prompt
            if args.workspace:
                body["workspace_id"] = args.workspace
            if args.project:
                body["project_id"] = args.project
            if args.timeout:
                body["timeout"] = args.timeout
            if args.session:
                body["resume_session_id"] = args.session
            if args.node:
                body["node_id"] = args.node
            task = client.create_task(body)
            logger.info(
                "cli task accepted request_id=%s task_id=%s status=%s",
                args.request_id,
                task.get("id"),
                task.get("status"),
            )
            note(f"accepted task_id={task.get('id')} status={task.get('status')}")
            if args.wait:
                task = client.wait_task(task["id"], timeout=args.wait_timeout)
        return _show_task(args, task, "tasks-run")

    if args.tasks_cmd == "cancel":
        task = demo_payload("task") if args.demo else client.cancel_task(args.task_id)
        _present(args, task, module="tasks-cancel")
        return EXIT_OK

    if args.tasks_cmd == "retry":
        if args.demo:
            task = demo_payload("task")
        else:
            task = client.retry_task(args.task_id)
            note(f"accepted task_id={task.get('id')} status={task.get('status')}")
            if args.wait:
                task = client.wait_task(task["id"], timeout=args.wait_timeout)
        return _show_task(args, task, "tasks-retry")

    if args.tasks_cmd == "watch":
        if args.demo:
            _present(args, {"type": "result", "content": "demo"}, module="tasks-watch")
            return EXIT_OK
        fmt, _raw = resolve_format(args)
        for event in client.stream_task_events(args.task_id):
            if fmt == "json":
                _present(args, event, module="tasks-watch")
            else:
                kind = event.get("type", "?")
                content = event.get("content") or event.get("output") or ""
                print(f"[{kind}] {content}" if content else f"[{kind}]")
        return EXIT_OK

    return EXIT_ERROR


def cmd_squads(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.squads_cmd == "list":
        data = _load(args, "squads", client.list_squads)
        rows = [
            {
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "leader": item.get("leader_id", ""),
            }
            for item in data
        ]
        _present(
            args,
            data,
            module="squads-list",
            columns=[("id", "ID"), ("name", "NAME"), ("leader", "LEADER")],
            rows=rows,
        )
        return EXIT_OK

    if args.demo:
        task = demo_payload("task")
    else:
        task = client.create_squad_task(args.squad_id, args.prompt, timeout=args.timeout)
        note(f"accepted task_id={task.get('id')} status={task.get('status')}")
        if args.wait:
            task = client.wait_task(task["id"], timeout=args.wait_timeout)
    return _show_task(args, task, "squads-run")


def cmd_skills(args: argparse.Namespace) -> int:
    data = _load(args, "skills", lambda: AgentCenterClient(args.base_url).list_skills())
    rows = [{"name": item.get("name", ""), "path": item.get("path", "")} for item in data]
    _present(
        args,
        data,
        module="skills",
        columns=[("name", "NAME"), ("path", "PATH")],
        rows=rows,
    )
    return EXIT_OK


def cmd_autopilots(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.autopilots_cmd == "list":
        data = _load(args, "autopilots", client.list_autopilots)
        rows = [
            {
                "id": str(item.get("id", ""))[:8],
                "name": item.get("name", ""),
                "agent": item.get("agent_id", ""),
                "enabled": "yes" if item.get("enabled") else "no",
            }
            for item in data
        ]
        _present(
            args,
            data,
            module="autopilots-list",
            columns=[("id", "ID"), ("name", "NAME"), ("agent", "AGENT"), ("enabled", "ON")],
            rows=rows,
        )
        return EXIT_OK

    if args.autopilots_cmd == "create":
        if args.demo:
            data = demo_payload("autopilots")[0]
        else:
            data = client.create_autopilot(
                args.name,
                args.agent_id,
                args.prompt,
                cron=args.cron,
                enabled=not args.disabled,
            )
        _present(args, data, module="autopilots-create")
        return EXIT_OK

    if args.autopilots_cmd == "trigger":
        if args.demo:
            task = demo_payload("task")
        else:
            task = client.trigger_autopilot(args.autopilot_id)
            note(f"accepted task_id={task.get('id')} status={task.get('status')}")
            if args.wait:
                task = client.wait_task(task["id"], timeout=args.wait_timeout)
        return _show_task(args, task, "autopilots-trigger")

    if args.autopilots_cmd == "delete":
        if not args.demo:
            client.delete_autopilot(args.autopilot_id)
        _fmt, raw = resolve_format(args)
        if raw:
            return EXIT_OK
        _present(
            args,
            {"id": args.autopilot_id, "deleted": True},
            module="autopilots-delete",
            human=f"deleted autopilot {args.autopilot_id}",
        )
        return EXIT_OK

    return EXIT_ERROR


def cmd_workspaces(args: argparse.Namespace) -> int:
    data = _load(args, "workspaces", lambda: AgentCenterClient(args.base_url).list_workspaces())
    rows = [
        {"slug": item.get("slug", ""), "name": item.get("name", ""), "id": str(item.get("id", ""))[:8]}
        for item in data
    ]
    _present(
        args,
        data,
        module="workspaces",
        columns=[("slug", "SLUG"), ("name", "NAME"), ("id", "ID")],
        rows=rows,
    )
    return EXIT_OK


def cmd_projects(args: argparse.Namespace) -> int:
    data = _load(
        args,
        "projects",
        lambda: AgentCenterClient(args.base_url).list_projects(workspace_id=args.workspace),
    )
    rows = [
        {
            "id": str(item.get("id", ""))[:8],
            "name": item.get("name", ""),
            "tasks": str(item.get("task_count", 0)),
        }
        for item in data
    ]
    _present(
        args,
        data,
        module="projects",
        columns=[("id", "ID"), ("name", "NAME"), ("tasks", "TASKS")],
        rows=rows,
    )
    return EXIT_OK


def cmd_knowledge(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.knowledge_cmd == "status":
        data = _load(args, "knowledge-status", client.knowledge_status)
        _present(args, data, module="knowledge-status")
        return EXIT_OK
    data = _load(
        args,
        "knowledge-hits",
        lambda: client.knowledge_search(
            args.q,
            limit=args.limit,
            mode=args.mode,
            runtime=args.runtime,
            kind=args.kind,
            workspace_id=args.workspace,
        ),
    )
    rows = [
        {
            "id": clip(item.get("id", ""), 12),
            "kind": item.get("kind", ""),
            "title": clip(item.get("title", ""), 48),
            "score": item.get("score", ""),
        }
        for item in data
    ]
    _present(
        args,
        data,
        module="knowledge-search",
        columns=[("id", "ID"), ("kind", "KIND"), ("title", "TITLE"), ("score", "SCORE")],
        rows=rows,
    )
    return EXIT_OK if data else EXIT_NO_DATA


def cmd_outputs(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.outputs_cmd == "status":
        data = _load(args, "outputs-status", client.outputs_status)
        _present(args, data, module="outputs-status")
        return EXIT_OK
    data = _load(
        args,
        "outputs",
        lambda: client.outputs_recent(limit=args.limit, source=args.source, q=args.q),
    )
    rows = [
        {
            "name": item.get("name", ""),
            "source": item.get("source", ""),
            "path": clip(item.get("path", ""), 48),
            "size": item.get("size", ""),
        }
        for item in data
    ]
    _present(
        args,
        data,
        module="outputs-recent",
        columns=[("name", "NAME"), ("source", "SOURCE"), ("path", "PATH"), ("size", "SIZE")],
        rows=rows,
    )
    return EXIT_OK


def cmd_system(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.system_cmd == "alerts":
        data = _load(args, "alerts", client.cron_alerts)
        errors = data.get("errors") or []
        recent = data.get("recent_alerts") or []
        human = f"errors={len(errors)} recent={len(recent)} persisted={data.get('persisted')}"
        _present(args, data, module="system-alerts", human=human)
        return EXIT_OK
    data = _load(args, "system", lambda: client.system_status(refresh=args.refresh))
    gateway = data.get("gateway") or {}
    runtimes = data.get("runtimes") or []
    runtime_text = ",".join(
        f"{item.get('runtime')}={'ok' if item.get('available') else 'down'}" for item in runtimes
    )
    human = (
        f"gateway={'up' if gateway.get('running') or gateway.get('probe_ok') else 'down'} "
        f"sessions={data.get('sessions_count', 0)} "
        f"cron_errors={len(data.get('cron_errors') or [])} "
        f"runtimes={runtime_text or '-'}"
    )
    _present(args, data, module="system-status", human=human)
    return EXIT_OK


def cmd_sessions(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.sessions_cmd == "list":
        data = _load(args, "sessions", lambda: client.list_sessions(limit=args.limit))
        rows = [
            {
                "session": clip(item.get("session_id", ""), 24),
                "runtime": item.get("runtime", ""),
                "agent": item.get("agent_id", ""),
                "model": item.get("model", ""),
            }
            for item in data
        ]
        _present(
            args,
            data,
            module="sessions-list",
            columns=[
                ("session", "SESSION"),
                ("runtime", "RUNTIME"),
                ("agent", "AGENT"),
                ("model", "MODEL"),
            ],
            rows=rows,
        )
        return EXIT_OK
    data = _load(args, "session", lambda: client.get_session(args.session_id))
    messages = data.get("messages") or []
    human = (
        f"session_id={data.get('session_id')} runtime={data.get('runtime')} "
        f"agent={data.get('agent_id')} messages={len(messages)}"
    )
    _present(args, data, module="sessions-get", human=human)
    return EXIT_OK


def cmd_fleet(args: argparse.Namespace) -> int:
    data = _load(
        args,
        "fleet",
        lambda: AgentCenterClient(args.base_url).list_fleet_nodes(args.workspace),
    )
    rows = [
        {
            "id": item.get("id", ""),
            "name": item.get("name", ""),
            "mode": item.get("mode", ""),
            "online": "yes" if item.get("online") else "no",
            "bound": "yes" if item.get("bound") else "no",
        }
        for item in data
    ]
    _present(
        args,
        data,
        module="fleet-nodes",
        columns=[
            ("id", "ID"),
            ("name", "NAME"),
            ("mode", "MODE"),
            ("online", "ONLINE"),
            ("bound", "BOUND"),
        ],
        rows=rows,
    )
    return EXIT_OK


def cmd_chain(args: argparse.Namespace) -> int:
    if not args.demo and not (args.task or args.run or args.actor):
        note("error: 需要 --task、--run 或 --actor")
        return EXIT_ERROR
    data = _load(
        args,
        "chain",
        lambda: AgentCenterClient(args.base_url).list_chain(
            task_id=args.task or "",
            run_id=args.run or "",
            actor_id=args.actor or "",
            limit=args.limit,
        ),
    )
    rows = [
        {
            "kind": item.get("kind", ""),
            "status": item.get("status", ""),
            "task": clip(item.get("task_id", ""), 12),
            "summary": clip(item.get("summary", ""), 48),
        }
        for item in data
    ]
    _present(
        args,
        data,
        module="chain",
        columns=[("kind", "KIND"), ("status", "STATUS"), ("task", "TASK"), ("summary", "SUMMARY")],
        rows=rows,
    )
    return EXIT_OK if data else EXIT_NO_DATA


def cmd_sops(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.sops_cmd == "list":
        data = _load(args, "sops", lambda: client.list_sops(args.workspace))
        rows = [
            {
                "id": str(item.get("id", ""))[:8],
                "name": item.get("name", ""),
                "steps": item.get("step_count", 0),
                "runs": item.get("run_count", 0),
            }
            for item in data
        ]
        _present(
            args,
            data,
            module="sops-list",
            columns=[("id", "ID"), ("name", "NAME"), ("steps", "STEPS"), ("runs", "RUNS")],
            rows=rows,
        )
        return EXIT_OK
    data = _load(args, "sop", lambda: client.get_sop(args.sop_id))
    _present(args, data, module="sops-get")
    return EXIT_OK


def build_parser() -> AcParser:
    parser = AcParser(
        prog="ac",
        description="AgentCenter 命令行工具 — 管理 Agent、任务、知识库、输出物与多端",
    )
    parser.add_argument("--version", action="version", version=f"ac {__version__}")
    parser.add_argument(
        "--base-url",
        default=None,
        help="API 地址 (默认 AGENTCENTER_URL 或 http://127.0.0.1:8013)",
    )
    parser.add_argument(
        "--format",
        choices=["table", "json", "csv", "markdown"],
        default=None,
        help="输出格式。json 为带 module/data_source/items 的契约",
    )
    parser.add_argument("--json", action="store_true", help="输出原始 JSON（兼容旧脚本）")
    parser.add_argument("-o", "--output", default=None, help="把结果写入文件")
    parser.add_argument("--demo", action="store_true", help="使用内置示例，不访问协调器")
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    log_group.add_argument("-q", "--quiet", action="store_true", help="仅警告及以上日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_cap = sub.add_parser("capabilities", help="命令目录与退出码")
    p_cap.set_defaults(func=cmd_capabilities)

    p_health = sub.add_parser("health", help="健康检查")
    p_health.set_defaults(func=cmd_health)

    p_agents = sub.add_parser("agents", help="Agent 管理")
    agents_sub = p_agents.add_subparsers(dest="agents_cmd", required=True)
    p_agents_list = agents_sub.add_parser("list", help="列出 Agent")
    p_agents_list.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    p_agents_list.set_defaults(func=cmd_agents)
    p_agents_stats = agents_sub.add_parser("stats", help="Agent 任务统计")
    p_agents_stats.set_defaults(func=cmd_agents)
    p_agents_get = agents_sub.add_parser("get", help="查看 Agent 详情")
    p_agents_get.add_argument("agent_id")
    p_agents_get.set_defaults(func=cmd_agents)

    p_tasks = sub.add_parser("tasks", help="任务管理")
    tasks_sub = p_tasks.add_subparsers(dest="tasks_cmd", required=True)

    p_tasks_list = tasks_sub.add_parser("list", help="列出任务")
    p_tasks_list.add_argument("--page", type=int, default=1)
    p_tasks_list.add_argument("--page-size", type=int, default=20)
    p_tasks_list.add_argument("--status")
    p_tasks_list.add_argument("--agent")
    p_tasks_list.add_argument("--project")
    p_tasks_list.add_argument("--workspace")
    p_tasks_list.set_defaults(func=cmd_tasks)

    p_tasks_get = tasks_sub.add_parser("get", help="任务详情")
    p_tasks_get.add_argument("task_id")
    p_tasks_get.set_defaults(func=cmd_tasks)

    p_tasks_run = tasks_sub.add_parser("run", help="创建并执行任务")
    p_tasks_run.add_argument("agent_id")
    p_tasks_run.add_argument("prompt")
    p_tasks_run.add_argument("--runtime", choices=["openclaw", "hermes"], default=None)
    p_tasks_run.add_argument("--system-prompt", default="")
    p_tasks_run.add_argument("--workspace", default="")
    p_tasks_run.add_argument("--project", default="")
    p_tasks_run.add_argument("--timeout", type=int, default=None)
    p_tasks_run.add_argument("--session", default=None, help="恢复 session_id")
    p_tasks_run.add_argument("--node", default=None, help="派到设备：auto 或节点 id")
    p_tasks_run.add_argument("--wait", action="store_true", help="等待任务完成")
    p_tasks_run.add_argument("--wait-timeout", type=float, default=600.0)
    p_tasks_run.set_defaults(func=cmd_tasks)

    p_tasks_cancel = tasks_sub.add_parser("cancel", help="取消任务")
    p_tasks_cancel.add_argument("task_id")
    p_tasks_cancel.set_defaults(func=cmd_tasks)

    p_tasks_retry = tasks_sub.add_parser("retry", help="重试任务")
    p_tasks_retry.add_argument("task_id")
    p_tasks_retry.add_argument("--wait", action="store_true")
    p_tasks_retry.add_argument("--wait-timeout", type=float, default=600.0)
    p_tasks_retry.set_defaults(func=cmd_tasks)

    p_tasks_watch = tasks_sub.add_parser("watch", help="SSE 实时事件流")
    p_tasks_watch.add_argument("task_id")
    p_tasks_watch.set_defaults(func=cmd_tasks)

    p_squads = sub.add_parser("squads", help="小队编排")
    squads_sub = p_squads.add_subparsers(dest="squads_cmd", required=True)
    p_squads_list = squads_sub.add_parser("list", help="列出小队")
    p_squads_list.set_defaults(func=cmd_squads)
    p_squads_run = squads_sub.add_parser("run", help="向小队 leader 分配任务")
    p_squads_run.add_argument("squad_id")
    p_squads_run.add_argument("prompt")
    p_squads_run.add_argument("--timeout", type=int, default=None)
    p_squads_run.add_argument("--wait", action="store_true")
    p_squads_run.add_argument("--wait-timeout", type=float, default=600.0)
    p_squads_run.set_defaults(func=cmd_squads)

    p_skills = sub.add_parser("skills", help="技能目录")
    p_skills.set_defaults(func=cmd_skills)

    p_ap = sub.add_parser("autopilots", help="Autopilot 定时任务")
    ap_sub = p_ap.add_subparsers(dest="autopilots_cmd", required=True)
    p_ap_list = ap_sub.add_parser("list")
    p_ap_list.set_defaults(func=cmd_autopilots)
    p_ap_create = ap_sub.add_parser("create")
    p_ap_create.add_argument("name")
    p_ap_create.add_argument("agent_id")
    p_ap_create.add_argument("prompt")
    p_ap_create.add_argument("--cron", default="3600")
    p_ap_create.add_argument("--disabled", action="store_true")
    p_ap_create.set_defaults(func=cmd_autopilots)
    p_ap_trigger = ap_sub.add_parser("trigger")
    p_ap_trigger.add_argument("autopilot_id")
    p_ap_trigger.add_argument("--wait", action="store_true")
    p_ap_trigger.add_argument("--wait-timeout", type=float, default=600.0)
    p_ap_trigger.set_defaults(func=cmd_autopilots)
    p_ap_del = ap_sub.add_parser("delete")
    p_ap_del.add_argument("autopilot_id")
    p_ap_del.set_defaults(func=cmd_autopilots)

    p_ws = sub.add_parser("workspaces", help="工作区")
    p_ws.set_defaults(func=cmd_workspaces)
    p_proj = sub.add_parser("projects", help="项目")
    p_proj.add_argument("--workspace", default=None)
    p_proj.set_defaults(func=cmd_projects)

    p_know = sub.add_parser("knowledge", help="知识库")
    know_sub = p_know.add_subparsers(dest="knowledge_cmd", required=True)
    p_know_status = know_sub.add_parser("status", help="知识库状态")
    p_know_status.set_defaults(func=cmd_knowledge)
    p_know_search = know_sub.add_parser("search", help="检索知识库")
    p_know_search.add_argument("q")
    p_know_search.add_argument("--limit", type=int, default=20)
    p_know_search.add_argument("--mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
    p_know_search.add_argument("--runtime", choices=["openclaw", "hermes"], default=None)
    p_know_search.add_argument("--kind", default=None)
    p_know_search.add_argument("--workspace", default=None)
    p_know_search.set_defaults(func=cmd_knowledge)

    p_out = sub.add_parser("outputs", help="输出物")
    out_sub = p_out.add_subparsers(dest="outputs_cmd", required=True)
    p_out_status = out_sub.add_parser("status", help="输出物库状态")
    p_out_status.set_defaults(func=cmd_outputs)
    p_out_recent = out_sub.add_parser("recent", help="最近文件")
    p_out_recent.add_argument("--limit", type=int, default=20)
    p_out_recent.add_argument("--source", choices=["openclaw", "hermes"], default=None)
    p_out_recent.add_argument("--q", default=None)
    p_out_recent.set_defaults(func=cmd_outputs)

    p_sys = sub.add_parser("system", help="系统状态")
    sys_sub = p_sys.add_subparsers(dest="system_cmd", required=True)
    p_sys_status = sys_sub.add_parser("status", help="Gateway / Cron / 会话概况")
    p_sys_status.add_argument("--refresh", action="store_true")
    p_sys_status.set_defaults(func=cmd_system)
    p_sys_alerts = sys_sub.add_parser("alerts", help="告警")
    p_sys_alerts.set_defaults(func=cmd_system)

    p_sess = sub.add_parser("sessions", help="会话")
    sess_sub = p_sess.add_subparsers(dest="sessions_cmd", required=True)
    p_sess_list = sess_sub.add_parser("list", help="列出会话")
    p_sess_list.add_argument("--limit", type=int, default=50)
    p_sess_list.set_defaults(func=cmd_sessions)
    p_sess_get = sess_sub.add_parser("get", help="会话详情")
    p_sess_get.add_argument("session_id")
    p_sess_get.set_defaults(func=cmd_sessions)

    p_fleet = sub.add_parser("fleet", help="多端设备")
    fleet_sub = p_fleet.add_subparsers(dest="fleet_cmd", required=True)
    p_fleet_nodes = fleet_sub.add_parser("nodes", help="设备名册")
    p_fleet_nodes.add_argument("--workspace", default=None)
    p_fleet_nodes.set_defaults(func=cmd_fleet)

    p_chain = sub.add_parser("chain", help="信息链")
    p_chain.add_argument("--task", default=None)
    p_chain.add_argument("--run", default=None)
    p_chain.add_argument("--actor", default=None)
    p_chain.add_argument("--limit", type=int, default=200)
    p_chain.set_defaults(func=cmd_chain)

    p_sops = sub.add_parser("sops", help="SOP")
    sops_sub = p_sops.add_subparsers(dest="sops_cmd", required=True)
    p_sops_list = sops_sub.add_parser("list", help="列出 SOP")
    p_sops_list.add_argument("--workspace", default=None)
    p_sops_list.set_defaults(func=cmd_sops)
    p_sops_get = sops_sub.add_parser("get", help="查看 SOP")
    p_sops_get.add_argument("sop_id")
    p_sops_get.set_defaults(func=cmd_sops)

    return parser


def exit_from_api(exc: ApiError) -> int:
    if exc.status == 404:
        return EXIT_NO_DATA
    if exc.status == 0 or exc.status >= 500:
        return EXIT_UPSTREAM
    return EXIT_ERROR


_VALUE_FLAGS = {"--format", "--base-url", "--output", "-o"}
_GLOBAL_FLAGS = _VALUE_FLAGS | {"--json", "--demo", "-v", "--verbose", "-q", "--quiet", "--version"}


def _hoist_globals(argv: list[str]) -> list[str]:
    """全局选项放在子命令前后都可以。"""
    flags: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            rest.extend(argv[index:])
            break
        name, sep, _inline = token.partition("=")
        if name in _GLOBAL_FLAGS:
            if name in _VALUE_FLAGS and not sep:
                if index + 1 >= len(argv):
                    flags.append(token)
                    index += 1
                    continue
                flags.extend((token, argv[index + 1]))
                index += 2
                continue
            flags.append(token)
            index += 1
            continue
        rest.append(token)
        index += 1
    return flags + rest


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    args = parser.parse_args(_hoist_globals(list(argv)))
    _setup_logging(args.verbose, args.quiet)
    args.request_id = uuid.uuid4().hex[:12]
    logger.info(
        "cli start request_id=%s command=%s demo=%s format=%s",
        args.request_id,
        args.command,
        bool(args.demo),
        args.format or ("json" if args.json else "table"),
    )
    try:
        return args.func(args)
    except ApiError as exc:
        logger.error("cli api request_id=%s status=%s detail=%s", args.request_id, exc.status, exc.detail)
        note(f"error: {exc}")
        return exit_from_api(exc)
    except TimeoutError as exc:
        logger.error("cli timeout request_id=%s detail=%s", args.request_id, exc)
        note(f"error: {exc}")
        return EXIT_ERROR
    except OSError as exc:
        logger.error("cli io request_id=%s detail=%s", args.request_id, exc)
        note(f"error: {exc}")
        return EXIT_ERROR
    except KeyboardInterrupt:
        note("interrupted")
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
