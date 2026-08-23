"""The reconciler: advances one workflow run, exactly once at a time.

`reconcile_run` answers "given this run's persisted state, what should
happen next?" and applies the answer. It is invoked on run creation and
after every task completion, and it is idempotent: running it repeatedly on
an unchanged run produces no writes and no dispatches.

Three mechanisms make this correct under concurrency. Their division of
labour matters, and was verified experimentally by removing each one and
re-running tests/integration/test_concurrency.py:

1. **Guarded compare-and-set is what enforces correctness.** Every state
   change is `UPDATE ... WHERE <expected state>` and acts only on
   rowcount == 1. Under READ COMMITTED, an UPDATE that blocks on a row
   lock re-evaluates its WHERE clause against the committed row afterwards,
   so of N concurrent reconcilers planning the same transition, exactly one
   matches a row and the rest match zero. Removing these guards makes the
   fan-in test fail immediately.

2. **`SELECT ... FOR UPDATE` serialises decision-making per run.** It is
   *not* what prevents double dispatch — the CAS guards already do that,
   and the fan-in test still passes without the lock. What it buys is a
   stable snapshot: a reconciler plans against task state that cannot shift
   underneath it, so concurrent reconcilers do not each redundantly plan
   work that will then be rejected. That stability becomes load-bearing in
   M5, where a single decision (UPSTREAM_FAILED propagation) writes many
   rows and must not interleave with another reconciler's writes.

3. **Commit before publish.** Broker messages are sent only after the
   transaction describing them has committed. A message that referenced
   uncommitted state would be rejected by the runner's claim guard as a
   stale delivery.

The database clock (`now()`) is the only clock used for persisted
timestamps; no Python wall-clock value is ever written.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, cast, func, select, update
from sqlalchemy.orm import Session

from app.core.states import TaskStatus, WorkflowStatus, validate_workflow_transition
from app.db.models import TaskRun, WorkflowRun
from app.logging import get_logger
from app.orchestration.dispatch import Dispatcher
from app.orchestration.planner import TaskSnapshot, plan

logger = get_logger(__name__)


def reconcile_run(run_id: uuid.UUID, dispatcher: Dispatcher, session_factory) -> None:
    """Advance `run_id` by one step, then publish whatever that step produced."""
    with session_factory() as session:
        dispatches = _reconcile_transaction(session, run_id)
        session.commit()

    # Strictly after commit. See invariant 2 above.
    for task_run_id, expected_attempt in dispatches:
        dispatcher.dispatch_task(task_run_id, expected_attempt)


def _reconcile_transaction(session: Session, run_id: uuid.UUID) -> list[tuple[uuid.UUID, int]]:
    """Apply one reconciliation step inside the caller's transaction.

    Returns the task dispatches to publish after commit. Separated from
    `reconcile_run` so the transactional logic can be exercised directly by
    the concurrency test, which needs to control commit timing.
    """
    run = session.execute(
        select(WorkflowRun).where(WorkflowRun.id == run_id).with_for_update()
    ).scalar_one_or_none()

    if run is None:
        logger.warning("reconcile_unknown_run", run_id=str(run_id))
        return []

    log = logger.bind(run_id=str(run_id), definition_key=run.definition_key)

    task_rows = (
        session.execute(select(TaskRun).where(TaskRun.run_id == run_id).order_by(TaskRun.task_key))
        .scalars()
        .all()
    )

    snapshots = tuple(
        TaskSnapshot(
            task_key=t.task_key,
            status=t.status,
            depends_on=tuple(t.depends_on),
            attempt_count=t.attempt_count,
        )
        for t in task_rows
    )

    decisions = plan(run.status, snapshots)
    if decisions.is_noop:
        log.debug("run_reconciled", outcome="noop", status=run.status.value)
        return []

    # Track the status this transaction has moved the run to, so a later
    # transition in the same pass validates against what we just wrote
    # rather than the now-stale value loaded at the top.
    effective_status = run.status

    if decisions.start_run:
        validate_workflow_transition(effective_status, WorkflowStatus.RUNNING)
        session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.status == WorkflowStatus.PENDING)
            .values(status=WorkflowStatus.RUNNING, started_at=func.now())
        )
        effective_status = WorkflowStatus.RUNNING
        log.info("run_started")

    by_key = {t.task_key: t for t in task_rows}
    dispatches: list[tuple[uuid.UUID, int]] = []

    for task_key in decisions.ready_task_keys:
        task = by_key[task_key]
        # Guarded transition: only claim this dispatch if the task is still
        # PENDING and still on the attempt we planned against. Under the run
        # lock a competing reconciler cannot be here simultaneously, but the
        # guard also protects against a stale plan and keeps the write
        # self-describing.
        claimed = session.execute(
            update(TaskRun)
            .where(
                TaskRun.id == task.id,
                TaskRun.status == TaskStatus.PENDING,
                TaskRun.attempt_count == task.attempt_count,
            )
            .values(status=TaskStatus.QUEUED, queued_at=func.now(), dispatch_count=1)
        ).rowcount

        if claimed != 1:
            log.info("task_queue_skipped", task_key=task_key, reason="state_changed")
            continue

        dispatches.append((task.id, task.attempt_count + 1))
        log.info("task_queued", task_key=task_key, task_run_id=str(task.id))

    # Failure isolation: tasks whose dependencies can never succeed are
    # marked UPSTREAM_FAILED (never ran) rather than FAILED (ran and
    # errored). Unrelated branches are simply absent from this list and keep
    # running.
    for blocked in decisions.blocked_tasks:
        task = by_key.get(blocked.task_key)
        if task is None:
            continue
        marked = session.execute(
            update(TaskRun)
            .where(
                TaskRun.id == task.id,
                TaskRun.status == TaskStatus.PENDING,
                TaskRun.attempt_count == task.attempt_count,
            )
            .values(
                status=TaskStatus.UPSTREAM_FAILED,
                finished_at=func.now(),
                error_type="UpstreamFailed",
                error_message=(
                    f"skipped: upstream task '{blocked.blocked_by}' did not succeed"
                ),
            )
        ).rowcount

        if marked == 1:
            log.info(
                "upstream_failed",
                task_key=blocked.task_key,
                blocked_by=blocked.blocked_by,
                task_run_id=str(task.id),
            )

    if decisions.run_failed:
        validate_workflow_transition(effective_status, WorkflowStatus.FAILED)
        session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.status.in_([WorkflowStatus.RUNNING, WorkflowStatus.PENDING]),
            )
            .values(
                status=WorkflowStatus.FAILED,
                finished_at=func.now(),
                duration_ms=cast(
                    func.extract(
                        "epoch",
                        func.now()
                        - func.coalesce(WorkflowRun.started_at, WorkflowRun.created_at),
                    )
                    * 1000,
                    Integer,
                ),
                error=decisions.run_error,
            )
        )
        log.info("run_failed", error=decisions.run_error)

    if decisions.run_succeeded:
        validate_workflow_transition(effective_status, WorkflowStatus.SUCCEEDED)
        session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == run_id, WorkflowRun.status == WorkflowStatus.RUNNING)
            .values(
                status=WorkflowStatus.SUCCEEDED,
                finished_at=func.now(),
                # Duration derived entirely in the database, from database
                # timestamps — never from a Python clock reading.
                duration_ms=cast(
                    func.extract("epoch", func.now() - WorkflowRun.started_at) * 1000,
                    Integer,
                ),
            )
        )
        log.info("run_succeeded")

    return dispatches
