#!/usr/bin/env bash
#
# NotebookLM Eval Runner
# ──────────────────────────────────────────────────────────────────
#
# USAGE:
#   bash scripts/eval.sh <pipeline> [profile] [options]
#
# PIPELINES:
#   search    搜索（Agent 网络搜索）
#   ingest    摄入（文档解析与向量化入库）
#   summary   摘要（文章摘要生成）
#   chat      对话（Notebook 问答）
#   all       依次运行全部 pipeline
#
# PROFILES:
#   smoke     快速冒烟，每 case 重复 5 次（默认）
#   stable    稳定性评测，每 case 重复 3 次
#   full      完整基准，每 case 重复 1 次
#
# OPTIONS:
#   -c, --case IDS        只跑指定 case_id（逗号分隔）
#   -n, --max-cases N     最多跑前 N 条 case
#   -r, --repeat N        每条 case 重复 N 次
#   -v, --verbose         DEBUG 日志 + 自动写到 evals/runs/debug.log
#   -o, --open            运行完自动打开 HTML 报告
#   --log-level LEVEL     日志级别（DEBUG/INFO/WARNING，默认 INFO）
#   --log-file PATH       日志文件路径（相对 backend/，默认不写文件）
#   -h, --help            显示帮助
#
# EXAMPLES:
#
#   # 基础：跑 search smoke 全量
#   bash scripts/eval.sh search
#   bash scripts/eval.sh search stable
#   bash scripts/eval.sh all smoke
#
#   # 单条 case 跑 5 次取平均 + 查看详细日志
#   bash scripts/eval.sh search smoke -c search_smoke_001 -v
#
#   # 单条 case 跑 3 次
#   bash scripts/eval.sh search smoke -c search_smoke_001 -r 3
#
#   # 跑多条指定 case
#   bash scripts/eval.sh search smoke -c search_smoke_001,search_smoke_002
#
#   # 快速验证：前 2 条各跑 1 次
#   bash scripts/eval.sh search smoke -n 2 -r 1
#
#   # 全量 + 日志 + 完成后打开报告
#   bash scripts/eval.sh search smoke -v -o
#
#   # 自定义日志路径
#   bash scripts/eval.sh search smoke --log-level DEBUG --log-file evals/runs/search-debug.log
#
# ──────────────────────────────────────────────────────────────────
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"

# ── defaults ────────────────────────────────────────────────────────
PIPELINE=""
PROFILE="smoke"
CASE_IDS=""
MAX_CASES=""
REPEAT=""
LOG_LEVEL="INFO"
LOG_JSON="false"
LOG_FILE=""
VERBOSE=false
OPEN_REPORT=false

# ── usage ───────────────────────────────────────────────────────────
usage() {
  cat <<'EOF'
NotebookLM Eval Runner

USAGE:
  bash scripts/eval.sh <pipeline> [profile] [options]

PIPELINES:
  search    搜索（Agent 网络搜索）
  ingest    摄入（文档解析与向量化入库）
  summary   摘要（文章摘要生成）
  chat      对话（Notebook 问答）
  all       依次运行全部 pipeline

PROFILES:
  smoke     快速冒烟，每 case 重复 5 次（默认）
  stable    稳定性，每 case 重复 3 次
  full      完整基准，每 case 重复 1 次

OPTIONS:
  -c, --case IDS        只跑指定 case（逗号分隔）
  -n, --max-cases N     最多跑前 N 条 case
  -r, --repeat N        每条 case 重复 N 次
  -v, --verbose         开启 DEBUG 日志 + 写入文件
  -o, --open            运行后用浏览器打开 HTML 报告
  --log-level LEVEL     日志级别（DEBUG/INFO/WARNING，默认 INFO）
  --log-file PATH       日志写入文件路径（相对于 backend/）
  -h, --help            显示帮助

EXAMPLES:
  # 跑一条 search case，5 次取平均，查看详细日志
  bash scripts/eval.sh search smoke -c search_smoke_001 -v

  # 跑 search 前 2 条 case，每条 1 次，快速验证
  bash scripts/eval.sh search smoke -n 2 -r 1

  # 跑全部 ingest stable，完成后打开报告
  bash scripts/eval.sh ingest stable -o

  # 自定义日志文件路径
  bash scripts/eval.sh search smoke -c search_smoke_001 --log-file evals/runs/my-debug.log --log-level DEBUG
EOF
  exit 0
}

# ── parse args ──────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
  usage
fi

# first positional: pipeline
case "$1" in
  search|ingest|summary|chat|all) PIPELINE="$1"; shift ;;
  -h|--help) usage ;;
  *) echo "Error: unknown pipeline '$1'. Use: search|ingest|summary|chat|all" >&2; exit 1 ;;
esac

# second positional (optional): profile
if [[ $# -gt 0 ]] && [[ "$1" != -* ]]; then
  PROFILE="$1"; shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--case)      CASE_IDS="$2";    shift 2 ;;
    -n|--max-cases) MAX_CASES="$2";   shift 2 ;;
    -r|--repeat)    REPEAT="$2";      shift 2 ;;
    -v|--verbose)   VERBOSE=true;     shift ;;
    -o|--open)      OPEN_REPORT=true; shift ;;
    --log-level)    LOG_LEVEL="$2";   shift 2 ;;
    --log-file)     LOG_FILE="$2";    shift 2 ;;
    -h|--help)      usage ;;
    *) echo "Error: unknown option '$1'" >&2; exit 1 ;;
  esac
done

# ── verbose mode ────────────────────────────────────────────────────
if $VERBOSE; then
  LOG_LEVEL="DEBUG"
  if [[ -z "$LOG_FILE" ]]; then
    LOG_FILE="evals/runs/debug.log"
  fi
fi

# ── build env vars ──────────────────────────────────────────────────
ENV_VARS=(
  "LOG_LEVEL=$LOG_LEVEL"
  "LOG_JSON=$LOG_JSON"
)
[[ -n "$CASE_IDS"  ]] && ENV_VARS+=("EVAL_CASE_IDS=$CASE_IDS")
[[ -n "$MAX_CASES" ]] && ENV_VARS+=("EVAL_MAX_CASES=$MAX_CASES")
[[ -n "$REPEAT"    ]] && ENV_VARS+=("EVAL_REPEAT_OVERRIDE=$REPEAT")
[[ -n "$LOG_FILE"  ]] && ENV_VARS+=("LOG_FILE=$LOG_FILE")

# ── print run info ──────────────────────────────────────────────────
echo "──────────────────────────────────────────────"
echo "  NotebookLM Eval"
echo "──────────────────────────────────────────────"
echo "  Pipeline:   $PIPELINE"
echo "  Profile:    $PROFILE"
[[ -n "$CASE_IDS"  ]] && echo "  Cases:      $CASE_IDS"
[[ -n "$MAX_CASES" ]] && echo "  Max cases:  $MAX_CASES"
[[ -n "$REPEAT"    ]] && echo "  Repeat:     $REPEAT"
echo "  Log level:  $LOG_LEVEL"
[[ -n "$LOG_FILE"  ]] && echo "  Log file:   backend/$LOG_FILE"
echo "──────────────────────────────────────────────"
echo ""

# ── clear log file if specified ─────────────────────────────────────
if [[ -n "$LOG_FILE" ]]; then
  mkdir -p "$BACKEND_DIR/$(dirname "$LOG_FILE")"
  : > "$BACKEND_DIR/$LOG_FILE"
fi

# ── run ─────────────────────────────────────────────────────────────
cd "$BACKEND_DIR"
env "${ENV_VARS[@]}" "$PYTHON_BIN" -m evals.run "$PIPELINE" "$PROFILE"
EXIT_CODE=$?

# ── find latest report ──────────────────────────────────────────────
LATEST_RUN_DIR=$(ls -dt "$BACKEND_DIR/evals/runs/${PIPELINE}-${PROFILE}-"* 2>/dev/null | head -1 || true)
if [[ "$PIPELINE" == "all" ]]; then
  LATEST_RUN_DIR=$(ls -dt "$BACKEND_DIR/evals/runs/all-${PROFILE}-"* 2>/dev/null | head -1 || true)
fi

echo ""
if [[ -n "$LATEST_RUN_DIR" && -f "$LATEST_RUN_DIR/report.md" ]]; then
  echo "──────────────────────────────────────────────"
  echo "  Report: $LATEST_RUN_DIR"
  echo "──────────────────────────────────────────────"
  echo ""
  cat "$LATEST_RUN_DIR/report.md"
  echo ""
  if $OPEN_REPORT && [[ -f "$LATEST_RUN_DIR/report.html" ]]; then
    open "$LATEST_RUN_DIR/report.html" 2>/dev/null || xdg-open "$LATEST_RUN_DIR/report.html" 2>/dev/null || true
  fi
fi

[[ -n "$LOG_FILE" ]] && echo "Log: $BACKEND_DIR/$LOG_FILE"

exit $EXIT_CODE
