"""Pydantic models for the persisted, declarative workflow specification.

A workflow is data, not code: `handler` is a string lookup key into a
handler registry (built in a later milestone), never a code path or a
pickled callable. This module validates SHAPE only — types, bounds,
required fields. Graph SEMANTICS (unique keys, cycle-freedom, dependency
resolution) are the job of app.core.dag, deliberately kept separate so
each module answers one question.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.retry import RetryPolicy

# Generous but bounded: long enough for any of this project's demo
# workloads, short enough that a misconfigured task cannot silently hang
# a run for hours on free-tier infrastructure.
_MIN_TIMEOUT_SECONDS = 1
_MAX_TIMEOUT_SECONDS = 3600


class TaskSpec(BaseModel):
    """One DAG node: a unit of work and its dependencies."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    handler: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = Field(default_factory=tuple)
    retry: RetryPolicy | None = None
    timeout_seconds: int | None = Field(
        default=None, ge=_MIN_TIMEOUT_SECONDS, le=_MAX_TIMEOUT_SECONDS
    )


class WorkflowDefaults(BaseModel):
    """Fallback retry policy and timeout applied to tasks that don't set their own."""

    model_config = ConfigDict(frozen=True)

    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: int = Field(
        default=60, ge=_MIN_TIMEOUT_SECONDS, le=_MAX_TIMEOUT_SECONDS
    )


class WorkflowSpec(BaseModel):
    """The full declarative document stored in workflow_definition.spec."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    params_schema: dict[str, Any] = Field(default_factory=dict)
    defaults: WorkflowDefaults = Field(default_factory=WorkflowDefaults)
    tasks: tuple[TaskSpec, ...] = Field(min_length=1)

    def effective_retry_policy(self, task: TaskSpec) -> RetryPolicy:
        """The retry policy that actually applies to `task`: its own, or the workflow default."""
        return task.retry if task.retry is not None else self.defaults.retry

    def effective_timeout_seconds(self, task: TaskSpec) -> int:
        """The timeout that actually applies to `task`: its own, or the workflow default."""
        if task.timeout_seconds is not None:
            return task.timeout_seconds
        return self.defaults.timeout_seconds
