"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import type { OutputEntry, OutputFile, OutputStatus } from "@/lib/types";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { MarkdownPreview } from "@/components/outputs/markdown-preview";
import { HtmlPreview } from "@/components/outputs/html-preview";
import {
  loadScopes,
  ScopeModal,
} from "@/components/outputs/scope-modal";

type ViewMode = "recent" | "tree";
type SourceFilter = "all" | "openclaw" | "hermes";
/** 近期时间窗（小时） */
type TimeRange = 4 | 24 | 72 | 168;

const TIME_RANGE_OPTIONS: { value: TimeRange; label: string }[] = [
  { value: 4, label: "近 4 小时" },
  { value: 24, label: "近 1 天" },
  { value: 72, label: "近 3 天" },
  { value: 168, label: "近 7 天" },
];

function formatMtime(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

function formatSize(n: number): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function withinHours(iso: string, hours: number): boolean {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return true;
  return t >= Date.now() - hours * 3600 * 1000;
}

function fileIcon(e: OutputEntry): string {
  if (e.kind === "dir") return "📁";
  const ext = (e.ext || e.name.split(".").pop() || "").toLowerCase();
  if (ext === "md" || ext === "markdown") return "📄";
  if (ext === "html" || ext === "htm") return "🌐";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return "🖼";
  if (["json", "yml", "yaml", "toml"].includes(ext)) return "⚙";
  if (["py", "ts", "tsx", "js", "sh"].includes(ext)) return "💻";
  return "📎";
}

function isMarkdown(file: OutputFile): boolean {
  const ext = (file.ext || "").toLowerCase();
  return ext === "md" || ext === "markdown" || file.name.toLowerCase().endsWith(".md");
}

function isHtml(file: OutputFile): boolean {
  const ext = (file.ext || "").toLowerCase();
  if (ext === "html" || ext === "htm") return true;
  const head = (file.content || "").trimStart().slice(0, 200).toLowerCase();
  return (
    head.startsWith("<!doctype html") ||
    head.startsWith("<html") ||
    head.includes("<html ")
  );
}

function parentPath(path: string): string {
  const i = path.lastIndexOf("/");
  return i > 0 ? path.slice(0, i) : "";
}

function pathInScopes(path: string, scopes: string[]): boolean {
  if (!scopes.length) return true;
  const normalized = path.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  return scopes.some(
    (s) => normalized === s || normalized.startsWith(`${s}/`)
  );
}

function scopeRootEntries(scopes: string[]): OutputEntry[] {
  return scopes.map((path) => {
    const name = path.includes("/") ? path.slice(path.lastIndexOf("/") + 1) : path;
    const parts = path.split("/").filter(Boolean);
    return {
      name,
      path,
      kind: "dir" as const,
      source: parts.includes("HermesCenter") ? "hermes" : "openclaw",
      mtime: "",
      size: 0,
      ext: "",
    };
  });
}

export function OutputsPage() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<OutputStatus | null>(null);
  const [view, setView] = useState<ViewMode>("recent");
  const [source, setSource] = useState<SourceFilter>("all");
  const [timeRange, setTimeRange] = useState<TimeRange>(24);
  const [q, setQ] = useState("");
  const [dirPath, setDirPath] = useState("");
  const [entries, setEntries] = useState<OutputEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [file, setFile] = useState<OutputFile | null>(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [scopes, setScopes] = useState<string[]>([]);
  const [scopeOpen, setScopeOpen] = useState(false);

  useEffect(() => {
    setScopes(loadScopes());
  }, []);

  const crumbs = useMemo(() => {
    if (!dirPath) return [] as { label: string; path: string }[];
    const parts = dirPath.split("/").filter(Boolean);
    return parts.map((label, i) => ({
      label,
      path: parts.slice(0, i + 1).join("/"),
    }));
  }, [dirPath]);

  const refreshStatus = useCallback(async () => {
    const maxAttempts = 3;
    let lastErr: unknown;
    for (let i = 0; i < maxAttempts; i++) {
      try {
        const s = await api.outputsStatus();
        setStatus(s);
        console.info(
          "[outputs] status ok readable=%s root=%s attempt=%d",
          s.readable,
          s.root_name,
          i + 1
        );
        return;
      } catch (err) {
        lastErr = err;
        console.error("[outputs] status failed attempt=%d", i + 1, err);
        if (i < maxAttempts - 1) {
          await new Promise((r) => setTimeout(r, 400 * (i + 1)));
        }
      }
    }
    const detail =
      lastErr instanceof Error && lastErr.message
        ? lastErr.message
        : "无法连接输出物 API";
    setStatus({
      status: "unavailable",
      readable: false,
      root_name: "",
      message:
        `${detail}。请用系统浏览器打开 http://127.0.0.1:3013（勿用 Cursor 内置预览），` +
        "并确认后端 http://127.0.0.1:8013/api/health 与 ./scripts/start.sh 已启动。",
    });
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const loadList = useCallback(async () => {
    if (status && !status.readable) {
      setEntries([]);
      return;
    }
    setLoading(true);
    setMsg("");
    try {
      if (view === "recent") {
        const res = await api.outputsRecent({
          limit: 80,
          source: source === "all" ? undefined : source,
          q: q.trim() || undefined,
          since_hours: timeRange,
          scopes: scopes.length ? scopes : undefined,
        });
        setEntries(res);
        const label =
          TIME_RANGE_OPTIONS.find((o) => o.value === timeRange)?.label || "";
        const scopeHint = scopes.length ? ` · 范围 ${scopes.length}` : "";
        setMsg(
          res.length
            ? `${label} ${res.length} 篇${scopeHint}`
            : `${label}无匹配文档${scopeHint}`
        );
      } else if (!dirPath && scopes.length) {
        const roots = scopeRootEntries(scopes);
        const byName = q.trim()
          ? roots.filter((e) =>
              e.name.toLowerCase().includes(q.trim().toLowerCase())
            )
          : roots;
        setEntries(byName);
        setMsg(`范围根目录 ${byName.length} 项`);
      } else {
        if (scopes.length && dirPath && !pathInScopes(dirPath, scopes)) {
          setDirPath("");
          setEntries([]);
          setMsg("当前目录不在范围内，已回到范围根");
          return;
        }
        const res = await api.outputsTree(dirPath);
        const filtered = res.filter((e) => {
          if (scopes.length && !pathInScopes(e.path, scopes)) return false;
          if (e.kind === "dir") return true;
          if (source !== "all" && e.source !== source) return false;
          if (!withinHours(e.mtime, timeRange)) return false;
          return true;
        });
        const byName = q.trim()
          ? filtered.filter((e) =>
              e.name.toLowerCase().includes(q.trim().toLowerCase())
            )
          : filtered;
        setEntries(byName);
        setMsg(byName.length ? `${byName.length} 项` : "空目录");
      }
    } catch (err) {
      console.error(err);
      setEntries([]);
      setMsg("加载失败");
    } finally {
      setLoading(false);
    }
  }, [status, view, source, timeRange, q, dirPath, scopes]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  const openFile = useCallback(async (path: string) => {
    setSelectedPath(path);
    setFileLoading(true);
    try {
      const f = await api.outputsFile(path);
      setFile(f);
      // 树视图定位到父目录，便于继续浏览
      const parent = path.includes("/")
        ? path.split("/").slice(0, -1).join("/")
        : "";
      setView("tree");
      setDirPath(parent);
      console.info("[outputs] openFile ok path=%s", path);
    } catch (err) {
      const detail = err instanceof Error ? err.message : "读取文件失败";
      console.error("[outputs] openFile failed", { path, detail, err });
      setFile(null);
      setMsg(detail.includes("不存在") ? `文件不存在：${path}` : detail);
    } finally {
      setFileLoading(false);
    }
  }, []);

  useEffect(() => {
    const fileParam =
      searchParams.get("file") || searchParams.get("path") || "";
    if (!fileParam) return;
    if (status && !status.readable) return;
    void openFile(fileParam);
  }, [searchParams, status, openFile]);

  const onEntryClick = (e: OutputEntry) => {
    if (e.kind === "dir") {
      setView("tree");
      setDirPath(e.path);
      setSelectedPath(null);
      setFile(null);
      return;
    }
    void openFile(e.path);
  };

  const vaultLabel = status?.root_name
    ? `vault · ${status.root_name}`
    : "OpenClaw / Hermes 文档产出";

  if (status && !status.readable) {
    return (
      <>
        <PageHeader title="输出物" description={vaultLabel} />
        <EmptyState
          title="Vault 不可读"
          description={
            status.message ||
            "请在 .env 配置 OUTPUTS_VAULT_ROOT 指向 Obsidian expe 目录"
          }
          action={
            <button
              type="button"
              onClick={() => void refreshStatus()}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
            >
              重试连接
            </button>
          }
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="输出物"
        description={vaultLabel}
        actions={
          <>
            <button
              type="button"
              onClick={() => void loadList()}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              刷新
            </button>
            <button
              type="button"
              onClick={() => setScopeOpen(true)}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
              title={
                scopes.length
                  ? `已选 ${scopes.length} 个目录`
                  : "限定 Obsidian 文件夹范围"
              }
            >
              定义范围
              {scopes.length > 0 ? ` (${scopes.length})` : ""}
            </button>
          </>
        }
      />

      <ScopeModal
        open={scopeOpen}
        initialScopes={scopes}
        onClose={() => setScopeOpen(false)}
        onSave={(next) => {
          setScopes(next);
          setDirPath("");
          setSelectedPath(null);
          setFile(null);
          console.info("[outputs] scopes updated", next);
        }}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-3">
        <div className="flex rounded-lg border border-slate-700 p-0.5 text-sm">
          <button
            type="button"
            onClick={() => setView("recent")}
            className={`rounded-md px-3 py-1.5 ${
              view === "recent"
                ? "bg-indigo-500/20 text-indigo-200"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            最近
          </button>
          <button
            type="button"
            onClick={() => setView("tree")}
            className={`rounded-md px-3 py-1.5 ${
              view === "tree"
                ? "bg-indigo-500/20 text-indigo-200"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            目录
          </button>
        </div>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value as SourceFilter)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm"
        >
          <option value="all">全部来源</option>
          <option value="openclaw">OpenClaw</option>
          <option value="hermes">Hermes</option>
        </select>
        <select
          value={timeRange}
          onChange={(e) => setTimeRange(Number(e.target.value) as TimeRange)}
          className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-2 text-sm"
          title="按修改时间筛选"
        >
          {TIME_RANGE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="按文件名筛选…"
          className="min-w-[200px] flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
        />
      </div>

      {view === "tree" && (
        <div className="mb-3 flex flex-wrap items-center gap-1 text-xs text-slate-500">
          <button
            type="button"
            onClick={() => setDirPath("")}
            className="rounded px-1.5 py-0.5 hover:bg-slate-800 hover:text-slate-300"
          >
            /
          </button>
          {crumbs.map((c) => (
            <span key={c.path} className="flex items-center gap-1">
              <span>/</span>
              <button
                type="button"
                onClick={() => setDirPath(c.path)}
                className="rounded px-1.5 py-0.5 hover:bg-slate-800 hover:text-slate-300"
              >
                {c.label}
              </button>
            </span>
          ))}
        </div>
      )}

      {msg && <p className="mb-2 text-xs text-slate-500">{msg}</p>}

      <div className="grid h-[calc(100svh-13.5rem)] min-h-[640px] gap-4 lg:grid-cols-[minmax(280px,360px)_1fr]">
        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40">
          {loading ? (
            <p className="p-4 text-sm text-slate-500">加载中…</p>
          ) : entries.length === 0 ? (
            <div className="flex flex-1 items-center justify-center p-4">
              <EmptyState title="无文档" description="调整筛选或切换目录" />
            </div>
          ) : (
            <ul className="min-h-0 flex-1 divide-y divide-slate-800 overflow-y-auto">
              {entries.map((e) => {
                const active = e.kind === "file" && selectedPath === e.path;
                return (
                  <li key={`${e.kind}:${e.path}`}>
                    <button
                      type="button"
                      onClick={() => onEntryClick(e)}
                      className={`flex w-full flex-col gap-0.5 px-3 py-2.5 text-left text-sm transition ${
                        active
                          ? "bg-indigo-500/15 text-indigo-100"
                          : "hover:bg-slate-800/60"
                      }`}
                    >
                      <span className="flex items-center gap-2">
                        <span className="shrink-0 text-slate-500">
                          {fileIcon(e)}
                        </span>
                        <span className="truncate text-slate-200">{e.name}</span>
                      </span>
                      <span className="flex flex-col gap-0.5 pl-6 text-[11px] text-slate-500">
                        {e.kind === "file" && parentPath(e.path) && (
                          <span className="truncate text-slate-600">
                            {parentPath(e.path)}
                          </span>
                        )}
                        <span className="flex flex-wrap gap-2">
                          <span className="uppercase">{e.source}</span>
                          {e.ext && <span>.{e.ext}</span>}
                          {e.kind === "file" && (
                            <>
                              <span>{formatMtime(e.mtime)}</span>
                              <span>{formatSize(e.size)}</span>
                            </>
                          )}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900/40">
          {!selectedPath ? (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState
                title="选择文件预览"
                description={
                  scopes.length
                    ? `当前范围：${scopes.join(" · ")}`
                    : "索引覆盖整个 expe 库（Document / Github / openclaw 等）"
                }
              />
            </div>
          ) : fileLoading ? (
            <p className="p-4 text-sm text-slate-500">读取中…</p>
          ) : !file ? (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState title="无法预览" description="请重试或检查文件权限" />
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="shrink-0 border-b border-slate-800 px-4 py-3">
                <p className="truncate text-sm font-medium text-slate-200">
                  {file.name}
                </p>
                <p className="mt-1 truncate text-xs text-slate-500">
                  <span className="uppercase">{file.source}</span>
                  {" · "}
                  {file.path}
                  {" · "}
                  {formatMtime(file.mtime)}
                  {" · "}
                  {formatSize(file.size)}
                </p>
              </div>
              {file.previewable === false ? (
                <div className="flex flex-1 items-center justify-center p-6">
                  <EmptyState
                    title="二进制文件，无法预览"
                    description={`${file.path} · ${formatSize(file.size)}`}
                  />
                </div>
              ) : isHtml(file) ? (
                <HtmlPreview content={file.content} title={file.name} />
              ) : isMarkdown(file) ? (
                <MarkdownPreview content={file.content} />
              ) : (
                <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-5 font-mono text-xs leading-relaxed text-slate-300">
                  {file.content}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
