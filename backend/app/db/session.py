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

from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session, closes it when the request ends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
