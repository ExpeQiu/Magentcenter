"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { OutputEntry } from "@/lib/types";

export const OUTPUTS_SCOPES_KEY = "agentcenter.outputs.scopes";

/** expe 库一级目录；其余视为旧 openclaw 根下的相对路径 */
const EXPE_TOP_LEVEL = new Set([
  "Document",
  "Github",
  "myKW",
  "openclaw",
  "综合附件区",
]);

function migrateScopePath(raw: string, extraRootNames: Set<string> = new Set()): string {
  const cleaned = raw.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  if (!cleaned) return "";
  const parts = cleaned.split("/").filter(Boolean);
  const first = parts[0];
  if (EXPE_TOP_LEVEL.has(first) || extraRootNames.has(first)) return cleaned;
  if (first === "openclaw" && parts[1] && extraRootNames.has(parts[1])) {
    return parts.slice(1).join("/");
  }
  return `openclaw/${cleaned}`;
}

export function loadScopes(extraRootNames: string[] = []): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(OUTPUTS_SCOPES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    const extra = new Set(extraRootNames);
    const migrated = [
      ...new Set(
        parsed
          .filter((x): x is string => typeof x === "string")
          .map((s) => migrateScopePath(s, extra))
          .filter(Boolean)
      ),
    ];
    const original = parsed
      .filter((x): x is string => typeof x === "string")
      .map((s) => s.replace(/\\/g, "/").replace(/^\/+|\/+$/g, ""))
      .filter(Boolean);
    if (JSON.stringify(migrated) !== JSON.stringify(original)) {
      localStorage.setItem(OUTPUTS_SCOPES_KEY, JSON.stringify(migrated));
      console.info("[outputs] migrated legacy scopes", original, "->", migrated);
    }
    return migrated;
  } catch {
    return [];
  }
}

export function saveScopes(scopes: string[]): void {
  const cleaned = [...new Set(scopes.map((s) => s.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "")).filter(Boolean))];
  localStorage.setItem(OUTPUTS_SCOPES_KEY, JSON.stringify(cleaned));
}

interface ScopeModalProps {
  open: boolean;
  initialScopes: string[];
  onClose: () => void;
  onSave: (scopes: string[]) => void;
}

export function ScopeModal({
  open,
  initialScopes,
  onClose,
  onSave,
}: ScopeModalProps) {
  const [draft, setDraft] = useState<string[]>([]);
  const [browsePath, setBrowsePath] = useState("");
  const [dirs, setDirs] = useState<OutputEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [manual, setManual] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    setDraft([...initialScopes]);
    setBrowsePath("");
    setManual("");
    setErr("");
  }, [open, initialScopes]);

  const loadDirs = useCallback(async (path: string) => {
    setLoading(true);
    setErr("");
    try {
      const entries = await api.outputsTree(path);
      setDirs(entries.filter((e) => e.kind === "dir"));
    } catch (e) {
      console.error(e);
      setDirs([]);
      setErr("目录加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void loadDirs(browsePath);
  }, [open, browsePath, loadDirs]);

  const crumbs = useMemo(() => {
    if (!browsePath) return [] as { label: string; path: string }[];
    const parts = browsePath.split("/").filter(Boolean);
    return parts.map((label, i) => ({
      label,
      path: parts.slice(0, i + 1).join("/"),
    }));
  }, [browsePath]);

  const toggle = (path: string) => {
    setDraft((prev) =>
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]
    );
  };

  const addManual = () => {
    const cleaned = manual.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "").trim();
    if (!cleaned) return;
    if (cleaned.includes("..")) {
      setErr("路径不能包含 ..");
      return;
    }
    setDraft((prev) => (prev.includes(cleaned) ? prev : [...prev, cleaned]));
    setManual("");
    setErr("");
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[85vh] w-full max-w-xl flex-col rounded-xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex shrink-0 items-center justify-between border-b border-slate-800 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">定义范围</h2>
            <p className="mt-0.5 text-xs text-slate-500">
              根目录为 Obsidian expe，另可挂 iCloud/本地额外文件夹；可逐级勾选。空=整库。
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200"
          >
            ✕
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
          <div>
            <p className="mb-1.5 text-xs text-slate-400">已选范围</p>
            {draft.length === 0 ? (
              <p className="rounded-lg border border-dashed border-slate-700 px-3 py-2 text-xs text-slate-500">
                未限定（整库）
              </p>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {draft.map((s) => (
                  <li key={s}>
                    <button
                      type="button"
                      onClick={() => toggle(s)}
                      className="rounded-md border border-indigo-500/40 bg-indigo-500/10 px-2 py-1 text-xs text-indigo-200 hover:bg-indigo-500/20"
                      title="点击移除"
                    >
                      {s} ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="flex gap-2">
            <input
              value={manual}
              onChange={(e) => setManual(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addManual();
                }
              }}
              placeholder="手动输入相对路径，如 openclaw/千岛湖团队"
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
            />
            <button
              type="button"
              onClick={addManual}
              className="shrink-0 rounded-lg border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800"
            >
              添加
            </button>
          </div>

          <div className="rounded-lg border border-slate-800 bg-slate-950/50">
            <div className="flex flex-wrap items-center gap-1 border-b border-slate-800 px-3 py-2 text-xs text-slate-500">
              <button
                type="button"
                onClick={() => setBrowsePath("")}
                className="rounded px-1.5 py-0.5 hover:bg-slate-800 hover:text-slate-300"
              >
                /
              </button>
              {crumbs.map((c) => (
                <span key={c.path} className="flex items-center gap-1">
                  <span>/</span>
                  <button
                    type="button"
                    onClick={() => setBrowsePath(c.path)}
                    className="rounded px-1.5 py-0.5 hover:bg-slate-800 hover:text-slate-300"
                  >
                    {c.label}
                  </button>
                </span>
              ))}
            </div>
            {loading ? (
              <p className="p-3 text-sm text-slate-500">加载中…</p>
            ) : dirs.length === 0 ? (
              <p className="p-3 text-sm text-slate-500">无子目录</p>
            ) : (
              <ul className="max-h-56 divide-y divide-slate-800 overflow-y-auto">
                {dirs.map((d) => {
                  const checked = draft.includes(d.path);
                  return (
                    <li
                      key={d.path}
                      className="flex items-center gap-2 px-3 py-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(d.path)}
                        className="accent-indigo-500"
                        id={`scope-${d.path}`}
                      />
                      <label
                        htmlFor={`scope-${d.path}`}
                        className="min-w-0 flex-1 cursor-pointer truncate text-slate-200"
                      >
                        📁 {d.name}
                      </label>
                      <button
                        type="button"
                        onClick={() => setBrowsePath(d.path)}
                        className="shrink-0 text-xs text-slate-500 hover:text-slate-300"
                      >
                        进入
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          {err && <p className="text-xs text-rose-400">{err}</p>}
        </div>

        <div className="flex shrink-0 items-center justify-between gap-2 border-t border-slate-800 px-5 py-3">
          <button
            type="button"
            onClick={() => setDraft([])}
            className="text-sm text-slate-500 hover:text-slate-300"
          >
            清空（整库）
          </button>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => {
                saveScopes(draft);
                onSave(draft);
                onClose();
              }}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm text-white hover:bg-indigo-500"
            >
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
