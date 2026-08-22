"""Thin Celery task wrappers.

These are adapters, nothing more: they translate a Celery delivery into a
call on the orchestration layer. All business logic lives in
app.orchestration, which knows nothing about Celery and is exercised
directly by the test suite without a broker.
"""

from __future__ import annotations

import uuid

from app.db.session import SessionLocal
from app.orchestration.dispatch import CeleryDispatcher
from app.orchestration.reconciler import reconcile_run
from app.orchestration.runner import execute_task_attempt
from app.worker.celery_app import celery_app

_dispatcher = CeleryDispatcher()


@celery_app.task(name="app.worker.tasks.reconcile")
def reconcile(run_id: str) -> None:
    reconcile_run(
        run_id=uuid.UUID(run_id),
        dispatcher=_dispatcher,
        session_factory=SessionLocal,
    )


@celery_app.task(name="app.worker.tasks.execute_task", bind=True)
def execute_task(self, task_run_id: str, expected_attempt: int) -> None:
    execute_task_attempt(
        task_run_id=uuid.UUID(task_run_id),
        expected_attempt=expected_attempt,
        dispatcher=_dispatcher,
        session_factory=SessionLocal,
        # Recording the Celery delivery ID alongside our own attempt row
        # makes a message traceable from broker to database when debugging.
        celery_task_id=self.request.id,
    )
