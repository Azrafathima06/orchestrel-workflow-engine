"""Public-demo protection middleware: body size and per-IP trigger rate.

This deployment is deliberately unauthenticated — a recruiter should be able
to run a workflow without signing up. These two controls are what make that
safe on shared free-tier infrastructure. Neither is an authentication
system, and neither should grow into one.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from threading import Lock

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging import get_logger

logger = get_logger(__name__)

# Only state-changing routes are rate limited. Browsing the dashboard polls
# GETs continuously and must never be throttled.
_RATE_LIMITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _error_body(code: str, message: str, details: list | None = None) -> dict:
    """Match app.api.errors._envelope so every error the client sees is one shape."""
    return {"error": {"code": code, "message": message, "details": details}}


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject request bodies larger than `max_bytes` with 413.

    Checks Content-Length before the body is read, so an oversized payload is
    refused without being buffered into the memory of an instance that is
    also running a Celery worker.
    """

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        raw_length = request.headers.get("content-length")
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                length = 0
            if length > self.max_bytes:
                return JSONResponse(
                    status_code=413,
                    content=_error_body(
                        "request_too_large",
                        f"request body exceeds the {self.max_bytes} byte limit",
                    ),
                )
        return await call_next(request)


class TriggerRateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP sliding-window rate limit on state-changing requests.

    In-process and in-memory, deliberately: the deployment is a single
    instance, so a shared store would add a Redis dependency (and a Redis
    *correctness* dependency) for no gain. Redis in this system is transport
    only, and this keeps it that way. If this ever scales beyond one
    instance the limit becomes per-instance, which is documented rather than
    silently wrong.

    The window is a bounded deque of timestamps per client, pruned on each
    request, so memory stays proportional to recently-active clients.
    """

    def __init__(self, app, max_per_minute: int) -> None:
        super().__init__(app)
        self.max_per_minute = max_per_minute
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()

    def _client_key(self, request: Request) -> str:
        # Render terminates TLS at its edge and forwards the original client
        # in X-Forwarded-For; the first entry is the caller.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            window = self._hits.setdefault(key, deque())
            while window and window[0] < cutoff:
                window.popleft()
            if len(window) >= self.max_per_minute:
                return False
            window.append(now)
            # Opportunistic cleanup so idle clients do not accumulate.
            if len(self._hits) > 1024:
                for stale_key in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale_key]
            return True

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method not in _RATE_LIMITED_METHODS:
            return await call_next(request)

        key = self._client_key(request)
        if not self._allow(key):
            logger.info("rate_limited", path=request.url.path, method=request.method)
            return JSONResponse(
                status_code=429,
                content=_error_body(
                    "rate_limited",
                    f"too many requests — this demo allows {self.max_per_minute} "
                    "workflow triggers per minute per client",
                ),
                headers={"Retry-After": "60"},
            )
        return await call_next(request)
