"""AgentCenter 配置模块。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.models.runtime import parse_enabled_runtimes


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8013
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/agentcenter.db"

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

    skills_dir: str = ""
    hermes_skills_dir: str = ""

    # Obsidian expe 库根（只读浏览；范围选择从一级目录起逐级下钻）
    outputs_vault_root: str = (
        "/Users/expeqiu/Library/Mobile Documents/"
        "iCloud~md~obsidian/Documents/expe"
    )

    # System 页 Cron 修复派单目标 Agent（可回退 ops / main）
    ops_repair_agent_id: str = "ops-agent"

    def enabled_runtimes(self) -> list[str]:
        return parse_enabled_runtimes(self.runtimes)

    def is_runtime_enabled(self, runtime: str) -> bool:
        return runtime in self.enabled_runtimes()


@lru_cache
def get_settings() -> Settings:
    return Settings()
