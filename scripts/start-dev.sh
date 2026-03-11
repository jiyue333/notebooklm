#!/bin/zsh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
WORKER_LOG="$LOG_DIR/worker.log"
SCHEDULER_LOG="$LOG_DIR/scheduler.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
WORKER_PID_FILE="$LOG_DIR/worker.pid"
SCHEDULER_PID_FILE="$LOG_DIR/scheduler.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"
SYSTEM_PYTHON_BIN="$(command -v python3)"
NODE_BIN="$(command -v node)"
VITE_BIN="$ROOT_DIR/frontend/node_modules/vite/bin/vite.js"
NOTEBOOKLM_PYTHON_BIN=""
BACKEND_MATCH="uvicorn app.main:app"
WORKER_MATCH="app.workers.run_worker"
SCHEDULER_MATCH="app.workers.run_scheduler"
FRONTEND_MATCH_VITE_BIN="frontend/node_modules/vite/bin/vite.js"
FRONTEND_MATCH_VITE_SHIM="frontend/node_modules/.bin/vite"

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

resolve_notebooklm_python() {
  if [[ -n "$NOTEBOOKLM_PYTHON_BIN" ]]; then
    echo "$NOTEBOOKLM_PYTHON_BIN"
    return
  fi

  NOTEBOOKLM_PYTHON_BIN="$(
    conda run --no-capture-output -n notebooklm python -c 'import sys; print(sys.executable)' 2>/dev/null | tail -n 1
  )"
  if [[ -z "$NOTEBOOKLM_PYTHON_BIN" || ! -x "$NOTEBOOKLM_PYTHON_BIN" ]]; then
    echo "failed to resolve python executable for conda env notebooklm" >&2
    exit 1
  fi
  echo "$NOTEBOOKLM_PYTHON_BIN"
}

start_detached_process() {
  local workdir="$1"
  local log_file="$2"
  shift 2

  (
    exec "$SYSTEM_PYTHON_BIN" -c 'import os, sys; os.chdir(sys.argv[1]); os.setsid(); os.execvp(sys.argv[2], sys.argv[2:])' "$workdir" "$@"
  ) >> "$log_file" 2>&1 &
  echo $!
}

read_pgid() {
  local pid="$1"
  ps -ax -o pid=,pgid= 2>/dev/null | awk -v pid="$pid" '$1 == pid { print $2; exit }'
}

list_group_pids() {
  local pgid="$1"
  ps -ax -o pid=,pgid= 2>/dev/null | awk -v pgid="$pgid" '$2 == pgid { print $1 }'
}

find_matching_pids() {
  local pattern="$1"
  ps -axww -o pid=,command= 2>/dev/null | awk -v needle="$pattern" 'index($0, needle) { print $1 }'
}

first_matching_pid() {
  local match_pattern="$1"
  shift
  local matched_pid

  while IFS= read -r matched_pid; do
    [[ -z "$matched_pid" ]] && continue
    echo "$matched_pid"
    return 0
  done < <(find_matching_pids "$match_pattern")

  for match_pattern in "$@"; do
    while IFS= read -r matched_pid; do
      [[ -z "$matched_pid" ]] && continue
      echo "$matched_pid"
      return 0
    done < <(find_matching_pids "$match_pattern")
  done

  return 1
}

resolve_existing_pid() {
  local pid_file="$1"
  shift
  local pid
  pid="$(read_pid "$pid_file")"
  if is_running "$pid"; then
    echo "$pid"
    return 0
  fi

  first_matching_pid "$@" || return 1
}

kill_pid_tree() {
  local pid="$1"
  local pgid
  pgid="$(read_pgid "$pid")"

  if [[ -n "$pgid" ]]; then
    kill -TERM -- "-$pgid" >/dev/null 2>&1 || true
    sleep 1
    if [[ -n "$(list_group_pids "$pgid")" ]]; then
      kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
    fi
    return
  fi

  kill "$pid" >/dev/null 2>&1 || true
  sleep 1
  if is_running "$pid"; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
}

start_backend() {
  local existing_pid
  existing_pid="$(resolve_existing_pid "$BACKEND_PID_FILE" "$BACKEND_MATCH" || true)"
  if is_running "$existing_pid"; then
    echo "$existing_pid" > "$BACKEND_PID_FILE"
    echo "backend is already running (pid=$existing_pid)"
    return
  fi

  append_banner "$BACKEND_LOG" "backend"
  local python_bin
  python_bin="$(resolve_notebooklm_python)"
  local pid
  pid="$(start_detached_process "$ROOT_DIR/backend" "$BACKEND_LOG" "$python_bin" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080 --no-access-log)"
  echo "$pid" > "$BACKEND_PID_FILE"
  echo "backend started (pid=$pid) -> $BACKEND_LOG"
}

start_frontend() {
  local existing_pid
  existing_pid="$(resolve_existing_pid "$FRONTEND_PID_FILE" "$FRONTEND_MATCH_VITE_BIN" "$FRONTEND_MATCH_VITE_SHIM" || true)"
  if is_running "$existing_pid"; then
    echo "$existing_pid" > "$FRONTEND_PID_FILE"
    echo "frontend is already running (pid=$existing_pid)"
    return
  fi

  append_banner "$FRONTEND_LOG" "frontend"
  if [[ ! -f "$VITE_BIN" ]]; then
    echo "frontend vite entry not found: $VITE_BIN"
    exit 1
  fi
  local pid
  pid="$(start_detached_process "$ROOT_DIR/frontend" "$FRONTEND_LOG" "$NODE_BIN" "$VITE_BIN" --host 127.0.0.1)"
  echo "$pid" > "$FRONTEND_PID_FILE"
  echo "frontend started (pid=$pid) -> $FRONTEND_LOG"
}

start_worker() {
  local existing_pid
  existing_pid="$(resolve_existing_pid "$WORKER_PID_FILE" "$WORKER_MATCH" || true)"
  if is_running "$existing_pid"; then
    echo "$existing_pid" > "$WORKER_PID_FILE"
    echo "worker is already running (pid=$existing_pid)"
    return
  fi

  append_banner "$WORKER_LOG" "worker"
  local python_bin
  python_bin="$(resolve_notebooklm_python)"
  local pid
  pid="$(start_detached_process "$ROOT_DIR/backend" "$WORKER_LOG" "$python_bin" -m app.workers.run_worker)"
  echo "$pid" > "$WORKER_PID_FILE"
  echo "worker started (pid=$pid) -> $WORKER_LOG"
}

start_scheduler() {
  local existing_pid
  existing_pid="$(resolve_existing_pid "$SCHEDULER_PID_FILE" "$SCHEDULER_MATCH" || true)"
  if is_running "$existing_pid"; then
    echo "$existing_pid" > "$SCHEDULER_PID_FILE"
    echo "scheduler is already running (pid=$existing_pid)"
    return
  fi

  append_banner "$SCHEDULER_LOG" "scheduler"
  local python_bin
  python_bin="$(resolve_notebooklm_python)"
  local pid
  pid="$(start_detached_process "$ROOT_DIR/backend" "$SCHEDULER_LOG" "$python_bin" -m app.workers.run_scheduler)"
  echo "$pid" > "$SCHEDULER_PID_FILE"
  echo "scheduler started (pid=$pid) -> $SCHEDULER_LOG"
}

kill_process() {
  local name="$1"
  local pid_file="$2"
  shift 2
  local pid
  pid="$(read_pid "$pid_file")"
  local matched_pids=()
  local matched_pid
  local match_pattern

  if is_running "$pid"; then
    matched_pids+=("$pid")
  fi

  for match_pattern in "$@"; do
    while IFS= read -r matched_pid; do
      [[ -z "$matched_pid" ]] && continue
      if [[ "$matched_pid" != "$$" && "$matched_pid" != "$PPID" ]]; then
        matched_pids+=("$matched_pid")
      fi
    done < <(find_matching_pids "$match_pattern")
  done

  if [[ "${#matched_pids[@]}" -eq 0 ]]; then
    rm -f "$pid_file"
    echo "$name is not running"
    return
  fi

  local unique_pids=()
  local seen=""
  for matched_pid in "${matched_pids[@]}"; do
    if [[ " $seen " == *" $matched_pid "* ]]; then
      continue
    fi
    seen="$seen $matched_pid"
    unique_pids+=("$matched_pid")
  done

  for matched_pid in "${unique_pids[@]}"; do
    kill_pid_tree "$matched_pid"
  done
  rm -f "$pid_file"
  echo "$name stopped"
}

clear_logs() {
  rm -f "$BACKEND_LOG" "$WORKER_LOG" "$SCHEDULER_LOG" "$FRONTEND_LOG"
}

show_status() {
  local backend_pid frontend_pid
  local worker_pid scheduler_pid
  backend_pid="$(read_pid "$BACKEND_PID_FILE")"
  worker_pid="$(read_pid "$WORKER_PID_FILE")"
  scheduler_pid="$(read_pid "$SCHEDULER_PID_FILE")"
  frontend_pid="$(read_pid "$FRONTEND_PID_FILE")"

  if is_running "$backend_pid"; then
    echo "backend: running (pid=$backend_pid)"
  elif [[ -n "$(find_matching_pids "$BACKEND_MATCH")" ]]; then
    echo "backend: running (orphaned process detected)"
  else
    echo "backend: stopped"
  fi

  if is_running "$worker_pid"; then
    echo "worker: running (pid=$worker_pid)"
  elif [[ -n "$(find_matching_pids "$WORKER_MATCH")" ]]; then
    echo "worker: running (orphaned process detected)"
  else
    echo "worker: stopped"
  fi

  if is_running "$scheduler_pid"; then
    echo "scheduler: running (pid=$scheduler_pid)"
  elif [[ -n "$(find_matching_pids "$SCHEDULER_MATCH")" ]]; then
    echo "scheduler: running (orphaned process detected)"
  else
    echo "scheduler: stopped"
  fi

  if is_running "$frontend_pid"; then
    echo "frontend: running (pid=$frontend_pid)"
  elif [[ -n "$(first_matching_pid "$FRONTEND_MATCH_VITE_BIN" "$FRONTEND_MATCH_VITE_SHIM" || true)" ]]; then
    echo "frontend: running (orphaned process detected)"
  else
    echo "frontend: stopped"
  fi
}

usage() {
  cat <<'EOF'
Usage:
  ./scripts/start-dev.sh start
  ./scripts/start-dev.sh kill
  ./scripts/start-dev.sh status
EOF
}

if ! command -v conda >/dev/null 2>&1; then
  echo "conda is not available in PATH"
  exit 1
fi

if [[ -z "$SYSTEM_PYTHON_BIN" ]]; then
  echo "python3 is not available in PATH"
  exit 1
fi

if [[ -z "$NODE_BIN" ]]; then
  echo "node is not available in PATH"
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
    start_worker
    start_scheduler
    start_frontend
    echo "logs:"
    echo "  backend:  $BACKEND_LOG"
    echo "  worker:   $WORKER_LOG"
    echo "  scheduler:$SCHEDULER_LOG"
    echo "  frontend: $FRONTEND_LOG"
    ;;
  kill)
    kill_process "backend" "$BACKEND_PID_FILE" "$BACKEND_MATCH"
    kill_process "worker" "$WORKER_PID_FILE" "$WORKER_MATCH"
    kill_process "scheduler" "$SCHEDULER_PID_FILE" "$SCHEDULER_MATCH"
    kill_process "frontend" "$FRONTEND_PID_FILE" "$FRONTEND_MATCH_VITE_BIN" "$FRONTEND_MATCH_VITE_SHIM"
    clear_logs
    ;;
  status)
    show_status
    ;;
  *)
    usage
    exit 1
    ;;
esac
