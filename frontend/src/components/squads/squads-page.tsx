"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { SquadInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export function SquadsPage() {
  const [squads, setSquads] = useState<SquadInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const wp = useWorkspacePaths();

  useEffect(() => {
    api
      .squads()
      .then(setSquads)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

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

  return (
    <>
      <PageHeader
        title="小队"
        description="由 Leader Agent 路由的小队任务分配"
      />
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : squads.length === 0 ? (
        <EmptyState title="暂无小队" description="在 guide/squads.yml 中配置" />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {squads.map((s) => (
            <div
              key={s.id}
              className="rounded-xl border border-slate-800 bg-slate-900/50 p-5"
            >
              <h3 className="font-semibold">{s.name}</h3>
              <p className="mt-1 text-sm text-slate-400">{s.description}</p>
              <div className="mt-3 text-xs text-slate-500">
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
              <button
                onClick={() => assign(s)}
                className="mt-4 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
              >
                分配给小队
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
