"""Explicit state machines for workflow runs and task runs.

These enums are the single source of truth for status values: the
SQLAlchemy models in app.db.models import them directly (mapped to native
PostgreSQL enum types) rather than defining a second, parallel set of
string constants. One universe, not two.
"""

from enum import StrEnum

from app.core.errors import IllegalTransition


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UPSTREAM_FAILED = "upstream_failed"
    CANCELLED = "cancelled"


class AttemptStatus(StrEnum):
    """Deliberately smaller than TaskStatus: an attempt is either in
    progress or finished, one way or the other. It does not need QUEUED,
    RETRYING, PENDING, or UPSTREAM_FAILED — those describe the task
    across its whole lifetime, not a single attempt.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class TriggerType(StrEnum):
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    API = "api"


TASK_TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.UPSTREAM_FAILED,
        TaskStatus.CANCELLED,
    }
)

WORKFLOW_TERMINAL_STATUSES: frozenset[WorkflowStatus] = frozenset(
    {
        WorkflowStatus.SUCCEEDED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    }
)

# Legal transition maps. Every non-terminal status maps to the set of
# statuses it may move to; terminal statuses map to the empty set
# (absorbing states). This is the whole state machine in one place —
# nothing elsewhere in the codebase should hand-roll a status comparison.
WORKFLOW_TRANSITIONS: dict[WorkflowStatus, frozenset[WorkflowStatus]] = {
    WorkflowStatus.PENDING: frozenset(
        {WorkflowStatus.RUNNING, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.RUNNING: frozenset(
        {WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED}
    ),
    WorkflowStatus.SUCCEEDED: frozenset(),
    WorkflowStatus.FAILED: frozenset(),
    WorkflowStatus.CANCELLED: frozenset(),
}

# RUNNING has no direct transition to CANCELLED: a running task is not
# force-killed (we hold no fencing token over handler side effects). A
# cancelled run instead lets in-flight tasks finish naturally and cancels
# only their not-yet-started dependents. See docs/reliability.md (future).
TASK_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.QUEUED, TaskStatus.UPSTREAM_FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.QUEUED: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {TaskStatus.SUCCEEDED, TaskStatus.RETRYING, TaskStatus.FAILED}
    ),
    TaskStatus.RETRYING: frozenset({TaskStatus.QUEUED, TaskStatus.CANCELLED}),
    TaskStatus.SUCCEEDED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.UPSTREAM_FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def is_workflow_transition_allowed(old: WorkflowStatus, new: WorkflowStatus) -> bool:
    return new in WORKFLOW_TRANSITIONS[old]


def is_task_transition_allowed(old: TaskStatus, new: TaskStatus) -> bool:
    return new in TASK_TRANSITIONS[old]


def validate_workflow_transition(old: WorkflowStatus, new: WorkflowStatus) -> None:
    """Raise IllegalTransition if old -> new is not a legal workflow transition."""
    if not is_workflow_transition_allowed(old, new):
        raise IllegalTransition(f"workflow: {old.value} -> {new.value} is not a legal transition")


def validate_task_transition(old: TaskStatus, new: TaskStatus) -> None:
    """Raise IllegalTransition if old -> new is not a legal task transition."""
    if not is_task_transition_allowed(old, new):
        raise IllegalTransition(f"task: {old.value} -> {new.value} is not a legal transition")
