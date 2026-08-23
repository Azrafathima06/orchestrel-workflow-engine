import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_error_handlers
from app.api.routes import health, runs, stats, workers, workflows
from app.config import get_settings
from app.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "startup",
        app_env=settings.app_env,
        app_version=settings.app_version,
        log_level=settings.log_level,
    )
    yield
    logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Distributed Workflow Orchestration & Automation Engine",
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    register_error_handlers(app)

    app.include_router(workflows.router)
    app.include_router(runs.router)
    app.include_router(stats.router)
    app.include_router(workers.router)
    app.include_router(health.router)

    return app


app = create_app()
