"""The fan-in race: simultaneous reconciles must dispatch the join exactly once.

Scenario: all four shards of a fan-out have just succeeded, and each shard's
worker enqueues reconcile(run_id). Those reconciles land concurrently. Every
one of them observes "all merge dependencies are SUCCEEDED" and plans to
dispatch merge. If more than one were allowed to act on that plan, merge
would be queued and executed several times.

**What this test actually proves.** Both protective mechanisms in the
reconciler were removed in turn and this file re-run:

- Removing the guarded compare-and-set (`WHERE status == PENDING AND
  attempt_count == ...`): **12 of 13 tests fail.** The CAS is the mechanism
  that enforces exactly-once dispatch.
- Removing `SELECT ... FOR UPDATE`: **all tests still pass.** The row lock
  serialises planning and keeps concurrent reconcilers from doing redundant
  work, but it is not what makes the dispatch unique.

So this suite is a regression test for the CAS guards specifically. The row
lock is retained for snapshot stability — see the reconciler module
docstring — and matters more in M5, where one decision writes many rows.

Threads are released from a common barrier and the scenario is repeated, so
a regression cannot hide behind lucky scheduling.
"""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import select

from app.core.states import TaskStatus
from app.db.models import TaskRun
from app.orchestration.dispatch import RecordingDispatcher
from app.orchestration.reconciler import reconcile_run
from tests.integration.factories import fanout_spec, make_run

CONCURRENT_RECONCILES = 4
REPETITIONS = 12


def _drive_to_all_shards_succeeded(session_factory) -> tuple:
    """Build a fan-out run and advance it to 'every shard SUCCEEDED, merge PENDING'."""
    with session_factory() as s:
        run = make_run(s, fanout_spec(shards=CONCURRENT_RECONCILES))

    reconcile_run(run.id, RecordingDispatcher(), session_factory)  # queues split

    with session_factory() as s:
        split = s.execute(
            select(TaskRun).where(TaskRun.run_id == run.id, TaskRun.task_key == "split")
        ).scalar_one()
        split.status = TaskStatus.SUCCEEDED
        split.attempt_count = 1
        split.output = {"ok": True}
        s.commit()

    reconcile_run(run.id, RecordingDispatcher(), session_factory)  # queues all shards

    with session_factory() as s:
        shards = (
            s.execute(
                select(TaskRun).where(
                    TaskRun.run_id == run.id, TaskRun.task_key.like("shard_%")
                )
            )
            .scalars()
            .all()
        )
        for shard in shards:
            shard.status = TaskStatus.SUCCEEDED
            shard.attempt_count = 1
            shard.output = {"ok": True}
        s.commit()

    with session_factory() as s:
        merge = s.execute(
            select(TaskRun).where(TaskRun.run_id == run.id, TaskRun.task_key == "merge")
        ).scalar_one()
        assert merge.status == TaskStatus.PENDING
        merge_id = merge.id

    return run.id, merge_id


@pytest.mark.parametrize("iteration", range(REPETITIONS))
def test_simultaneous_reconciles_dispatch_merge_exactly_once(
    session_factory, iteration: int
) -> None:
    run_id, merge_id = _drive_to_all_shards_succeeded(session_factory)

    dispatchers = [RecordingDispatcher() for _ in range(CONCURRENT_RECONCILES)]
    barrier = threading.Barrier(CONCURRENT_RECONCILES)
    errors: list[BaseException] = []

    def worker(dispatcher: RecordingDispatcher) -> None:
        try:
            # Release all threads at the same instant so their reconciles
            # genuinely contend for the run row.
            barrier.wait(timeout=10)
            reconcile_run(run_id, dispatcher, session_factory)
        except BaseException as exc:  # noqa: BLE001 - surfaced via `errors`
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(d,)) for d in dispatchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"reconcile raised under concurrency: {errors!r}"
    assert not any(t.is_alive() for t in threads), "a reconcile thread deadlocked"

    # 1. Exactly one dispatch instruction for merge, across ALL reconcilers.
    merge_dispatches = [
        d for dispatcher in dispatchers for d in dispatcher.tasks if d.task_run_id == merge_id
    ]
    assert len(merge_dispatches) == 1, (
        f"merge was dispatched {len(merge_dispatches)} times under "
        f"{CONCURRENT_RECONCILES} simultaneous reconciles"
    )
    assert merge_dispatches[0].expected_attempt == 1

    # 2. And the persisted state agrees: merge moved to QUEUED once.
    with session_factory() as s:
        merge = s.get(TaskRun, merge_id)
        assert merge.status == TaskStatus.QUEUED
        assert merge.dispatch_count == 1


def test_concurrent_reconciles_on_a_fresh_run_queue_the_source_once(session_factory) -> None:
    """The same guarantee at the other end of the DAG: a burst of reconciles
    on a brand-new run must queue its source task exactly once."""
    with session_factory() as s:
        run = make_run(s, fanout_spec(shards=2))

    dispatchers = [RecordingDispatcher() for _ in range(CONCURRENT_RECONCILES)]
    barrier = threading.Barrier(CONCURRENT_RECONCILES)
    errors: list[BaseException] = []

    def worker(dispatcher: RecordingDispatcher) -> None:
        try:
            barrier.wait(timeout=10)
            reconcile_run(run.id, dispatcher, session_factory)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(d,)) for d in dispatchers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"reconcile raised under concurrency: {errors!r}"
    total_dispatches = sum(len(d.tasks) for d in dispatchers)
    assert total_dispatches == 1, f"source task dispatched {total_dispatches} times"
