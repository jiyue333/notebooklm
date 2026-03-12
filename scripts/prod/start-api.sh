#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUN_DIR="$ROOT_DIR/run"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$RUN_DIR/api.pid"

mkdir -p "$RUN_DIR" "$LOG_DIR"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "api already running: $(cat "$PID_FILE")"
  exit 0
fi

cd "$ROOT_DIR/backend"
export PYTHONUNBUFFERED=1
nohup "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8080 --workers 2 \
  >>"$LOG_DIR/backend.log" 2>&1 &
echo $! >"$PID_FILE"
echo "api started: $(cat "$PID_FILE")"
