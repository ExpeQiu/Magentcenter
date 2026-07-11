import type {
  AgentInfo,
  AgentStats,
  AutopilotInfo,
  HealthResponse,
  ProjectInfo,
  ProjectResourceInfo,
  RecentAlert,
  SessionDetail,
  SessionInfo,
  SkillInfo,
  SquadInfo,
  SystemStatus,
  TaskInfo,
  TaskListResponse,
  WorkspaceInfo,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed: ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  workspaces: () => request<WorkspaceInfo[]>("/api/workspaces"),
  workspaceBySlug: (slug: string) =>
    request<WorkspaceInfo>(`/api/workspaces/by-slug/${encodeURIComponent(slug)}`),
  agents: (refresh = false) =>
    request<AgentInfo[]>(`/api/agents?refresh=${refresh}`),
  agentStats: () => request<AgentStats[]>("/api/agents/stats"),
  agent: (id: string) => request<AgentInfo>(`/api/agents/${id}`),
  tasks: (
    page = 1,
    opts?: {
      status?: string;
      agentId?: string;
      projectId?: string;
      workspaceId?: string;
      scheduled?: boolean;
    }
  ) => {
    const q = new URLSearchParams({ page: String(page), page_size: "100" });
    if (opts?.status) q.set("status", opts.status);
    if (opts?.agentId) q.set("agent_id", opts.agentId);
    if (opts?.projectId) q.set("project_id", opts.projectId);
    if (opts?.workspaceId) q.set("workspace_id", opts.workspaceId);
    if (opts?.scheduled) q.set("scheduled", "true");
    return request<TaskListResponse>(`/api/tasks?${q}`);
  },
  task: (id: string) => request<TaskInfo>(`/api/tasks/${id}`),
  createTask: (data: {
    agent_id: string;
    prompt: string;
    system_prompt?: string;
    workspace_id?: string;
    project_id?: string;
    start_date?: string;
    due_date?: string;
  }) =>
    request<TaskInfo>("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateTask: (
    id: string,
    data: { start_date?: string; due_date?: string; project_id?: string }
  ) =>
    request<TaskInfo>(`/api/tasks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  cancelTask: (id: string) =>
    request<TaskInfo>(`/api/tasks/${id}/cancel`, { method: "POST" }),
  retryTask: (id: string) =>
    request<TaskInfo>(`/api/tasks/${id}/retry`, { method: "POST" }),
  squads: () => request<SquadInfo[]>("/api/squads"),
  projects: (workspaceId?: string) => {
    const q = workspaceId
      ? `?workspace_id=${encodeURIComponent(workspaceId)}`
      : "";
    return request<ProjectInfo[]>(`/api/projects${q}`);
  },
  project: (id: string) => request<ProjectInfo>(`/api/projects/${id}`),
  createProject: (data: {
    name: string;
    description?: string;
    color?: string;
    workspace_id?: string;
    lead_type?: string;
    lead_id?: string;
  }) =>
    request<ProjectInfo>("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  updateProject: (
    id: string,
    data: {
      name?: string;
      description?: string;
      lead_type?: string;
      lead_id?: string;
    }
  ) =>
    request<ProjectInfo>(`/api/projects/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  projectResources: (projectId: string) =>
    request<ProjectResourceInfo[]>(`/api/projects/${projectId}/resources`),
  createProjectResource: (
    projectId: string,
    data: {
      resource_type: "github_repo" | "local_directory";
      label?: string;
      ref: Record<string, string>;
    }
  ) =>
    request<ProjectResourceInfo>(`/api/projects/${projectId}/resources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  deleteProjectResource: (projectId: string, resourceId: string) =>
    request<void>(`/api/projects/${projectId}/resources/${resourceId}`, {
      method: "DELETE",
    }),
  squad: (id: string) => request<SquadInfo>(`/api/squads/${id}`),
  createSquadTask: (squadId: string, prompt: string) =>
    request<TaskInfo>("/api/squads/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ squad_id: squadId, prompt }),
    }),
  skills: () => request<SkillInfo[]>("/api/skills"),
  installSkill: (data: { url?: string; name?: string; instructions?: string }) =>
    request<TaskInfo>("/api/skills/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  auditSkill: (skillId: string) =>
    request<TaskInfo>("/api/skills/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_id: skillId }),
    }),
  systemStatus: (refresh = false) =>
    request<SystemStatus>(`/api/system-status?refresh=${refresh}`),
  sessions: (limit = 50) =>
    request<SessionInfo[]>(`/api/sessions?limit=${limit}`),
  sessionDetail: (sessionId: string) =>
    request<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  recentAlerts: () =>
    request<{ errors: unknown[]; recent_alerts: RecentAlert[] }>("/api/cron-alerts"),
  autopilots: (includeOpenclaw = true) =>
    request<AutopilotInfo[]>(
      `/api/autopilots?include_openclaw=${includeOpenclaw}`
    ),
  createAutopilot: (data: {
    name: string;
    agent_id: string;
    prompt: string;
    cron?: string;
    sync_to_openclaw?: boolean;
  }) =>
    request<AutopilotInfo>("/api/autopilots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  triggerAutopilot: (id: string) =>
    request<TaskInfo>(`/api/autopilots/${id}/trigger`, { method: "POST" }),
};
