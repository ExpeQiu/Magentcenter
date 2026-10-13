"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import type { SopInfo } from "@/lib/types";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export function SopsPage() {
  const wp = useWorkspacePaths();
  const { workspaceId } = useWorkspace();
  const [items, setItems] = useState<SopInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const router = useRouter();

  const load = () =>
    api
      .sops(workspaceId || undefined)
      .then(setItems)
      .catch(console.error)
      .finally(() => setLoading(false));

  useEffect(() => {
    if (workspaceId) load();
  }, [workspaceId]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const sop = await api.createSop({
        name,
        description,
        workspace_id: workspaceId,
      });
      setShowForm(false);
      setName("");
      setDescription("");
      router.push(wp.projectDetail(sop.id));
    } catch (err) {
      alert(err instanceof Error ? err.message : "创建失败");
    }
  };

  return (
    <>
      <PageHeader
        title="SOP 工作流"
        description="按步骤定义标准流程，运行时依次派给 Agent"
        actions={
          <button
            onClick={() => setShowForm(!showForm)}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
          >
            + 新建 SOP
          </button>
        }
      />
      {showForm && (
        <form
          onSubmit={create}
          className="mb-6 space-y-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
        >
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="流程名称"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="何时使用（可选）"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm">
            创建
          </button>
        </form>
      )}
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : items.length === 0 ? (
        <EmptyState title="暂无 SOP" description="先建一条流程，再按顺序添加步骤" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((sop) => (
            <Link
              key={sop.id}
              href={wp.projectDetail(sop.id)}
              className="rounded-xl border border-slate-700 bg-slate-900/40 p-5 transition hover:border-indigo-500/40"
            >
              <h3 className="font-semibold">{sop.name}</h3>
              {sop.description && (
                <p className="mt-1 line-clamp-2 text-sm text-slate-400">{sop.description}</p>
              )}
              <p className="mt-3 text-xs text-slate-500">
                {sop.step_count} 步 · 已运行 {sop.run_count} 次
              </p>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
