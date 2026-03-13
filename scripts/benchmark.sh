#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-}"
K6_BIN="${K6_BIN:-k6}"
DEFAULT_PROFILE="${BENCHMARK_PROFILE:-stable}"

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

resolve_k6() {
  if command -v "$K6_BIN" >/dev/null 2>&1; then
    echo "$K6_BIN"
    return
  fi
  echo "k6 is not available in PATH" >&2
  exit 1
}

load_root_env_if_present() {
  if [[ -f "$ROOT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env"
    set +a
  fi
}

run_python_module() {
  local module="$1"
  shift
  (cd "$ROOT_DIR" && "$(resolve_python)" -m "$module" "$@")
}

is_profile() {
  [[ "${1:-}" == "demo" || "${1:-}" == "stable" ]]
}

dataset_path() {
  local profile="$1"
  local benchmark="$2"
  local suffix="$benchmark"
  if [[ "$benchmark" == "rag_qa" ]]; then
    suffix="rag"
  fi
  echo "backend/evals/datasets/${benchmark}/${profile}-${suffix}-dataset.jsonl"
}

case_path() {
  local profile="$1"
  local benchmark="$2"
  local suffix="$benchmark"
  if [[ "$benchmark" == "rag_qa" ]]; then
    suffix="rag"
  fi
  echo "backend/evals/cases/${benchmark}/${profile}-${suffix}-cases.jsonl"
}

prediction_path() {
  local profile="$1"
  local benchmark="$2"
  echo "backend/evals/reports/predictions/${benchmark}-${profile}.jsonl"
}

report_json_path() {
  local profile="$1"
  local benchmark="$2"
  echo "backend/evals/reports/${benchmark}-${profile}.json"
}

report_markdown_path() {
  local profile="$1"
  local benchmark="$2"
  echo "backend/evals/reports/${benchmark}-${profile}.md"
}

report_prom_path() {
  local profile="$1"
  local benchmark="$2"
  echo "backend/evals/reports/prometheus/${benchmark}-${profile}.prom"
}

baseline_path() {
  local benchmark="$1"
  echo "backend/evals/reports/baselines/${benchmark}-stable.json"
}

default_ragas_metrics_path() {
  local profile="$1"
  echo "backend/evals/reports/ragas/rag-${profile}-metrics.json"
}

build_datasets_for_profile() {
  local profile="$1"
  run_python_module backend.evals.dataset_builders.build_search_dataset \
    --input "$(case_path "$profile" "search")" \
    --output "$(dataset_path "$profile" "search")"
  run_python_module backend.evals.dataset_builders.build_ingest_dataset \
    --input "$(case_path "$profile" "ingest")" \
    --output "$(dataset_path "$profile" "ingest")"
  run_python_module backend.evals.dataset_builders.build_summary_dataset \
    --input "$(case_path "$profile" "summary")" \
    --output "$(dataset_path "$profile" "summary")"
  run_python_module backend.evals.dataset_builders.build_rag_dataset \
    --input "$(case_path "$profile" "rag_qa")" \
    --output "$(dataset_path "$profile" "rag_qa")"
}

build_datasets() {
  local profile="${1:-all}"
  case "$profile" in
    demo|stable)
      build_datasets_for_profile "$profile"
      ;;
    all)
      build_datasets_for_profile demo
      build_datasets_for_profile stable
      ;;
    *)
      echo "unknown dataset profile: $profile" >&2
      exit 1
      ;;
  esac
}

run_search() {
  local profile="$1"
  shift
  run_python_module backend.evals.runners.search_benchmark \
    --dataset "$(dataset_path "$profile" "search")" \
    --predictions "$(prediction_path "$profile" "search")" \
    --output "$(report_json_path "$profile" "search")" \
    --markdown-output "$(report_markdown_path "$profile" "search")" \
    --prometheus-output "$(report_prom_path "$profile" "search")" \
    --baseline "$(baseline_path "search")" \
    "$@"
}

run_ingest() {
  local profile="$1"
  shift
  run_python_module backend.evals.runners.ingest_benchmark \
    --dataset "$(dataset_path "$profile" "ingest")" \
    --results "$(prediction_path "$profile" "ingest")" \
    --output "$(report_json_path "$profile" "ingest")" \
    --markdown-output "$(report_markdown_path "$profile" "ingest")" \
    --prometheus-output "$(report_prom_path "$profile" "ingest")" \
    --baseline "$(baseline_path "ingest")" \
    "$@"
}

run_summary() {
  local profile="$1"
  shift
  run_python_module backend.evals.runners.summary_benchmark \
    --dataset "$(dataset_path "$profile" "summary")" \
    --predictions "$(prediction_path "$profile" "summary")" \
    --output "$(report_json_path "$profile" "summary")" \
    --markdown-output "$(report_markdown_path "$profile" "summary")" \
    --prometheus-output "$(report_prom_path "$profile" "summary")" \
    --baseline "$(baseline_path "summary")" \
    "$@"
}

run_rag() {
  local profile="$1"
  shift
  local use_default_ragas_metrics=true
  for arg in "$@"; do
    if [[ "$arg" == "--with-ragas" || "$arg" == "--ragas-metrics" ]]; then
      use_default_ragas_metrics=false
      break
    fi
  done

  local extra_args=()
  if [[ "$use_default_ragas_metrics" == true ]]; then
    extra_args+=(--ragas-metrics "$(default_ragas_metrics_path "$profile")")
  fi

  run_python_module backend.evals.runners.rag_benchmark \
    --dataset "$(dataset_path "$profile" "rag_qa")" \
    --predictions "$(prediction_path "$profile" "rag")" \
    --output "$(report_json_path "$profile" "rag")" \
    --markdown-output "$(report_markdown_path "$profile" "rag")" \
    --prometheus-output "$(report_prom_path "$profile" "rag")" \
    --baseline "$(baseline_path "rag")" \
    "${extra_args[@]}" \
    "$@"
}

run_benchmark_target() {
  local target="$1"
  local profile="$2"
  shift 2
  case "$target" in
    search) run_search "$profile" "$@" ;;
    ingest) run_ingest "$profile" "$@" ;;
    summary) run_summary "$profile" "$@" ;;
    rag) run_rag "$profile" "$@" ;;
    all)
      run_search "$profile" "$@"
      run_ingest "$profile" "$@"
      run_summary "$profile" "$@"
      run_rag "$profile" "$@"
      ;;
    *)
      echo "unknown benchmark target: $target" >&2
      exit 1
      ;;
  esac
}

load_test_script() {
  local target="$1"
  case "$target" in
    search) echo "backend/evals/k6/search-load.js" ;;
    import) echo "backend/evals/k6/source-import.js" ;;
    notebook) echo "backend/evals/k6/notebook-detail-poll.js" ;;
    chat) echo "backend/evals/k6/chat-stream.js" ;;
    summary) echo "backend/evals/k6/summary-stream.js" ;;
    *)
      echo ""
      ;;
  esac
}

run_load_test() {
  local target="$1"
  shift
  load_root_env_if_present
  export BASE_URL="${BASE_URL:-${NOTEBOOKLM_BASE_URL:-http://127.0.0.1:8080/api}}"
  export TOKEN="${TOKEN:-${NOTEBOOKLM_API_TOKEN:-}}"
  if [[ "$target" == "all" ]]; then
    for item in search import notebook chat summary; do
      "$(resolve_k6)" run "$(load_test_script "$item")" "$@"
    done
    return
  fi
  local script_path
  script_path="$(load_test_script "$target")"
  if [[ -z "$script_path" ]]; then
    echo "unknown load-test target: $target" >&2
    exit 1
  fi
  "$(resolve_k6)" run "$script_path" "$@"
}

show_reports() {
  echo "=============== benchmark reports ==============="
  find "$ROOT_DIR/backend/evals/reports" -maxdepth 2 -type f | sort
}

usage() {
  cat <<'EOF'
=============== benchmark.sh ===============
Usage:
  ./scripts/benchmark.sh build-datasets [demo|stable|all]
  ./scripts/benchmark.sh run [search|ingest|summary|rag|all] [demo|stable] [extra runner args...]
  ./scripts/benchmark.sh gate [search|ingest|summary|rag|all] [demo|stable] [extra runner args...]
  ./scripts/benchmark.sh load-test [search|import|notebook|chat|summary|all] [extra k6 args...]
  ./scripts/benchmark.sh show reports

Notes:
  - run 和 gate 默认 profile 为 stable，也可通过 BENCHMARK_PROFILE 覆盖
  - gate 会自动追加 --fail-on-regression
  - load-test 会尝试从根目录 .env 读取 NOTEBOOKLM_BASE_URL / NOTEBOOKLM_API_TOKEN
EOF
}

COMMAND="${1:-}"
TARGET="${2:-}"
THIRD_ARG="${3:-}"

case "$COMMAND" in
  build-datasets)
    build_datasets "${TARGET:-all}"
    ;;
  run|gate)
    if [[ -z "$TARGET" ]]; then
      usage
      exit 1
    fi
    PROFILE="$DEFAULT_PROFILE"
    EXTRA_INDEX=3
    if is_profile "$THIRD_ARG"; then
      PROFILE="$THIRD_ARG"
      EXTRA_INDEX=4
    fi
    if (( $# >= EXTRA_INDEX )); then
      EXTRA_ARGS=("${@:EXTRA_INDEX}")
    else
      EXTRA_ARGS=()
    fi
    if [[ "$COMMAND" == "gate" ]]; then
      EXTRA_ARGS+=(--fail-on-regression)
    fi
    if (( ${#EXTRA_ARGS[@]} )); then
      run_benchmark_target "$TARGET" "$PROFILE" "${EXTRA_ARGS[@]}"
    else
      run_benchmark_target "$TARGET" "$PROFILE"
    fi
    ;;
  load-test)
    if [[ -z "$TARGET" ]]; then
      usage
      exit 1
    fi
    if (( $# >= 3 )); then
      EXTRA_ARGS=("${@:3}")
    else
      EXTRA_ARGS=()
    fi
    if (( ${#EXTRA_ARGS[@]} )); then
      run_load_test "$TARGET" "${EXTRA_ARGS[@]}"
    else
      run_load_test "$TARGET"
    fi
    ;;
  show)
    if [[ "$TARGET" == "reports" ]]; then
      show_reports
    else
      usage
      exit 1
    fi
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
