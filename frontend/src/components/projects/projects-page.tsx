"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useWorkspace, useWorkspacePaths } from "@/lib/context/workspace-context";
import type { ProjectInfo } from "@/lib/types";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

const COLOR_RING: Record<string, string> = {
  indigo: "border-indigo-500/40 bg-indigo-500/10",
  emerald: "border-emerald-500/40 bg-emerald-500/10",
  amber: "border-amber-500/40 bg-amber-500/10",
  slate: "border-slate-600 bg-slate-800/40",
};

export function ProjectsPage() {
  const wp = useWorkspacePaths();
  const { workspaceId } = useWorkspace();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const router = useRouter();

  const load = () =>
    api
      .projects(workspaceId || undefined)
      .then(setProjects)
      .catch(console.error)
      .finally(() => setLoading(false));

  useEffect(() => {
    if (workspaceId) load();
  }, [workspaceId]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const p = await api.createProject({
        name,
        description,
        workspace_id: workspaceId,
      });
      setShowForm(false);
      setName("");
      setDescription("");
      router.push(wp.projectDetail(p.id));
    } catch {
      alert("创建失败");
    }
  };

  return (
    <>
      <PageHeader
        title="项目"
        description="按业务线组织任务 · 绑定 Repo / 本地目录"
        actions={
          <button
            onClick={() => setShowForm(!showForm)}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
          >
            + 新建项目
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
            placeholder="项目名称"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="描述（可选）"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm">
            创建
          </button>
        </form>
      )}
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : projects.length === 0 ? (
        <EmptyState title="暂无项目" description="在当前工作区创建第一个项目" />
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.map((p) => (
            <Link
              key={p.id}
              href={wp.projectDetail(p.id)}
              className={`rounded-xl border p-5 transition hover:opacity-90 ${COLOR_RING[p.color] || COLOR_RING.slate}`}
            >
              <h3 className="font-semibold">{p.name}</h3>
              {p.description && (
                <p className="mt-1 line-clamp-2 text-sm text-slate-400">
                  {p.description}
                </p>
              )}
              <p className="mt-3 text-xs text-slate-500">
                {p.task_count} 任务 · {p.resource_count} 资源
                {p.lead_id && ` · Lead: ${p.lead_id}`}
              </p>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
