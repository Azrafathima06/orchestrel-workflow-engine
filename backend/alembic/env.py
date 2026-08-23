import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make `app` importable regardless of the current working directory alembic
# is invoked from (backend/ locally, /app in the container).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import (  # noqa: E402, F401
    Schedule,
    ScheduleFire,
    TaskAttempt,
    TaskRun,
    WorkflowDefinition,
    WorkflowRun,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The app's own settings are the single source of truth — migrations must
# run against exactly the database the application uses, not a value
# hand-copied into alembic.ini.
#
# `migration_database_url` prefers DATABASE_DIRECT_URL when set. Neon's
# pooled endpoint runs PgBouncer in transaction mode, which is fine for
# ordinary queries but is not what its own documentation recommends for
# DDL; the direct endpoint is. Locally there is only one endpoint, so this
# resolves to DATABASE_URL and nothing changes.
config.set_main_option("sqlalchemy.url", get_settings().migration_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
