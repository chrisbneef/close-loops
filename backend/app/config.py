from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./cadence.db"

    @field_validator("database_url")
    @classmethod
    def _normalize_postgres_driver(cls, v: str) -> str:
        """Force psycopg3 (the installed driver) when the URL uses the bare
        `postgresql://` prefix — SQLAlchemy otherwise defaults to psycopg2."""
        if v.startswith("postgresql://"):
            return "postgresql+psycopg://" + v[len("postgresql://") :]
        return v
    anthropic_api_key: str = ""

    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = "http://localhost:8000/oauth/google/callback"

    slack_webhook_url: str = ""
    expo_access_token: str = ""

    sched_alpha: float = 1.0
    sched_beta: float = 1.0
    sched_gamma: float = 0.5
    sched_delta: float = 0.7

    # Scheduler loop — disable in tests via env var or in conftest.
    enable_scheduler_loop: bool = True
    scheduler_tick_seconds: int = 60

    # Reminder loop — Phase 6c. Fires push N minutes before scheduled start.
    reminder_tick_seconds: int = 60
    reminder_lead_minutes: int = 5


settings = Settings()
