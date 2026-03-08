#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"

mkdir -p "$LOG_DIR"

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

append_banner() {
  local file="$1"
  {
    echo ""
    echo "[$(timestamp)] starting $2"
  } >> "$file"
}

is_running() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d '[:space:]' < "$file"
  fi
}

start_backend() {
  local existing_pid
  existing_pid="$(read_pid "$BACKEND_PID_FILE")"
  if is_running "$existing_pid"; then
    echo "backend is already running (pid=$existing_pid)"
    return
  fi

  append_banner "$BACKEND_LOG" "backend"
  (
    cd "$ROOT_DIR/backend"
    exec conda run --no-capture-output -n notebooklm \
      uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
  ) >> "$BACKEND_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$BACKEND_PID_FILE"
  echo "backend started (pid=$pid) -> $BACKEND_LOG"
}

start_frontend() {
  local existing_pid
  existing_pid="$(read_pid "$FRONTEND_PID_FILE")"
  if is_running "$existing_pid"; then
    echo "frontend is already running (pid=$existing_pid)"
    return
  fi

  append_banner "$FRONTEND_LOG" "frontend"
  (
    cd "$ROOT_DIR/frontend"
    exec npm run dev -- --host 127.0.0.1
  ) >> "$FRONTEND_LOG" 2>&1 &
  local pid=$!
  echo "$pid" > "$FRONTEND_PID_FILE"
  echo "frontend started (pid=$pid) -> $FRONTEND_LOG"
}

kill_process() {
  local name="$1"
  local pid_file="$2"
  local pid
  pid="$(read_pid "$pid_file")"

  if ! is_running "$pid"; then
    rm -f "$pid_file"
    echo "$name is not running"
    return
  fi

  kill "$pid" >/dev/null 2>&1 || true
  sleep 1
  if is_running "$pid"; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$pid_file"
  echo "$name stopped"
}

show_status() {
  local backend_pid frontend_pid
  backend_pid="$(read_pid "$BACKEND_PID_FILE")"
  frontend_pid="$(read_pid "$FRONTEND_PID_FILE")"

  if is_running "$backend_pid"; then
    echo "backend: running (pid=$backend_pid)"
  else
    echo "backend: stopped"
  fi

  if is_running "$frontend_pid"; then
    echo "frontend: running (pid=$frontend_pid)"
  else
    echo "frontend: stopped"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  ./start-dev.sh start
  ./start-dev.sh kill
  ./start-dev.sh status
EOF
}

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is not available in PATH"
  exit 1
fi

if [[ ! -f "$ROOT_DIR/backend/.env" ]]; then
  echo "backend/.env not found"
  exit 1
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "frontend/node_modules not found, run: cd frontend && npm install"
  exit 1
fi

COMMAND="${1:-start}"

case "$COMMAND" in
  start)
    start_backend
    start_frontend
    echo "logs:"
    echo "  backend:  $BACKEND_LOG"
    echo "  frontend: $FRONTEND_LOG"
    ;;
  kill)
    kill_process "backend" "$BACKEND_PID_FILE"
    kill_process "frontend" "$FRONTEND_PID_FILE"
    ;;
  status)
    show_status
    ;;
  *)
    usage
    exit 1
    ;;
esac
