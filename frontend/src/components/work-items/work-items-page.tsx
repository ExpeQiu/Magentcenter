"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { WorkItemInfo } from "@/lib/types";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import { StatusBadge, formatTime, truncate } from "@/components/ui/status-badge";

export function WorkItemsPage() {
  const { workspace } = useWorkspace();
  const wp = useWorkspacePaths();
  const [items, setItems] = useState<WorkItemInfo[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .workItems({ workspaceId: workspace?.id || "", limit: 100 })
      .then((d) => {
        setItems(d.items || []);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [workspace?.id]);

  useEffect(() => {
    load();
  }, [load]);

  const accept = async (id: string) => {
    try {
      await api.acceptWorkItem(id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">工作主线</h1>
          <p className="mt-1 text-sm text-slate-400">
            WorkItem 与任务关联；可在手机上验收完成。
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200"
        >
          刷新
        </button>
      </div>
      {error && (
        <p className="rounded-lg border border-rose-900/60 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}
      {loading ? (
        <p className="text-sm text-slate-500">加载中…</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-500">暂无工作项。用超级AI建任务后会自动挂上。</p>
      ) : (
        <div className="space-y-3">
          {items.map((w) => (
            <div
              key={w.id}
              className="rounded-xl border border-slate-800 bg-slate-900/40 p-4"
            >
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <Link
                  href={wp.workItemDetail(w.id)}
                  className="font-medium text-indigo-200 hover:underline"
                >
                  {w.title || truncate(w.goal, 60)}
                </Link>
                <StatusBadge status={w.status} />
              </div>
              <p className="text-sm text-slate-300">{truncate(w.goal, 160)}</p>
              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                <span>{formatTime(w.updated_at || w.created_at)}</span>
                {w.task_id ? (
                  <Link
                    href={wp.taskDetail(w.task_id)}
                    className="text-sky-400 hover:underline"
                  >
                    任务 {w.task_id.slice(0, 8)}…
                  </Link>
                ) : (
                  <span>未挂任务</span>
                )}
                {w.status !== "accepted" && (
                  <button
                    type="button"
                    onClick={() => accept(w.id)}
                    className="rounded border border-emerald-800/80 px-2 py-0.5 text-emerald-300"
                  >
                    验收
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
