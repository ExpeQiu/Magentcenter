export interface AgentInfo {
  id: string;
  name: string;
  model: string;
  workspace: string;
  identity_name: string;
  identity_emoji: string;
  is_default: boolean;
}

export interface WorkspaceInfo {
  id: string;
  slug: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
}

export interface TaskInfo {
  id: string;
  workspace_id: string;
  project_id: string;
  agent_id: string;
  prompt: string;
  system_prompt: string;
  status: string;
  session_id: string;
  output: string;
  error: string;
  duration_ms: number;
  start_date: string;
  due_date: string;
  created_at: string;
  updated_at: string;
}

export interface TaskListResponse {
  items: TaskInfo[];
  total: number;
  page: number;
  page_size: number;
}

export interface SquadInfo {
  id: string;
  name: string;
  leader: string;
  members: string[];
  description: string;
}

export interface SkillInfo {
  id: string;
  name: string;
  path: string;
  description: string;
}

export interface GithubRepoRef {
  url: string;
  ref: string;
  default_branch_hint?: string;
}

export interface LocalDirectoryRef {
  local_path: string;
  label?: string;
}

export interface ProjectResourceInfo {
  id: string;
  project_id: string;
  workspace_id: string;
  resource_type: "github_repo" | "local_directory";
  label: string;
  position: number;
  ref: GithubRepoRef | LocalDirectoryRef;
  created_at: string;
  updated_at: string;
}

export interface ProjectInfo {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  color: string;
  lead_type: string;
  lead_id: string;
  task_count: number;
  resource_count: number;
  created_at: string;
  updated_at: string;
}

export interface AutopilotInfo {
  id: string;
  name: string;
  agent_id: string;
  prompt: string;
  cron: string;
  enabled: boolean;
  last_run: string | null;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  openclaw_available: boolean;
  openclaw_version: string;
  mock_mode: boolean;
}

export interface StreamEvent {
  type: string;
  content?: string;
  tool?: string;
  output?: string;
  status?: string;
  timestamp?: string;
}

export type TaskViewMode = "list" | "board" | "gantt";
export type TaskStatusFilter = "all" | "queued" | "running" | "completed" | "failed";
