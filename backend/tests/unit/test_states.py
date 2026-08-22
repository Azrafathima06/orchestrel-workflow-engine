"""Exhaustive coverage of the workflow and task state machines.

Every (old, new) pair for both enums is checked against the transition
tables — not a hand-picked subset — so a future edit that silently
loosens or tightens a transition fails immediately.
"""

import itertools

import pytest

from app.core.errors import IllegalTransition
from app.core.states import (
    TASK_TERMINAL_STATUSES,
    TASK_TRANSITIONS,
    WORKFLOW_TERMINAL_STATUSES,
    WORKFLOW_TRANSITIONS,
    TaskStatus,
    WorkflowStatus,
    is_task_transition_allowed,
    is_workflow_transition_allowed,
    validate_task_transition,
    validate_workflow_transition,
)

ALL_WORKFLOW_PAIRS = list(itertools.product(WorkflowStatus, WorkflowStatus))
ALL_TASK_PAIRS = list(itertools.product(TaskStatus, TaskStatus))


@pytest.mark.parametrize("old,new", ALL_WORKFLOW_PAIRS, ids=lambda s: s.value)
def test_workflow_transition_matches_table(old: WorkflowStatus, new: WorkflowStatus) -> None:
    legal = new in WORKFLOW_TRANSITIONS[old]
    assert is_workflow_transition_allowed(old, new) is legal
    if legal:
        validate_workflow_transition(old, new)  # must not raise
    else:
        with pytest.raises(IllegalTransition):
            validate_workflow_transition(old, new)


@pytest.mark.parametrize("old,new", ALL_TASK_PAIRS, ids=lambda s: s.value)
def test_task_transition_matches_table(old: TaskStatus, new: TaskStatus) -> None:
    legal = new in TASK_TRANSITIONS[old]
    assert is_task_transition_allowed(old, new) is legal
    if legal:
        validate_task_transition(old, new)
    else:
        with pytest.raises(IllegalTransition):
            validate_task_transition(old, new)


def test_workflow_terminal_states_are_absorbing() -> None:
    for status in WORKFLOW_TERMINAL_STATUSES:
        assert WORKFLOW_TRANSITIONS[status] == frozenset()


def test_task_terminal_states_are_absorbing() -> None:
    for status in TASK_TERMINAL_STATUSES:
        assert TASK_TRANSITIONS[status] == frozenset()


def test_every_status_has_a_transition_table_entry() -> None:
    assert set(WORKFLOW_TRANSITIONS) == set(WorkflowStatus)
    assert set(TASK_TRANSITIONS) == set(TaskStatus)


@pytest.mark.parametrize(
    "old,new",
    [
        (TaskStatus.PENDING, TaskStatus.QUEUED),
        (TaskStatus.PENDING, TaskStatus.UPSTREAM_FAILED),
        (TaskStatus.PENDING, TaskStatus.CANCELLED),
        (TaskStatus.QUEUED, TaskStatus.RUNNING),
        (TaskStatus.QUEUED, TaskStatus.CANCELLED),
        (TaskStatus.RUNNING, TaskStatus.SUCCEEDED),
        (TaskStatus.RUNNING, TaskStatus.RETRYING),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
        (TaskStatus.RETRYING, TaskStatus.QUEUED),
        (TaskStatus.RETRYING, TaskStatus.CANCELLED),
    ],
)
def test_task_transition_explicitly_legal(old: TaskStatus, new: TaskStatus) -> None:
    """Spot checks mirroring the architecture doc, so a regression here
    fails with a specific, readable case rather than only a generic
    cross-product failure."""
    assert is_task_transition_allowed(old, new)


def test_running_task_has_no_direct_cancellation() -> None:
    """A RUNNING task is never force-cancelled: we hold no fencing token
    over handler side effects, so cancellation must let the in-flight
    attempt finish naturally rather than transition it straight to
    CANCELLED."""
    assert not is_task_transition_allowed(TaskStatus.RUNNING, TaskStatus.CANCELLED)


@pytest.mark.parametrize(
    "old,new",
    [
        (WorkflowStatus.PENDING, WorkflowStatus.RUNNING),
        (WorkflowStatus.PENDING, WorkflowStatus.FAILED),
        (WorkflowStatus.PENDING, WorkflowStatus.CANCELLED),
        (WorkflowStatus.RUNNING, WorkflowStatus.SUCCEEDED),
        (WorkflowStatus.RUNNING, WorkflowStatus.FAILED),
        (WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED),
    ],
)
def test_workflow_transition_explicitly_legal(old: WorkflowStatus, new: WorkflowStatus) -> None:
    assert is_workflow_transition_allowed(old, new)
