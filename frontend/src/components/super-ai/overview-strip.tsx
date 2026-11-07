"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspacePaths } from "@/lib/context/workspace-context";

interface OverviewData {
  compact: boolean;
  attention: Array<{ id: string; kind: string; summary: string; work_item_id?: string }>;
  health: { ok: boolean; issues: string[]; detail?: { slots?: { active: number; capacity: number; free: number } } };
  recent: Array<{ id: string; title: string; status: string }>;
}

export function OverviewStrip() {
  const wp = useWorkspacePaths();
  const [data, setData] = useState<OverviewData | null>(null);

  const load = useCallback(() => {
    api
      .superagentOverview()
      .then((d) => setData(d as unknown as OverviewData))
      .catch(() => setData(null));
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 20000);
    return () => window.clearInterval(t);
  }, [load]);

  if (!data) return null;

  if (data.compact) {
    const slots = data.health.detail?.slots;
    return (
      <div className="mx-4 mt-3 rounded-lg border border-slate-800/80 bg-slate-900/40 px-3 py-2 text-xs text-slate-400 sm:mx-5">
        一切正常
        {slots ? ` · 槽位 ${slots.active}/${slots.capacity}` : ""}
        {" · "}
        <Link href={wp.attention()} className="text-slate-300 hover:underline">
          待办
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-4 mt-3 space-y-2 sm:mx-5">
      {data.attention.length > 0 && (
        <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 px-3 py-2">
          <p className="text-xs font-medium text-amber-200">要我做什么？</p>
          <ul className="mt-1 space-y-1">
            {data.attention.slice(0, 3).map((a) => (
              <li key={a.id} className="text-xs text-slate-200">
                {a.summary}
              </li>
            ))}
          </ul>
          <Link href={wp.attention()} className="mt-1 inline-block text-xs text-indigo-300 hover:underline">
            打开待办
          </Link>
        </div>
      )}
      {!data.health.ok && (
        <div className="rounded-lg border border-rose-900/40 bg-rose-950/20 px-3 py-2 text-xs text-rose-100">
          系统异常：{(data.health.issues || []).join("、") || "未知"}
        </div>
      )}
      {data.recent[0] && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-400">
          最近：{data.recent[0].title || data.recent[0].id}（{data.recent[0].status}）
        </div>
      )}
    </div>
  );
}
