"use client";

import type { TaskStatusFilter, TaskViewMode } from "@/lib/types";
import { ProjectPicker } from "@/components/pickers/project-picker";

interface TaskSurfaceHeaderProps {
  viewMode: TaskViewMode;
  onViewModeChange: (m: TaskViewMode) => void;
  statusFilter: TaskStatusFilter;
  onStatusFilterChange: (s: TaskStatusFilter) => void;
  agentFilter: string;
  onAgentFilterChange: (id: string) => void;
  projectFilter: string;
  onProjectFilterChange: (id: string) => void;
  hideProjectFilter?: boolean;
  allowGantt?: boolean;
  search: string;
  onSearchChange: (s: string) => void;
  total: number;
}

const STATUS_OPTIONS: { value: TaskStatusFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "queued", label: "排队" },
  { value: "running", label: "执行中" },
  { value: "completed", label: "完成" },
  { value: "failed", label: "失败" },
];

export function TaskSurfaceHeader({
  viewMode,
  onViewModeChange,
  statusFilter,
  onStatusFilterChange,
  agentFilter,
  onAgentFilterChange,
  projectFilter,
  onProjectFilterChange,
  hideProjectFilter,
  allowGantt,
  search,
  onSearchChange,
  total,
}: TaskSurfaceHeaderProps) {
  return (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex items-center gap-2">
        <div className="flex rounded-lg border border-slate-700 p-0.5">
          {(["list", "board", ...(allowGantt ? (["gantt"] as const) : [])] as TaskViewMode[]).map(
            (m) => (
            <button
              key={m}
              onClick={() => onViewModeChange(m)}
              className={`rounded-md px-3 py-1 text-xs font-medium ${
                viewMode === m
                  ? "bg-indigo-600 text-white"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              {m === "list" ? "列表" : m === "board" ? "看板" : "Gantt"}
            </button>
          ))}
        </div>
        <span className="text-xs text-slate-500">{total} 条任务</span>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {!hideProjectFilter && (
          <div className="w-36">
            <ProjectPicker
              value={projectFilter}
              onChange={onProjectFilterChange}
            />
          </div>
        )}
        <input
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          placeholder="搜索任务…"
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
        />
        <input
          value={agentFilter}
          onChange={(e) => onAgentFilterChange(e.target.value)}
          placeholder="Agent ID"
          className="w-28 rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
        />
        <select
          value={statusFilter}
          onChange={(e) =>
            onStatusFilterChange(e.target.value as TaskStatusFilter)
          }
          className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-sm"
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
