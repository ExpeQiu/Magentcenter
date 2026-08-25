"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { SessionDetail } from "@/lib/types";
import { formatTime } from "@/components/ui/status-badge";

function formatTimestamp(iso: string) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const ROLE_STYLES: Record<string, string> = {
  user: "bg-slate-800 border-slate-700",
  assistant: "bg-indigo-950/60 border-indigo-800",
  toolResult: "bg-amber-950/40 border-amber-900/50",
};

const ROLE_LABELS: Record<string, string> = {
  user: "用户",
  assistant: "助手",
  toolResult: "工具",
};

export function SessionDetailView() {
  const params = useSearchParams();
  const router = useRouter();
  const sessionId = (params.get("id") || "").trim();

  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [indexing, setIndexing] = useState(false);
  const [indexMsg, setIndexMsg] = useState("");

  useEffect(() => {
    if (!sessionId) return;
    api
      .sessionDetail(sessionId)
      .then(setDetail)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [sessionId]);

  const indexToKnowledge = async () => {
    setIndexing(true);
    setIndexMsg("");
    try {
      const res = await api.indexSession(sessionId);
      setIndexMsg(`已索引 ${res.indexed} 条消息到知识库`);
    } catch (e) {
      setIndexMsg(e instanceof Error ? e.message : "索引失败");
    } finally {
      setIndexing(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button
          onClick={() => router.back()}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
        >
          ← 返回
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-semibold">Session 详情</h1>
          <p className="font-mono text-xs text-slate-400">{sessionId}</p>
        </div>
        <button
          onClick={indexToKnowledge}
          disabled={indexing || !detail?.messages?.length}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500 disabled:opacity-50"
        >
          {indexing ? "索引中…" : "索引到知识库"}
        </button>
      </div>
      {indexMsg && <p className="text-xs text-slate-400">{indexMsg}</p>}

      {loading && <p className="text-slate-500">加载中…</p>}
      {error && (
        <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-4 text-sm text-red-300">
          加载失败: {error}
        </div>
      )}

      {detail && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
              <p className="text-xs text-slate-500">运行时</p>
              <p className="mt-1 text-sm uppercase">{detail.runtime || "openclaw"}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
              <p className="text-xs text-slate-500">Agent</p>
              <p className="mt-1 font-mono text-sm">{detail.agent_id || "—"}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
              <p className="text-xs text-slate-500">Model</p>
              <p className="mt-1 text-sm">{detail.model || "—"}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
              <p className="text-xs text-slate-500">Tokens</p>
              <p className="mt-1 text-sm">{detail.total_tokens.toLocaleString()}</p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-3">
              <p className="text-xs text-slate-500">更新于</p>
              <p className="mt-1 text-sm">{formatTime(detail.updated_at)}</p>
            </div>
          </div>

          <div>
            <h2 className="mb-3 text-sm font-medium text-slate-300">
              消息流 ({detail.messages.length})
            </h2>
            <div className="space-y-3">
              {detail.messages.map((msg, i) => (
                <div
                  key={i}
                  className={`rounded-xl border p-4 ${ROLE_STYLES[msg.role] || "bg-slate-900 border-slate-800"}`}
                >
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-xs font-medium">
                      {ROLE_LABELS[msg.role] || msg.role}
                    </span>
                    {msg.timestamp && (
                      <span className="text-xs text-slate-500">
                        {formatTimestamp(msg.timestamp)}
                      </span>
                    )}
                  </div>
                  <div className="text-sm leading-relaxed whitespace-pre-wrap">
                    {msg.content || <span className="text-slate-600 italic">（空）</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
