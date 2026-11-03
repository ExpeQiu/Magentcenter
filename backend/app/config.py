"""AgentCenter 配置模块。"""

import os
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.content_roots import DEFAULT_OUTPUTS_DIR, DEFAULT_SKILLS_DIR, DEFAULT_WIKI_DIR
from app.models.runtime import parse_enabled_runtimes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.environ.get("AGENTCENTER_ENV_FILE", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8013
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/agentcenter.db"
    # cloud：全局中心；full：PC/Mac 自治节点；edge：轻量执行端
    deploy_profile: str = "full"
    # auto 按 profile 决定；on / off 显式覆盖
    local_executor_scan: str = "auto"
    cloud_connector: str = "auto"
    local_auth_enabled: bool = True
    # 控制台进入鉴权码。空值在启动时生成实例独有口令，不使用源码里的固定值。
    entry_code: str = ""
    admin_token: str = ""

    @field_validator("entry_code", mode="before")
    @classmethod
    def keep_entry_code(cls, value: object) -> str:
        return str(value or "").strip()
    min_free_mb: int = 64

    # 双运行时：openclaw,hermes
    runtimes: str = "openclaw,hermes"
    default_runtime: str = "openclaw"

    openclaw_executable: str = "openclaw"
    openclaw_mode: str = "local"
    openclaw_gateway_host: str = ""
    openclaw_gateway_port: int = 18789
    openclaw_gateway_token: str = ""
    openclaw_default_timeout: int = 600
    openclaw_min_version: str = "2026.5.5"

    hermes_executable: str = "hermes"
    hermes_home: str = ""
    hermes_default_timeout: int = 600

    ai_mock_mode: bool = False
    max_concurrent_tasks: int = 3
    agent_serial_execution: bool = True

    feishu_webhook_url: str = ""
    cron_alert_interval: int = 300
    cron_alert_enabled: bool = True
    gateway_alert_enabled: bool = True
    # 磁盘占用告警阈值（百分比）；0 = 关闭
    disk_alert_threshold: int = 90
    # 告警规则环境名：default / dev / prod …
    alert_profile: str = "default"

    # 知识库向量：hash（默认）| openai | http（OpenAI 兼容）
    embedding_provider: str = "hash"
    embedding_api_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    # 任务创建前自动检索注入；任务完成后蒸馏卡片
    knowledge_inject_enabled: bool = True
    knowledge_inject_top_k: int = 3
    # L2,L3,L1
    knowledge_layer_weights: str = "3.0,1.2,1.0"

    # Personal Wiki 与技能仓。控制台可改，改动写在 data/content_roots.json。
    knowledge_wiki_dir: str = DEFAULT_WIKI_DIR
    skills_dir: str = ""
    hermes_skills_dir: str = ""
    skills_catalog_dir: str = DEFAULT_SKILLS_DIR
    # 任务收尾捕获；显式标记才提炼
    skill_mine_enabled: bool = True
    skill_inject_top_k: int = 2

    # Obsidian expe 库根。控制台可改，改动写在 data/content_roots.json。
    outputs_vault_root: str = DEFAULT_OUTPUTS_DIR
    # 额外只读根（逗号/分号/换行分隔的绝对路径），以文件夹名出现在一级目录
    outputs_vault_extra: str = ""

    # System 页 Cron 修复派单目标 Agent（可回退 ops / main）
    ops_repair_agent_id: str = "ops-agent"

    # 多端连接器。设备用此令牌注册；webhook 推送也用它签名。留空则拒绝注册。
    fleet_enroll_token: str = ""
    fleet_heartbeat_ttl: int = 45
    # 只在控制台还没保存过云端地址时作为默认值。已保存的地址以 data/fleet_link.json 为准。
    fleet_cloud_url: str = ""
    # 云端派到本机的任务额度（与本地槽位分开计）
    cloud_inbound_slots: int = 2

    def enabled_runtimes(self) -> list[str]:
        return parse_enabled_runtimes(self.runtimes)

    def is_runtime_enabled(self, runtime: str) -> bool:
        return runtime in self.enabled_runtimes()

    def normalized_profile(self) -> str:
        value = (self.deploy_profile or "full").strip().lower()
        if value not in {"cloud", "full", "edge"}:
            return "full"
        return value

    def executors_enabled(self) -> bool:
        """本机是否允许创建/承接本地执行任务（含外置 Node Agent）。cloud 默认否。"""
        return self.normalized_profile() != "cloud"

    def local_cli_scan_enabled(self) -> bool:
        """Core 是否扫描/内嵌调用本机 OpenClaw/Hermes。"""
        mode = (self.local_executor_scan or "auto").strip().lower()
        if mode == "off":
            return False
        if mode == "on":
            return self.executors_enabled()
        # auto：无 Node Agent 时才扫描
        return self.executors_enabled() and not _node_agent_alive()

    def embedded_executor_preferred(self) -> bool:
        """True 时 Core 进程内跑 OpenClaw/Hermes；False 时排队等 Node Agent claim。"""
        mode = (self.local_executor_scan or "auto").strip().lower()
        if mode == "on":
            return True
        if mode == "off":
            return False
        return not _node_agent_alive()

    def connector_enabled(self) -> bool:
        mode = (self.cloud_connector or "auto").strip().lower()
        if mode == "on":
            return True
        if mode == "off":
            return False
        return self.normalized_profile() == "full"

    def execution_slots(self) -> int:
        profile = self.normalized_profile()
        if profile == "cloud":
            return 0
        if profile == "edge":
            return 1
        return max(1, int(self.max_concurrent_tasks or 1))


def _node_agent_alive() -> bool:
    from pathlib import Path

    from app.paths import data_dir

    pid_path = data_dir() / "node-agent.pid"
    if not pid_path.is_file():
        return False
    try:
        pid = int((pid_path.read_text(encoding="utf-8") or "").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
