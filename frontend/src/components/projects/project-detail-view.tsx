"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useWorkspacePaths } from "@/lib/context/workspace-context";
import type { ProjectInfo } from "@/lib/types";
import { TaskSurface } from "@/components/task-surface/task-surface";
import { useModal } from "@/lib/context/modal-context";
import { ProjectLeadPicker } from "@/components/pickers/project-lead-picker";
import { ProjectResourcesSection } from "@/components/projects/project-resources-section";

export function ProjectDetailView() {
  const params = useSearchParams();
  const projectId = (params.get("id") || "").trim();
  const wp = useWorkspacePaths();
  const [project, setProject] = useState<ProjectInfo | null>(null);
  const { openCreateTask } = useModal();

  const reload = () =>
    api.project(projectId).then(setProject).catch(console.error);

  useEffect(() => {
    if (!projectId) return;
    reload();
  }, [projectId]);

  const updateLead = async (leadType: string, leadId: string) => {
    if (!project) return;
    const updated = await api.updateProject(project.id, {
      lead_type: leadType,
      lead_id: leadId,
    });
    setProject(updated);
  };

  if (!project) {
    return <p className="text-slate-500">加载中…</p>;
  }

  return (
    <div>
      <Link
        href={wp.projects()}
        className="mb-4 inline-block text-sm text-indigo-400 hover:underline"
      >
        ← 返回项目
      </Link>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{project.name}</h1>
          {project.description && (
            <p className="mt-1 text-sm text-slate-400">{project.description}</p>
          )}
          <p className="mt-2 text-xs text-slate-500">
            {project.task_count} 个任务 · {project.resource_count} 个资源 ·{" "}
            <code>{project.id}</code>
          </p>
        </div>
        <button
          onClick={() => openCreateTask("", projectId)}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
        >
          + 项目内新建任务
        </button>
      </div>

      <div className="mb-6 grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <h2 className="mb-2 text-sm font-medium text-slate-300">项目 Lead</h2>
          <ProjectLeadPicker
            leadType={project.lead_type}
            leadId={project.lead_id}
            onChange={updateLead}
          />
        </div>
      </div>

      <ProjectResourcesSection projectId={projectId} />
      <TaskSurface projectId={projectId} allowGantt />
    </div>
  );
}
