"""Pydantic 请求/响应模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class AgentInfo(BaseModel):
    id: str
    name: str
    model: str = ""
    workspace: str = ""
    identity_name: str = ""
    identity_emoji: str = ""
    is_default: bool = False
    runtime: Literal["openclaw", "hermes"] = "openclaw"


class AgentStats(BaseModel):
    agent_id: str
    task_count: int = 0
    running_count: int = 0
    last_active_at: datetime | None = None
    runtime: str = ""


class RuntimeHealth(BaseModel):
    runtime: str
    available: bool = False
    version: str = ""


class HealthResponse(BaseModel):
    status: str
    openclaw_available: bool
    openclaw_version: str = ""
    hermes_available: bool = False
    hermes_version: str = ""
    runtimes: list[RuntimeHealth] = Field(default_factory=list)
    default_runtime: str = "openclaw"
    mock_mode: bool


class WorkspaceInfo(BaseModel):
    id: str
    slug: str
    name: str
    description: str = ""
    created_at: datetime
    updated_at: datetime


class CreateWorkspaceRequest(BaseModel):
    slug: str
    name: str
    description: str = ""
    id: str | None = None


class GithubRepoRef(BaseModel):
    url: str
    ref: str = "main"
    default_branch_hint: str = ""


class LocalDirectoryRef(BaseModel):
    local_path: str
    label: str = ""


class ProjectResourceInfo(BaseModel):
    id: str
    project_id: str
    workspace_id: str
    resource_type: Literal["github_repo", "local_directory"]
    label: str = ""
    position: int = 0
    ref: GithubRepoRef | LocalDirectoryRef
    created_at: datetime
    updated_at: datetime


class CreateProjectResourceRequest(BaseModel):
    resource_type: Literal["github_repo", "local_directory"]
    label: str = ""
    ref: GithubRepoRef | LocalDirectoryRef


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    color: str | None = None
    lead_type: Literal["agent", "member", ""] | None = None
    lead_id: str | None = None


class CreateTaskRequest(BaseModel):
    agent_id: str
    prompt: str
    system_prompt: str = ""
    runtime: Literal["openclaw", "hermes"] | None = None
    workspace_id: str = ""
    project_id: str = ""
    start_date: str = ""
    due_date: str = ""
    timeout: int | None = None
    resume_session_id: str | None = None
    # 空或 local = 协调器本机执行；auto = 在线设备；其它 = 指定设备
    node_id: str = ""
    # None = 跟随 Settings.knowledge_inject_enabled
    inject_knowledge: bool | None = None
    # 高风险且召回为空时仍派发，但记下「已跳过门禁」
    skip_knowledge_gate: bool = False


class UpdateTaskRequest(BaseModel):
    start_date: str | None = None
    due_date: str | None = None
    project_id: str | None = None


class ProjectInfo(BaseModel):
    id: str
    workspace_id: str = ""
    name: str
    description: str = ""
    color: str = "slate"
    lead_type: str = ""
    lead_id: str = ""
    task_count: int = 0
    resource_count: int = 0
    created_at: datetime
    updated_at: datetime


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    color: str = "slate"
    workspace_id: str = ""
    lead_type: str = ""
    lead_id: str = ""
    id: str | None = None


class TaskInfo(BaseModel):
    id: str
    workspace_id: str = ""
    project_id: str = ""
    agent_id: str
    runtime: Literal["openclaw", "hermes"] = "openclaw"
    prompt: str
    system_prompt: str = ""
    status: str
    session_id: str = ""
    output: str = ""
    error: str = ""
    usage: TokenUsage | None = None
    duration_ms: int = 0
    start_date: str = ""
    due_date: str = ""
    node_id: str = ""
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: list[TaskInfo]
    total: int
    page: int
    page_size: int


class TaskEvent(BaseModel):
    type: str
    content: str = ""
    tool: str = ""
    call_id: str = ""
    input: dict[str, Any] | None = None
    output: str = ""
    status: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InstallSkillRequest(BaseModel):
    url: str = ""
    name: str = ""
    instructions: str = ""
    runtime: Literal["openclaw", "hermes"] = "openclaw"
    category: str = ""
    force: bool = False


class InstallSkillResult(BaseModel):
    """技能安装结果：OpenClaw 走 skill-agent 任务；Hermes 直调 CLI。"""

    runtime: Literal["openclaw", "hermes"]
    status: str  # queued | completed | failed
    identifier: str = ""
    message: str = ""
    task_id: str = ""
    task: TaskInfo | None = None


class AuditSkillRequest(BaseModel):
    skill_id: str


class CreateAutopilotRequest(BaseModel):
    name: str
    agent_id: str
    prompt: str
    cron: str = "3600"
    enabled: bool = True
    runtime: Literal["openclaw", "hermes"] = "openclaw"
    sync_to_openclaw: bool = False
    sync_to_hermes: bool = False


class SuperAiPending(BaseModel):
    """写操作确认单。前端原样带回，确认后才执行。"""

    action: Literal["create_task"]
    prompt: str
    agent_id: str
    agent_name: str = ""
    runtime: Literal["openclaw", "hermes"] = "openclaw"


class SuperAiTurnRequest(BaseModel):
    text: str = ""
    workspace_slug: str = "cyber"
    pending: SuperAiPending | None = None
    last_href: str = ""


class SuperAiTurnResponse(BaseModel):
    run_id: str
    reply: str
    intent: str
    service: str = ""
    href: str = ""
    pending: SuperAiPending | None = None
    task_id: str = ""
    task_status: str = ""


class DeviceEnrollRequest(BaseModel):
    enroll_token: str
    device_id: str
    name: str = ""


class DeviceEnrollResponse(BaseModel):
    device_id: str
    device_token: str
    name: str


class DeviceTurnRequest(BaseModel):
    text: str = ""
    workspace_slug: str = "cyber"
    pending: SuperAiPending | None = None


class DeviceTaskResponse(BaseModel):
    task_id: str
    status: str
    done: bool
    reply: str
