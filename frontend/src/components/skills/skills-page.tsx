"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SkillInfo } from "@/lib/types";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState } from "@/components/ui/empty-state";

export function SkillsPage() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .skills()
      .then(setSkills)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = skills.filter(
    (s) => !filter || s.id.includes(filter) || s.name.includes(filter)
  );

  return (
    <>
      <PageHeader
        title="技能目录"
        description={`~/.openclaw/skills 共 ${skills.length} 个技能`}
        actions={
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="搜索技能…"
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
          />
        }
      />
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
              <p className="font-mono text-sm font-medium text-slate-200">
                {s.id}
              </p>
              {s.description && (
                <p className="mt-1 line-clamp-2 text-xs text-slate-500">
                  {s.description}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}
