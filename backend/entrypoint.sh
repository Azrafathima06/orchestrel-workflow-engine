#!/bin/sh
# Production entrypoint for the single Render Web Service.
#
# Ordering is the same one Compose stages locally: schema first, then
# definitions, then the processes that depend on both. Both steps are
# idempotent, so this is safe to re-run on every deploy and on every
# wake-from-spin-down.
#
# `exec` matters: honcho replaces this shell as PID 1, so Render's SIGTERM
# reaches honcho, which forwards it to all three children. honcho also
# terminates the whole group when any child exits, so a dead uvicorn takes
# the container down and Render restarts it — rather than leaving a
# half-dead instance that still answers health checks.
set -e

echo "[entrypoint] applying database migrations"
alembic upgrade head

echo "[entrypoint] seeding workflow definitions"
python -m app.seed

echo "[entrypoint] starting web + worker + beat"
exec honcho start
