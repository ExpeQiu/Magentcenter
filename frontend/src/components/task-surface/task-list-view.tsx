"use client";

import Link from "next/link";
import type { TaskInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { StatusBadge, formatTime, truncate } from "@/components/ui/status-badge";

export function TaskListView({ tasks }: { tasks: TaskInfo[] }) {
  const wp = useWorkspacePaths();
  return (
    <div className="overflow-hidden rounded-xl border border-slate-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
            <th className="px-4 py-3 font-medium">Agent</th>
            <th className="px-4 py-3 font-medium">任务</th>
            <th className="px-4 py-3 font-medium">排期</th>
            <th className="px-4 py-3 font-medium">状态</th>
            <th className="px-4 py-3 font-medium">时间</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((t) => (
            <tr
              key={t.id}
              className="border-t border-slate-800/80 transition hover:bg-slate-900/50"
            >
              <td className="px-4 py-3 font-mono text-xs text-slate-400">
                {t.agent_id}
              </td>
              <td className="max-w-md px-4 py-3">
                <Link
                  href={wp.taskDetail(t.id)}
                  className="text-indigo-300 hover:underline"
                >
                  {truncate(t.prompt, 100)}
                </Link>
              </td>
              <td className="px-4 py-3 text-xs text-slate-500">
                {t.start_date || t.due_date
                  ? `${t.start_date || "—"} → ${t.due_date || "—"}`
                  : "—"}
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={t.status} />
              </td>
              <td className="px-4 py-3 text-xs text-slate-500">
                {formatTime(t.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
