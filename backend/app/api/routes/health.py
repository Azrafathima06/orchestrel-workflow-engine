"""Readiness: actually measured, not asserted.

/health (in main.py) answers instantly and touches nothing, so it can
respond the moment uvicorn binds. /ready is the honest, slightly more
expensive check the Overview page's status strip uses: a real round-trip
to PostgreSQL and a real round-trip to Redis, each timed.
"""

from __future__ import annotations

import time

import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import ComponentHealth, ReadyResponse
from app.config import get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])
settings = get_settings()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check. Deliberately touches nothing but the process itself."""
    return {"status": "ok", "version": settings.app_version}


# A worker is "observed" for readiness purposes if it executed an attempt
# within this window — the same activity signal the /workers endpoint uses,
# just condensed to a count here.
WORKERS_OBSERVED_WINDOW_MINUTES = 5


def _check_database(db: Session) -> ComponentHealth:
    start = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return ComponentHealth(ok=True, latency_ms=latency_ms)
    except Exception as exc:  # noqa: BLE001 - reported to the caller, not raised
        return ComponentHealth(ok=False, error=str(exc)[:200])


def _check_broker() -> ComponentHealth:
    start = time.perf_counter()
    try:
        client = redis.Redis.from_url(
            settings.broker_url, socket_connect_timeout=2, socket_timeout=2
        )
        client.ping()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return ComponentHealth(ok=True, latency_ms=latency_ms)
    except Exception as exc:  # noqa: BLE001
        return ComponentHealth(ok=False, error=str(exc)[:200])


@router.get("/ready", response_model=ReadyResponse)
def ready(db: Session = Depends(get_db)) -> ReadyResponse:
    database = _check_database(db)
    broker = _check_broker()

    workers_observed = 0
    if database.ok:
        workers_observed = db.execute(
            text(
                "SELECT count(DISTINCT worker_id) FROM task_attempt "
                "WHERE coalesce(finished_at, started_at) >= now() - make_interval(mins => :m)"
            ),
            {"m": WORKERS_OBSERVED_WINDOW_MINUTES},
        ).scalar_one()

    return ReadyResponse(
        database=database,
        broker=broker,
        workers_observed_5m=int(workers_observed),
    )
