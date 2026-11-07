"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AttentionItem } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { formatTime } from "@/components/ui/status-badge";

export function AttentionPage() {
  const wp = useWorkspacePaths();
  const [items, setItems] = useState<AttentionItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .attentionList()
      .then((d) => {
        setItems(d.items || []);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dismiss = async (id: string) => {
    try {
      await api.dismissAttention(id);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">待人工处理</h1>
          <p className="mt-1 text-sm text-slate-400">
            只列出需要你决定或确认的事项；健康状态不占这里。
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
        <p className="text-sm text-slate-500">没有待办。系统正常时这里是空的。</p>
      ) : (
        <div className="space-y-3">
          {items.map((item) => (
            <div
              key={item.id}
              className="rounded-xl border border-amber-900/40 bg-slate-900/40 p-4"
            >
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="rounded bg-amber-950/60 px-2 py-0.5 text-xs text-amber-200">
                  {item.kind || "attention"}
                </span>
                <span className="text-xs text-slate-500">
                  {item.created_at ? formatTime(item.created_at) : ""}
                </span>
              </div>
              <p className="text-sm text-slate-100">{item.summary}</p>
              <div className="mt-3 flex flex-wrap gap-3 text-xs">
                {item.work_item_id ? (
                  <Link
                    href={wp.workItemDetail(item.work_item_id)}
                    className="text-indigo-300 hover:underline"
                  >
                    工作主线
                  </Link>
                ) : null}
                {item.task_id ? (
                  <Link
                    href={wp.taskDetail(item.task_id)}
                    className="text-indigo-300 hover:underline"
                  >
                    任务
                  </Link>
                ) : null}
                <button
                  type="button"
                  onClick={() => dismiss(item.id)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  忽略
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
