"""Worker activity, derived entirely from task_attempt.

This is NOT Celery remote-control discovery — we deliberately disabled that
(worker_enable_remote_control=False) to keep broker traffic low. What we
show instead is honest: which processes have actually executed task
attempts, and how recently. A worker that is up but idle looks identical to
one that isn't running at all, which is why liveness is labelled from
observed activity, not asserted as "online".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import WorkerObservation
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/workers", tags=["workers"])

# Thresholds for the derived liveness label, measured against last_seen_at.
MAX_WORKERS = 100

ACTIVE_WITHIN_SECONDS = 120
IDLE_WITHIN_SECONDS = 1800


@router.get("", response_model=list[WorkerObservation])
def list_workers(db: Session = Depends(get_db)) -> list[WorkerObservation]:
    rows = db.execute(
        text(
            """
            WITH activity AS (
                SELECT
                    worker_id,
                    min(started_at)                                        AS first_seen_at,
                    max(coalesce(finished_at, started_at))                 AS last_seen_at,
                    count(*)                                               AS attempts_total,
                    count(*) FILTER (WHERE started_at >= now() - interval '1 hour')
                                                                            AS attempts_1h,
                    count(*) FILTER (WHERE status = 'running')             AS currently_running
                  FROM task_attempt
                 GROUP BY worker_id
            )
            SELECT
                *,
                extract(epoch FROM (now() - last_seen_at)) AS age_seconds
              FROM activity
             ORDER BY last_seen_at DESC
             LIMIT :max_workers
            """
        ),
        {"max_workers": MAX_WORKERS},
    ).all()

    observations = []
    for row in rows:
        if row.age_seconds <= ACTIVE_WITHIN_SECONDS:
            liveness = "active"
        elif row.age_seconds <= IDLE_WITHIN_SECONDS:
            liveness = "idle"
        else:
            liveness = "stale"

        observations.append(
            WorkerObservation(
                worker_id=row.worker_id,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                attempts_total=row.attempts_total,
                attempts_1h=row.attempts_1h,
                currently_running=row.currently_running,
                liveness=liveness,
            )
        )
    return observations
