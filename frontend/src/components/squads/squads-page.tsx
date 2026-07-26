"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { AgentStats, SquadInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";

export function SquadsPage() {
  const [squads, setSquads] = useState<SquadInfo[]>([]);
  const [stats, setStats] = useState<AgentStats[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const router = useRouter();
  const wp = useWorkspacePaths();

  useEffect(() => {
    Promise.all([api.squads(), api.agentStats()])
      .then(([s, st]) => {
        setSquads(s);
        setStats(st);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const getAgentStat = (agentId: string) =>
    stats.find((s) => s.agent_id === agentId);

  const assign = async (s: SquadInfo) => {
    const prompt = window.prompt(`向「${s.name}」分配任务：`);
    if (!prompt) return;
    try {
      const task = await api.createSquadTask(s.id, prompt);
      router.push(wp.taskDetail(task.id));
    } catch {
      alert("分配失败");
    }
  };

  const toggle = (id: string) =>
    setExpanded((prev) => (prev === id ? null : id));

  return (
    <>
      <PageHeader
        title="小队"
        description="OpenClaw Leader 路由 / Hermes profile 执行"
      />
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : squads.length === 0 ? (
        <EmptyState title="暂无小队" description="在 guide/squads.yml 中配置" />
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {squads.map((s) => {
            const isOpen = expanded === s.id;
            return (
              <div
                key={s.id}
                className={`rounded-xl border transition-colors ${
                  isOpen
                    ? "border-indigo-800 bg-indigo-950/30"
                    : "border-slate-800 bg-slate-900/50"
                } p-5`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold truncate">{s.name}</h3>
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] uppercase text-slate-400">
                        {s.runtime || "openclaw"}
                      </span>
                      {isOpen && (
                        <span className="rounded bg-indigo-500/20 px-2 py-0.5 text-xs text-indigo-300">
                          展开中
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-slate-400 line-clamp-2">
                      {s.description}
                    </p>
                    <div className="mt-2 text-xs text-slate-500">
                      Leader: <code className="text-slate-300">{s.leader}</code>
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {s.members.map((m) => (
                        <span
                          key={m}
                          className="rounded bg-slate-800 px-2 py-0.5 font-mono text-xs text-slate-400"
                        >
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                  <button
                    onClick={() => toggle(s.id)}
                    className={`shrink-0 rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                      isOpen
                        ? "border-indigo-700 bg-indigo-900/50 text-indigo-300 hover:bg-indigo-900"
                        : "border-slate-700 hover:bg-slate-800"
                    }`}
                  >
                    {isOpen ? "收起" : "详情"}
                  </button>
                </div>

                {isOpen && (
                  <div className="mt-4 space-y-4 border-t border-slate-800 pt-4">
                    <div>
                      <h4 className="mb-2 text-xs font-medium text-slate-400 uppercase tracking-wide">
                        成员状态
                      </h4>
                      {s.members.length === 0 ? (
                        <p className="text-sm text-slate-500">无成员</p>
                      ) : (
                        <div className="space-y-2">
                          {[s.leader, ...s.members].map((memberId) => {
                            const stat = getAgentStat(memberId);
                            return (
                              <div
                                key={memberId}
                                className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2"
                              >
                                <div className="flex items-center gap-2">
                                  <span className="font-mono text-xs">{memberId}</span>
                                  {memberId === s.leader && (
                                    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-300">
                                      Leader
                                    </span>
                                  )}
                                </div>
                                {stat ? (
                                  <div className="flex items-center gap-3 text-xs">
                                    <StatusBadge
                                      status={
                                        stat.running_count > 0 ? "running" : "completed"
                                      }
                                    />
                                    <span className="text-slate-400">
                                      {stat.running_count > 0
                                        ? `运行中 ${stat.running_count}`
                                        : "空闲"}
                                    </span>
                                    <span className="text-slate-500">
                                      共 {stat.task_count} 任务
                                    </span>
                                  </div>
                                ) : (
                                  <span className="text-xs text-slate-600">无数据</span>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>

                    <div className="flex gap-2">
                      <button
                        onClick={() => assign(s)}
                        className="flex-1 rounded-lg bg-indigo-600 px-3 py-2 text-sm font-medium hover:bg-indigo-500 transition-colors"
                      >
                        分配任务给小队
                      </button>
                      <button
                        onClick={() => router.push(wp.sessions())}
                        className="rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800 transition-colors"
                      >
                        查看 Session
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
