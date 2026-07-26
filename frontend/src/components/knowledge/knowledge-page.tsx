"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { KnowledgeHit } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export function KnowledgePage() {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"hybrid" | "keyword" | "vector">("hybrid");
  const [runtime, setRuntime] = useState<"all" | "openclaw" | "hermes">("all");
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [provider, setProvider] = useState("");
  const [msg, setMsg] = useState("");
  const router = useRouter();
  const wp = useWorkspacePaths();

  useEffect(() => {
    api
      .knowledgeStatus()
      .then((s) => {
        const emb = s.embedding || {};
        setProvider(`${emb.provider || "hash"} / ${emb.model || "—"}`);
      })
      .catch(console.error);
  }, []);

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!q.trim()) {
      setHits([]);
      return;
    }
    setSearching(true);
    setMsg("");
    try {
      const res = await api.knowledgeSearch(q.trim(), {
        limit: 30,
        mode,
        runtime: runtime === "all" ? undefined : runtime,
      });
      setHits(res);
      setMsg(res.length ? `命中 ${res.length}` : "无结果");
    } catch (err) {
      console.error(err);
      setMsg("检索失败");
      setHits([]);
    } finally {
      setSearching(false);
    }
  };

  const backfill = async () => {
    setMsg("补索引中…");
    try {
      const res = await api.knowledgeBackfill();
      setMsg(`已补索引 ${res.indexed} 条任务`);
      const emb = res.embedding;
      if (emb) setProvider(`${emb.provider} / ${emb.model}`);
    } catch {
      setMsg("补索引失败");
    }
  };

  const openHit = (h: KnowledgeHit) => {
    if (h.source_type === "task" && h.source_id) {
      router.push(wp.taskDetail(h.source_id));
    } else if (h.session_id) {
      router.push(wp.sessionDetail(h.session_id));
    } else if (h.source_type === "session_msg" && h.source_id) {
      const sid = h.source_id.split(":")[0];
      if (sid) router.push(wp.sessionDetail(sid));
    }
  };

  return (
    <>
      <PageHeader
        title="知识库"
        description={
          provider
            ? `任务输出 + Session 消息 · 向量 ${provider}`
            : "任务输出 + Session 消息检索"
        }
        actions={
          <button
            onClick={backfill}
            className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
          >
            从任务补索引
          </button>
        }
      />

      <form
        onSubmit={search}
        className="mb-6 flex flex-wrap gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
      >
        <select
          value={mode}
          onChange={(e) =>
            setMode(e.target.value as "hybrid" | "keyword" | "vector")
          }
          className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm"
        >
          <option value="hybrid">混合</option>
          <option value="keyword">关键词</option>
          <option value="vector">向量</option>
        </select>
        <select
          value={runtime}
          onChange={(e) =>
            setRuntime(e.target.value as "all" | "openclaw" | "hermes")
          }
          className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm"
        >
          <option value="all">全部运行时</option>
          <option value="openclaw">OpenClaw</option>
          <option value="hermes">Hermes</option>
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="检索任务输出 / Session 消息…"
          className="min-w-[240px] flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={searching}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm disabled:opacity-50"
        >
          {searching ? "检索中…" : "检索"}
        </button>
      </form>

      {msg && <p className="mb-3 text-xs text-slate-500">{msg}</p>}

      {hits.length === 0 ? (
        <EmptyState
          title="输入关键词开始检索"
          description="可在 Session 详情页将消息索引到知识库"
        />
      ) : (
        <div className="space-y-2">
          {hits.map((h) => (
            <button
              key={h.id}
              type="button"
              onClick={() => openHit(h)}
              className="block w-full rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3 text-left hover:bg-slate-800/50"
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                <span className="uppercase">{h.runtime || "—"}</span>
                <span>{h.source_type}</span>
                <span>{h.agent_id || "—"}</span>
                <span>score {h.score}</span>
              </div>
              <p className="mt-1 text-sm text-slate-200">{h.title || h.source_id}</p>
              <p className="mt-1 line-clamp-2 text-xs text-slate-500">{h.snippet}</p>
            </button>
          ))}
        </div>
      )}
    </>
  );
}
