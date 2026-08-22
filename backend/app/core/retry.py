"""Retry policy and exponential-backoff calculation.

This module implements retry POLICY only: how to decide the delay before
a retry and how to classify an error as retriable or permanent. It does
not execute retries — that belongs to the future orchestration layer,
which persists these decisions to task_run/task_attempt rows.
"""

from collections.abc import Callable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import IllegalTransition, PermanentError, RetriableError


class RetryPolicy(BaseModel):
    """Immutable retry configuration for a task.

    Defaults describe a task that does not retry (max_attempts=1); the
    backoff fields only matter once max_attempts > 1.
    """

    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=1, ge=1)
    backoff_seconds: float = Field(default=1.0, ge=0)
    backoff_factor: float = Field(default=2.0, ge=1)
    max_backoff_seconds: float = Field(default=30.0, ge=0)
    jitter: float = Field(default=0.0, ge=0, le=1)


def next_backoff(attempt: int, policy: RetryPolicy, rand: Callable[[], float]) -> float:
    """Compute the delay, in seconds, before retrying after `attempt` has failed.

    `attempt` is the 1-indexed attempt number that just failed. `rand` must
    return a float in [0, 1); it is injected rather than read from the
    global `random` module so the sequence is deterministic in tests and
    reproducible in production logs.

    Formula: raw = backoff_seconds * backoff_factor ** (attempt - 1),
    capped at max_backoff_seconds, then jittered by up to ±jitter of the
    capped value. Jitter is applied AFTER capping (so a jittered value can
    exceed max_backoff_seconds by at most a factor of 1 + jitter) — this
    keeps the cap meaningful as a "typical" ceiling while still
    de-synchronising a thundering herd of simultaneously failing tasks.
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")

    raw = policy.backoff_seconds * (policy.backoff_factor ** (attempt - 1))
    capped = min(raw, policy.max_backoff_seconds)

    if policy.jitter <= 0:
        return capped

    # rand() in [0, 1) maps to a jitter multiplier in [1 - jitter, 1 + jitter);
    # rand() == 0.5 is the exact midpoint and yields zero deviation, which is
    # what makes the deterministic geometric-sequence tests exact rather than
    # approximate.
    multiplier = 1.0 + policy.jitter * (2.0 * rand() - 1.0)
    return max(0.0, capped * multiplier)


class ErrorClassification(StrEnum):
    RETRIABLE = "retriable"
    PERMANENT = "permanent"


def classify_error(exc: Exception) -> ErrorClassification:
    """Classify an exception raised during task execution as retriable or permanent.

    Order matters:
    - PermanentError and IllegalTransition are always permanent: a
      business-rule failure or a state-machine bug will not be fixed by
      trying again.
    - Pydantic's ValidationError is permanent: malformed input data does
      not become valid on retry.
    - RetriableError (and its subclasses TaskTimeout, WorkerLost) is
      always retriable.
    - Any other, unclassified exception is treated as retriable. A
      transient infrastructure hiccup (a DB blip, a DNS failure, an OOM
      kill) is indistinguishable from a code bug at this layer, and the
      cost of wrongly retrying a real bug is bounded by max_attempts,
      while the cost of NOT retrying a transient failure is an
      unnecessary run failure. Conservative retry is the safer default.
    """
    if isinstance(exc, PermanentError | IllegalTransition):
        return ErrorClassification.PERMANENT

    if isinstance(exc, PydanticValidationError):
        return ErrorClassification.PERMANENT

    if isinstance(exc, RetriableError):
        return ErrorClassification.RETRIABLE

    return ErrorClassification.RETRIABLE
