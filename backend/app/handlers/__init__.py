"""Handler registry and the demo handler implementations.

Importing this package registers every handler as a side effect of importing
`demo`. Anything that needs a populated registry (the seeder, the task
runner, the DAG validator's handler check) imports `app.handlers`.
"""

from app.handlers import demo  # noqa: F401  (import registers the handlers)
from app.handlers.registry import (
    HandlerContext,
    HandlerFn,
    UnknownHandler,
    get_handler,
    handler,
    handler_names,
)

__all__ = [
    "HandlerContext",
    "HandlerFn",
    "UnknownHandler",
    "get_handler",
    "handler",
    "handler_names",
]
