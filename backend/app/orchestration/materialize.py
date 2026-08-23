"""Create a workflow run and materialise its DAG into task_run rows.

Kept out of the API layer because it is orchestration, not HTTP: scheduled
triggers (M5+) create runs through exactly this function.

Every task_run row is created up front, in PENDING, with its effective
handler/params/retry/timeout resolved from the spec snapshot. Materialising
the whole DAG immediately means the reconciler only ever reads state — it
never has to interpret the spec to discover that a task exists — and the API
can show the full graph the instant a run is created.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.spec import WorkflowSpec
from app.core.states import TaskStatus, TriggerType, WorkflowStatus
from app.db.models import TaskRun, WorkflowDefinition, WorkflowRun


def create_run(
    session: Session,
    definition: WorkflowDefinition,
    params: dict,
    trigger_type: TriggerType = TriggerType.MANUAL,
) -> WorkflowRun:
    """Persist a new run plus one PENDING task_run per DAG node.

    The caller owns the transaction and must commit; the run is durable
    before any broker message referring to it is published.
    """
    spec = WorkflowSpec.model_validate(definition.spec)

    run = WorkflowRun(
        id=uuid.uuid4(),
        definition_id=definition.id,
        definition_key=definition.key,
        # Frozen copy: a run stays renderable and re-runnable exactly as it
        # was defined, even if the definition is edited later.
        spec_snapshot=definition.spec,
        status=WorkflowStatus.PENDING,
        trigger_type=trigger_type,
        params=params,
    )
    session.add(run)
    session.flush()

    for task in spec.tasks:
        session.add(
            TaskRun(
                run_id=run.id,
                task_key=task.key,
                handler=task.handler,
                status=TaskStatus.PENDING,
                depends_on=list(task.depends_on),
                params=_effective_task_params(spec, task, params),
                attempt_count=0,
                max_attempts=spec.effective_retry_policy(task).max_attempts,
                timeout_seconds=spec.effective_timeout_seconds(task),
            )
        )

    session.flush()
    return run


def _effective_task_params(spec: WorkflowSpec, task, run_params: dict) -> dict:
    """Task params with run-level overrides applied.

    Only keys the workflow explicitly declares in `params_schema` may be
    overridden, and only on tasks that already define them. That keeps the
    trigger API from injecting arbitrary keys into handler inputs while
    still letting a run tune declared knobs — e.g. `fail_until` on
    retry_backoff, which is what lets one workflow demonstrate both
    "succeeds after retries" and "exhausts retries".
    """
    effective = dict(task.params)
    for key in spec.params_schema:
        if key in run_params and key in effective:
            effective[key] = run_params[key]
    return effective
