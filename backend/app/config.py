from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./cadence.db"
    anthropic_api_key: str = ""

    google_calendar_mcp_url: str = ""
    composio_api_key: str = ""

    slack_webhook_url: str = ""
    discord_webhook_url: str = ""
    expo_access_token: str = ""

    sched_alpha: float = 1.0
    sched_beta: float = 1.0
    sched_gamma: float = 0.5
    sched_delta: float = 0.7

    # Scheduler loop — disable in tests via env var or in conftest.
    enable_scheduler_loop: bool = True
    scheduler_tick_seconds: int = 60


settings = Settings()
