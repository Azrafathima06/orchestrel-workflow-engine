"""Workflow definition endpoints and the run trigger."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_dispatcher
from app.api.schemas import RunDetail, TriggerRunRequest, WorkflowDetail, WorkflowSummary
from app.api.serializers import run_to_detail
from app.core.states import TriggerType
from app.db.models import WorkflowDefinition
from app.db.session import get_db
from app.logging import get_logger
from app.orchestration.dispatch import Dispatcher
from app.orchestration.materialize import create_run

router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])
logger = get_logger(__name__)


def _get_definition(db: Session, key: str) -> WorkflowDefinition:
    definition = db.execute(
        select(WorkflowDefinition).where(WorkflowDefinition.key == key)
    ).scalar_one_or_none()
    if definition is None:
        raise HTTPException(status_code=404, detail=f"unknown workflow '{key}'")
    return definition


@router.get("", response_model=list[WorkflowSummary])
def list_workflows(db: Session = Depends(get_db)) -> list[WorkflowSummary]:
    definitions = (
        db.execute(select(WorkflowDefinition).order_by(WorkflowDefinition.key)).scalars().all()
    )
    return [
        WorkflowSummary(
            key=d.key,
            name=d.name,
            description=d.description,
            version=d.version,
            is_active=d.is_active,
            task_count=len(d.spec.get("tasks", [])),
        )
        for d in definitions
    ]


@router.get("/{key}", response_model=WorkflowDetail)
def get_workflow(key: str, db: Session = Depends(get_db)) -> WorkflowDetail:
    d = _get_definition(db, key)
    return WorkflowDetail(
        key=d.key,
        name=d.name,
        description=d.description,
        version=d.version,
        is_active=d.is_active,
        spec=d.spec,
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
        raise HTTPException(status_code=409, detail=f"workflow '{key}' is not active")

    run = create_run(db, definition, params=body.params, trigger_type=TriggerType.MANUAL)
    detail = run_to_detail(db, run)

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
