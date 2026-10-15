"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE, api, ensureSession } from "@/lib/api";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import type { ChainEvent, StreamEvent, TaskInfo } from "@/lib/types";
import { StatusBadge } from "@/components/ui/status-badge";

const CHAIN_LABEL: Record<string, string> = {
  turn: "开口",
  dispatch: "派发",
  call: "调用",
  webhook: "推送",
  claim: "领取",
  finish: "完成",
  translate: "转译",
  deliver: "回传",
  enroll: "登记",
};

export function TaskDetailView() {
  const params = useSearchParams();
  const taskId = (params.get("id") || "").trim();
  const wp = useWorkspacePaths();
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [chain, setChain] = useState<ChainEvent[]>([]);
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
    api.chain(taskId).then(setChain).catch(console.error);
  }, [taskId]);

  useEffect(() => {
    if (!taskId) return;
    let closed = false;
    let es: EventSource | null = null;
    const handler = (type: string) => (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as StreamEvent;
        data.type = type;
        setEvents((prev) => {
          if (data.id && prev.some((item) => item.id === data.id)) return prev;
          return [...prev, data];
        });
        if (type === "result") {
          api.task(taskId).then(setTask);
          api.chain(taskId).then(setChain).catch(() => undefined);
        }
      } catch {}
    };
    ensureSession().then(() => {
      if (closed) return;
      es = new EventSource(`${API_BASE}/api/tasks/${encodeURIComponent(taskId)}/stream`, {
        withCredentials: true,
      });
      es.addEventListener("text", handler("text"));
      es.addEventListener("tool_use", handler("tool_use"));
      es.addEventListener("tool_result", handler("tool_result"));
      es.addEventListener("status", handler("status"));
      es.addEventListener("error", handler("error"));
      es.addEventListener("result", handler("result"));
    });
    return () => {
      closed = true;
      es?.close();
    };
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
            {task.attention_required && (
              <span className="text-amber-300">待核实</span>
            )}
            {task.cancel_phase === "requested" && (
              <span className="text-amber-300">请求取消</span>
            )}
            {task.cancel_phase === "stopping" && (
              <span className="text-amber-300">正在停止</span>
            )}
            {task.owner_center_id && (
              <span>
                中心: <code className="text-slate-200">{task.owner_center_id.slice(0, 8)}</code>
              </span>
            )}
            <span>{task.node_id ? `执行位置: ${task.node_id}` : "执行位置: 本机"}</span>
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
        <h2 className="mb-2 text-sm font-medium text-slate-400">传递链路</h2>
        <ol className="space-y-2">
          {chain.length === 0 ? (
            <li className="text-sm text-slate-500">还没有传递记录。</li>
          ) : (
            chain.map((row) => (
              <li
                key={row.id}
                className="rounded-xl border border-slate-800 bg-slate-900/50 px-4 py-3 text-sm"
              >
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span className="rounded bg-slate-800 px-1.5 py-0.5 text-slate-200">
                    {CHAIN_LABEL[row.kind] || row.kind}
                  </span>
                  {row.actor_id ? <span>从 {row.actor_id}</span> : null}
                  {row.target_id ? <span>到 {row.target_id}</span> : null}
                  {row.status ? <span>{row.status}</span> : null}
                  <span>{row.created_at?.replace("T", " ").slice(0, 19)}</span>
                </div>
                {row.summary ? (
                  <p className="mt-1 whitespace-pre-wrap text-slate-200">{row.summary}</p>
                ) : null}
              </li>
            ))
          )}
        </ol>
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
