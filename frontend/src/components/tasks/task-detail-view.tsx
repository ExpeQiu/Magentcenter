"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE, api } from "@/lib/api";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import type { StreamEvent, TaskInfo } from "@/lib/types";
import { StatusBadge } from "@/components/ui/status-badge";

export function TaskDetailView() {
  const params = useSearchParams();
  const taskId = (params.get("id") || "").trim();
  const wp = useWorkspacePaths();
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [startDate, setStartDate] = useState("");
  const [dueDate, setDueDate] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!taskId) return;
    api.task(taskId).then((t) => {
      setTask(t);
      setStartDate(t.start_date || "");
      setDueDate(t.due_date || "");
    }).catch(console.error);
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;
    const es = new EventSource(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}/stream`);
    const handler = (type: string) => (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as StreamEvent;
        data.type = type;
        setEvents((prev) => [...prev, data]);
        if (type === "result") api.task(taskId).then(setTask);
      } catch {}
    };
    es.addEventListener("text", handler("text"));
    es.addEventListener("tool_use", handler("tool_use"));
    es.addEventListener("tool_result", handler("tool_result"));
    es.addEventListener("status", handler("status"));
    es.addEventListener("error", handler("error"));
    es.addEventListener("result", handler("result"));
    return () => es.close();
  }, [taskId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  const saveSchedule = async () => {
    const updated = await api.updateTask(taskId, {
      start_date: startDate,
      due_date: dueDate,
    });
    setTask(updated);
  };

  if (!task) {
    return <p className="text-slate-500">加载中…</p>;
  }

  return (
    <div>
      <Link
        href={wp.tasks()}
        className="mb-4 inline-block text-sm text-indigo-400 hover:underline"
      >
        ← 返回任务
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">任务详情</h1>
          <div className="mt-2 flex flex-wrap gap-3 text-sm text-slate-400">
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-300">
              {task.runtime || "openclaw"}
            </span>
            <span>
              Agent: <code className="text-slate-200">{task.agent_id}</code>
            </span>
            {task.node_id && (
              <span>
                设备: <code className="text-slate-200">{task.node_id}</code>
              </span>
            )}
            {task.project_id && (
              <span>
                项目: <code className="text-slate-200">{task.project_id}</code>
              </span>
            )}
            <StatusBadge status={task.status} />
            {task.duration_ms > 0 && <span>{task.duration_ms}ms</span>}
          </div>
        </div>
        <div className="flex gap-2">
          {task.status === "running" && (
            <button
              onClick={() => api.cancelTask(taskId).then(setTask)}
              className="rounded-lg border border-slate-700 px-3 py-1 text-xs hover:bg-slate-800"
            >
              取消
            </button>
          )}
          {(task.status === "failed" || task.status === "cancelled") && (
            <button
              onClick={() =>
                api.retryTask(taskId).then((t) => {
                  window.location.href = wp.taskDetail(t.id);
                })
              }
              className="rounded-lg bg-indigo-600 px-3 py-1 text-xs hover:bg-indigo-500"
            >
              重试
            </button>
          )}
        </div>
      </div>
      <p className="mb-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm">
        {task.prompt}
      </p>
      <section className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <h2 className="mb-2 text-sm font-medium text-slate-400">排期（Gantt）</h2>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-slate-500">开始</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-slate-500">截止</label>
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            />
          </div>
          <button
            onClick={saveSchedule}
            className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm hover:bg-slate-600"
          >
            保存排期
          </button>
        </div>
      </section>
      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium text-slate-400">实时事件</h2>
        <div className="max-h-80 overflow-y-auto rounded-xl border border-slate-800 bg-slate-900/50 p-4 font-mono text-xs">
          {events.map((ev, i) => (
            <div key={i} className="mb-1.5">
              <span className="text-slate-600">[{ev.type}]</span>{" "}
              {ev.content && (
                <span className="whitespace-pre-wrap text-slate-300">
                  {ev.content}
                </span>
              )}
              {ev.tool && (
                <span className="text-purple-400">
                  {ev.tool}
                  {ev.output ? `: ${ev.output}` : ""}
                </span>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </section>
      {task.output && (
        <section className="mb-4">
          <h2 className="mb-2 text-sm font-medium text-slate-400">输出</h2>
          <pre className="whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-sm">
            {task.output}
          </pre>
        </section>
      )}
      {task.error && (
        <section>
          <h2 className="mb-2 text-sm font-medium text-red-400">错误</h2>
          <pre className="whitespace-pre-wrap rounded-xl border border-red-900/40 bg-red-950/20 p-4 text-sm text-red-300">
            {task.error}
          </pre>
        </section>
      )}
    </div>
  );
}
