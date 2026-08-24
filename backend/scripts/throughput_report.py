"""Measure sustained task throughput against a running Orchestrel stack.

Triggers a batch of workflow runs through the public API, waits for every
one of them to reach a terminal state, then reports throughput computed
from persisted rows — not from anything this script kept in memory.

    uv run python scripts/throughput_report.py [--runs N] [--workflow KEY]

Every number printed is measured on the machine you run it on, against the
worker pool you happen to have running. Throughput is bounded by the number
of execution slots (containers x --concurrency) and by how long the demo
handlers genuinely take, so a figure from one machine does not transfer to
another. Report it with its context or not at all.

Exits non-zero if any run failed to reach a terminal state in time.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_URL = "postgresql+psycopg://workflow:workflow@localhost:5432/workflow_engine"
DEFAULT_API = "http://localhost:8000"
POLL_INTERVAL_S = 0.25


def trigger(api: str, workflow: str) -> str:
    req = urllib.request.Request(
        f"{api}/api/v1/workflows/{workflow}/runs",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        import json

        return json.load(resp)["id"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=25)
    parser.add_argument("--workflow", default="sequential_etl")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--api", default=os.environ.get("API_BASE_URL", DEFAULT_API))
    args = parser.parse_args()

    engine = create_engine(os.environ.get("DATABASE_URL", DEFAULT_URL))

    print(f"triggering {args.runs} x {args.workflow} against {args.api} ...")
    started = time.monotonic()

    run_ids: list[str] = []
    for _ in range(args.runs):
        try:
            run_ids.append(trigger(args.api, args.workflow))
        except urllib.error.HTTPError as exc:  # rate limit / active-run cap
            print(f"  trigger refused with HTTP {exc.code}; continuing with {len(run_ids)}")
            break

    if not run_ids:
        print("no runs were accepted")
        return 1

    # Wait for terminal state by polling the database directly: the point of
    # the measurement is when work actually finished, not when some API cache
    # noticed.
    ids = tuple(run_ids)
    deadline = started + args.timeout
    while True:
        with engine.connect() as conn:
            pending = conn.execute(
                text(
                    "SELECT count(*) FROM workflow_run "
                    "WHERE id = ANY(CAST(:ids AS uuid[])) "
                    "AND status NOT IN ('succeeded', 'failed', 'cancelled')"
                ).bindparams(ids=list(ids))
            ).scalar_one()
        if pending == 0:
            break
        if time.monotonic() > deadline:
            print(f"timed out with {pending} run(s) still non-terminal")
            return 1
        time.sleep(POLL_INTERVAL_S)

    # ---------------------------------------------------------- measurement
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT count(*)                                   AS attempts,
                       count(DISTINCT ta.worker_id)               AS workers,
                       min(ta.started_at)                         AS first_start,
                       max(ta.finished_at)                        AS last_finish,
                       avg(ta.duration_ms)                        AS avg_ms,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY ta.duration_ms) AS p95_ms
                  FROM task_attempt ta
                  JOIN task_run tr ON tr.id = ta.task_run_id
                 WHERE tr.run_id = ANY(CAST(:ids AS uuid[]))
                """
            ).bindparams(ids=list(ids))
        ).one()

    attempts, workers, first_start, last_finish, avg_ms, p95_ms = row
    if not first_start or not last_finish:
        print("no attempts recorded")
        return 1

    # Wall-clock window in which the engine was actually executing tasks.
    window_s = (last_finish - first_start).total_seconds()
    per_s = attempts / window_s if window_s > 0 else 0.0

    print()
    print(f"  runs completed        {len(ids)}")
    print(f"  task attempts         {attempts}")
    print(f"  distinct workers      {workers}")
    print(f"  execution window      {window_s:.2f}s")
    print(f"  throughput            {per_s:.1f} task attempts/sec")
    print(f"                        {per_s * 60:.0f} task attempts/min")
    print(f"  mean task duration    {float(avg_ms):.0f}ms")
    print(f"  p95 task duration     {float(p95_ms):.0f}ms")
    print()
    print("  Measured locally. Bounded by execution slots (worker containers x")
    print("  --concurrency) and by real handler cost; not a claim about any")
    print("  deployed environment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
