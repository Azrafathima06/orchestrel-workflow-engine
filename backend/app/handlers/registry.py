"""Fixed handler registry: maps a spec's `handler` string to reviewed Python code.

A workflow definition is data. It names a handler ("data.extract"); it never
carries a code path, an import string, or a serialized callable. Lookup is a
dict access against functions registered at import time via @handler, so
there is no eval, no exec, and no dynamic import driven by user input. The
worst a malicious spec can do is name a handler that does not exist, which
raises UnknownHandler.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import structlog

from app.core.errors import PermanentError


class UnknownHandler(PermanentError):
    """A spec referenced a handler name that is not in the registry.

    Permanent by classification: retrying cannot make a missing handler
    appear.
    """


@dataclass(frozen=True)
class HandlerContext:
    """Execution context handed to a handler.

    Deliberately small and framework-free: a handler can be called from a
    Celery worker, a test, or a synchronous inline dispatcher without
    knowing the difference. It holds no database session and no Celery
    object, which is what keeps handlers testable in isolation.
    """

    run_id: str
    task_run_id: str
    task_key: str
    attempt_number: int
    worker_id: str
    logger: structlog.typing.FilteringBoundLogger


class HandlerFn(Protocol):
    def __call__(
        self,
        context: HandlerContext,
        params: dict[str, Any],
        upstream_outputs: dict[str, Any],
    ) -> dict[str, Any]: ...


_REGISTRY: dict[str, HandlerFn] = {}


def handler(name: str) -> Callable[[HandlerFn], HandlerFn]:
    """Register a function under `name`. Duplicate registration fails loudly."""

    def decorator(fn: HandlerFn) -> HandlerFn:
        if name in _REGISTRY:
            raise ValueError(
                f"handler '{name}' is already registered to "
                f"{_REGISTRY[name].__module__}.{_REGISTRY[name].__name__}"
            )
        _REGISTRY[name] = fn
        return fn

    return decorator


def get_handler(name: str) -> HandlerFn:
    try:
        return _REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(_REGISTRY)) or "<none registered>"
        raise UnknownHandler(f"unknown handler '{name}'; registered handlers: {known}") from None


def handler_names() -> frozenset[str]:
    """All registered handler names.

    Passed to app.core.dag.validate_dag() as a plain collection, which is
    how the pure DAG validator checks handler existence without importing
    this module.
    """
    return frozenset(_REGISTRY)
