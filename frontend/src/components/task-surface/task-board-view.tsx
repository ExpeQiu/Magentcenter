"use client";

import Link from "next/link";
import type { TaskInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { StatusBadge, truncate } from "@/components/ui/status-badge";
import { isLiveTaskId, taskHref } from "@/lib/task-links";

const COLUMNS = [
  { key: "queued", label: "排队", color: "border-amber-500/30" },
  { key: "running", label: "执行中", color: "border-sky-500/30" },
  { key: "completed", label: "完成", color: "border-emerald-500/30" },
  { key: "failed", label: "失败", color: "border-red-500/30" },
] as const;

export function TaskBoardView({ tasks }: { tasks: TaskInfo[] }) {
  const wp = useWorkspacePaths();
  const byStatus = (status: string) =>
    tasks.filter(
      (t) =>
        t.status === status ||
        (status === "failed" && (t.status === "cancelled" || t.status === "timeout"))
    );

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      {COLUMNS.map((col) => {
        const items = byStatus(col.key);
        return (
          <div
            key={col.key}
            className={`flex flex-col rounded-xl border bg-slate-900/40 ${col.color}`}
          >
            <div className="flex items-center justify-between border-b border-slate-800/80 px-3 py-2">
              <span className="text-sm font-medium">{col.label}</span>
              <span className="text-xs text-slate-500">{items.length}</span>
            </div>
            <div className="flex-1 space-y-2 p-2">
              {items.map((t) => (
                <Link
                  key={t.id}
                  href={taskHref(t.id, wp)}
                  className={`block rounded-lg border bg-slate-900 p-3 transition hover:border-indigo-500/50 ${
                    isLiveTaskId(t.id)
                      ? "border-sky-700/50"
                      : "border-slate-800"
                  }`}
                >
                  <p className="text-sm text-slate-200">
                    {truncate(t.prompt, 60)}
                  </p>
                  <div className="mt-2 flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-slate-500">
                      {t.agent_id}
                      {isLiveTaskId(t.id) && (
                        <span className="ml-1 uppercase text-sky-500">live</span>
                      )}
                    </span>
                    <StatusBadge status={t.status} />
                  </div>
                </Link>
              ))}
              {items.length === 0 && (
                <p className="py-6 text-center text-xs text-slate-600">暂无</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
