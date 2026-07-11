"use client";

import { PageHeader } from "@/components/layout/page-header";
import { TaskSurface } from "@/components/task-surface/task-surface";
import { QuickStatsBar } from "./quick-stats-bar";
import { useModal } from "@/lib/context/modal-context";

export function TasksPage() {
  const { openCreateTask } = useModal();

  return (
    <>
      <PageHeader
        title="任务"
        description="OpenClaw Agent 任务看板 · 快捷键 C 新建"
        actions={
          <button
            onClick={() => openCreateTask()}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm hover:bg-indigo-500"
          >
            + 新建任务
          </button>
        }
      />
      <QuickStatsBar />
      <TaskSurface />
    </>
  );
}
