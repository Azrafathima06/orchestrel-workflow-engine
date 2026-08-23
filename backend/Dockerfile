# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# uv, copied from its official distroless image rather than curl|sh, keeps the
# build deterministic and avoids installing curl into the runtime image.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependency layer: only invalidated when pyproject.toml/uv.lock change,
# independent of application code changes.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Application layer. alembic/ and workflows/ are part of the runtime
# image, not just build inputs: the same image runs the `migrate` and
# `seed` Compose services.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY workflows ./workflows
# Procfile + entrypoint drive the production process group (see entrypoint.sh).
COPY Procfile ./Procfile
COPY entrypoint.sh ./entrypoint.sh
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

ENV PATH="/opt/venv/bin:${PATH}"

RUN chmod +x /app/entrypoint.sh

RUN useradd --create-home --uid 1000 appuser
USER appuser

# Documentation only. In production Render injects PORT (default 10000) and
# the entrypoint binds ${PORT:-10000}; Compose overrides the command and
# publishes 8000 locally.
EXPOSE 8000

CMD ["./entrypoint.sh"]
