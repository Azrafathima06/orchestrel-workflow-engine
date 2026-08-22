"""Dispatcher abstraction: the single seam between orchestration and Celery.

Orchestration modules (reconciler, runner) never call `.delay()` or
`.apply_async()` directly. They hand dispatch instructions to a Dispatcher.
That keeps two things true:

- The reconciler and runner are testable against a real PostgreSQL database
  with no broker running at all (InlineDispatcher / RecordingDispatcher).
- Swapping or reconfiguring the transport touches one file.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class TaskDispatch:
    task_run_id: uuid.UUID
    expected_attempt: int


@dataclass(frozen=True)
class ReconcileDispatch:
    run_id: uuid.UUID


class Dispatcher(Protocol):
    """Publishes work to be executed elsewhere.

    Implementations must only ever be invoked AFTER the database
    transaction describing the work has committed — a message referring to
    uncommitted state is a message a worker will reject as stale.
    """

    def dispatch_task(self, task_run_id: uuid.UUID, expected_attempt: int) -> None: ...

    def dispatch_reconcile(self, run_id: uuid.UUID) -> None: ...


@dataclass
class RecordingDispatcher:
    """Records dispatch instructions without executing them.

    Used by tests that assert *what would be dispatched* — most importantly
    the fan-in concurrency test, which asserts exactly one merge dispatch is
    produced across simultaneous reconciles.
    """

    tasks: list[TaskDispatch] = field(default_factory=list)
    reconciles: list[ReconcileDispatch] = field(default_factory=list)

    def dispatch_task(self, task_run_id: uuid.UUID, expected_attempt: int) -> None:
        self.tasks.append(TaskDispatch(task_run_id=task_run_id, expected_attempt=expected_attempt))

    def dispatch_reconcile(self, run_id: uuid.UUID) -> None:
        self.reconciles.append(ReconcileDispatch(run_id=run_id))


class InlineDispatcher:
    """Executes dispatched work synchronously, in-process, on the same code path.

    This is not a mock: it drives the real reconciler and the real task
    runner, with real database writes and real handler execution. Only the
    transport is different. It exists so the engine's correctness can be
    tested in milliseconds without Redis, and it is what proves the
    orchestration layer is genuinely independent of Celery.

    Recursion is bounded by the DAG itself: each task completion triggers
    one reconcile, which dispatches only newly-ready tasks, and a finished
    run dispatches nothing.
    """

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def dispatch_task(self, task_run_id: uuid.UUID, expected_attempt: int) -> None:
        # Imported here rather than at module scope to avoid a circular
        # import: runner imports dispatch for its type hints.
        from app.orchestration.runner import execute_task_attempt

        execute_task_attempt(
            task_run_id=task_run_id,
            expected_attempt=expected_attempt,
            dispatcher=self,
            session_factory=self._session_factory,
            celery_task_id=None,
        )

    def dispatch_reconcile(self, run_id: uuid.UUID) -> None:
        from app.orchestration.reconciler import reconcile_run

        reconcile_run(run_id=run_id, dispatcher=self, session_factory=self._session_factory)


class CeleryDispatcher:
    """Publishes to Redis via Celery. The production transport."""

    def dispatch_task(self, task_run_id: uuid.UUID, expected_attempt: int) -> None:
        from app.worker.tasks import execute_task

        execute_task.apply_async(
            args=[str(task_run_id), expected_attempt],
            queue="tasks",
        )

    def dispatch_reconcile(self, run_id: uuid.UUID) -> None:
        from app.worker.tasks import reconcile

        reconcile.apply_async(args=[str(run_id)], queue="orchestrator")
