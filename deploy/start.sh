#!/bin/bash
set -eu

celery -A app.queue:celery_app worker --loglevel=INFO &
worker_pid=$!
uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" &
api_pid=$!

terminate() {
  kill "$worker_pid" "$api_pid" 2>/dev/null || true
  wait "$worker_pid" "$api_pid" 2>/dev/null || true
}
trap terminate INT TERM

wait -n "$worker_pid" "$api_pid"
exit_code=$?
terminate
exit "$exit_code"
