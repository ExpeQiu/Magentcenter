"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { KanbanBoard, KanbanTask, SwarmGraph } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { SwarmGraphView } from "@/components/kanban/swarm-graph";

export function KanbanPage() {
  const [boards, setBoards] = useState<KanbanBoard[]>([]);
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showSwarm, setShowSwarm] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [assignee, setAssignee] = useState("default");
  const [swarmGoal, setSwarmGoal] = useState("");
  const [swarmWorkers, setSwarmWorkers] = useState(
    "default:Research\ndefault:Draft"
  );
  const [swarmVerifier, setSwarmVerifier] = useState("default");
  const [swarmSynth, setSwarmSynth] = useState("default");
  const [swarm, setSwarm] = useState<SwarmGraph | null>(null);
  const [busy, setBusy] = useState("");
  const router = useRouter();
  const wp = useWorkspacePaths();

  const load = () =>
    Promise.all([api.kanbanBoards(), api.kanbanTasks()])
      .then(([b, t]) => {
        setBoards(b);
        setTasks(t);
      })
      .catch(console.error)
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setBusy("create");
    try {
      await api.createKanbanTask({
        title,
        body,
        assignee: assignee || "default",
        triage: true,
      });
      setShowForm(false);
      setTitle("");
      setBody("");
      await load();
    } catch {
      alert("创建 Kanban 任务失败");
    } finally {
      setBusy("");
    }
  };

  const createSwarm = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!swarmGoal.trim()) return;
    const workers = swarmWorkers
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    if (workers.length === 0) {
      alert("至少一行 worker（PROFILE:TITLE）");
      return;
    }
    setBusy("swarm");
    try {
      const graph = await api.createSwarm({
        goal: swarmGoal.trim(),
        workers,
        verifier: swarmVerifier || "default",
        synthesizer: swarmSynth || "default",
      });
      setSwarm(graph);
      setShowSwarm(false);
      await load();
    } catch (err) {
      console.error(err);
      alert("创建 Swarm 失败");
    } finally {
      setBusy("");
    }
  };

  const run = async (id: string) => {
    setBusy(`run:${id}`);
    try {
      const task = await api.runKanbanTask(id);
      router.push(wp.taskDetail(task.id));
    } catch {
      alert("映射执行失败");
    } finally {
      setBusy("");
    }
  };

  const loadSwarm = async (rootId: string) => {
    setBusy(`swarm:${rootId}`);
    try {
      const graph = await api.getSwarm(rootId);
      setSwarm(graph);
    } catch {
      alert("未找到 Swarm 拓扑（需为 swarm root）");
    } finally {
      setBusy("");
    }
  };

  const current = boards.find((b) => b.current) || boards[0];

  return (
    <>
      <PageHeader
        title="Hermes Kanban"
        description={
          current
            ? `看板 ${current.name} (${current.slug}) · ${tasks.length} 条任务`
            : "Hermes 多 profile 协作看板"
        }
        actions={
          <div className="flex gap-2">
            <button
              onClick={() => {
                setShowSwarm(!showSwarm);
                setShowForm(false);
              }}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              + Swarm
            </button>
            <button
              onClick={() => {
                setShowForm(!showForm);
                setShowSwarm(false);
              }}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
            >
              + 新建
            </button>
          </div>
        }
      />

      {showSwarm && (
        <form
          onSubmit={createSwarm}
          className="mb-6 space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
        >
          <p className="text-xs text-slate-500">
            创建 Swarm 图：并行 workers → verifier → synthesizer
          </p>
          <input
            value={swarmGoal}
            onChange={(e) => setSwarmGoal(e.target.value)}
            placeholder="Swarm 目标 / 最终产出"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            required
          />
          <textarea
            value={swarmWorkers}
            onChange={(e) => setSwarmWorkers(e.target.value)}
            placeholder={"每行一个 worker：PROFILE:TITLE[:skill]\n例如 default:Research"}
            rows={3}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 font-mono text-sm"
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              value={swarmVerifier}
              onChange={(e) => setSwarmVerifier(e.target.value)}
              placeholder="verifier profile"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            />
            <input
              value={swarmSynth}
              onChange={(e) => setSwarmSynth(e.target.value)}
              placeholder="synthesizer profile"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={!!busy}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm disabled:opacity-50"
          >
            创建 Swarm
          </button>
        </form>
      )}

      {showForm && (
        <form
          onSubmit={create}
          className="mb-6 space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
        >
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="任务标题"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="说明（可选）"
            rows={2}
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <input
            value={assignee}
            onChange={(e) => setAssignee(e.target.value)}
            placeholder="assignee profile（默认 default）"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={!!busy}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm disabled:opacity-50"
          >
            创建到 triage
          </button>
        </form>
      )}

      {swarm && (
        <div className="mb-6">
          <SwarmGraphView graph={swarm} />
        </div>
      )}

      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : tasks.length === 0 ? (
        <EmptyState title="暂无 Kanban 任务" description="创建任务或在 Hermes CLI 中添加" />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
                <th className="px-4 py-3">ID</th>
                <th className="px-4 py-3">标题</th>
                <th className="px-4 py-3">Assignee</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">优先级</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id} className="border-t border-slate-800/80">
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">{t.id}</td>
                  <td className="px-4 py-3">
                    <p>{t.title}</p>
                    {t.body && (
                      <p className="mt-0.5 line-clamp-1 text-xs text-slate-500">{t.body}</p>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{t.assignee || "—"}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status || "todo"} />
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">{t.priority}</td>
                  <td className="px-4 py-3 space-x-2 whitespace-nowrap">
                    {t.title?.startsWith("Swarm:") && (
                      <button
                        onClick={() => loadSwarm(t.id)}
                        disabled={busy === `swarm:${t.id}`}
                        className="text-xs text-sky-400 hover:underline disabled:opacity-50"
                      >
                        查看图
                      </button>
                    )}
                    <button
                      onClick={() => run(t.id)}
                      disabled={busy === `run:${t.id}`}
                      className="text-xs text-indigo-400 hover:underline disabled:opacity-50"
                    >
                      用 Hermes 执行
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
