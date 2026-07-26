export interface AgentStats {
  agent_id: string;
  task_count: number;
  running_count: number;
  last_active_at: string | null;
}

export type RuntimeName = "openclaw" | "hermes";

export interface AgentInfo {
  id: string;
  name: string;
  model: string;
  workspace: string;
  identity_name: string;
  identity_emoji: string;
  is_default: boolean;
  runtime: RuntimeName;
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
  runtime: RuntimeName;
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
  runtime?: RuntimeName;
}

export interface SkillInfo {
  id: string;
  name: string;
  path: string;
  description: string;
  description_full?: string;
  version?: string;
  owner?: string;
  disable_model_invocation?: boolean;
  allowed_tools?: string[];
  emoji?: string;
  archived?: boolean;
  runtime?: RuntimeName | string;
}

export interface KanbanBoard {
  slug: string;
  name: string;
  current: boolean;
  counts: string;
}

export interface KanbanTask {
  id: string;
  title: string;
  body: string;
  assignee: string;
  status: string;
  priority: number;
  workspace_kind?: string;
  created_at?: number | null;
  skills?: string[];
  runtime?: string;
}

export interface SwarmNode {
  id: string;
  role: "root" | "worker" | "verifier" | "synthesizer" | string;
  title: string;
  assignee: string;
  status: string;
}

export interface SwarmEdge {
  from_id: string;
  to_id: string;
}

export interface SwarmGraph {
  root_id: string;
  goal: string;
  worker_ids: string[];
  verifier_id: string;
  synthesizer_id: string;
  nodes: SwarmNode[];
  edges: SwarmEdge[];
}

export interface InstallSkillResult {
  runtime: RuntimeName;
  status: string;
  identifier: string;
  message: string;
  task_id: string;
  task: TaskInfo | null;
}

export interface AlertSettings {
  webhook_url_set: boolean;
  webhook_url_masked: string;
  cron_alert_interval: number;
  cron_alert_enabled: boolean;
  gateway_alert_enabled: boolean;
  disk_alert_threshold: number;
  persisted?: boolean;
  profile?: string;
  profiles?: string[];
}

export interface EmbeddingStatus {
  provider: string;
  model: string;
  api_url_set?: boolean;
  dim?: number | null;
  mock?: boolean;
}

export interface KnowledgeHit {
  id: string;
  source_type: string;
  source_id: string;
  runtime: string;
  agent_id: string;
  session_id: string;
  title: string;
  snippet: string;
  status: string;
  score: number;
  created_at: string;
}

export interface OutputEntry {
  name: string;
  path: string;
  kind: "dir" | "file" | string;
  source: "openclaw" | "hermes" | string;
  mtime: string;
  size: number;
  ext?: string;
}

export interface OutputFile {
  path: string;
  name: string;
  source: string;
  mtime: string;
  size: number;
  content: string;
  ext?: string;
  previewable?: boolean;
}

export interface OutputStatus {
  status: string;
  readable: boolean;
  root_name: string;
  message: string;
}

export interface SkillDetail extends SkillInfo {
  body_preview: string;
  skill_md_path: string;
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
  source?: string;
  openclaw_id?: string;
  hermes_id?: string;
  runtime?: RuntimeName | string;
  status?: string;
  schedule?: string;
}

export interface GatewayStatus {
  running: boolean;
  pid: number;
  port: number;
  version: string;
  dashboard_url: string;
  probe_ok: boolean;
}

export interface CronJobInfo {
  id: string;
  name: string;
  agent_id: string;
  schedule: string;
  status: string;
  enabled: boolean;
  next_run: string;
  last_run: string;
  last_status: string;
  source: string;
  runtime?: RuntimeName | string;
}

export interface SessionMessage {
  role: string;
  content: string;
  timestamp: string;
}

export interface SessionDetail {
  session_id: string;
  agent_id: string;
  key: string;
  model: string;
  updated_at: string;
  total_tokens: number;
  messages: SessionMessage[];
  runtime?: RuntimeName | string;
}

export interface SessionInfo {
  session_id: string;
  agent_id: string;
  key: string;
  model: string;
  updated_at: string;
  age_ms: number;
  total_tokens: number;
  kind: string;
  runtime?: RuntimeName | string;
}

export interface RuntimePane {
  runtime: RuntimeName | string;
  available: boolean;
  version: string;
  gateway: GatewayStatus;
}

export interface RecentAlert {
  at: string;
  count: number;
  sent: boolean;
  jobs: string[];
  kind?: "cron" | "gateway" | string;
}

export interface SystemStatus {
  gateway: GatewayStatus;
  runtimes?: RuntimePane[];
  cron_jobs: CronJobInfo[];
  cron_errors: CronJobInfo[];
  sessions_count: number;
  sessions: SessionInfo[];
  checked_at: string;
}

export interface HealthResponse {
  status: string;
  openclaw_available: boolean;
  openclaw_version: string;
  hermes_available?: boolean;
  hermes_version?: string;
  default_runtime?: RuntimeName | string;
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
