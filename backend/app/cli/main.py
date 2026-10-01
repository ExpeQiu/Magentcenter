"""AgentCenter CLI 入口。"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from app.cli.client import AgentCenterClient, ApiError
from app.cli.output import format_agent_row, format_task_row, print_json, print_table

logger = logging.getLogger("agentcenter.cli")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _emit(data: Any, *, as_json: bool, table_fn=None) -> None:
    if as_json:
        print_json(data)
    elif table_fn and isinstance(data, list):
        print_table(data, table_fn)
    elif isinstance(data, dict) and "items" in data:
        rows = [format_task_row(t) for t in data["items"]]
        print_table(
            rows,
            [
                ("id", "ID"),
                ("runtime", "RUNTIME"),
                ("agent", "AGENT"),
                ("status", "STATUS"),
                ("prompt", "PROMPT"),
            ],
        )
        print(f"\ntotal={data.get('total', len(rows))} page={data.get('page', 1)}")
    else:
        print_json(data)


def cmd_health(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    data = client.health()
    if args.json:
        print_json(data)
    else:
        mock = "mock" if data.get("mock_mode") else "live"
        oc = "ok" if data.get("openclaw_available") else "unavailable"
        hm = "ok" if data.get("hermes_available") else "unavailable"
        oc_ver = data.get("openclaw_version") or "-"
        hm_ver = data.get("hermes_version") or "-"
        print(
            f"status={data.get('status')} mode={mock} "
            f"openclaw={oc}/{oc_ver} hermes={hm}/{hm_ver} "
            f"default={data.get('default_runtime', 'openclaw')}"
        )
    return 0


def cmd_agents(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.agents_cmd == "list":
        data = client.list_agents(refresh=args.refresh)
        _emit(
            [format_agent_row(a) for a in data] if not args.json else data,
            as_json=args.json,
            table_fn=[
                ("runtime", "RUNTIME"),
                ("id", "ID"),
                ("name", "NAME"),
                ("model", "MODEL"),
                ("default", "DEFAULT"),
            ],
        )
    elif args.agents_cmd == "stats":
        data = client.agent_stats()
        _emit(data, as_json=args.json)
    else:
        data = client.get_agent(args.agent_id)
        _emit(data, as_json=args.json)
    return 0


def cmd_tasks(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)

    if args.tasks_cmd == "list":
        data = client.list_tasks(
            page=args.page,
            page_size=args.page_size,
            status=args.status,
            agent_id=args.agent,
            project_id=args.project,
            workspace_id=args.workspace,
        )
        _emit(data, as_json=args.json)
        return 0

    if args.tasks_cmd == "get":
        _emit(client.get_task(args.task_id), as_json=args.json)
        return 0

    if args.tasks_cmd == "run":
        body: dict[str, Any] = {
            "agent_id": args.agent_id,
            "prompt": args.prompt,
        }
        if getattr(args, "runtime", None):
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
        if getattr(args, "node", None):
            body["node_id"] = args.node

        task = client.create_task(body)
        if args.wait:
            task = client.wait_task(task["id"], timeout=args.wait_timeout)
        if args.json:
            print_json(task)
        else:
            print(f"task_id={task['id']} status={task['status']}")
            if task.get("output"):
                print("\n--- output ---")
                print(task["output"])
            if task.get("error"):
                print("\n--- error ---", file=sys.stderr)
                print(task["error"], file=sys.stderr)
        return 0 if task.get("status") != "failed" else 1

    if args.tasks_cmd == "cancel":
        _emit(client.cancel_task(args.task_id), as_json=args.json)
        return 0

    if args.tasks_cmd == "retry":
        task = client.retry_task(args.task_id)
        if args.wait:
            task = client.wait_task(task["id"], timeout=args.wait_timeout)
        _emit(task, as_json=args.json)
        return 0 if task.get("status") != "failed" else 1

    if args.tasks_cmd == "watch":
        for ev in client.stream_task_events(args.task_id):
            if args.json:
                print_json(ev)
            else:
                et = ev.get("type", "?")
                content = ev.get("content") or ev.get("output") or ""
                if content:
                    print(f"[{et}] {content}")
                else:
                    print(f"[{et}]")
        return 0

    return 1


def cmd_squads(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.squads_cmd == "list":
        data = client.list_squads()
        if args.json:
            print_json(data)
        else:
            rows = [
                {
                    "id": s.get("id", ""),
                    "name": s.get("name", ""),
                    "leader": s.get("leader_id", ""),
                }
                for s in data
            ]
            print_table(rows, [("id", "ID"), ("name", "NAME"), ("leader", "LEADER")])
        return 0

    task = client.create_squad_task(args.squad_id, args.prompt, timeout=args.timeout)
    if args.wait:
        task = client.wait_task(task["id"], timeout=args.wait_timeout)
    if args.json:
        print_json(task)
    else:
        print(f"task_id={task['id']} status={task['status']}")
        if task.get("output"):
            print(task["output"])
    return 0 if task.get("status") != "failed" else 1


def cmd_skills(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    data = client.list_skills()
    if args.json:
        print_json(data)
    else:
        rows = [{"name": s.get("name", ""), "path": s.get("path", "")} for s in data]
        print_table(rows, [("name", "NAME"), ("path", "PATH")])
    return 0


def cmd_autopilots(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    if args.autopilots_cmd == "list":
        data = client.list_autopilots()
        if args.json:
            print_json(data)
        else:
            rows = [
                {
                    "id": a.get("id", "")[:8],
                    "name": a.get("name", ""),
                    "agent": a.get("agent_id", ""),
                    "enabled": "yes" if a.get("enabled") else "no",
                }
                for a in data
            ]
            print_table(
                rows,
                [("id", "ID"), ("name", "NAME"), ("agent", "AGENT"), ("enabled", "ON")],
            )
        return 0

    if args.autopilots_cmd == "create":
        data = client.create_autopilot(
            args.name, args.agent_id, args.prompt, cron=args.cron, enabled=not args.disabled
        )
        _emit(data, as_json=args.json)
        return 0

    if args.autopilots_cmd == "trigger":
        task = client.trigger_autopilot(args.autopilot_id)
        if args.wait:
            task = client.wait_task(task["id"], timeout=args.wait_timeout)
        _emit(task, as_json=args.json)
        return 0 if task.get("status") != "failed" else 1

    if args.autopilots_cmd == "delete":
        client.delete_autopilot(args.autopilot_id)
        if not args.json:
            print(f"deleted autopilot {args.autopilot_id}")
        return 0

    return 1


def cmd_workspaces(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    data = client.list_workspaces()
    if args.json:
        print_json(data)
    else:
        rows = [
            {"slug": w.get("slug", ""), "name": w.get("name", ""), "id": w.get("id", "")[:8]}
            for w in data
        ]
        print_table(rows, [("slug", "SLUG"), ("name", "NAME"), ("id", "ID")])
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    client = AgentCenterClient(args.base_url)
    data = client.list_projects(workspace_id=args.workspace)
    if args.json:
        print_json(data)
    else:
        rows = [
            {
                "id": p.get("id", "")[:8],
                "name": p.get("name", ""),
                "tasks": str(p.get("task_count", 0)),
            }
            for p in data
        ]
        print_table(rows, [("id", "ID"), ("name", "NAME"), ("tasks", "TASKS")])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ac",
        description="AgentCenter 命令行工具 — 管理 Agent、任务、小队与 Autopilot",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API 地址 (默认 AGENTCENTER_URL 或 http://127.0.0.1:8013)",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    # health
    p_health = sub.add_parser("health", help="健康检查")
    p_health.set_defaults(func=cmd_health)

    # agents
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

    # tasks
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
    p_tasks_run.add_argument(
        "--runtime",
        choices=["openclaw", "hermes"],
        default=None,
        help="运行时（默认取服务 DEFAULT_RUNTIME）",
    )
    p_tasks_run.add_argument("--system-prompt", default="")
    p_tasks_run.add_argument("--workspace", default="")
    p_tasks_run.add_argument("--project", default="")
    p_tasks_run.add_argument("--timeout", type=int, default=None)
    p_tasks_run.add_argument("--session", default=None, help="恢复 session_id")
    p_tasks_run.add_argument(
        "--node",
        default=None,
        help="派到设备：auto 或 macmin1/macmin2/raspberry/macpro",
    )
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

    # squads
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

    # skills
    p_skills = sub.add_parser("skills", help="技能目录")
    p_skills.set_defaults(func=cmd_skills)

    # autopilots
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

    # workspaces / projects
    p_ws = sub.add_parser("workspaces", help="工作区")
    p_ws.set_defaults(func=cmd_workspaces)
    p_proj = sub.add_parser("projects", help="项目")
    p_proj.add_argument("--workspace", default=None)
    p_proj.set_defaults(func=cmd_projects)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)
    try:
        return args.func(args)
    except ApiError as e:
        logger.error("API error: %s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except TimeoutError as e:
        logger.error("%s", e)
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
