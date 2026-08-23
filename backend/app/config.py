from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, sourced entirely from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application identity
    app_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"

    # Infrastructure
    database_url: str = "postgresql+psycopg://workflow:workflow@postgres:5432/workflow_engine"
    broker_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost:5173"

    # Reliability / recovery knobs (see docs/reliability.md)
    queued_stale_seconds: int = 120
    lease_grace_seconds: int = 60
    retry_release_grace_seconds: int = 30
    run_stall_seconds: int = 300
    max_dispatch_attempts: int = 5
    sweep_batch: int = 100
    scheduler_tick_seconds: int = 30
    # Must exceed max_task_timeout_seconds + lease_grace_seconds +
    # max_retry_countdown_seconds (asserted at Celery startup), or Redis
    # redelivers messages that are still legitimately in flight.
    # A long value is safe here precisely because we do NOT depend on
    # broker redelivery for worker-loss recovery — the PostgreSQL lease
    # sweep owns that, and it reacts in seconds rather than hours.
    broker_visibility_timeout: int = 7200

    # Upper bound on a handler's serialized JSON output before we refuse to
    # persist it. task_run.output is JSONB in a free-tier database; a handler
    # returning a whole dataset instead of a summary is a bug we want to
    # surface loudly, not silently truncate.
    max_task_output_bytes: int = 131072

    # Task lease headroom, added to a task's own timeout_seconds when a
    # worker claims an attempt. Consumed by the recovery sweeper.
    lease_seconds_default: int = 300

    # Bounds used only to assert broker timing consistency at startup:
    # visibility_timeout must exceed the longest possible in-flight time.
    # max_task_timeout_seconds mirrors the ceiling enforced by the spec
    # model; max_retry_countdown_seconds mirrors the backoff cap.
    max_task_timeout_seconds: int = 3600
    max_retry_countdown_seconds: int = 300

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
