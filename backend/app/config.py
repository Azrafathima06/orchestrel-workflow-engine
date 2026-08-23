from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# The driver this application is built against. Managed Postgres providers
# (Neon, Render, Heroku) hand out bare `postgresql://` or legacy
# `postgres://` URLs; SQLAlchemy needs the driver made explicit or it falls
# back to psycopg2, which is not installed.
_REQUIRED_DRIVER = "psycopg"

# The Compose-only default. It is a valid local value and a useless
# production one, so production refuses to start on it rather than failing
# later with an opaque DNS error for a host named "postgres".
_LOCAL_DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://workflow:workflow@postgres:5432/workflow_engine"
)


def normalize_database_url(url: str) -> str:
    """Force the psycopg driver onto a Postgres URL without touching anything else.

    Parsed and re-rendered through SQLAlchemy's own URL type rather than
    string-replaced: a password containing "postgres", an `@` in a
    credential, a non-default port, or a `?sslmode=require` query string
    would all be corrupted by naive substitution. `render_as_string` with
    `hide_password=False` reproduces the URL exactly, with only the driver
    changed.

    Non-Postgres URLs are returned untouched so this never silently mangles
    something it does not understand.
    """
    if not url:
        return url

    parsed = make_url(url)
    if not parsed.drivername.startswith("postgres"):
        return url
    if parsed.drivername == f"postgresql+{_REQUIRED_DRIVER}":
        return url

    return parsed.set(drivername=f"postgresql+{_REQUIRED_DRIVER}").render_as_string(
        hide_password=False
    )


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
    database_url: str = _LOCAL_DEFAULT_DATABASE_URL
    # Optional second URL for migrations and startup DDL. Neon recommends a
    # direct (unpooled) connection for schema changes, because its pooled
    # endpoint runs PgBouncer in transaction mode. Empty means "use
    # database_url", which is correct for local Docker where there is only
    # one endpoint.
    database_direct_url: str = ""
    broker_url: str = "redis://redis:6379/0"
    cors_origins: str = "http://localhost:5173"

    # ---- Public-demo protection --------------------------------------
    # This deployment is an unauthenticated public demo. These are the
    # smallest controls that stop a visitor from exhausting shared free-tier
    # CPU, and are deliberately NOT an authentication system.
    public_trigger_rate_per_minute: int = 10
    max_active_runs: int = 10
    max_request_body_bytes: int = 16384

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

    # Grace between Celery's soft limit (raises inside the handler, so the
    # attempt is recorded normally) and its hard limit (kills the child
    # process). The gap must be large enough for the soft-limit handler to
    # write its failure row and schedule the retry.
    task_hard_time_limit_grace_seconds: int = 30

    @field_validator("database_url", "database_direct_url")
    @classmethod
    def _normalize_db_urls(cls, value: str) -> str:
        return normalize_database_url(value)

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def migration_database_url(self) -> str:
        """URL for Alembic and startup seeding: direct if provided, else the app URL."""
        return self.database_direct_url or self.database_url

    @property
    def task_soft_time_limit(self) -> int:
        """Celery soft limit: the longest a single handler may run."""
        return self.max_task_timeout_seconds

    @property
    def task_hard_time_limit(self) -> int:
        """Celery hard limit. Strictly greater than the soft limit by design."""
        return self.max_task_timeout_seconds + self.task_hard_time_limit_grace_seconds

    def assert_production_ready(self) -> None:
        """Refuse to run in production on development defaults.

        Silently falling back to the Compose hostname would surface as a DNS
        failure inside a request handler minutes after a "successful" deploy.
        Failing at startup makes the misconfiguration obvious and immediate.
        """
        if not self.is_production:
            return

        problems: list[str] = []
        if self.database_url == _LOCAL_DEFAULT_DATABASE_URL:
            problems.append("DATABASE_URL is still the local Docker default")
        if "@redis:" in self.broker_url or "@localhost:" in self.broker_url:
            problems.append("BROKER_URL still points at a local development host")
        if self.broker_url == "redis://redis:6379/0":
            problems.append("BROKER_URL is still the local Docker default")
        if not self.cors_origins_list:
            problems.append("CORS_ORIGINS is empty")
        if any(o == "*" for o in self.cors_origins_list):
            problems.append("CORS_ORIGINS must not be '*' in production")

        if problems:
            raise RuntimeError(
                "refusing to start in production with development configuration: "
                + "; ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
