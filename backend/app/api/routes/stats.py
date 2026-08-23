"""System-wide statistics. Every number is a real SQL aggregate over persisted state."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import DailyCount, RunCounts, StatsOverview
from app.db.session import get_db

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

# How far back the daily activity series looks and how "recovered" is
# defined, in one place so the query and the docs agree.
DAILY_WINDOW_DAYS = 14


@router.get("/overview", response_model=StatsOverview)
def get_stats_overview(db: Session = Depends(get_db)) -> StatsOverview:
    run_counts = db.execute(
        text(
            """
            SELECT
                count(*) FILTER (WHERE true)                          AS total,
                count(*) FILTER (WHERE status = 'succeeded')          AS succeeded,
                count(*) FILTER (WHERE status = 'failed')             AS failed,
                count(*) FILTER (WHERE status = 'running')            AS running,
                count(*) FILTER (WHERE status = 'cancelled')          AS cancelled,
                avg(duration_ms) FILTER (WHERE duration_ms IS NOT NULL)      AS avg_duration_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                    FILTER (WHERE duration_ms IS NOT NULL)                  AS p95_duration_ms
            FROM workflow_run
            """
        )
    ).one()

    retries = db.execute(
        text("SELECT coalesce(sum(greatest(attempt_count - 1, 0)), 0) FROM task_run")
    ).scalar_one()

    tasks_executed = db.execute(text("SELECT count(*) FROM task_attempt")).scalar_one()

    # A task counts as "recovered" if the recovery sweep intervened on it:
    # either it was re-dispatched after appearing stuck in QUEUED
    # (dispatch_count > 1), or one of its attempts was reclaimed from a
    # worker that stopped responding (WorkerLost).
    recovered_tasks = db.execute(
        text(
            """
            SELECT count(DISTINCT tr.id)
              FROM task_run tr
              LEFT JOIN task_attempt ta
                ON ta.task_run_id = tr.id AND ta.error_type = 'WorkerLost'
             WHERE tr.dispatch_count > 1 OR ta.id IS NOT NULL
            """
        )
    ).scalar_one()

    daily_rows = db.execute(
        text(
            """
            SELECT
                date_trunc('day', finished_at)::date AS day,
                count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
                count(*) FILTER (WHERE status = 'failed')    AS failed
              FROM workflow_run
             WHERE finished_at >= now() - make_interval(days => :window_days)
             GROUP BY day
             ORDER BY day
            """
        ),
        {"window_days": DAILY_WINDOW_DAYS},
    ).all()

    succeeded, failed = run_counts.succeeded, run_counts.failed
    success_rate = (succeeded / (succeeded + failed)) if (succeeded + failed) > 0 else None

    return StatsOverview(
        runs=RunCounts(
            total=run_counts.total,
            succeeded=run_counts.succeeded,
            failed=run_counts.failed,
            running=run_counts.running,
            cancelled=run_counts.cancelled,
        ),
        success_rate=success_rate,
        avg_duration_ms=(
            float(run_counts.avg_duration_ms) if run_counts.avg_duration_ms is not None else None
        ),
        p95_duration_ms=(
            float(run_counts.p95_duration_ms) if run_counts.p95_duration_ms is not None else None
        ),
        retries=int(retries),
        tasks_executed=int(tasks_executed),
        recovered_tasks=int(recovered_tasks),
        daily=[
            DailyCount(date=row.day.isoformat(), succeeded=row.succeeded, failed=row.failed)
            for row in daily_rows
        ],
    )
