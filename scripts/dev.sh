#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
WORKER_LOG="$LOG_DIR/worker.log"
SCHEDULER_LOG="$LOG_DIR/scheduler.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_PID_FILE="$LOG_DIR/backend.pid"
WORKER_PID_FILE="$LOG_DIR/worker.pid"
SCHEDULER_PID_FILE="$LOG_DIR/scheduler.pid"
FRONTEND_PID_FILE="$LOG_DIR/frontend.pid"
SYSTEM_PYTHON_BIN="$(command -v python3 || true)"
NODE_BIN="$(command -v node || true)"
VITE_BIN="$ROOT_DIR/frontend/node_modules/vite/bin/vite.js"
VENV_PYTHON_BIN=""
BACKEND_MATCH="uvicorn app.main:app"
WORKER_MATCH="app.workers.run_worker"
SCHEDULER_MATCH="app.workers.run_scheduler"
FRONTEND_MATCH_VITE_BIN="frontend/node_modules/vite/bin/vite.js"
FRONTEND_MATCH_VITE_SHIM="frontend/node_modules/.bin/vite"
BACKEND_PORT=8080
WORKER_METRICS_PORT=9101
SCHEDULER_METRICS_PORT=9102
FRONTEND_PORT=5173

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
  local pid="${1:-}"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

read_pid() {
  local file="$1"
  if [[ -f "$file" ]]; then
    tr -d '[:space:]' < "$file"
  fi
}

resolve_backend_python() {
  if [[ -n "$VENV_PYTHON_BIN" ]]; then
    echo "$VENV_PYTHON_BIN"
    return
  fi

  # Prefer backend/.venv (created by uv sync), fallback to project .venv
  if [[ -x "$ROOT_DIR/backend/.venv/bin/python" ]]; then
    VENV_PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
  elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    VENV_PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  else
    echo "venv not found. Run: cd backend && uv sync" >&2
    exit 1
  fi
  echo "$VENV_PYTHON_BIN"
}

ensure_backend_sync() {
  if command -v uv >/dev/null 2>&1; then
    (cd "$ROOT_DIR/backend" && uv sync --quiet)
  else
    local pip_bin
    if [[ -x "$ROOT_DIR/backend/.venv/bin/pip" ]]; then
      pip_bin="$ROOT_DIR/backend/.venv/bin/pip"
    elif [[ -x "$ROOT_DIR/.venv/bin/pip" ]]; then
      pip_bin="$ROOT_DIR/.venv/bin/pip"
    else
      echo "venv not found. Install uv and run: cd backend && uv sync" >&2
      exit 1
    fi
    (cd "$ROOT_DIR/backend" && "$pip_bin" install -e . --quiet)
  fi
}

# 本机动态库：python-magic 依赖 libmagic。设置 SKIP_NATIVE_LIB_SETUP=1 可跳过。
ensure_libmagic() {
  [[ "${SKIP_NATIVE_LIB_SETUP:-}" == "1" ]] && return 0
  local py_bin
  py_bin="$(resolve_backend_python)"
  if "$py_bin" -c 'import magic; magic.from_buffer(b"\x89PNG\r\n\x1a\n", mime=True)' 2>/dev/null; then
    return 0
  fi
  case "$(uname -s)" in
    Darwin)
      if command -v brew >/dev/null 2>&1; then
        echo "[dev] 安装 libmagic（python-magic / MIME 检测，Homebrew）..."
        HOMEBREW_NO_AUTO_UPDATE=1 brew install libmagic
      else
        echo "[dev] 未检测到 Homebrew；MIME 将使用代码回退。可选: brew install libmagic" >&2
      fi
      ;;
    Linux)
      if command -v apt-get >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        echo "[dev] 安装 libmagic1（python-magic，apt）..."
        sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends libmagic1
      else
        echo "[dev] 需要系统包 libmagic1 时请执行: sudo apt-get install -y libmagic1" >&2
      fi
      ;;
  esac
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

kill_port_holders() {
  local port="$1"
  local label="$2"
  shift 2
  local patterns=("$@")
  local pids
  pids="$(lsof -ti ":$port" 2>/dev/null || true)"
  [[ -z "$pids" ]] && return
  local pid cmd pattern
  for pid in $pids; do
    [[ "$pid" == "$$" || "$pid" == "$PPID" ]] && continue
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    [[ -z "$cmd" ]] && continue
    for pattern in "${patterns[@]}"; do
      if [[ "$cmd" == *"$pattern"* ]]; then
        kill -9 "$pid" 2>/dev/null || true
        echo "  killed orphan $pid on port $port ($label)"
        break
      fi
    done
  done
}

release_all_ports() {
  kill_port_holders "$BACKEND_PORT" "backend" "$BACKEND_MATCH"
  kill_port_holders "$WORKER_METRICS_PORT" "worker-metrics" "$WORKER_MATCH"
  kill_port_holders "$SCHEDULER_METRICS_PORT" "scheduler-metrics" "$SCHEDULER_MATCH"
  kill_port_holders "$FRONTEND_PORT" "frontend" "$FRONTEND_MATCH_VITE_BIN" "$FRONTEND_MATCH_VITE_SHIM"
}

clean_logs() {
  for f in "$BACKEND_LOG" "$WORKER_LOG" "$SCHEDULER_LOG" "$FRONTEND_LOG"; do
    : > "$f" 2>/dev/null || true
  done
  echo "log files cleared"
}

clean_pid_files() {
  rm -f "$BACKEND_PID_FILE" "$WORKER_PID_FILE" "$SCHEDULER_PID_FILE" "$FRONTEND_PID_FILE"
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
  python_bin="$(resolve_backend_python)"
  local pid
  pid="$(start_detached_process "$ROOT_DIR/backend" "$BACKEND_LOG" "$python_bin" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8080 --no-access-log)"
  echo "$pid" > "$BACKEND_PID_FILE"
  echo "backend started (pid=$pid) -> $BACKEND_LOG"
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
  python_bin="$(resolve_backend_python)"
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
  python_bin="$(resolve_backend_python)"
  local pid
  pid="$(start_detached_process "$ROOT_DIR/backend" "$SCHEDULER_LOG" "$python_bin" -m app.workers.run_scheduler)"
  echo "$pid" > "$SCHEDULER_PID_FILE"
  echo "scheduler started (pid=$pid) -> $SCHEDULER_LOG"
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

show_logs() {
  local target="${1:-all}"
  case "$target" in
    backend) tail -n 200 -f "$BACKEND_LOG" ;;
    worker) tail -n 200 -f "$WORKER_LOG" ;;
    scheduler) tail -n 200 -f "$SCHEDULER_LOG" ;;
    frontend) tail -n 200 -f "$FRONTEND_LOG" ;;
    all) tail -n 200 -f "$BACKEND_LOG" "$WORKER_LOG" "$SCHEDULER_LOG" "$FRONTEND_LOG" ;;
    *)
      echo "unknown log target: $target"
      exit 1
      ;;
  esac
}

ensure_dev_prerequisites() {
  if [[ -z "$SYSTEM_PYTHON_BIN" ]]; then
    echo "python3 is not available in PATH"
    exit 1
  fi

  if [[ -z "$NODE_BIN" ]]; then
    echo "node is not available in PATH"
    exit 1
  fi

  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "root .env not found"
    exit 1
  fi

  if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
    echo "frontend/node_modules not found, run: cd frontend && npm install"
    exit 1
  fi

  if [[ ! -d "$ROOT_DIR/tools/remark-processor/node_modules" ]]; then
    echo "installing remark-processor dependencies..."
    (cd "$ROOT_DIR/tools/remark-processor" && npm install --silent)
  fi

  ensure_backend_sync
  ensure_libmagic
}

usage() {
  cat <<'EOF'
=============== dev.sh ===============
Usage:
  ./scripts/dev.sh start
  ./scripts/dev.sh stop
  ./scripts/dev.sh status
  ./scripts/dev.sh logs [backend|worker|scheduler|frontend|all]
  ./scripts/dev.sh restart

环境变量:
  SKIP_NATIVE_LIB_SETUP=1  跳过本机 libmagic 检测/安装（依赖代码回退）
EOF
}

COMMAND="${1:-start}"
TARGET="${2:-}"

case "$COMMAND" in
  start)
    ensure_dev_prerequisites
    start_backend
    start_worker
    start_scheduler
    start_frontend
    echo "logs:"
    echo "  backend:   $BACKEND_LOG"
    echo "  worker:    $WORKER_LOG"
    echo "  scheduler: $SCHEDULER_LOG"
    echo "  frontend:  $FRONTEND_LOG"
    ;;
  stop)
    kill_process "backend" "$BACKEND_PID_FILE" "$BACKEND_MATCH"
    kill_process "worker" "$WORKER_PID_FILE" "$WORKER_MATCH"
    kill_process "scheduler" "$SCHEDULER_PID_FILE" "$SCHEDULER_MATCH"
    kill_process "frontend" "$FRONTEND_PID_FILE" "$FRONTEND_MATCH_VITE_BIN" "$FRONTEND_MATCH_VITE_SHIM"
    release_all_ports
    clean_pid_files
    clean_logs
    ;;
  status)
    show_status
    ;;
  logs)
    show_logs "$TARGET"
    ;;
  restart)
    ensure_dev_prerequisites
    "$0" stop
    "$0" start
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
