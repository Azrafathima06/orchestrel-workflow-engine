"""API dependencies.

The dispatcher is injected rather than imported at call sites so tests can
substitute a recording dispatcher, and so the API's only relationship with
Celery is "publish this message" — never "import the worker".
"""

from app.orchestration.dispatch import CeleryDispatcher, Dispatcher

_dispatcher = CeleryDispatcher()


def get_dispatcher() -> Dispatcher:
    return _dispatcher
