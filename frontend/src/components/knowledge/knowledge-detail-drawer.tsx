"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { KnowledgeHit, OutputFile } from "@/lib/types";
import { MarkdownPreview } from "@/components/outputs/markdown-preview";

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

function extractPath(h: KnowledgeHit): string {
  const p = h.payload || {};
  if (str(p.path)) return str(p.path);
  const refs = p.source_refs;
  if (refs && typeof refs === "object" && str((refs as { path?: unknown }).path)) {
    return str((refs as { path?: unknown }).path);
  }
  if (h.source_type === "outputs" && h.source_id && !h.source_id.startsWith("vault-")) {
    return h.source_id;
  }
  if (h.source_id.startsWith("vault-playbook:")) {
    return h.source_id.slice("vault-playbook:".length);
  }
  if (h.source_id.startsWith("vault-fact:")) {
    return h.source_id.slice("vault-fact:".length);
  }
  if (h.source_id.startsWith("vault-case:")) {
    return h.source_id.slice("vault-case:".length);
  }
  return "";
}

function extractTaskId(h: KnowledgeHit): string {
  const p = h.payload || {};
  if (str(p.task_id)) return str(p.task_id);
  const refs = p.source_refs;
  if (refs && typeof refs === "object" && str((refs as { task_id?: unknown }).task_id)) {
    return str((refs as { task_id?: unknown }).task_id);
  }
  if (h.source_type === "task" && h.source_id) {
    const id = h.source_id.split(":")[0];
    // uuid-ish
    if (id && id.length >= 8 && !id.startsWith("vault")) return id;
  }
  return "";
}

export function KnowledgeDetailDrawer({
  hit,
  onClose,
  onOpenTask,
  onOpenSession,
  onOpenOutputs,
}: {
  hit: KnowledgeHit | null;
  onClose: () => void;
  onOpenTask: (id: string) => void;
  onOpenSession: (id: string) => void;
  onOpenOutputs: (path: string) => void;
}) {
  const [detail, setDetail] = useState<KnowledgeHit | null>(hit);
  const [file, setFile] = useState<OutputFile | null>(null);
  const [fileErr, setFileErr] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setDetail(hit);
    setFile(null);
    setFileErr("");
    if (!hit) return;

    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const full = await api.knowledgeGet(hit.id);
        if (!cancelled) setDetail(full);
      } catch (e) {
        console.warn("[knowledge] detail fetch fallback to list hit", e);
        if (!cancelled) setDetail(hit);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hit]);

  const path = useMemo(() => (detail ? extractPath(detail) : ""), [detail]);
  const taskId = useMemo(() => (detail ? extractTaskId(detail) : ""), [detail]);
  const sessionId = detail?.session_id || str(detail?.payload?.session_id);

  useEffect(() => {
    if (!path) {
      setFile(null);
      return;
    }
    let cancelled = false;
    setFileErr("");
    api
      .outputsFile(path)
      .then((f) => {
        if (!cancelled) setFile(f);
      })
      .catch((err) => {
        console.error("[knowledge] outputs preview failed", path, err);
        if (!cancelled) {
          setFile(null);
          setFileErr(err instanceof Error ? err.message : "无法读取原文");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  if (!hit || !detail) return null;

  const p = detail.payload || {};
  const summary = str(p.summary) || detail.snippet || "";
  const steps = Array.isArray(p.steps) ? (p.steps as unknown[]).map(String) : [];
  const body = str(p.body) || str(p.fact) || "";
  const symptom = str(p.symptom);
  const rootCause = str(p.root_cause);
  const fix = str(p.fix);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <aside
        className="flex h-full w-full max-w-xl flex-col border-l border-slate-800 bg-slate-950 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-800 px-4 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wide text-slate-500">{detail.kind}</p>
            <h2 className="mt-1 text-base font-medium text-slate-100">{detail.title}</h2>
            {loading && <p className="mt-1 text-xs text-slate-500">加载详情…</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 px-2 py-1 text-sm text-slate-300 hover:bg-slate-800"
          >
            关闭
          </button>
        </header>

        <div className="flex flex-wrap gap-2 border-b border-slate-800 px-4 py-2 text-xs">
          {detail.runtime && (
            <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">
              {detail.runtime}
            </span>
          )}
          {detail.agent_id && (
            <span className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">
              {detail.agent_id}
            </span>
          )}
          {(detail.tags || []).map((t) => (
            <span key={t} className="rounded bg-slate-900 px-2 py-0.5 text-slate-500">
              #{t}
            </span>
          ))}
        </div>

        <div className="flex flex-wrap gap-2 border-b border-slate-800 px-4 py-2">
          {taskId && (
            <button
              type="button"
              onClick={() => onOpenTask(taskId)}
              className="rounded-lg border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
            >
              打开任务
            </button>
          )}
          {sessionId && (
            <button
              type="button"
              onClick={() => onOpenSession(sessionId)}
              className="rounded-lg border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
            >
              打开 Session
            </button>
          )}
          {path && (
            <button
              type="button"
              onClick={() => onOpenOutputs(path)}
              className="rounded-lg border border-slate-700 px-2 py-1 text-xs hover:bg-slate-800"
            >
              在输出物中打开
            </button>
          )}
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm">
          {summary && (
            <section>
              <h3 className="mb-1 text-xs font-medium text-slate-500">摘要</h3>
              <p className="whitespace-pre-wrap text-slate-200">{summary}</p>
            </section>
          )}

          {steps.length > 0 && (
            <section>
              <h3 className="mb-1 text-xs font-medium text-slate-500">步骤</h3>
              <ol className="list-decimal space-y-1 pl-5 text-slate-300">
                {steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </section>
          )}

          {(symptom || rootCause || fix) && (
            <section className="space-y-2">
              <h3 className="text-xs font-medium text-slate-500">故障信息</h3>
              {symptom && (
                <p className="text-slate-300">
                  <span className="text-slate-500">症状：</span>
                  {symptom}
                </p>
              )}
              {rootCause && (
                <p className="text-slate-300">
                  <span className="text-slate-500">根因：</span>
                  {rootCause}
                </p>
              )}
              {fix && (
                <p className="text-slate-300">
                  <span className="text-slate-500">修复：</span>
                  {fix}
                </p>
              )}
            </section>
          )}

          {body && (
            <section>
              <h3 className="mb-1 text-xs font-medium text-slate-500">正文</h3>
              <p className="whitespace-pre-wrap text-slate-200">{body}</p>
            </section>
          )}

          {path && (
            <section>
              <h3 className="mb-1 text-xs font-medium text-slate-500">来源路径</h3>
              <p className="break-all font-mono text-xs text-slate-400">{path}</p>
            </section>
          )}

          {fileErr && (
            <p className="text-xs text-rose-300">原文预览失败：{fileErr}</p>
          )}

          {file?.content && (
            <section>
              <h3 className="mb-2 text-xs font-medium text-slate-500">
                原文预览 {file.previewable ? "" : "(截断/二进制)"}
              </h3>
              {file.ext === ".md" || file.ext === ".markdown" ? (
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                  <MarkdownPreview content={file.content.slice(0, 12000)} />
                </div>
              ) : (
                <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-800 bg-slate-900/50 p-3 text-xs text-slate-300">
                  {file.content.slice(0, 12000)}
                </pre>
              )}
            </section>
          )}

          <section>
            <h3 className="mb-1 text-xs font-medium text-slate-500">元数据</h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs text-slate-400">
              <dt>id</dt>
              <dd className="break-all">{detail.id}</dd>
              <dt>source</dt>
              <dd className="break-all">
                {detail.source_type}:{detail.source_id}
              </dd>
              <dt>status</dt>
              <dd>{detail.status || "—"}</dd>
              <dt>created</dt>
              <dd>{detail.created_at || "—"}</dd>
            </dl>
          </section>
        </div>
      </aside>
    </div>
  );
}
