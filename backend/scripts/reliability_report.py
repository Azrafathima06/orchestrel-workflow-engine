"""Print the reliability evidence for a run: retries, backoff, workers, recovery.

Reads only persisted PostgreSQL state — task_run and task_attempt — and
computes the backoff gaps between successive attempts from real timestamps.

    uv run python scripts/reliability_report.py <run_id>
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, text

DEFAULT_URL = "postgresql+psycopg://workflow:workflow@localhost:5432/workflow_engine"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    run_id = sys.argv[1]
    engine = create_engine(os.environ.get("DATABASE_URL", DEFAULT_URL))

    with engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT definition_key, status, duration_ms, error, started_at, finished_at "
                "FROM workflow_run WHERE id = :r"
            ),
            {"r": run_id},
        ).one_or_none()

        if run is None:
            print(f"no run found with id {run_id}")
            return 1

        tasks = conn.execute(
            text(
                "SELECT id, task_key, status, attempt_count, max_attempts, dispatch_count, "
                "next_attempt_at, error_type, error_message, duration_ms "
                "FROM task_run WHERE run_id = :r ORDER BY task_key"
            ),
            {"r": run_id},
        ).all()

        attempts = conn.execute(
            text(
                "SELECT tr.task_key, ta.attempt_number, ta.status, ta.worker_id, "
                "ta.started_at, ta.finished_at, ta.duration_ms, ta.error_type "
                "FROM task_attempt ta JOIN task_run tr ON tr.id = ta.task_run_id "
                "WHERE tr.run_id = :r ORDER BY tr.task_key, ta.attempt_number"
            ),
            {"r": run_id},
        ).all()

    definition_key, status, duration_ms, error, started_at, finished_at = run
    print(f"run          : {run_id}")
    print(f"workflow     : {definition_key}")
    print(f"status       : {status}")
    print(f"duration_ms  : {duration_ms}")
    if error:
        print(f"error        : {error}")

    print()
    hdr = (
        f"{'task_key':<12}| {'status':<16}| {'att':<4}| {'max':<4}| "
        f"{'disp':<5}| {'error_type':<20}| duration_ms"
    )
    print(hdr)
    print("-" * len(hdr))
    for _, key, st, att, mx, disp, _next, etype, _emsg, dur in tasks:
        print(
            f"{key:<12}| {st:<16}| {att:<4}| {mx:<4}| {disp:<5}| "
            f"{(etype or '-'):<20}| {dur if dur is not None else '-'}"
        )

    print()
    hdr2 = (
        f"{'task_key':<12}| {'#':<3}| {'status':<10}| {'worker_id':<20}| "
        f"{'started':<13}| {'dur_ms':<7}| {'error_type':<16}| gap_before"
    )
    print(hdr2)
    print("-" * len(hdr2))

    previous_finish: dict[str, object] = {}
    for key, number, st, worker, started, _finished, dur, etype in attempts:
        prev = previous_finish.get(key)
        # Gap between the previous attempt finishing and this one starting:
        # the backoff the engine actually waited, measured from real
        # persisted timestamps rather than from the configured policy.
        gap = f"{(started - prev).total_seconds():.2f}s" if prev else "-"
        print(
            f"{key:<12}| {number:<3}| {st:<10}| {worker:<20}| "
            f"{started.strftime('%H:%M:%S.%f')[:-3]:<13}| "
            f"{dur if dur is not None else '-':<7}| {(etype or '-'):<16}| {gap}"
        )
        previous_finish[key] = _finished or started

    retried = [t for t in tasks if t[3] > 1]
    lost = [a for a in attempts if a[7] == "WorkerLost"]
    redispatched = [t for t in tasks if t[5] > 1]
    workers = {a[3] for a in attempts}

    print()
    print(f"tasks with >1 attempt      : {len(retried)} {[t[1] for t in retried]}")
    print(f"WorkerLost attempts        : {len(lost)} {[(a[0], a[1]) for a in lost]}")
    print(f"tasks re-dispatched by sweep: {len(redispatched)} {[t[1] for t in redispatched]}")
    print(f"distinct workers           : {len(workers)} {sorted(workers)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
