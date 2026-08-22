"""Print the distributed-parallelism evidence for a fan-out run.

Reads only persisted task_attempt rows and computes interval overlap
mechanically — no eyeballing of timestamps, nothing fabricated.

    uv run python scripts/parallelism_report.py <run_id>

Exits non-zero unless the run genuinely demonstrates parallelism:
more than one distinct worker executed shards, and at least two shard
execution intervals overlap.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.integration.overlap import (  # noqa: E402
    count_overlapping_pairs,
    overlapping_pair_labels,
)

DEFAULT_URL = "postgresql+psycopg://workflow:workflow@localhost:5432/workflow_engine"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    run_id = sys.argv[1]
    engine = create_engine(os.environ.get("DATABASE_URL", DEFAULT_URL))

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT tr.task_key, ta.worker_id, ta.started_at, ta.finished_at, ta.duration_ms
                  FROM task_attempt ta
                  JOIN task_run tr ON tr.id = ta.task_run_id
                 WHERE tr.run_id = :run_id
                 ORDER BY ta.started_at
                """
            ),
            {"run_id": run_id},
        ).all()

    if not rows:
        print(f"no attempts found for run {run_id}")
        return 1

    header = (
        f"{'task_key':<10}| {'worker_id':<18}| "
        f"{'started_at':<15}| {'finished_at':<15}| duration_ms"
    )
    print(header)
    print("-" * len(header))
    for task_key, worker_id, started, finished, duration in rows:
        print(
            f"{task_key:<10}| {worker_id:<18}| "
            f"{started.strftime('%H:%M:%S.%f')[:-3]:<15}| "
            f"{finished.strftime('%H:%M:%S.%f')[:-3]:<15}| {duration}"
        )

    shards = [(k, s, f) for k, _, s, f, _ in rows if k.startswith("shard_")]
    shard_workers = {w for k, w, _, _, _ in rows if k.startswith("shard_")}
    overlaps = count_overlapping_pairs(shards)

    print()
    print(f"distinct worker IDs (shards) : {len(shard_workers)} {sorted(shard_workers)}")
    print(f"overlapping shard pairs      : {overlaps} {overlapping_pair_labels(shards)}")
    print(f"OVERLAPPING SHARD INTERVALS  : {'YES' if overlaps else 'NO'}")

    ok = len(shard_workers) > 1 and overlaps > 0
    print(f"RESULT                       : {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
