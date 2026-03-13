#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/run"
LOG_DIR="$ROOT_DIR/logs"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
UVICORN_BIN="$ROOT_DIR/.venv/bin/uvicorn"

mkdir -p "$RUN_DIR" "$LOG_DIR"

ensure_prod_prerequisites() {
  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "root .env not found"
    exit 1
  fi
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "python executable not found: $PYTHON_BIN"
    exit 1
  fi
  if [[ ! -x "$UVICORN_BIN" ]]; then
    echo "uvicorn executable not found: $UVICORN_BIN"
    exit 1
  fi
}

component_pid_file() {
  local component="$1"
  echo "$RUN_DIR/$component.pid"
}

component_log_file() {
  local component="$1"
  case "$component" in
    api) echo "$LOG_DIR/backend.log" ;;
    worker) echo "$LOG_DIR/worker.log" ;;
    scheduler) echo "$LOG_DIR/scheduler.log" ;;
    *)
      echo "unknown component: $component" >&2
      exit 1
      ;;
  esac
}

start_one() {
  local component="$1"
  local pid_file
  pid_file="$(component_pid_file "$component")"
  local log_file
  log_file="$(component_log_file "$component")"

  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    echo "$component already running: $(cat "$pid_file")"
    return
  fi

  cd "$ROOT_DIR/backend"
  export PYTHONUNBUFFERED=1
  case "$component" in
    api)
      nohup "$UVICORN_BIN" app.main:app --host 127.0.0.1 --port 8080 --workers 2 >>"$log_file" 2>&1 &
      ;;
    worker)
      nohup "$PYTHON_BIN" -m app.workers.run_worker >>"$log_file" 2>&1 &
      ;;
    scheduler)
      nohup "$PYTHON_BIN" -m app.workers.run_scheduler >>"$log_file" 2>&1 &
      ;;
  esac
  echo $! > "$pid_file"
  echo "$component started: $(cat "$pid_file")"
}

stop_one() {
  local component="$1"
  local pid_file
  pid_file="$(component_pid_file "$component")"
  if [[ ! -f "$pid_file" ]]; then
    echo "$component not running"
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "stopped $component: $pid"
  else
    echo "$component pid file stale: $pid"
  fi
  rm -f "$pid_file"
}

status_one() {
  local component="$1"
  local pid_file
  pid_file="$(component_pid_file "$component")"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      echo "$component running: $pid"
      return
    fi
    echo "$component stale pid file: $pid"
    return
  fi
  echo "$component not running"
}

usage() {
  cat <<'EOF'
=============== prod.sh ===============
Usage:
  ./scripts/prod.sh start [all|api|worker|scheduler]
  ./scripts/prod.sh stop [all|api|worker|scheduler]
  ./scripts/prod.sh status
EOF
}

ACTION="${1:-status}"
TARGET="${2:-all}"

case "$ACTION" in
  start)
    ensure_prod_prerequisites
    if [[ "$TARGET" == "all" ]]; then
      start_one api
      start_one worker
      start_one scheduler
    else
      start_one "$TARGET"
    fi
    ;;
  stop)
    if [[ "$TARGET" == "all" ]]; then
      stop_one scheduler
      stop_one worker
      stop_one api
    else
      stop_one "$TARGET"
    fi
    ;;
  status)
    status_one api
    status_one worker
    status_one scheduler
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
