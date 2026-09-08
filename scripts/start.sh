#!/usr/bin/env sh
set -eu

# Production process manager — mirrors Quizzer's gunicorn + uvicorn workers pattern.
WORKERS="${WEB_CONCURRENCY:-2}"
PORT="${PORT:-8100}"
HOST="${HOST:-0.0.0.0}"

# Build/refresh the Chroma index once per container start (before workers
# fork) so a fresh deploy — or a fresh Render disk — doesn't serve keyword-
# only retrieval until someone remembers a manual step. Incremental (no
# --force): a no-op in ms if the corpus/model haven't changed. Never fails
# the boot — /ready and retrieve.py's keyword fallback both degrade
# honestly if this doesn't produce an index (e.g. LLM_API_KEY missing).
if [ "${QUE_RAG_ENABLED:-true}" = "true" ]; then
  python -m app.knowledge || echo "warn: knowledge index build failed — falling back to keyword retrieval" >&2
fi

exec gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers "${WORKERS}" \
  --bind "${HOST}:${PORT}" \
  --access-logfile - \
  --error-logfile - \
  --capture-output \
  --timeout 120
