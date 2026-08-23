"""Database URL normalization and production configuration guards.

Managed Postgres providers hand out `postgresql://` (Neon) or legacy
`postgres://` (Heroku-lineage) URLs, while SQLAlchemy needs the driver made
explicit. Getting this wrong silently is expensive: a naive string replace
corrupts any credential or query parameter containing the word it replaced,
and a missing `sslmode=require` fails against Neon at connect time.
"""

import pytest

from app.config import Settings, normalize_database_url


class TestNormalization:
    def test_bare_postgresql_scheme_gains_the_driver(self) -> None:
        assert (
            normalize_database_url("postgresql://u:p@host:5432/db")
            == "postgresql+psycopg://u:p@host:5432/db"
        )

    def test_legacy_postgres_scheme_is_accepted(self) -> None:
        assert (
            normalize_database_url("postgres://u:p@host:5432/db")
            == "postgresql+psycopg://u:p@host:5432/db"
        )

    def test_already_correct_url_is_unchanged(self) -> None:
        url = "postgresql+psycopg://u:p@host:5432/db"

        assert normalize_database_url(url) == url

    def test_sslmode_is_preserved(self) -> None:
        """Neon refuses non-TLS connections; losing this parameter breaks prod."""
        result = normalize_database_url(
            "postgresql://u:p@ep-x-pooler.aws.neon.tech/db?sslmode=require"
        )

        assert result.startswith("postgresql+psycopg://")
        assert "sslmode=require" in result

    def test_all_query_parameters_are_preserved(self) -> None:
        result = normalize_database_url(
            "postgresql://u:p@host/db?sslmode=require&channel_binding=require"
        )

        assert "sslmode=require" in result
        assert "channel_binding=require" in result

    def test_password_containing_the_scheme_word_is_not_corrupted(self) -> None:
        """The exact failure mode a naive str.replace() would introduce."""
        result = normalize_database_url("postgresql://user:postgres@host:5432/db")

        assert result == "postgresql+psycopg://user:postgres@host:5432/db"

    def test_special_characters_in_password_survive(self) -> None:
        url = "postgresql://user:p%40ss%2Fword@host:5432/db"
        result = normalize_database_url(url)

        assert result.startswith("postgresql+psycopg://")
        # Round-trips through SQLAlchemy's URL type without double-encoding.
        assert "p%40ss%2Fword" in result

    def test_pooler_hostname_is_preserved_exactly(self) -> None:
        result = normalize_database_url(
            "postgresql://u:p@ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech/main"
        )

        assert "ep-cool-darkness-123456-pooler.us-east-2.aws.neon.tech" in result

    def test_non_postgres_url_is_left_alone(self) -> None:
        assert normalize_database_url("sqlite:///tmp/x.db") == "sqlite:///tmp/x.db"

    def test_empty_string_is_tolerated(self) -> None:
        assert normalize_database_url("") == ""


class TestSettingsIntegration:
    def test_settings_normalizes_both_urls(self) -> None:
        settings = Settings(
            database_url="postgresql://u:p@pooled/db?sslmode=require",
            database_direct_url="postgres://u:p@direct/db?sslmode=require",
        )

        assert settings.database_url.startswith("postgresql+psycopg://")
        assert settings.database_direct_url.startswith("postgresql+psycopg://")
        assert "sslmode=require" in settings.database_direct_url

    def test_migration_url_prefers_direct_when_set(self) -> None:
        settings = Settings(
            database_url="postgresql://u:p@pooled/db",
            database_direct_url="postgresql://u:p@direct/db",
        )

        assert "direct" in settings.migration_database_url

    def test_migration_url_falls_back_to_app_url(self) -> None:
        """Local Docker has one endpoint; DATABASE_DIRECT_URL stays empty."""
        settings = Settings(database_url="postgresql://u:p@only/db", database_direct_url="")

        assert "only" in settings.migration_database_url


# Every guard test pins each field explicitly. Settings also reads .env and
# the ambient environment, so relying on defaults here would make these
# assertions depend on the developer's local configuration.
_LOCAL_DB = "postgresql+psycopg://workflow:workflow@postgres:5432/workflow_engine"
_LOCAL_BROKER = "redis://redis:6379/0"
_REAL_DB = "postgresql://u:p@neon-pooler.aws.neon.tech/db?sslmode=require"
_REAL_BROKER = "redis://red-abc123:6379"


class TestProductionGuards:
    def test_development_tolerates_local_defaults(self) -> None:
        Settings(
            app_env="development",
            database_url=_LOCAL_DB,
            broker_url=_LOCAL_BROKER,
        ).assert_production_ready()  # must not raise

    def test_production_rejects_the_docker_database_default(self) -> None:
        settings = Settings(
            app_env="production",
            database_url=_LOCAL_DB,
            broker_url=_REAL_BROKER,
            cors_origins="https://x.example",
        )

        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            settings.assert_production_ready()

    def test_production_rejects_the_docker_broker_default(self) -> None:
        settings = Settings(
            app_env="production",
            database_url=_REAL_DB,
            broker_url=_LOCAL_BROKER,
            cors_origins="https://x.example",
        )

        with pytest.raises(RuntimeError, match="BROKER_URL"):
            settings.assert_production_ready()

    def test_production_rejects_wildcard_cors(self) -> None:
        settings = Settings(
            app_env="production",
            database_url=_REAL_DB,
            broker_url="rediss://real-broker:6379/0",
            cors_origins="*",
        )

        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            settings.assert_production_ready()

    def test_fully_configured_production_passes(self) -> None:
        settings = Settings(
            app_env="production",
            database_url=_REAL_DB,
            database_direct_url="postgresql://u:p@neon.aws.neon.tech/db?sslmode=require",
            broker_url=_REAL_BROKER,
            cors_origins="https://orchestrel.example",
        )

        settings.assert_production_ready()  # must not raise


class TestTimeLimits:
    def test_hard_limit_strictly_exceeds_soft_limit(self) -> None:
        """A hard limit at or below the soft limit kills the handler before it
        can record its own timeout, losing the attempt row."""
        settings = Settings()

        assert settings.task_hard_time_limit > settings.task_soft_time_limit

    def test_soft_limit_matches_the_task_timeout_ceiling(self) -> None:
        settings = Settings()

        assert settings.task_soft_time_limit == settings.max_task_timeout_seconds
