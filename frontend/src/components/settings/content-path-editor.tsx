"use client";

import { useEffect, useState } from "react";
import { api, type ContentRoots } from "@/lib/api";

type Kind = "knowledge" | "skills" | "outputs";

const FIELDS: Record<
  Kind,
  {
    value: keyof ContentRoots;
    info: keyof ContentRoots;
    fallback: keyof ContentRoots;
    label: string;
    hint: string;
  }
> = {
  knowledge: {
    value: "knowledge_wiki_dir",
    info: "knowledge",
    fallback: "knowledge_default",
    label: "知识库目录",
    hint: "默认读取 iCloud / WaytoAI / personalwiki",
  },
  skills: {
    value: "skills_catalog_dir",
    info: "skills",
    fallback: "skills_default",
    label: "技能目录",
    hint: "默认读取 iCloud / WaytoAI / skills",
  },
  outputs: {
    value: "outputs_vault_dir",
    info: "outputs",
    fallback: "outputs_default",
    label: "输出物目录",
    hint: "默认读取 iCloud / Obsidian / expe",
  },
};

export function ContentPathEditor({
  kind,
  onSaved,
}: {
  kind: Kind;
  onSaved?: () => void;
}) {
  const field = FIELDS[kind];
  const [roots, setRoots] = useState<ContentRoots | null>(null);
  const [draft, setDraft] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const apply = (data: ContentRoots) => {
    setRoots(data);
    setDraft(String(data[field.value] || ""));
  };

  useEffect(() => {
    api
      .contentRoots()
      .then((data) => {
        apply(data);
        const info = data[field.info] as ContentRoots["knowledge"];
        console.info("[content-roots] loaded", kind, info.path, info.exists, info.file_count);
      })
      .catch((err) => {
        console.error("[content-roots] load failed", err);
        setMsg("无法读取路径");
      });
  }, [kind]);

  const save = async (next: string) => {
    setBusy(true);
    setMsg("");
    try {
      const data = await api.updateContentRoots({ [field.value]: next });
      apply(data);
      const info = data[field.info] as ContentRoots["knowledge"];
      setMsg(info.exists ? `已保存，读到 ${info.file_count} 个文件` : "已保存，但目录不存在");
      console.info("[content-roots] saved", kind, info.path, info.exists);
      onSaved?.();
    } catch (err) {
      console.error("[content-roots] save failed", err);
      setMsg(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  const info = roots ? (roots[field.info] as ContentRoots["knowledge"]) : null;
  const fallback = roots ? String(roots[field.fallback] || "") : "";
  const label = field.label;
  const hint = field.hint;

  return (
    <section className="mb-4 rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-slate-200">{label}</p>
          <p className="mt-1 text-xs text-slate-500">{hint}</p>
        </div>
        {info && (
          <p className={info.exists ? "text-xs text-emerald-300" : "text-xs text-amber-200"}>
            {info.exists ? `可读 · ${info.file_count} 个文件` : "目录不存在"}
          </p>
        )}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={fallback}
          className="min-w-[16rem] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-sm text-slate-100"
        />
        <button
          type="button"
          disabled={busy || !draft.trim()}
          onClick={() => void save(draft.trim())}
          className="rounded-lg bg-sky-500 px-3 py-1.5 text-sm font-medium text-slate-950 disabled:opacity-50"
        >
          保存
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void save("")}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-300 disabled:opacity-50"
        >
          恢复默认
        </button>
      </div>
      {msg && <p className="mt-2 text-xs text-slate-400">{msg}</p>}
    </section>
  );
}
