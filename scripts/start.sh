#!/usr/bin/env sh
set -eu

# Production process manager — mirrors Quizzer's gunicorn + uvicorn workers pattern.
WORKERS="${WEB_CONCURRENCY:-2}"
PORT="${PORT:-8100}"
HOST="${HOST:-0.0.0.0}"

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "${WORKERS}" \
  --bind "${HOST}:${PORT}" \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --timeout 120
