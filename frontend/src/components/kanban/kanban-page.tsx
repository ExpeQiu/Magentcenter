"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AgentInfo, KanbanBoard, KanbanTask, SquadInfo, SwarmGraph } from "@/lib/types";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { SwarmGraphView } from "@/components/kanban/swarm-graph";
import { OfficeFloor } from "@/components/kanban/office/office-floor";
import { OfficeTaskFlow } from "@/components/kanban/office/task-flow";
import { OfficeWhiteboard } from "@/components/kanban/office/whiteboard";
import { officeLog } from "@/components/kanban/office/office-log";
import { useOfficeDirector } from "@/components/kanban/office/use-office-director";
import {
  beatsFromEvent,
  buildOfficeDemo,
  columnOf,
  layoutOffice,
  parseDriveScript,
  resolveAgentId,
  rosterFrom,
  withTaskPoses,
} from "@/components/kanban/office/office-model";

export function KanbanPage() {
  const [boards, setBoards] = useState<KanbanBoard[]>([]);
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [squads, setSquads] = useState<SquadInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [focusGroupId, setFocusGroupId] = useState<string | null>(null);
  const [goal, setGoal] = useState("");
  const [chat, setChat] = useState("");
  const [drive, setDrive] = useState("");
  const [driveTouched, setDriveTouched] = useState(false);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [asking, setAsking] = useState(false);
  const [swarm, setSwarm] = useState<SwarmGraph | null>(null);
  const [swarmWorkers, setSwarmWorkers] = useState("");
  const [swarmVerifier, setSwarmVerifier] = useState("default");
  const [swarmSynth, setSwarmSynth] = useState("default");
  const router = useRouter();
  const wp = useWorkspacePaths();
  const { slug } = useWorkspace();
  const director = useOfficeDirector();
  const clientIdRef = useRef(`office-${Math.random().toString(36).slice(2, 10)}`);
  const cursorRef = useRef(0);
  const drivePrimedRef = useRef(false);
  const driveFailRef = useRef(false);
  const roster = useMemo(() => rosterFrom(agents), [agents]);
  const rosterRef = useRef(roster);
  rosterRef.current = roster;
  const playRef = useRef(director.play);
  playRef.current = director.play;
  const addNoteRef = useRef(director.addNote);
  addNoteRef.current = director.addNote;

  const office = useMemo(() => layoutOffice(agents, squads), [agents, squads]);
  const officeKey = office.actors.map((agent) => `${agent.id}@${agent.groupId}`).join("|");
  const taskKey = tasks.map((task) => `${task.id}:${task.status}:${task.assignee}`).join("|");

  useEffect(() => {
    let stop = false;
    const load = (silent = false) =>
      Promise.all([
        api.kanbanBoards(),
        api.kanbanTasks(),
        api.agents(),
        api.squads().catch(() => [] as SquadInfo[]),
      ])
        .then(([nextBoards, nextTasks, nextAgents, nextSquads]) => {
          if (stop) return;
          setBoards(nextBoards);
          setTasks(nextTasks);
          setAgents(nextAgents);
          setSquads(nextSquads);
          officeLog("load", {
            boards: nextBoards.length,
            tasks: nextTasks.length,
            agents: nextAgents.length,
            squads: nextSquads.length,
            silent,
          });
        })
        .catch((err: unknown) => {
          officeLog("load_fail", {
            message: err instanceof Error ? err.message : "load failed",
          });
        })
        .finally(() => {
          if (!silent) setLoading(false);
        });
    void load();
    const timer = setInterval(() => void load(true), 8000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    director.syncDesks(
      withTaskPoses(office.actors, tasks, director.statusOverride)
    );
    officeLog("layout_groups", {
      agents: office.actors.length,
      groups: office.groups.length,
    });
  }, [officeKey, taskKey, director.epoch, director.syncDesks, director.statusOverride, office, tasks]);

  useEffect(() => {
    if (driveTouched || office.actors.length === 0) return;
    const first = office.actors[0];
    const second = office.actors[1];
    const lines = [`agent ${first.id} board 把这轮目标写到白板上`];
    if (second) lines.push(`agent ${second.id} visit ${first.id} 我过来对齐一下`);
    lines.push("board 协作先对齐，再回工位");
    setDrive(lines.join("\n"));
  }, [officeKey, driveTouched, office.actors]);

  useEffect(() => {
    let stop = false;
    const tick = async () => {
      try {
        const res = await api.officeDriveSince(cursorRef.current);
        if (stop) return;
        driveFailRef.current = false;
        if (!drivePrimedRef.current) {
          drivePrimedRef.current = true;
          cursorRef.current = res.latest || 0;
          officeLog("drive_prime", { latest: cursorRef.current });
          return;
        }
        if (res.events.length === 0) {
          cursorRef.current = Math.max(cursorRef.current, res.latest || 0);
          return;
        }
        cursorRef.current = res.events[res.events.length - 1].id;
        for (const event of res.events) {
          if (event.source === clientIdRef.current) continue;
          const parsed = beatsFromEvent(event, rosterRef.current);
          parsed.errors.forEach((message) => addNoteRef.current("驱动", message));
          if (parsed.beats.length === 0) continue;
          officeLog("remote_drive", {
            event_id: event.id,
            source: event.source,
            beats: parsed.beats.length,
          });
          playRef.current(parsed.beats, `remote:${event.source}`);
        }
      } catch (err) {
        if (driveFailRef.current) return;
        driveFailRef.current = true;
        officeLog("remote_drive_fail", {
          message: err instanceof Error ? err.message : "drive poll failed",
        });
      }
    };
    const timer = setInterval(() => void tick(), 2500);
    void tick();
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, []);

  const publish = (script: string, beats: { agent?: string; to?: string; pose?: string; say?: string; board?: string; task_id?: string; task_status?: string; hold_ms?: number }[]) => {
    void api
      .officeDrivePush({
        source: clientIdRef.current,
        script,
        beats,
      })
      .catch((err: unknown) => {
        officeLog("drive_push_fail", {
          message: err instanceof Error ? err.message : "push failed",
        });
      });
  };

  const demo = () => {
    const beats = buildOfficeDemo(director.actors, goal, tasks);
    if (beats.length === 0) {
      director.addNote("办公室", "没有在岗 Agent，没法演示");
      return;
    }
    director.play(beats, "demo");
    publish("", beatsToPayload(beats));
  };

  const talk = () => {
    const text = chat.trim();
    if (!text || director.playing) return;
    setGoal(text);
    setChat("");
    officeLog("chat", { text: text.slice(0, 120) });
    director.addNote("你", text);
    const beats = buildOfficeDemo(director.actors, text, tasks);
    if (beats.length === 0) {
      director.addNote("办公室", "没有在岗 Agent，没法回应");
      return;
    }
    director.play(beats, "chat");
    publish("", beatsToPayload(beats));
  };

  const summon = (id: string) => {
    const actor = director.actors.find((item) => item.id === id);
    if (!actor) return;
    setSelectedId(id);
    director.play(
      [
        { agentId: id, to: "board", pose: "walking", holdMs: 1000 },
        {
          agentId: id,
          to: "board",
          pose: "talking",
          say: "我到白板了",
          board: `${actor.name}：我到白板了`,
          holdMs: 1600,
        },
        { agentId: id, to: "desk", pose: "idle", holdMs: 700 },
      ],
      "summon"
    );
  };

  const ask = async () => {
    const text = (chat.trim() || goal.trim());
    if (!text) {
      director.addNote("办公室", "先说这轮要做成什么");
      return;
    }
    setGoal(text);
    setChat("");
    director.addNote("你", text);
    const beats = buildOfficeDemo(director.actors, text, tasks);
    if (beats.length) {
      director.play(beats, "ask");
      publish("", beatsToPayload(beats));
    }
    setAsking(true);
    try {
      const turn = await api.superAiTurn({ text, workspace_slug: slug });
      officeLog("super_ai", {
        run_id: turn.run_id,
        intent: turn.intent,
        service: turn.service,
      });
      director.addNote("超级AI", turn.reply);
      const lead = director.actors[0];
      if (lead) {
        const say = turn.reply.replace(/\s+/g, " ").trim().slice(0, 42);
        director.play(
          [
            { agentId: lead.id, to: "board", pose: "walking", holdMs: 1000 },
            {
              agentId: lead.id,
              to: "board",
              pose: "talking",
              say,
              holdMs: 2200,
            },
            { agentId: lead.id, to: "desk", pose: "idle", holdMs: 800 },
          ],
          "super-ai-reply"
        );
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "超级AI没有接上";
      officeLog("super_ai_fail", { message });
      director.addNote("超级AI", message);
    } finally {
      setAsking(false);
    }
  };

  const playDrive = () => {
    const parsed = parseDriveScript(drive, roster);
    parsed.errors.forEach((message) => director.addNote("驱动", message));
    if (parsed.beats.length === 0) return;
    director.play(parsed.beats, "script");
    publish(drive, []);
  };

  const focusTask = (task: KanbanTask) => {
    setFocusId(task.id);
    const agentId = resolveAgentId(task.assignee || "", roster);
    const actor = director.actors.find((item) => item.id === agentId);
    if (!actor) {
      director.addNote("任务流", `「${task.title}」的负责人不在工位上`);
      officeLog("focus_miss", { task_id: task.id, assignee: task.assignee || "" });
      return;
    }
    setSelectedId(actor.id);
    director.play(
      [
        { agentId: actor.id, to: "board", pose: "walking", holdMs: 1100 },
        {
          agentId: actor.id,
          to: "board",
          pose: "talking",
          say: task.title.slice(0, 32),
          board: `${actor.name}：${task.title}`,
          holdMs: 1600,
        },
        { agentId: actor.id, to: "desk", pose: "idle", holdMs: 700 },
      ],
      "focus-task"
    );
  };

  const createTask = async (input: { title: string; body: string; assignee: string }) => {
    setBusy("create");
    try {
      const task = await api.createKanbanTask({ ...input, triage: true });
      officeLog("task_create", { task_id: task.id, assignee: input.assignee });
      director.addNote("任务流", `${input.assignee} 接到「${input.title}」`);
      const next = await api.kanbanTasks();
      setTasks(next);
    } finally {
      setBusy("");
    }
  };

  const run = async (id: string) => {
    setBusy(`run:${id}`);
    try {
      const task = await api.runKanbanTask(id);
      officeLog("task_run", { kanban_id: id, task_id: task.id });
      router.push(wp.taskDetail(task.id));
    } catch (err) {
      director.addNote("任务流", err instanceof Error ? err.message : "执行失败");
    } finally {
      setBusy("");
    }
  };

  const createSwarm = async (event: React.FormEvent) => {
    event.preventDefault();
    const text = goal.trim();
    if (!text) return;
    const workers = swarmWorkers
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    if (workers.length === 0) return;
    setBusy("swarm");
    try {
      const graph = await api.createSwarm({
        goal: text,
        workers,
        verifier: swarmVerifier || "default",
        synthesizer: swarmSynth || "default",
      });
      setSwarm(graph);
      director.addNote("Swarm", `已写入 ${graph.root_id}：${graph.goal}`);
      officeLog("swarm_create", { root_id: graph.root_id, workers: workers.length });
      demo();
    } catch (err) {
      director.addNote("Swarm", err instanceof Error ? err.message : "创建失败");
    } finally {
      setBusy("");
    }
  };

  const current = boards.find((board) => board.current) || boards[0];
  const boardName =
    current?.name && !/not found/i.test(current.name) ? current.name : "";
  const preview = director.notes[0]?.text || "";
  const runningCount = tasks.filter(
    (task) => columnOf(director.statusOverride[task.id] ?? task.status) === "running"
  ).length;
  const doneCount = tasks.filter(
    (task) => columnOf(director.statusOverride[task.id] ?? task.status) === "done"
  ).length;
  const pendingCount = Math.max(tasks.length - runningCount - doneCount, 0);
  const stats = [
    { label: "进行中", value: String(runningCount), hint: "当前任务" },
    { label: "已完成", value: String(doneCount), hint: "看板完成" },
    { label: "待处理", value: String(pendingCount), hint: "还没开始" },
    { label: "AI 员工", value: String(agents.length), hint: "按小队分组" },
  ];

  return (
    <>
      <PageHeader
        title="数字办公室"
        description={
          boardName
            ? `${boardName} · ${director.actors.length} 个工位 · ${tasks.length} 条任务`
            : `${director.actors.length} 个工位 · ${tasks.length} 条任务`
        }
        actions={
          <button
            type="button"
            onClick={() => {
              director.clearOverrides();
              director.stop();
            }}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
          >
            回工位
          </button>
        }
      />

      {loading ? (
        <p className="text-slate-500">办公室正在开门…</p>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {stats.map((item) => (
              <div key={item.label} className="rounded-xl border border-slate-800 bg-slate-950/50 px-3 py-2.5">
                <p className="text-[11px] text-slate-500">{item.label}</p>
                <p className="mt-1 text-2xl font-semibold tracking-tight">{item.value}</p>
                <p className="text-[11px] text-slate-500">{item.hint}</p>
              </div>
            ))}
          </div>

          <div className="mb-3 flex items-center gap-2">
            <div className="office-duty flex min-w-0 flex-1 gap-2 overflow-x-auto">
              <button
                type="button"
                onClick={() => setFocusGroupId(null)}
                className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                  focusGroupId
                    ? "border-slate-700 text-slate-400"
                    : "border-indigo-400 bg-indigo-950/50 text-indigo-100"
                }`}
              >
                全部 {agents.length}
              </button>
              {office.groups.map((group) => {
                const on = focusGroupId === group.id;
                return (
                  <button
                    key={group.id}
                    type="button"
                    onClick={() => setFocusGroupId(on ? null : group.id)}
                    className={`flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
                      on
                        ? "border-indigo-400 bg-indigo-950/50 text-indigo-100"
                        : "border-slate-700 text-slate-300"
                    }`}
                  >
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: group.color }} />
                    {group.name}
                    <span className="text-slate-500">{group.count}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="grid items-stretch gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.85fr)]">
            <OfficeFloor
              actors={director.actors}
              groups={office.groups}
              tasks={tasks}
              selectedId={selectedId}
              focusGroupId={focusGroupId}
              preview={preview}
              playing={director.playing}
              asking={asking}
              chat={chat}
              onChat={setChat}
              onSend={talk}
              onAsk={() => void ask()}
              onSelect={setSelectedId}
              onFocusGroup={setFocusGroupId}
              onStop={director.stop}
              onSummon={summon}
            />
            <div className="flex min-h-0 flex-col gap-4">
              <OfficeTaskFlow
                tasks={tasks}
                actors={director.actors}
                statusOverride={director.statusOverride}
                focusId={focusId}
                busy={busy}
                onFocus={focusTask}
                onRun={run}
                onCreate={createTask}
              />
              <OfficeWhiteboard
                notes={director.notes}
                drive={drive}
                playing={director.playing}
                onDrive={(value) => {
                  setDriveTouched(true);
                  setDrive(value);
                }}
                onPlayDrive={playDrive}
              />
            </div>
          </div>

          <details className="mt-4 rounded-xl border border-slate-800 px-4 py-3 text-sm">
            <summary className="cursor-pointer text-slate-300">落到 Hermes Swarm</summary>
            <form onSubmit={createSwarm} className="mt-3 space-y-2">
              <textarea
                value={swarmWorkers}
                onChange={(event) => setSwarmWorkers(event.target.value)}
                placeholder={"每行 PROFILE:标题\n" + office.actors.slice(0, 2).map((agent) => `${agent.id}:协作`).join("\n")}
                rows={3}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs"
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={swarmVerifier}
                  onChange={(event) => setSwarmVerifier(event.target.value)}
                  placeholder="verifier"
                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
                />
                <input
                  value={swarmSynth}
                  onChange={(event) => setSwarmSynth(event.target.value)}
                  placeholder="synthesizer"
                  className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={busy === "swarm"}
                className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs disabled:opacity-50"
              >
                写入并演示
              </button>
            </form>
            {swarm && (
              <div className="mt-3">
                <SwarmGraphView graph={swarm} />
              </div>
            )}
          </details>
        </>
      )}
    </>
  );
}

function beatsToPayload(
  beats: {
    agentId?: string;
    to?: string;
    pose?: string;
    say?: string;
    board?: string;
    taskId?: string;
    taskStatus?: string;
    holdMs?: number;
  }[]
) {
  return beats.map((beat) => ({
    agent: beat.agentId || "",
    to: beat.to || "",
    pose: beat.pose || "",
    say: beat.say || "",
    board: beat.board || "",
    task_id: beat.taskId || "",
    task_status: beat.taskStatus || "",
    hold_ms: beat.holdMs || 1200,
  }));
}
