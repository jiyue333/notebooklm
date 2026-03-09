#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COLLECTION_DIR="$ROOT_DIR/api-collections/bruno"
ENV_FILE="$COLLECTION_DIR/environments/Local.bru"
RESULT_DIR="$COLLECTION_DIR/results"
RESULT_FILE="$RESULT_DIR/http-scenarios.json"
INCLUDE_LIVE=0
SEED_ONLY=0

usage() {
  cat <<'EOF'
用法:
  scripts/run-http-scenarios.sh [--live] [--seed-only]

说明:
  --seed-only   只写入 HTTP demo 数据，不运行 Bruno collection
  --live        额外运行需要真实 Exa / LLM 的 live folders
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --live)
      INCLUDE_LIVE=1
      shift
      ;;
    --seed-only)
      SEED_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage
      exit 1
      ;;
  esac
done

echo "[1/3] 写入 HTTP demo 数据"
conda run -n notebooklm python "$ROOT_DIR/backend/scripts/seed_http_demo_data.py"

if [[ "$SEED_ONLY" -eq 1 ]]; then
  exit 0
fi

if ! command -v bru >/dev/null 2>&1; then
  echo "未检测到 Bruno CLI，请先安装: npm install -g @usebruno/cli" >&2
  exit 127
fi

if ! curl --noproxy '*' -fsS http://127.0.0.1:8080/api/health >/dev/null 2>&1; then
  echo "后端未启动或 http://127.0.0.1:8080/api/health 不可访问" >&2
  exit 1
fi

mkdir -p "$ROOT_DIR/logs"
mkdir -p "$RESULT_DIR"

FOLDERS=(
  "00-system"
  "10-auth"
  "20-notebooks"
  "30-notes"
  "40-settings"
  "50-sources-local"
  "70-ai-local"
  "99-cleanup"
)

if [[ "$INCLUDE_LIVE" -eq 1 ]]; then
  FOLDERS+=("60-sources-live" "80-ai-live")
fi

echo "[2/3] 运行 Bruno collection"
(
  cd "$COLLECTION_DIR"
  bru run "${FOLDERS[@]}" --env-file "$ENV_FILE" --reporter-json "$RESULT_FILE"
)

echo "[3/3] 完成，结果文件: $RESULT_FILE"
