"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { WorkItemInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { StatusBadge, formatTime } from "@/components/ui/status-badge";

export function WorkItemDetail() {
  const params = useSearchParams();
  const id = params.get("id") || "";
  const wp = useWorkspacePaths();
  const [item, setItem] = useState<WorkItemInfo | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    if (!id) return;
    api
      .workItem(id)
      .then(setItem)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (!id) {
    return <p className="text-sm text-slate-500">缺少工作 ID</p>;
  }
  if (error) {
    return <p className="text-sm text-rose-300">{error}</p>;
  }
  if (!item) {
    return <p className="text-sm text-slate-500">加载中…</p>;
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Link href={wp.workItems()} className="text-sm text-slate-400 hover:text-slate-200">
        ← 工作列表
      </Link>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold text-slate-100">{item.title}</h1>
        <StatusBadge status={item.status} />
      </div>
      <p className="whitespace-pre-wrap text-sm text-slate-300">{item.goal}</p>
      <dl className="grid grid-cols-2 gap-3 text-sm text-slate-400">
        <div>
          <dt className="text-xs text-slate-500">版本</dt>
          <dd>
            req {item.requirement_revision} / state {item.state_version}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">更新</dt>
          <dd>{formatTime(item.updated_at || item.created_at)}</dd>
        </div>
        {item.wait_reason ? (
          <div className="col-span-2">
            <dt className="text-xs text-slate-500">等待原因</dt>
            <dd>{item.wait_reason}</dd>
          </div>
        ) : null}
      </dl>
      {item.task_id && (
        <Link
          href={wp.taskDetail(item.task_id)}
          className="inline-block rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white"
        >
          打开关联任务
        </Link>
      )}
      {item.status !== "accepted" && (
        <button
          type="button"
          className="ml-2 rounded-lg border border-emerald-700 px-3 py-2 text-sm text-emerald-200"
          onClick={async () => {
            await api.acceptWorkItem(item.id);
            load();
          }}
        >
          验收通过
        </button>
      )}
    </div>
  );
}
