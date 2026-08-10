"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { KnowledgeHit, KnowledgeKind } from "@/lib/types";
import {
  useWorkspace,
  useWorkspacePaths,
} from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { KnowledgeDetailDrawer } from "@/components/knowledge/knowledge-detail-drawer";

const KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "playbook,precedent,shared_fact,incident,artifact_ref", label: "卡片（默认）" },
  { value: "playbook", label: "Playbook" },
  { value: "precedent", label: "Precedent" },
  { value: "incident", label: "Incident" },
  { value: "artifact_ref", label: "产物指针" },
  { value: "shared_fact", label: "共享事实" },
  { value: "archive", label: "Archive 原文" },
];

export function KnowledgePage({
  initialHits = [],
}: {
  initialHits?: KnowledgeHit[];
}) {
  const [q, setQ] = useState("");
  const [mode, setMode] = useState<"hybrid" | "keyword" | "vector">("hybrid");
  const [runtime, setRuntime] = useState<"all" | "openclaw" | "hermes">("all");
  const [kind, setKind] = useState(KIND_OPTIONS[0].value);
  const [hits, setHits] = useState<KnowledgeHit[]>(initialHits);
  const [searching, setSearching] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [provider, setProvider] = useState("");
  const [msg, setMsg] = useState(
    initialHits.length ? `最近 ${initialHits.length} 条卡片` : ""
  );
  const [factTitle, setFactTitle] = useState("");
  const [factBody, setFactBody] = useState("");
  const [preview, setPreview] = useState("");
  const [selected, setSelected] = useState<KnowledgeHit | null>(null);
  const router = useRouter();
  const wp = useWorkspacePaths();
  const { workspaceId } = useWorkspace();

  const listRecent = useCallback(async () => {
    setSearching(true);
    setPreview("");
    setLoadError("");
    try {
      const includeArchive = kind === "archive";
      // 列表默认不按 workspace 收窄，避免空 workspace 卡片被误滤
      const res = await api.knowledgeList({
        limit: 50,
        kind: includeArchive ? "archive" : kind,
        runtime: runtime === "all" ? undefined : runtime,
      });
      setHits(res);
      setMsg(res.length ? `最近 ${res.length} 条卡片` : "暂无知识卡片，可点「从任务蒸馏」");
      console.info("[knowledge] list count=%d kind=%s", res.length, kind);
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      console.error("[knowledge] list failed", err);
      setLoadError(
        `加载失败: ${detail}。请确认后端 8013 已启动，并用系统浏览器打开 http://127.0.0.1:3013`
      );
      setMsg("加载知识库失败");
      setHits((prev) => (prev.length ? prev : initialHits));
    } finally {
      setSearching(false);
    }
  }, [kind, runtime, initialHits]);

  useEffect(() => {
    api
      .knowledgeStatus()
      .then((s) => {
        const emb = s.embedding || {};
        setProvider(`${emb.provider || "hash"} / ${emb.model || "—"}`);
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    void listRecent();
  }, [listRecent]);

  const search = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!q.trim()) {
      await listRecent();
      return;
    }
    setSearching(true);
    setMsg("");
    setPreview("");
    try {
      const includeArchive = kind === "archive";
      const res = await api.knowledgeSearch(q.trim(), {
        limit: 30,
        mode,
        runtime: runtime === "all" ? undefined : runtime,
        kind: includeArchive ? "archive" : kind,
        workspaceId: workspaceId || undefined,
        includeArchive,
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
    setMsg("蒸馏补索引中…");
    try {
      const res = await api.knowledgeBackfill();
      setMsg(`已从 ${res.indexed} 条任务蒸馏卡片`);
      const emb = res.embedding;
      if (emb) setProvider(`${emb.provider} / ${emb.model}`);
      await listRecent();
    } catch {
      setMsg("补索引失败");
    }
  };

  const mineVault = async () => {
    setMsg("正在从 openclaw 文档挖掘…");
    setSearching(true);
    try {
      const res = await api.knowledgeMineVault({
        scope: "openclaw",
        limit: 400,
        distill_high_value: true,
      });
      setMsg(
        `vault 挖掘完成：扫描 ${res.scanned} · 指针 ${res.artifact_refs} · ` +
          `Playbook ${res.playbooks} · Incident ${res.incidents} · 事实 ${res.shared_facts}` +
          (res.errors ? ` · 错误 ${res.errors}` : "")
      );
      setKind("playbook,precedent,shared_fact,incident,artifact_ref");
      await listRecent();
    } catch (err) {
      console.error("[knowledge] mine-vault failed", err);
      setMsg("vault 挖掘失败");
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setSearching(false);
    }
  };

  const showInjectPreview = async () => {
    if (!q.trim()) {
      setMsg("请先输入关键词再预览注入");
      return;
    }
    try {
      const res = await api.knowledgeInjectPreview(q.trim(), {
        workspaceId: workspaceId || undefined,
        runtime: runtime === "all" ? undefined : runtime,
      });
      setPreview(res.block || "(无注入内容)");
      setMsg(`注入预览 ${res.hits.length} 条`);
    } catch {
      setMsg("注入预览失败");
    }
  };

  const createSharedFact = async () => {
    if (!factTitle.trim() || !factBody.trim()) {
      setMsg("请填写共享事实标题与正文");
      return;
    }
    try {
      await api.knowledgeCreateEntry({
        kind: "shared_fact",
        title: factTitle.trim(),
        summary: factBody.trim().slice(0, 500),
        workspace_id: workspaceId || "",
        tags: ["shared_fact"],
        payload: { body: factBody.trim() },
      });
      setFactTitle("");
      setFactBody("");
      setMsg("已创建共享事实");
      if (q.trim()) await search();
      else await listRecent();
    } catch {
      setMsg("创建共享事实失败");
    }
  };

  const openHit = (h: KnowledgeHit) => {
    console.info("[knowledge] open detail id=%s kind=%s", h.id, h.kind);
    setSelected(h);
  };

  const kindBadge = (k: KnowledgeKind) => {
    const map: Record<string, string> = {
      playbook: "bg-emerald-900/50 text-emerald-300",
      precedent: "bg-sky-900/50 text-sky-300",
      incident: "bg-rose-900/50 text-rose-300",
      artifact_ref: "bg-amber-900/50 text-amber-300",
      shared_fact: "bg-violet-900/50 text-violet-300",
      archive: "bg-slate-800 text-slate-400",
    };
    return map[k] || "bg-slate-800 text-slate-400";
  };

  return (
    <>
      <KnowledgeDetailDrawer
        hit={selected}
        onClose={() => setSelected(null)}
        onOpenTask={(id) => {
          setSelected(null);
          router.push(wp.taskDetail(id));
        }}
        onOpenSession={(id) => {
          setSelected(null);
          router.push(wp.sessionDetail(id));
        }}
        onOpenOutputs={(path) => {
          setSelected(null);
          router.push(`${wp.outputs()}?file=${encodeURIComponent(path)}`);
        }}
      />
      <PageHeader
        title="知识库"
        description={
          provider
            ? `经验卡片 · Playbook / Precedent / Incident · 向量 ${provider}`
            : "经验卡片检索（非 Session 原文堆砌）"
        }
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => void listRecent()}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              刷新列表
            </button>
            <button
              onClick={showInjectPreview}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              注入预览
            </button>
            <button
              onClick={backfill}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              从任务蒸馏
            </button>
            <button
              onClick={() => void mineVault()}
              disabled={searching}
              className="rounded-lg border border-emerald-800 bg-emerald-950/40 px-3 py-1.5 text-sm text-emerald-200 hover:bg-emerald-900/40 disabled:opacity-50"
            >
              从 openclaw 文档挖掘
            </button>
          </div>
        }
      />

      <form
        onSubmit={search}
        className="mb-4 flex flex-wrap gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
      >
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm"
        >
          {KIND_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
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
          placeholder="留空显示最近卡片；输入后检索…"
          className="min-w-[240px] flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={searching}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm disabled:opacity-50"
        >
          {searching ? "加载中…" : q.trim() ? "检索" : "刷新"}
        </button>
      </form>

      <div className="mb-6 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
        <p className="mb-2 text-xs text-slate-500">新增跨栈共享事实（Shared Fact）</p>
        <div className="flex flex-wrap gap-2">
          <input
            value={factTitle}
            onChange={(e) => setFactTitle(e.target.value)}
            placeholder="标题，如 HTML 报告归档约定"
            className="min-w-[200px] flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <input
            value={factBody}
            onChange={(e) => setFactBody(e.target.value)}
            placeholder="约定正文"
            className="min-w-[240px] flex-[2] rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <button
            type="button"
            onClick={createSharedFact}
            className="rounded-lg border border-slate-600 px-3 py-2 text-sm hover:bg-slate-800"
          >
            保存
          </button>
        </div>
      </div>

      {msg && <p className="mb-3 text-xs text-slate-500">{msg}</p>}
      {loadError && (
        <div className="mb-3 rounded-lg border border-rose-800 bg-rose-950/40 px-3 py-2 text-xs text-rose-200">
          {loadError}
          <button
            type="button"
            onClick={() => void listRecent()}
            className="ml-3 underline"
          >
            重试
          </button>
        </div>
      )}

      {preview && (
        <pre className="mb-4 max-h-64 overflow-auto rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300 whitespace-pre-wrap">
          {preview}
        </pre>
      )}

      {hits.length === 0 ? (
        <EmptyState
          title={
            searching
              ? "加载中…"
              : loadError
                ? "知识库加载失败"
                : "暂无知识卡片"
          }
          description={
            loadError ||
            "任务完成后会自动蒸馏；也可点「从任务蒸馏」回填。有关键词时再检索。"
          }
          action={
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => void listRecent()}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
              >
                重试加载
              </button>
              <button
                type="button"
                onClick={() => void backfill()}
                className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
              >
                从任务蒸馏
              </button>
            </div>
          }
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
                <span className={`rounded px-1.5 py-0.5 uppercase ${kindBadge(h.kind)}`}>
                  {h.kind || "archive"}
                </span>
                <span className="uppercase">{h.runtime || "—"}</span>
                <span>{h.agent_id || "—"}</span>
                {q.trim() ? <span>score {h.score}</span> : null}
                {(h.tags || []).slice(0, 4).map((t) => (
                  <span key={t} className="text-slate-600">
                    #{t}
                  </span>
                ))}
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
