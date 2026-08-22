"""Domain-level exceptions for the orchestration engine.

Deliberately framework-independent: these are the exceptions the DAG
validator, state machine, and (in later milestones) the reconciler and
task runner raise and catch. They carry no dependency on FastAPI,
SQLAlchemy, or Celery.
"""


class DomainError(Exception):
    """Base class for all orchestration-domain errors."""


class IllegalTransition(DomainError):
    """Raised when a state transition violates the workflow/task state machine."""


class RetriableError(DomainError):
    """A failure that is safe to retry.

    Raised by task handlers to signal a transient failure (a flaky
    dependency, a timeout, a temporary resource conflict).
    """


class PermanentError(DomainError):
    """A failure that must not be retried.

    Raised by task handlers to signal that retrying cannot possibly help
    (invalid input, a business-rule violation).
    """


class TaskTimeout(RetriableError):
    """A task exceeded its configured timeout_seconds.

    Subclasses RetriableError: a timeout is usually a transient condition
    (slow dependency, resource contention), so it is retried like any
    other retriable failure rather than requiring special-case handling.
    """


class WorkerLost(RetriableError):
    """A worker's lease expired before it reported an outcome.

    Raised by the recovery sweeper (not by handler code) when a task stays
    RUNNING past `lease_expires_at`. Subclasses RetriableError because the
    task itself never definitively failed — the worker running it did.
    """


class UndeliverableTask(DomainError):
    """A task could not be delivered to a worker after repeated recovery attempts.

    Raised by the recovery sweeper's circuit breaker (see
    MAX_DISPATCH_ATTEMPTS), not by the ordinary retry path — this is a
    terminal infrastructure failure, not a retriable handler outcome.
    """
