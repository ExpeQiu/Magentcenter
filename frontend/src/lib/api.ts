import type {
  AgentInfo,
  AgentStats,
  AlertSettings,
  AutopilotInfo,
  HealthResponse,
  InstallSkillResult,
  EmbeddingStatus,
  KnowledgeHit,
  KnowledgeInjectPreview,
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
  SkillCapture,
  SkillMineRecord,
  SquadInfo,
  SwarmGraph,
  SystemStatus,
  FleetAgent,
  FleetNode,
  FleetScan,
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

const REQUEST_TIMEOUT_MS = 20_000;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), REQUEST_TIMEOUT_MS);
  try {
    const res = await fetch(`${API_BASE}${url}`, {
      ...init,
      signal: init?.signal ?? ctrl.signal,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(errorMessageFromBody(text, res.status));
    }
    if (res.status === 204) return undefined as T;
    return res.json();
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(`请求超时：${url}`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export interface ContentRootInfo {
  path: string;
  exists: boolean;
  file_count: number;
}

export interface ContentRoots {
  knowledge_wiki_dir: string;
  skills_catalog_dir: string;
  outputs_vault_dir: string;
  knowledge_default: string;
  skills_default: string;
  outputs_default: string;
  knowledge: ContentRootInfo;
  skills: ContentRootInfo;
  outputs: ContentRootInfo;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  contentRoots: () => request<ContentRoots>("/api/settings/content-roots"),
  updateContentRoots: (body: {
    knowledge_wiki_dir?: string;
    skills_catalog_dir?: string;
    outputs_vault_dir?: string;
  }) =>
    request<ContentRoots>("/api/settings/content-roots", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  fleetNodes: (workspaceId = "") => {
    const q = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return request<FleetNode[]>(`/api/fleet/nodes${q}`);
  },
  fleetScan: () => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 90_000);
    return request<FleetScan>("/api/fleet/scan", { signal: ctrl.signal }).finally(() =>
      clearTimeout(timer)
    );
  },
  fleetBind: (body: {
    node_id?: string;
    name?: string;
    workspace_id?: string;
    agents: FleetAgent[];
  }) =>
    request<FleetNode>("/api/fleet/bind", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  fleetUnbind: (nodeId: string) =>
    request<FleetNode | { id: string; removed: boolean }>(
      `/api/fleet/nodes/${encodeURIComponent(nodeId)}`,
      { method: "DELETE" }
    ),
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
      /** 合并 OpenClaw/Hermes 近期 Session 为执行中（默认 true） */
      includeLive?: boolean;
      nodeId?: string;
      remoteOnly?: boolean;
    }
  ) => {
    const q = new URLSearchParams({ page: String(page), page_size: "100" });
    if (opts?.status) q.set("status", opts.status);
    if (opts?.agentId) q.set("agent_id", opts.agentId);
    if (opts?.projectId) q.set("project_id", opts.projectId);
    if (opts?.workspaceId) q.set("workspace_id", opts.workspaceId);
    if (opts?.scheduled) q.set("scheduled", "true");
    if (opts?.includeLive === false) q.set("include_live", "false");
    if (opts?.nodeId) q.set("node_id", opts.nodeId);
    if (opts?.remoteOnly) q.set("remote_only", "true");
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
    node_id?: string;
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
    includeDraft?: boolean;
    runtime?: "openclaw" | "hermes" | "catalog" | "all";
  }) => {
    const q = new URLSearchParams();
    if (opts?.includeHidden) q.set("include_hidden", "true");
    if (opts?.includeArchived) q.set("include_archived", "true");
    if (opts?.includeDraft) q.set("include_draft", "true");
    if (opts?.runtime && opts.runtime !== "all") q.set("runtime", opts.runtime);
    const qs = q.toString();
    return request<SkillInfo[]>(`/api/skills${qs ? `?${qs}` : ""}`);
  },
  skillCaptured: (runtime?: "openclaw" | "hermes" | "all") => {
    const q = new URLSearchParams();
    if (runtime && runtime !== "all") q.set("runtime", runtime);
    const qs = q.toString();
    return request<SkillCapture[]>(`/api/skills/captured${qs ? `?${qs}` : ""}`);
  },
  skillRefine: (captureId: string) =>
    request<SkillMineRecord>(`/api/skills/captured/${encodeURIComponent(captureId)}/refine`, {
      method: "POST",
    }),
  skillVerify: (skillId: string, runtime: "openclaw" | "hermes" = "openclaw") =>
    request<SkillMineRecord>(
      `/api/skills/${encodeURIComponent(skillId)}/verify?runtime=${runtime}`,
      { method: "POST" }
    ),
  skillDetail: (skillId: string, runtime: "openclaw" | "hermes" | "catalog" = "openclaw") => {
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
  refreshAutopilots: () =>
    request<{
      items: AutopilotInfo[];
      count: number;
      pruned_count: number;
      pruned: string[];
      synced_openclaw: number;
      synced_hermes: number;
    }>("/api/autopilots/refresh", { method: "POST" }),
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
    opts?: {
      limit?: number;
      runtime?: string;
      mode?: "keyword" | "vector" | "hybrid";
      kind?: string;
      layer?: string;
      workspaceId?: string;
      includeArchive?: boolean;
    }
  ) => {
    const params = new URLSearchParams({ q });
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.runtime) params.set("runtime", opts.runtime);
    if (opts?.mode) params.set("mode", opts.mode);
    if (opts?.kind) params.set("kind", opts.kind);
    if (opts?.layer) params.set("layer", opts.layer);
    if (opts?.workspaceId) params.set("workspace_id", opts.workspaceId);
    if (opts?.includeArchive) params.set("include_archive", "true");
    return request<KnowledgeHit[]>(`/api/knowledge/search?${params}`);
  },
  knowledgeStatus: () =>
    request<{
      status: string;
      embedding: EmbeddingStatus;
      kinds?: string[];
      inject_default_kinds?: string[];
    }>("/api/knowledge/status"),
  knowledgeList: (opts?: {
    limit?: number;
    kind?: string;
    layer?: string;
    workspaceId?: string;
    runtime?: string;
  }) => {
    const params = new URLSearchParams();
    if (opts?.limit) params.set("limit", String(opts.limit));
    if (opts?.kind) params.set("kind", opts.kind);
    if (opts?.layer) params.set("layer", opts.layer);
    if (opts?.workspaceId) params.set("workspace_id", opts.workspaceId);
    if (opts?.runtime) params.set("runtime", opts.runtime);
    const qs = params.toString();
    return request<KnowledgeHit[]>(`/api/knowledge/entries${qs ? `?${qs}` : ""}`);
  },
  knowledgeBackfill: (limit = 200) =>
    request<{ indexed: number; status: string; embedding?: EmbeddingStatus }>(
      `/api/knowledge/backfill?limit=${limit}`,
      { method: "POST" }
    ),
  knowledgeMineVault: (body?: {
    scope?: string;
    limit?: number;
    distill_high_value?: boolean;
    workspace_id?: string;
  }) =>
    request<{
      status: string;
      scope: string;
      scanned: number;
      artifact_refs: number;
      playbooks: number;
      incidents: number;
      shared_facts: number;
      skipped: number;
      errors: number;
    }>("/api/knowledge/mine-vault", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        scope: body?.scope ?? "openclaw",
        limit: body?.limit ?? 300,
        distill_high_value: body?.distill_high_value ?? true,
        workspace_id: body?.workspace_id ?? "",
      }),
    }),
  knowledgeCreateEntry: (body: {
    kind: string;
    layer?: string;
    facet?: string;
    title: string;
    summary?: string;
    workspace_id?: string;
    tags?: string[];
    payload?: Record<string, unknown>;
  }) =>
    request<KnowledgeHit>("/api/knowledge/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  knowledgeGet: (id: string) =>
    request<KnowledgeHit>(`/api/knowledge/entries/${encodeURIComponent(id)}`),
  knowledgeDeleteEntry: (id: string) =>
    request<{ status: string }>(`/api/knowledge/entries/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }),
  knowledgeInjectPreview: (
    q: string,
    opts?: { workspaceId?: string; runtime?: string; topK?: number; forOps?: boolean }
  ) => {
    const params = new URLSearchParams({ q });
    if (opts?.workspaceId) params.set("workspace_id", opts.workspaceId);
    if (opts?.runtime) params.set("runtime", opts.runtime);
    if (opts?.topK) params.set("top_k", String(opts.topK));
    if (opts?.forOps) params.set("for_ops", "true");
    return request<KnowledgeInjectPreview>(`/api/knowledge/inject-preview?${params}`);
  },
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
