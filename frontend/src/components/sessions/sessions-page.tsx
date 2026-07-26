"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { SessionInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { formatTime } from "@/components/ui/status-badge";

function formatAge(ms: number) {
  if (ms < 60000) return `${Math.round(ms / 1000)}s 前`;
  if (ms < 3600000) return `${Math.round(ms / 60000)}m 前`;
  return `${Math.round(ms / 3600000)}h 前`;
}

export function SessionsPage() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const wp = useWorkspacePaths();

  useEffect(() => {
    api
      .sessions(100)
      .then(setSessions)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = sessions.filter(
    (s) =>
      !filter ||
      s.agent_id.includes(filter) ||
      s.session_id.includes(filter) ||
      s.key.includes(filter) ||
      (s.runtime || "").includes(filter)
  );

  return (
    <>
      <PageHeader
        title="Session 历史"
        description={`OpenClaw / Hermes 聚合 ${sessions.length} 条`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href={wp.knowledge()}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              知识库检索 →
            </Link>
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="筛选 Agent / Session / runtime…"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            />
          </div>
        }
      />

      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : filtered.length === 0 ? (
        <EmptyState title="未找到 Session" />
      ) : (
        <div className="overflow-hidden rounded-xl border border-slate-800">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-900/80 text-left text-xs text-slate-400">
                <th className="px-4 py-3">运行时</th>
                <th className="px-4 py-3">Agent</th>
                <th className="px-4 py-3">Session ID</th>
                <th className="px-4 py-3">Model</th>
                <th className="px-4 py-3">Tokens</th>
                <th className="px-4 py-3">更新</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s) => (
                <tr
                  key={`${s.runtime || "oc"}-${s.session_id}-${s.key}`}
                  onClick={() => router.push(wp.sessionDetail(s.session_id))}
                  className="cursor-pointer border-t border-slate-800/80 transition-colors hover:bg-slate-800/50"
                >
                  <td className="px-4 py-3 text-xs uppercase text-slate-500">
                    {s.runtime || "openclaw"}
                  </td>
                  <td className="px-4 py-3">{s.agent_id}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">
                    {s.session_id.slice(0, 16)}…
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{s.model || "—"}</td>
                  <td className="px-4 py-3 text-xs">{s.total_tokens || 0}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {s.updated_at
                      ? formatTime(s.updated_at)
                      : formatAge(s.age_ms || 0)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
