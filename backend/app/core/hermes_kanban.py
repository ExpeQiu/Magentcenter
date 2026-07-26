"""Hermes Kanban 只读聚合 + 创建任务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings

logger = logging.getLogger(__name__)


class KanbanBoard(BaseModel):
    slug: str
    name: str = ""
    current: bool = False
    counts: str = ""


class KanbanTask(BaseModel):
    id: str
    title: str
    body: str = ""
    assignee: str = ""
    status: str = ""
    priority: int = 0
    workspace_kind: str = ""
    created_at: int | None = None
    skills: list[str] = Field(default_factory=list)
    runtime: str = "hermes"


class SwarmNode(BaseModel):
    id: str
    role: str  # root | worker | verifier | synthesizer
    title: str = ""
    assignee: str = ""
    status: str = ""


class SwarmEdge(BaseModel):
    from_id: str
    to_id: str


class SwarmGraph(BaseModel):
    root_id: str
    goal: str = ""
    worker_ids: list[str] = Field(default_factory=list)
    verifier_id: str = ""
    synthesizer_id: str = ""
    nodes: list[SwarmNode] = Field(default_factory=list)
    edges: list[SwarmEdge] = Field(default_factory=list)


class HermesKanban:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.executable = settings.hermes_executable

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.settings.hermes_home:
            env["HERMES_HOME"] = os.path.expanduser(self.settings.hermes_home)
        return env

    async def _run(self, *args: str, timeout: float = 30) -> tuple[int, str, str]:
        if not shutil.which(self.executable):
            return 127, "", "hermes not found"
        logger.info("hermes kanban cmd: %s", " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def list_boards(self) -> list[KanbanBoard]:
        if self.settings.ai_mock_mode:
            return [KanbanBoard(slug="default", name="Default", current=True, counts="(mock)")]
        if "hermes" not in self.settings.enabled_runtimes():
            return []
        code, out, err = await self._run("kanban", "boards", "list", timeout=30)
        text = out or err
        boards: list[KanbanBoard] = []
        for line in text.splitlines():
            line = line.rstrip()
            if not line or "SLUG" in line or line.startswith("Current"):
                continue
            current = line.lstrip().startswith("●")
            raw = line.replace("●", " ").strip()
            parts = raw.split()
            if len(parts) < 1:
                continue
            slug = parts[0]
            # NAME 可能含空格：取中间段
            counts = parts[-1] if parts[-1].startswith("(") else ""
            name_parts = parts[1:-1] if counts else parts[1:]
            name = " ".join(name_parts) if name_parts else slug
            boards.append(
                KanbanBoard(slug=slug, name=name, current=current, counts=counts)
            )
        logger.info("kanban boards count=%d exit=%s", len(boards), code)
        return boards or [KanbanBoard(slug="default", name="Default", current=True)]

    def _parse_tasks(self, raw: str) -> list[KanbanTask]:
        raw = raw.strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("kanban list json parse failed")
            return []
        items = data if isinstance(data, list) else data.get("tasks") or []
        tasks: list[KanbanTask] = []
        for t in items:
            if not isinstance(t, dict):
                continue
            tasks.append(
                KanbanTask(
                    id=str(t.get("id") or ""),
                    title=str(t.get("title") or ""),
                    body=str(t.get("body") or ""),
                    assignee=str(t.get("assignee") or ""),
                    status=str(t.get("status") or ""),
                    priority=int(t.get("priority") or 0),
                    workspace_kind=str(t.get("workspace_kind") or ""),
                    created_at=t.get("created_at"),
                    skills=list(t.get("skills") or []),
                    runtime="hermes",
                )
            )
        return tasks

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        assignee: str | None = None,
        archived: bool = False,
    ) -> list[KanbanTask]:
        if self.settings.ai_mock_mode:
            return [
                KanbanTask(
                    id="t_mock1",
                    title="【Mock】Hermes Kanban 任务",
                    body="mock kanban body",
                    assignee="default",
                    status="todo",
                    priority=10,
                ),
                KanbanTask(
                    id="t_mock2",
                    title="【Mock】运行中任务",
                    assignee="default",
                    status="running",
                    priority=5,
                ),
            ]
        if "hermes" not in self.settings.enabled_runtimes():
            return []
        args = ["kanban", "list", "--json"]
        if status:
            args.extend(["--status", status])
        if assignee:
            args.extend(["--assignee", assignee])
        if archived:
            args.append("--archived")
        code, out, err = await self._run(*args, timeout=30)
        tasks = self._parse_tasks(out or err)
        logger.info("kanban tasks count=%d exit=%s", len(tasks), code)
        return tasks

    async def create_task(
        self,
        title: str,
        *,
        body: str = "",
        assignee: str = "default",
        priority: int = 0,
        triage: bool = False,
    ) -> KanbanTask:
        if self.settings.ai_mock_mode:
            return KanbanTask(
                id=f"t_mock_{abs(hash(title)) % 100000:05d}",
                title=title,
                body=body,
                assignee=assignee or "default",
                status="triage" if triage else "todo",
                priority=priority,
            )
        args = ["kanban", "create", title, "--json", "--assignee", assignee or "default"]
        if body:
            args.extend(["--body", body])
        if priority:
            args.extend(["--priority", str(priority)])
        if triage:
            args.append("--triage")
        code, out, err = await self._run(*args, timeout=30)
        text = (out or err).strip()
        if code != 0:
            raise ValueError(f"hermes kanban create failed: {err or out}")
        try:
            data = json.loads(text.splitlines()[-1])
        except json.JSONDecodeError as e:
            raise ValueError(f"hermes kanban create bad json: {text[:200]}") from e
        logger.info("kanban created id=%s title=%s", data.get("id"), title)
        return KanbanTask(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or title),
            body=str(data.get("body") or body),
            assignee=str(data.get("assignee") or assignee),
            status=str(data.get("status") or ""),
            priority=int(data.get("priority") or priority),
            workspace_kind=str(data.get("workspace_kind") or ""),
            created_at=data.get("created_at"),
            skills=list(data.get("skills") or []),
        )

    async def get_task(self, task_id: str) -> KanbanTask | None:
        tasks = await self.list_tasks(archived=True)
        for t in tasks:
            if t.id == task_id:
                return t
        # list without archived
        for t in await self.list_tasks():
            if t.id == task_id:
                return t
        return None

    async def show_task(self, task_id: str) -> dict[str, Any] | None:
        """hermes kanban show --json（含 parents/children/comments）。"""
        if self.settings.ai_mock_mode:
            if task_id.startswith("t_mock_swarm"):
                return {
                    "task": {
                        "id": task_id,
                        "title": "Swarm: mock goal",
                        "assignee": "default",
                        "status": "done",
                    },
                    "parents": [],
                    "children": ["t_mock_w1", "t_mock_w2"],
                    "comments": [
                        {
                            "body": (
                                '[swarm:blackboard] {"key": "topology", "value": '
                                '{"goal": "mock goal", "root_id": "t_mock_swarm_root", '
                                '"worker_ids": ["t_mock_w1", "t_mock_w2"], '
                                '"verifier_id": "t_mock_v", "synthesizer_id": "t_mock_s"}}'
                            )
                        }
                    ],
                }
            return None
        code, out, err = await self._run(
            "kanban", "show", task_id, "--json", timeout=30
        )
        text = (out or err).strip()
        if code != 0 or not text:
            logger.warning("kanban show failed id=%s exit=%s", task_id, code)
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("kanban show bad json id=%s", task_id)
            return None

    def _parse_swarm_topology(self, show: dict[str, Any]) -> dict[str, Any] | None:
        for c in show.get("comments") or []:
            body = str(c.get("body") or "")
            marker = "[swarm:blackboard]"
            if marker not in body:
                continue
            raw = body.split(marker, 1)[-1].strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            value = payload.get("value") if isinstance(payload, dict) else None
            if isinstance(value, dict) and value.get("root_id"):
                return value
        return None

    def _build_swarm_graph(
        self,
        *,
        root_id: str,
        goal: str,
        worker_ids: list[str],
        verifier_id: str,
        synthesizer_id: str,
        title_map: dict[str, tuple[str, str, str]] | None = None,
    ) -> SwarmGraph:
        """title_map: id -> (title, assignee, status)"""
        tm = title_map or {}

        def node(tid: str, role: str) -> SwarmNode:
            title, assignee, status = tm.get(tid, ("", "", ""))
            return SwarmNode(
                id=tid, role=role, title=title, assignee=assignee, status=status
            )

        nodes = [node(root_id, "root")]
        edges: list[SwarmEdge] = []
        for wid in worker_ids:
            nodes.append(node(wid, "worker"))
            edges.append(SwarmEdge(from_id=root_id, to_id=wid))
            if verifier_id:
                edges.append(SwarmEdge(from_id=wid, to_id=verifier_id))
        if verifier_id:
            nodes.append(node(verifier_id, "verifier"))
            if synthesizer_id:
                edges.append(SwarmEdge(from_id=verifier_id, to_id=synthesizer_id))
        if synthesizer_id:
            nodes.append(node(synthesizer_id, "synthesizer"))
        return SwarmGraph(
            root_id=root_id,
            goal=goal,
            worker_ids=worker_ids,
            verifier_id=verifier_id,
            synthesizer_id=synthesizer_id,
            nodes=nodes,
            edges=edges,
        )

    async def _enrich_titles(self, ids: list[str]) -> dict[str, tuple[str, str, str]]:
        out: dict[str, tuple[str, str, str]] = {}
        for tid in ids:
            if not tid:
                continue
            show = await self.show_task(tid)
            if not show:
                continue
            task = show.get("task") or {}
            out[tid] = (
                str(task.get("title") or ""),
                str(task.get("assignee") or ""),
                str(task.get("status") or ""),
            )
        return out

    async def create_swarm(
        self,
        goal: str,
        *,
        workers: list[str],
        verifier: str = "default",
        synthesizer: str = "default",
        priority: int = 0,
        created_by: str = "default",
    ) -> SwarmGraph:
        """创建 Swarm 图：parallel workers → verifier → synthesizer。

        workers 格式与 CLI 一致：PROFILE:TITLE[:SKILL,SKILL]
        """
        if not goal.strip():
            raise ValueError("goal required")
        if not workers:
            raise ValueError("at least one worker required")
        if not verifier or not synthesizer:
            raise ValueError("verifier and synthesizer required")

        if self.settings.ai_mock_mode:
            root_id = "t_mock_swarm_root"
            worker_ids = [f"t_mock_w{i+1}" for i in range(len(workers))]
            verifier_id = "t_mock_v"
            synthesizer_id = "t_mock_s"
            title_map: dict[str, tuple[str, str, str]] = {
                root_id: (f"Swarm: {goal}", created_by or "default", "done"),
                verifier_id: ("Verify", verifier, "todo"),
                synthesizer_id: ("Synthesize", synthesizer, "todo"),
            }
            for i, w in enumerate(workers):
                parts = w.split(":")
                profile = parts[0] if parts else "default"
                title = parts[1] if len(parts) > 1 else f"Worker {i+1}"
                title_map[worker_ids[i]] = (title, profile, "todo")
            graph = self._build_swarm_graph(
                root_id=root_id,
                goal=goal,
                worker_ids=worker_ids,
                verifier_id=verifier_id,
                synthesizer_id=synthesizer_id,
                title_map=title_map,
            )
            logger.info("kanban swarm mock root=%s workers=%d", root_id, len(worker_ids))
            return graph

        if "hermes" not in self.settings.enabled_runtimes():
            raise ValueError("hermes runtime not enabled")

        args = ["kanban", "swarm", goal, "--json", "--verifier", verifier, "--synthesizer", synthesizer]
        for w in workers:
            args.extend(["--worker", w])
        if priority:
            args.extend(["--priority", str(priority)])
        if created_by:
            args.extend(["--created-by", created_by])

        code, out, err = await self._run(*args, timeout=60)
        text = (out or err).strip()
        if code != 0:
            raise ValueError(f"hermes kanban swarm failed: {err or out}")
        try:
            data = json.loads(text.splitlines()[-1])
        except json.JSONDecodeError as e:
            raise ValueError(f"hermes kanban swarm bad json: {text[:300]}") from e

        root_id = str(data.get("root_id") or "")
        worker_ids = [str(x) for x in (data.get("worker_ids") or [])]
        verifier_id = str(data.get("verifier_id") or "")
        synthesizer_id = str(data.get("synthesizer_id") or "")
        if not root_id:
            raise ValueError("swarm response missing root_id")

        ids = [root_id, *worker_ids, verifier_id, synthesizer_id]
        title_map = await self._enrich_titles(ids)
        graph = self._build_swarm_graph(
            root_id=root_id,
            goal=goal,
            worker_ids=worker_ids,
            verifier_id=verifier_id,
            synthesizer_id=synthesizer_id,
            title_map=title_map,
        )
        logger.info(
            "kanban swarm created root=%s workers=%d goal=%s",
            root_id,
            len(worker_ids),
            goal[:80],
        )
        return graph

    async def get_swarm(self, root_id: str) -> SwarmGraph | None:
        show = await self.show_task(root_id)
        if not show:
            return None
        topo = self._parse_swarm_topology(show)
        if not topo:
            # 无 blackboard 时用 children 做降级图
            children = [str(c) for c in (show.get("children") or [])]
            if not children:
                return None
            task = show.get("task") or {}
            title_map = await self._enrich_titles([root_id, *children])
            return self._build_swarm_graph(
                root_id=root_id,
                goal=str(task.get("title") or ""),
                worker_ids=children,
                verifier_id="",
                synthesizer_id="",
                title_map=title_map,
            )
        worker_ids = [str(x) for x in (topo.get("worker_ids") or [])]
        verifier_id = str(topo.get("verifier_id") or "")
        synthesizer_id = str(topo.get("synthesizer_id") or "")
        goal = str(topo.get("goal") or "")
        ids = [root_id, *worker_ids, verifier_id, synthesizer_id]
        title_map = await self._enrich_titles(ids)
        return self._build_swarm_graph(
            root_id=root_id,
            goal=goal,
            worker_ids=worker_ids,
            verifier_id=verifier_id,
            synthesizer_id=synthesizer_id,
            title_map=title_map,
        )
