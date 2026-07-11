"""AgentCenter 配置模块。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    openclaw_executable: str = "openclaw"
    openclaw_mode: str = "local"
    openclaw_gateway_host: str = ""
    openclaw_gateway_port: int = 18789
    openclaw_gateway_token: str = ""
    openclaw_default_timeout: int = 600
    openclaw_min_version: str = "2026.5.5"

    ai_mock_mode: bool = False
    max_concurrent_tasks: int = 3
    agent_serial_execution: bool = True

    feishu_webhook_url: str = ""
    cron_alert_interval: int = 300
    skills_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
