"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/context/workspace-context";
import type { ProjectInfo } from "@/lib/types";

interface ProjectPickerProps {
  value: string;
  onChange: (id: string) => void;
  allowEmpty?: boolean;
}

export function ProjectPicker({
  value,
  onChange,
  allowEmpty = true,
}: ProjectPickerProps) {
  const { workspaceId } = useWorkspace();
  const [projects, setProjects] = useState<ProjectInfo[]>([]);

  useEffect(() => {
    if (!workspaceId) return;
    api.projects(workspaceId).then(setProjects).catch(console.error);
  }, [workspaceId]);

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm"
    >
      {allowEmpty && <option value="">无项目</option>}
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}
