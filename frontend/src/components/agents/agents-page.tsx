"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AgentInfo, AgentStats } from "@/lib/types";
import { useModal } from "@/lib/context/modal-context";
import { agentRefKey } from "@/components/pickers/agent-picker";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { formatTime } from "@/components/ui/status-badge";

export function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [stats, setStats] = useState<Record<string, AgentStats>>({});
  const [filter, setFilter] = useState("");
  const [runtimeFilter, setRuntimeFilter] = useState<"all" | "openclaw" | "hermes">(
    "all"
  );
  const [loading, setLoading] = useState(true);
  const { openCreateTask } = useModal();

  useEffect(() => {
    Promise.all([api.agents(), api.agentStats()])
      .then(([agentList, statList]) => {
        setAgents(agentList);
        const map: Record<string, AgentStats> = {};
        for (const s of statList) map[s.agent_id] = s;
        setStats(map);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = agents.filter(
    (a) =>
      (runtimeFilter === "all" || a.runtime === runtimeFilter) &&
      (!filter ||
        a.id.includes(filter) ||
        a.name.includes(filter) ||
        a.identity_name.includes(filter) ||
        (a.runtime || "").includes(filter))
  );

  const ocCount = agents.filter((a) => a.runtime === "openclaw").length;
  const hmCount = agents.filter((a) => a.runtime === "hermes").length;

  return (
    <>
      <PageHeader
        title="Agents"
        description={`OpenClaw ${ocCount} · Hermes ${hmCount} · 合计 ${agents.length}`}
        actions={
          <div className="flex items-center gap-2">
            <select
              value={runtimeFilter}
              onChange={(e) =>
                setRuntimeFilter(e.target.value as "all" | "openclaw" | "hermes")
              }
              className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm"
            >
              <option value="all">全部运行时</option>
              <option value="openclaw">OpenClaw</option>
              <option value="hermes">Hermes</option>
            </select>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索…"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            />
          </div>
        }
      />
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : filtered.length === 0 ? (
        <EmptyState title="未找到 Agent" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((a) => {
            const st = stats[a.id];
            const isActive = (st?.running_count ?? 0) > 0;
            return (
              <div
                key={agentRefKey(a)}
                className="group rounded-xl border border-slate-800 bg-slate-900/50 p-4 transition hover:border-indigo-500/40"
              >
                <div className="mb-2 flex items-start justify-between">
                  <div className="text-lg">
                    {a.identity_emoji || "🤖"} {a.name}
                  </div>
                  <span
                    className={`mt-1 h-2 w-2 rounded-full ${
                      isActive ? "bg-emerald-400 animate-pulse" : "bg-slate-600"
                    }`}
                    title={isActive ? "运行中" : "空闲"}
                  />
                </div>
                <p className="font-mono text-xs text-slate-500">{a.id}</p>
                <span className="mt-1 inline-block rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                  {a.runtime}
                </span>
                {a.model && (
                  <p className="mt-1 truncate text-xs text-slate-400">{a.model}</p>
                )}
                {st && (
                  <div className="mt-2 flex gap-3 text-xs text-slate-500">
                    <span>{st.task_count} 任务</span>
                    {st.last_active_at && (
                      <span>活跃 {formatTime(st.last_active_at)}</span>
                    )}
                  </div>
                )}
                {a.is_default && (
                  <span className="mt-2 inline-block rounded bg-indigo-500/20 px-2 py-0.5 text-xs text-indigo-300">
                    默认
                  </span>
                )}
                <button
                  onClick={() => openCreateTask(agentRefKey(a))}
                  className="mt-3 w-full rounded-lg bg-slate-800 py-1.5 text-xs opacity-0 transition group-hover:opacity-100 hover:bg-indigo-600"
                >
                  分配任务
                </button>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
