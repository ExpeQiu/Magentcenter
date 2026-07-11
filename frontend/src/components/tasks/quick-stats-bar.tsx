"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useModal } from "@/lib/context/modal-context";
import type { SystemStatus, AgentStats } from "@/lib/types";

export function QuickStatsBar() {
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [stats, setStats] = useState<AgentStats[]>([]);
  const { openCreateTask } = useModal();

  useEffect(() => {
    api.systemStatus().then(setStatus).catch(() => {});
    api.agentStats().then(setStats).catch(() => {});
    const t = setInterval(() => {
      api.systemStatus().then(setStatus).catch(() => {});
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const gw = status?.gateway;
  const runningTasks = stats.reduce((acc, s) => acc + s.running_count, 0);
  const totalTasks = stats.reduce((acc, s) => acc + s.task_count, 0);

  return (
    <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {/* Gateway 状态 */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
        <p className="text-xs text-slate-500">Gateway</p>
        <div className="mt-1 flex items-center gap-1.5">
          <span
            className={`h-2 w-2 rounded-full ${gw?.running ? "bg-emerald-400" : "bg-red-400"}`}
          />
          <span className="text-sm font-medium">
            {gw?.running ? "在线" : "离线"}
          </span>
        </div>
        <p className="mt-1 text-xs text-slate-500">v{gw?.version || "—"}</p>
      </div>

      {/* 活跃任务 */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
        <p className="text-xs text-slate-500">运行中</p>
        <p className="mt-1 text-2xl font-semibold text-indigo-400">
          {runningTasks}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          共 {totalTasks} 个任务
        </p>
      </div>

      {/* Cron 状态 */}
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
        <p className="text-xs text-slate-500">Cron 告警</p>
        <p
          className={`mt-1 text-2xl font-semibold ${
            (status?.cron_errors.length || 0) > 0
              ? "text-amber-400"
              : "text-emerald-400"
          }`}
        >
          {status?.cron_errors.length || 0}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {status?.cron_jobs.length || 0} 个任务
        </p>
      </div>

      {/* 新建任务 */}
      <div className="flex items-center justify-center rounded-xl border border-indigo-800/50 bg-indigo-950/30 p-3">
        <button
          onClick={() => openCreateTask()}
          className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium hover:bg-indigo-500"
        >
          + 新建任务
        </button>
      </div>
    </div>
  );
}
