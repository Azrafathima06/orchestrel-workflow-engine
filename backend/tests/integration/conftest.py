"""Fixtures for tests that hit the real PostgreSQL database.

Deliberately real Postgres, not SQLite: the schema relies on JSONB,
native ARRAY, native enum types, and (in later milestones) row locking —
none of which SQLite models faithfully. Run `alembic upgrade head`
against DATABASE_URL before running this suite.

Each test runs inside its own connection + external transaction; the
session is bound to that connection and the transaction is rolled back at
teardown, so tests never need to clean up after themselves and never see
each other's data.
"""

import os
from collections.abc import Generator

import pytest
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

# Host-side test default: the Compose postgres service is published to
# localhost:5432 specifically for local tooling (see docker-compose.yml).
# Override with DATABASE_URL when running inside a container instead.
TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://workflow:workflow@localhost:5432/workflow_engine"
)


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine: Engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        # A failed flush (e.g. an expected IntegrityError from a
        # constraint test) already rolls back and deassociates this
        # transaction internally; only roll it back here if it's still
        # the one holding the connection open.
        if transaction.is_active:
            transaction.rollback()
        connection.close()
