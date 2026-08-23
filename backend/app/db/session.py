"""SQLAlchemy engine and session factory.

A small, fixed connection pool is deliberate: this API is expected to run
as a single uvicorn worker against a free-tier managed Postgres (Neon)
with its own connection ceiling. `pool_pre_ping=True` matters specifically
because Neon autosuspends idle compute — a stale pooled connection must be
detected and replaced, not handed to a caller and fail.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_direct_session_factory() -> sessionmaker:
    """Session factory bound to the direct (unpooled) database URL.

    Used by startup operations that run once per boot — currently the
    workflow seed. Neon recommends the direct endpoint for anything
    schema-adjacent, and a NullPool avoids leaving idle connections behind
    for a task that exits immediately. Locally `migration_database_url`
    resolves to the same URL as the app engine, so this is a no-op.
    """
    direct_engine = create_engine(
        settings.migration_database_url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    return sessionmaker(bind=direct_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, closes it when the request ends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
