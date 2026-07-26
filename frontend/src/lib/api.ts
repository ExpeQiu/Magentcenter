import type {
  AgentInfo,
  AgentStats,
  AlertSettings,
  AutopilotInfo,
  HealthResponse,
  InstallSkillResult,
  EmbeddingStatus,
  KnowledgeHit,
  KanbanBoard,
  KanbanTask,
  OutputEntry,
  OutputFile,
  OutputStatus,
  ProjectInfo,
  ProjectResourceInfo,
  RecentAlert,
  SessionDetail,
  SessionInfo,
  SkillDetail,
  SkillInfo,
  SquadInfo,
  SwarmGraph,
  SystemStatus,
  TaskInfo,
  TaskListResponse,
  WorkspaceInfo,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "";

function errorMessageFromBody(text: string, status: number): string {
  if (!text) return `Request failed: ${status}`;
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail.trim()) {
      return parsed.detail;
    }
  } catch {
    /* plain text */
  }
  return text;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(errorMessageFromBody(text, res.status));
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
    runtime?: "openclaw" | "hermes";
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
  skills: (opts?: {
    includeHidden?: boolean;
    includeArchived?: boolean;
    runtime?: "openclaw" | "hermes" | "all";
  }) => {
    const q = new URLSearchParams();
    if (opts?.includeHidden) q.set("include_hidden", "true");
    if (opts?.includeArchived) q.set("include_archived", "true");
    if (opts?.runtime && opts.runtime !== "all") q.set("runtime", opts.runtime);
    const qs = q.toString();
    return request<SkillInfo[]>(`/api/skills${qs ? `?${qs}` : ""}`);
  },
  skillDetail: (skillId: string, runtime: "openclaw" | "hermes" = "openclaw") => {
    const path = skillId.split("/").map(encodeURIComponent).join("/");
    return request<SkillDetail>(`/api/skills/${path}?runtime=${runtime}`);
  },
  installSkill: (data: {
    url?: string;
    name?: string;
    instructions?: string;
    runtime?: "openclaw" | "hermes";
    category?: string;
    force?: boolean;
  }) =>
    request<InstallSkillResult>("/api/skills/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  alertSettings: () => request<AlertSettings>("/api/settings/alert"),
  updateAlertSettings: (data: {
    feishu_webhook_url?: string;
    cron_alert_interval?: number;
    cron_alert_enabled?: boolean;
    gateway_alert_enabled?: boolean;
    disk_alert_threshold?: number;
    profile?: string;
    activate?: boolean;
  }) =>
    request<{
      updated: string[];
      status: string;
      persisted?: boolean;
      profile?: string;
      settings: AlertSettings;
    }>("/api/settings/alert", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  alertProfiles: () =>
    request<{ active: string; profiles: string[] }>("/api/settings/alert/profiles"),
  createAlertProfile: (data: {
    name: string;
    from_current?: boolean;
    activate?: boolean;
  }) =>
    request<{ status: string; active: string; profiles: string[]; settings: AlertSettings }>(
      "/api/settings/alert/profiles",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      }
    ),
  activateAlertProfile: (name: string) =>
    request<{ status: string; active: string; settings: AlertSettings }>(
      `/api/settings/alert/profiles/${encodeURIComponent(name)}/activate`,
      { method: "POST" }
    ),
  auditSkill: (skillId: string) =>
    request<TaskInfo>("/api/skills/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_id: skillId }),
    }),
  archiveSkill: (
    skillId: string,
    runtime: "openclaw" | "hermes" = "openclaw"
  ) => {
    const path = skillId.split("/").map(encodeURIComponent).join("/");
    return request<SkillDetail>(`/api/skills/${path}/archive?runtime=${runtime}`, {
      method: "POST",
    });
  },
  systemStatus: (refresh = false) =>
    request<SystemStatus>(`/api/system-status?refresh=${refresh}`),
  repairCron: (cronId: string, data?: { note?: string; workspace_id?: string }) =>
    request<TaskInfo>(`/api/cron/${encodeURIComponent(cronId)}/repair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    }),
  sessions: (limit = 50) =>
    request<SessionInfo[]>(`/api/sessions?limit=${limit}`),
  sessionDetail: (sessionId: string) =>
    request<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  recentAlerts: () =>
    request<{
      errors: unknown[];
      recent_alerts: RecentAlert[];
      gateway_alerts?: RecentAlert[];
    }>("/api/cron-alerts"),
  autopilots: (includeOpenclaw = true, includeHermes = true) =>
    request<AutopilotInfo[]>(
      `/api/autopilots?include_openclaw=${includeOpenclaw}&include_hermes=${includeHermes}`
    ),
  createAutopilot: (data: {
    name: string;
    agent_id: string;
    prompt: string;
    cron?: string;
    runtime?: "openclaw" | "hermes";
    sync_to_openclaw?: boolean;
    sync_to_hermes?: boolean;
  }) =>
    request<AutopilotInfo>("/api/autopilots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  triggerAutopilot: (id: string) =>
    request<TaskInfo>(`/api/autopilots/${encodeURIComponent(id)}/trigger`, {
      method: "POST",
    }),
  kanbanBoards: () => request<KanbanBoard[]>("/api/kanban/boards"),
  kanbanTasks: (opts?: { status?: string; assignee?: string }) => {
    const q = new URLSearchParams();
    if (opts?.status) q.set("status", opts.status);
    if (opts?.assignee) q.set("assignee", opts.assignee);
    const qs = q.toString();
    return request<KanbanTask[]>(`/api/kanban/tasks${qs ? `?${qs}` : ""}`);
  },
  createKanbanTask: (data: {
    title: string;
    body?: string;
    assignee?: string;
    priority?: number;
    triage?: boolean;
  }) =>
    request<KanbanTask>("/api/kanban/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  runKanbanTask: (id: string, data?: { prompt?: string; agent_id?: string }) =>
    request<TaskInfo>(`/api/kanban/tasks/${encodeURIComponent(id)}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data || {}),
    }),
  createSwarm: (data: {
    goal: string;
    workers: string[];
    verifier?: string;
    synthesizer?: string;
    priority?: number;
    created_by?: string;
  }) =>
    request<SwarmGraph>("/api/kanban/swarm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }),
  getSwarm: (rootId: string) =>
    request<SwarmGraph>(`/api/kanban/swarm/${encodeURIComponent(rootId)}`),
  knowledgeSearch: (
    q: string,
    opts?: { limit?: number; runtime?: string; mode?: "keyword" | "vector" | "hybrid" }
  ) => {
    const params = new URLSearchParams({ q });
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.runtime) params.set("runtime", opts.runtime);
    if (opts?.mode) params.set("mode", opts.mode);
    return request<KnowledgeHit[]>(`/api/knowledge/search?${params}`);
  },
  knowledgeStatus: () =>
    request<{ status: string; embedding: EmbeddingStatus }>("/api/knowledge/status"),
  knowledgeBackfill: (limit = 200) =>
    request<{ indexed: number; status: string; embedding?: EmbeddingStatus }>(
      `/api/knowledge/backfill?limit=${limit}`,
      { method: "POST" }
    ),
  indexSession: (sessionId: string) =>
    request<{ status: string; session_id: string; indexed: number; runtime?: string }>(
      `/api/knowledge/index-session/${encodeURIComponent(sessionId)}`,
      { method: "POST" }
    ),
  outputsStatus: () => request<OutputStatus>("/api/outputs/status"),
  outputsTree: (path = "") => {
    const params = new URLSearchParams();
    if (path) params.set("path", path);
    const qs = params.toString();
    return request<OutputEntry[]>(`/api/outputs/tree${qs ? `?${qs}` : ""}`);
  },
  outputsRecent: (opts?: {
    limit?: number;
    source?: "openclaw" | "hermes";
    q?: string;
    since_hours?: number;
    /** 相对 vault 的目录范围，可多选 */
    scopes?: string[];
  }) => {
    const params = new URLSearchParams();
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.source) params.set("source", opts.source);
    if (opts?.q) params.set("q", opts.q);
    if (opts?.since_hours != null) {
      params.set("since_hours", String(opts.since_hours));
    }
    for (const s of opts?.scopes || []) {
      const cleaned = s.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
      if (cleaned) params.append("scopes", cleaned);
    }
    const qs = params.toString();
    return request<OutputEntry[]>(`/api/outputs/recent${qs ? `?${qs}` : ""}`);
  },
  outputsFile: (path: string) =>
    request<OutputFile>(
      `/api/outputs/file?path=${encodeURIComponent(path)}`
    ),
};
