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

usage() {
  cat <<'EOF'
=============== online.sh ===============
用法:
  ./scripts/online.sh --help    - 显示此帮助

注意: evals 和 seed 工具已随 ADR 重写移除，后续会重建。
EOF
}

COMMAND="${1:-}"

case "$COMMAND" in
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
