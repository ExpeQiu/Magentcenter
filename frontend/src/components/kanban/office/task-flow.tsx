"use client";

import { useState } from "react";
import type { KanbanTask } from "@/lib/types";
import {
  columnOf,
  flowLabel,
  progressOf,
  type OfficeActor,
} from "@/components/kanban/office/office-model";

interface OfficeTaskFlowProps {
  tasks: KanbanTask[];
  actors: OfficeActor[];
  statusOverride: Record<string, string>;
  focusId: string | null;
  busy: string;
  onFocus: (task: KanbanTask) => void;
  onRun: (id: string) => void;
  onCreate: (input: { title: string; body: string; assignee: string }) => Promise<void>;
}

const BAR: Record<string, string> = {
  running: "bg-indigo-400",
  todo: "bg-sky-400",
  triage: "bg-amber-400",
  done: "bg-emerald-400",
  other: "bg-slate-500",
};

export function OfficeTaskFlow({
  tasks,
  actors,
  statusOverride,
  focusId,
  busy,
  onFocus,
  onRun,
  onCreate,
}: OfficeTaskFlowProps) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [assignee, setAssignee] = useState(actors[0]?.id || "");
  const [error, setError] = useState("");

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    setError("");
    try {
      await onCreate({
        title: title.trim(),
        body: body.trim(),
        assignee: assignee || actors[0]?.id || "default",
      });
      setTitle("");
      setBody("");
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  };

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-950/40">
      <div className="flex items-center justify-between px-4 py-2.5">
        <h2 className="text-sm font-medium">当前任务流</h2>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500">{tasks.length}</span>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="rounded-lg bg-indigo-600 px-2.5 py-1 text-xs hover:bg-indigo-500"
          >
            + 任务
          </button>
        </div>
      </div>
      {open && (
        <form onSubmit={submit} className="space-y-2 border-t border-slate-800 px-4 py-3">
          <input
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="任务标题"
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm"
          />
          <textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            placeholder="说明，可选"
            rows={2}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm"
          />
          <select
            value={assignee || actors[0]?.id || ""}
            onChange={(event) => setAssignee(event.target.value)}
            className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm"
          >
            {actors.length === 0 && <option value="default">default</option>}
            {actors.map((actor) => (
              <option key={actor.id} value={actor.id}>
                {actor.name}
              </option>
            ))}
          </select>
          {error && <p className="text-xs text-rose-300">{error}</p>}
          <button
            type="submit"
            disabled={busy === "create"}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-xs disabled:opacity-50"
          >
            放进分拣
          </button>
        </form>
      )}
      <div className="max-h-[280px] space-y-2 overflow-y-auto px-3 pb-3">
        {tasks.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-800 px-3 py-6 text-center text-xs text-slate-500">
            还没有任务。在左侧和办公室说一句，或新建一条。
          </p>
        ) : (
          tasks.map((task) => {
            const status = statusOverride[task.id] ?? task.status;
            const column = columnOf(status);
            const progress = progressOf(status);
            const owner =
              actors.find((actor) =>
                actor.keys.includes((task.assignee || "").trim().toLowerCase())
              )?.name || task.assignee || "未分配";
            return (
              <article
                key={task.id}
                className={`rounded-xl border px-3 py-2.5 ${
                  focusId === task.id
                    ? "border-indigo-400 bg-indigo-950/30"
                    : "border-slate-800 bg-slate-900/60"
                }`}
              >
                <button type="button" onClick={() => onFocus(task)} className="w-full text-left">
                  <div className="flex items-start justify-between gap-2">
                    <p className="line-clamp-2 text-sm text-slate-100">{task.title}</p>
                    <span className="shrink-0 text-[10px] text-slate-400">{flowLabel(status)}</span>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500">{owner}</p>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className={`h-full rounded-full ${BAR[column] || BAR.other}`}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="mt-1 text-right text-[10px] text-slate-500">{progress}%</p>
                </button>
                <button
                  type="button"
                  onClick={() => onRun(task.id)}
                  disabled={busy === `run:${task.id}`}
                  className="text-[10px] text-indigo-300 hover:underline disabled:opacity-50"
                >
                  用 Hermes 执行
                </button>
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
