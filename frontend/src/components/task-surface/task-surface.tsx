"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/context/workspace-context";
import { usePersistedState } from "@/lib/hooks/use-persisted-state";
import type { TaskInfo, TaskStatusFilter, TaskViewMode } from "@/lib/types";
import { EmptyState } from "@/components/ui/empty-state";
import { useModal } from "@/lib/context/modal-context";
import { TaskSurfaceHeader } from "./task-surface-header";
import { TaskListView } from "./task-list-view";
import { TaskBoardView } from "./task-board-view";
import { TaskGanttView } from "./task-gantt-view";

interface TaskSurfaceProps {
  agentId?: string;
  projectId?: string;
  /** 项目详情页启用 Gantt */
  allowGantt?: boolean;
}

export function TaskSurface({
  agentId,
  projectId,
  allowGantt = false,
}: TaskSurfaceProps) {
  const { openCreateTask } = useModal();
  const { workspaceId } = useWorkspace();
  const [viewMode, setViewMode] = usePersistedState<TaskViewMode>(
    projectId ? `agentcenter:task-view-${projectId}` : "agentcenter:task-view-mode",
    "list"
  );
  const [statusFilter, setStatusFilter] = usePersistedState<TaskStatusFilter>(
    "agentcenter:task-status-filter",
    "all"
  );
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [agentFilter, setAgentFilter] = useState(agentId || "");
  const [projectFilter, setProjectFilter] = useState(projectId || "");

  const load = useCallback(async () => {
    try {
      const status = statusFilter === "all" ? undefined : statusFilter;
      const res = await api.tasks(1, {
        status,
        agentId: agentFilter || undefined,
        projectId: projectFilter || undefined,
        workspaceId: workspaceId || undefined,
        scheduled: viewMode === "gantt",
      });
      setTasks(res.items);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, agentFilter, projectFilter, workspaceId, viewMode]);

  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [load]);

  const filtered = useMemo(() => {
    if (!search) return tasks;
    const q = search.toLowerCase();
    return tasks.filter(
      (t) =>
        t.prompt.toLowerCase().includes(q) ||
        t.agent_id.toLowerCase().includes(q)
    );
  }, [tasks, search]);

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center text-slate-500">
        加载任务…
      </div>
    );
  }

  const isEmpty = viewMode !== "gantt" && filtered.length === 0;

  return (
    <div>
      <TaskSurfaceHeader
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        agentFilter={agentFilter}
        onAgentFilterChange={setAgentFilter}
        projectFilter={projectFilter}
        onProjectFilterChange={setProjectFilter}
        hideProjectFilter={!!projectId}
        allowGantt={allowGantt}
        search={search}
        onSearchChange={setSearch}
        total={filtered.length}
      />
      {isEmpty ? (
        <EmptyState
          title="暂无任务"
          description="分配第一个任务给你的 OpenClaw Agent"
          action={
            <button
              onClick={() => openCreateTask(agentFilter, projectFilter)}
              className="rounded-lg bg-indigo-600 px-4 py-2 text-sm hover:bg-indigo-500"
            >
              新建任务
            </button>
          }
        />
      ) : viewMode === "gantt" ? (
        <TaskGanttView tasks={filtered} />
      ) : viewMode === "board" ? (
        <TaskBoardView tasks={filtered} />
      ) : (
        <TaskListView tasks={filtered} />
      )}
    </div>
  );
}
