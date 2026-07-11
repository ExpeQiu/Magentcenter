"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { SkillInfo } from "@/lib/types";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [installUrl, setInstallUrl] = useState("");
  const [showInstall, setShowInstall] = useState(false);
  const router = useRouter();
  const wp = useWorkspacePaths();

  const load = () =>
    api
      .skills()
      .then(setSkills)
      .catch(console.error)
      .finally(() => setLoading(false));

  useEffect(() => {
    load();
  }, []);

  const install = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const task = await api.installSkill({ url: installUrl });
      setShowInstall(false);
      setInstallUrl("");
      router.push(wp.taskDetail(task.id));
    } catch {
      alert("安装任务创建失败");
    }
  };

  const audit = async (skillId: string) => {
    try {
      const task = await api.auditSkill(skillId);
      router.push(wp.taskDetail(task.id));
    } catch {
      alert("审核任务创建失败");
    }
  };

  const filtered = skills.filter(
    (s) => !filter || s.id.includes(filter) || s.name.includes(filter)
  );

  return (
    <>
      <PageHeader
        title="技能目录"
        description={`~/.openclaw/skills 共 ${skills.length} 个技能`}
        actions={
          <div className="flex gap-2">
            <input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索技能…"
              className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
            />
            <button
              onClick={() => setShowInstall(!showInstall)}
              className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
            >
              安装
            </button>
          </div>
        }
      />
      {showInstall && (
        <form
          onSubmit={install}
          className="mb-6 flex gap-2 rounded-xl border border-slate-800 bg-slate-900/50 p-4"
        >
          <input
            value={installUrl}
            onChange={(e) => setInstallUrl(e.target.value)}
            placeholder="技能 URL 或名称"
            className="flex-1 rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
          />
          <button type="submit" className="rounded-lg bg-indigo-600 px-4 py-2 text-sm">
            提交安装
          </button>
        </form>
      )}
      {loading ? (
        <p className="text-slate-500">加载中…</p>
      ) : filtered.length === 0 ? (
        <EmptyState title="未找到技能" />
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((s) => (
            <div
              key={s.id}
              className="rounded-lg border border-slate-800 bg-slate-900/40 p-4"
            >
              <p className="font-mono text-sm font-medium text-slate-200">{s.id}</p>
              {s.description && (
                <p className="mt-1 line-clamp-2 text-xs text-slate-500">{s.description}</p>
              )}
              <button
                onClick={() => audit(s.id)}
                className="mt-2 text-xs text-indigo-400 hover:underline"
              >
                审核
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
