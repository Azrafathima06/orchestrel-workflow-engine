"""Workflow definition endpoints and the run trigger."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.aggregates import retry_counts_for_runs, task_counts_for_runs
from app.api.deps import get_dispatcher
from app.api.errors import AppError
from app.api.schemas import (
    RunDetail,
    RunSummary,
    TriggerRunRequest,
    WorkflowDetail,
    WorkflowNode,
    WorkflowSummary,
)
from app.api.serializers import run_to_detail, run_to_summary, spec_snapshot_to_edges
from app.config import get_settings
from app.core.params import validate_params
from app.core.spec import WorkflowSpec
from app.core.states import TriggerType, WorkflowStatus
from app.db.models import WorkflowDefinition, WorkflowRun
from app.db.session import get_db
from app.logging import get_logger
from app.orchestration.dispatch import Dispatcher
from app.orchestration.materialize import create_run

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
logger = get_logger(__name__)
settings = get_settings()

# Run states that still consume worker capacity. RETRYING counts: the task
# is not finished and will be dispatched again, so a run full of retrying
# tasks is very much still active work.
_ACTIVE_RUN_STATUSES = (WorkflowStatus.PENDING, WorkflowStatus.RUNNING)

# How many recent runs count toward a workflow's "recent success/failure"
# summary on the list page. Small and fixed: cheap to compute, and a
# workflow's health right now matters more than its all-time history.
RECENT_RUN_WINDOW = 20


def _get_definition(db: Session, key: str) -> WorkflowDefinition:
    definition = db.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.key == key)
    ).scalar_one_or_none()
    if definition is None:
        raise AppError("workflow_not_found", f"unknown workflow '{key}'", status_code=404)
    return definition


def _recent_runs(db: Session, definition_id, limit: int) -> list[WorkflowRun]:
    return (
        db.execute(
            select(WorkflowRun)
            .where(WorkflowRun.definition_id == definition_id)
            .order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def _runs_to_summaries(
    db: Session, runs: list[WorkflowRun], workflow_name: str
) -> list[RunSummary]:
    run_ids = [r.id for r in runs]
    counts = task_counts_for_runs(db, run_ids)
    retries = retry_counts_for_runs(db, run_ids)
    return [
        run_to_summary(r, workflow_name, counts[r.id], retries[r.id]) for r in runs
    ]


@router.get("", response_model=list[WorkflowSummary])
def list_workflows(db: Session = Depends(get_db)) -> list[WorkflowSummary]:
    definitions = (
        db.execute(select(WorkflowDefinition).order_by(WorkflowDefinition.key)).scalars().all()
    )

    result: list[WorkflowSummary] = []
    for d in definitions:
        recent = _recent_runs(db, d.id, RECENT_RUN_WINDOW)
        summaries = _runs_to_summaries(db, recent, d.name)
        result.append(
            WorkflowSummary(
                key=d.key,
                name=d.name,
                description=d.description,
                version=d.version,
                is_active=d.is_active,
                is_public=bool(d.spec.get("is_public", True)),
                task_count=len(d.spec.get("tasks", [])),
                last_run=summaries[0] if summaries else None,
                recent_success_count=sum(
                    1 for r in recent if r.status == WorkflowStatus.SUCCEEDED
                ),
                recent_failure_count=sum(
                    1 for r in recent if r.status == WorkflowStatus.FAILED
                ),
            )
        )
    return result


@router.get("/{key}", response_model=WorkflowDetail)
def get_workflow(key: str, db: Session = Depends(get_db)) -> WorkflowDetail:
    d = _get_definition(db, key)
    spec = WorkflowSpec.model_validate(d.spec)

    nodes = [
        WorkflowNode(
            task_key=t.key,
            handler=t.handler,
            depends_on=list(t.depends_on),
            max_attempts=spec.effective_retry_policy(t).max_attempts,
            timeout_seconds=spec.effective_timeout_seconds(t),
        )
        for t in spec.tasks
    ]

    recent = _recent_runs(db, d.id, 10)
    recent_summaries = _runs_to_summaries(db, recent, d.name)

    return WorkflowDetail(
        key=d.key,
        name=d.name,
        description=d.description,
        version=d.version,
        is_active=d.is_active,
        is_public=spec.is_public,
        spec=d.spec,
        params_schema=spec.params_schema,
        nodes=nodes,
        edges=spec_snapshot_to_edges(d.spec),
        recent_runs=recent_summaries,
    )


@router.post("/{key}/runs", response_model=RunDetail, status_code=status.HTTP_202_ACCEPTED)
def trigger_run(
    key: str,
    body: TriggerRunRequest,
    response: Response,
    db: Session = Depends(get_db),
    dispatcher: Dispatcher = Depends(get_dispatcher),
) -> RunDetail:
    """Create a run and hand it to the orchestrator.

    202, not 200: the run is durably created and queued, but no work has
    happened yet. The API process never executes handler code — it commits
    state, publishes one reconcile message, and returns.
    """
    definition = _get_definition(db, key)
    if not definition.is_active:
        raise AppError(
            "workflow_inactive", f"workflow '{key}' is not active", status_code=409
        )

    spec = WorkflowSpec.model_validate(definition.spec)

    # Fault-injection workflows stay seeded and inspectable, but a public
    # visitor must not be able to start a deliberately heavy or
    # deliberately-killed workload on shared infrastructure.
    if not spec.is_public:
        raise AppError(
            "workflow_not_publicly_triggerable",
            f"workflow '{key}' is a fault-injection workflow and cannot be "
            "triggered through the public API; run it locally with the "
            "recovery-test Compose overlay",
            status_code=403,
        )

    # Validate BEFORE creating anything, so a rejected request leaves no
    # trace in the database.
    param_errors = validate_params(body.params, spec.params_schema)
    if param_errors:
        raise AppError(
            "invalid_parameters",
            "one or more run parameters are invalid",
            status_code=422,
            details=[e.as_dict() for e in param_errors],
        )

    # Capacity check. A single cheap COUNT with no lock and no open
    # transaction across network work — it cannot deadlock against the
    # reconciler's SELECT ... FOR UPDATE, which locks individual
    # workflow_run rows rather than scanning them.
    active_runs = db.execute(
        select(func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.status.in_(_ACTIVE_RUN_STATUSES))
    ).scalar_one()
    if active_runs >= settings.max_active_runs:
        raise AppError(
            "too_many_active_runs",
            f"this demo allows {settings.max_active_runs} concurrent runs; "
            f"{active_runs} are already in flight — wait for one to finish",
            status_code=429,
        )

    run = create_run(db, definition, params=body.params, trigger_type=TriggerType.MANUAL)
    detail = run_to_detail(db, run, definition.name)

    # Commit BEFORE publishing: a reconcile message for an uncommitted run
    # would find nothing to do.
    db.commit()

    logger.info(
        "workflow_triggered",
        run_id=str(run.id),
        definition_key=key,
        task_count=len(detail.tasks),
    )
    dispatcher.dispatch_reconcile(run.id)

    response.headers["Location"] = f"/api/v1/runs/{run.id}"
    return detail
