#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"

resolve_python() {
  if [[ -n "$PYTHON_BIN" ]]; then
    echo "$PYTHON_BIN"
    return
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
  else
    PYTHON_BIN="$(command -v python3 || true)"
  fi
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "python3 is not available in PATH" >&2
    exit 1
  fi
  echo "$PYTHON_BIN"
}

load_root_env() {
  if [[ ! -f "$ROOT_DIR/.env" ]]; then
    echo "root .env not found"
    exit 1
  fi
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
}

run_python_module() {
  local module="$1"
  shift
  load_root_env
  (cd "$ROOT_DIR" && "$(resolve_python)" -m "$module" "$@")
}

seed_notebooks() {
  run_python_module backend.evals.online_seed.create_demo_notebooks "$@"
}

seed_search() {
  run_python_module backend.evals.online_seed.create_search_sessions "$@"
}

seed_import() {
  run_python_module backend.evals.online_seed.create_import_jobs "$@"
}

seed_chat() {
  run_python_module backend.evals.online_seed.create_chat_threads "$@"
}

seed_summary() {
  run_python_module backend.evals.online_seed.create_summary_runs "$@"
}

seed_all() {
  seed_notebooks "${@}"
  seed_search "${@}"
  seed_import "${@}"
  seed_chat "${@}"
  seed_summary "${@}"
}

inspect_redis() {
  load_root_env
  (
    cd "$ROOT_DIR/backend"
    PYTHONPATH="$ROOT_DIR/backend" "$(resolve_python)" - <<'PY'
import asyncio
from app.modules.tracker.redis import inspect_redis_keyspace

async def main():
    result = await inspect_redis_keyspace()
    print(f"keys_scanned={result.keys_scanned}")
    print(f"bigkeys={result.bigkey_count}")
    print(f"hotkeys={result.hotkey_count}")

asyncio.run(main())
PY
  )
}

show_search_samples() {
  local latest
  latest="$(find "$ROOT_DIR/backend/evals/reports/search_samples" -type f -name '*.jsonl' | sort | tail -n 1)"
  if [[ -z "$latest" ]]; then
    echo "no search sample report found"
    return
  fi
  echo "=============== latest search samples ==============="
  echo "$latest"
  tail -n 20 "$latest"
}

show_redis_report() {
  local latest="$ROOT_DIR/backend/evals/reports/redis/inspection-latest.json"
  if [[ ! -f "$latest" ]]; then
    echo "redis inspection report not found"
    return
  fi
  echo "=============== latest redis report ==============="
  echo "$latest"
  cat "$latest"
}

usage() {
  cat <<'EOF'
=============== online.sh ===============
Usage:
  ./scripts/online.sh seed notebooks [extra args...]
  ./scripts/online.sh seed search [extra args...]
  ./scripts/online.sh seed import [extra args...]
  ./scripts/online.sh seed chat [extra args...]
  ./scripts/online.sh seed summary [extra args...]
  ./scripts/online.sh seed all [notebook seed args...]
  ./scripts/online.sh inspect redis
  ./scripts/online.sh show search-samples
  ./scripts/online.sh show redis-report

Notes:
  - search/import/chat/summary 都支持不传 --input 的 one-click 模式
  - seed all 会先造 notebook，再串行触发 search/import/chat/summary
EOF
}

COMMAND="${1:-}"
TARGET="${2:-}"
EXTRA_ARGS=("${@:3}")

case "$COMMAND" in
  seed)
    case "$TARGET" in
      notebooks) seed_notebooks "${EXTRA_ARGS[@]}" ;;
      search) seed_search "${EXTRA_ARGS[@]}" ;;
      import) seed_import "${EXTRA_ARGS[@]}" ;;
      chat) seed_chat "${EXTRA_ARGS[@]}" ;;
      summary) seed_summary "${EXTRA_ARGS[@]}" ;;
      all) seed_all "${EXTRA_ARGS[@]}" ;;
      *)
        usage
        exit 1
        ;;
    esac
    ;;
  inspect)
    if [[ "$TARGET" == "redis" ]]; then
      inspect_redis
    else
      usage
      exit 1
    fi
    ;;
  show)
    case "$TARGET" in
      search-samples) show_search_samples ;;
      redis-report) show_redis_report ;;
      *)
        usage
        exit 1
        ;;
    esac
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
