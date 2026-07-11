"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AgentInfo } from "@/lib/types";
import { useModal } from "@/lib/context/modal-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const { openCreateTask } = useModal();

  useEffect(() => {
    api
      .agents()
      .then(setAgents)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = agents.filter(
    (a) =>
      !filter ||
      a.id.includes(filter) ||
      a.name.includes(filter) ||
      a.identity_name.includes(filter)
  );

  return (
    <>
      <PageHeader
        title="Agents"
        description={`OpenClaw 已注册 ${agents.length} 个 Agent`}
        actions={
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="搜索…"
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
          />
        }
      />
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : filtered.length === 0 ? (
        <EmptyState title="未找到 Agent" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((a) => (
            <div
              key={a.id}
              className="group rounded-xl border border-slate-800 bg-slate-900/50 p-4 transition hover:border-indigo-500/40"
            >
              <div className="mb-2 text-lg">
                {a.identity_emoji || "🤖"} {a.name}
              </div>
              <p className="font-mono text-xs text-slate-500">{a.id}</p>
              {a.model && (
                <p className="mt-1 truncate text-xs text-slate-400">{a.model}</p>
              )}
              {a.is_default && (
                <span className="mt-2 inline-block rounded bg-indigo-500/20 px-2 py-0.5 text-xs text-indigo-300">
                  默认
                </span>
              )}
              <button
                onClick={() => openCreateTask(a.id)}
                className="mt-3 w-full rounded-lg bg-slate-800 py-1.5 text-xs opacity-0 transition group-hover:opacity-100 hover:bg-indigo-600"
              >
                分配任务
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
