#!/usr/bin/env bash
set -euo pipefail

# ========== 加载 .env ==========

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="docker-compose-prod.yml"

if [[ -f "$PROJECT_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$PROJECT_DIR/.env"
  set +a
fi

# ========== 配置（.env 提供默认值，环境变量可覆盖） ==========

REMOTE_HOST="${DEPLOY_HOST:?请设置 DEPLOY_HOST，例如在 .env 中填写 DEPLOY_HOST=root@1.2.3.4}"
REMOTE_DIR="${DEPLOY_DIR:-/opt/notebooklm}"
SSH_PORT="${DEPLOY_SSH_PORT:-22}"
SSH_KEY="${DEPLOY_SSH_KEY:-}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new -p ${SSH_PORT}"
if [[ -n "$SSH_KEY" ]]; then
  SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

# ========== 工具函数 ==========

info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m    $*"; }
err()   { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; }
step()  { echo -e "\n\033[1;36m===> $*\033[0m"; }

ssh_cmd() { ssh ${SSH_OPTS} "${REMOTE_HOST}" "$@"; }

confirm() {
  local msg="${1:-确认继续？}"
  read -rp "$msg [y/N] " ans
  [[ "$ans" =~ ^[Yy]$ ]] || { info "已取消"; exit 0; }
}

# ========== 检查前置条件 ==========

preflight() {
  step "检查前置条件"

  if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    err ".env 文件不存在，请从 .env.example 复制并配置"
    exit 1
  fi

  if [[ ! -f "$PROJECT_DIR/$COMPOSE_FILE" ]]; then
    err "$COMPOSE_FILE 不存在"
    exit 1
  fi

  for cmd in rsync ssh; do
    if ! command -v "$cmd" &>/dev/null; then
      err "缺少命令: $cmd"
      exit 1
    fi
  done

  info "本地检查通过"

  info "测试 SSH 连接 ${REMOTE_HOST}..."
  if ! ssh ${SSH_OPTS} -o ConnectTimeout=10 "${REMOTE_HOST}" "echo ok"; then
    err "连接失败，下面用 -v 输出诊断信息："
    ssh ${SSH_OPTS} -v -o ConnectTimeout=10 "${REMOTE_HOST}" "echo ok" 2>&1 || true
    exit 1
  fi
  ok "SSH 连接正常"
}

# ========== 同步代码 ==========

sync_code() {
  step "同步代码到 ${REMOTE_HOST}:${REMOTE_DIR}"

  ssh_cmd "mkdir -p ${REMOTE_DIR}"

  rsync -az --delete \
    -e "ssh ${SSH_OPTS}" \
    --exclude='.git' \
    --exclude='.cursor' \
    --exclude='.venv' \
    --exclude='backend/.venv' \
    --exclude='node_modules' \
    --exclude='frontend/node_modules' \
    --exclude='frontend/dist' \
    --exclude='logs' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='.ruff_cache' \
    --exclude='backend/evals/reports' \
    "$PROJECT_DIR/" "${REMOTE_HOST}:${REMOTE_DIR}/"

  ok "代码同步完成"
}

# ========== 远程构建并部署 ==========

remote_deploy() {
  step "远程构建并部署"

  ssh_cmd bash <<-DEPLOY_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"

    echo "[1/3] 构建镜像..."
    docker compose -f ${COMPOSE_FILE} build --parallel

    echo "[2/3] 停止旧服务..."
    docker compose -f ${COMPOSE_FILE} down --timeout 30

    echo "[3/3] 启动服务..."
    docker compose -f ${COMPOSE_FILE} up -d

    echo ""
    echo "========== 服务状态 =========="
    docker compose -f ${COMPOSE_FILE} ps
DEPLOY_EOF

  ok "部署完成"
}

# ========== 回滚：使用已有镜像重启 ==========

remote_rollback() {
  step "回滚（使用上一次镜像重启）"

  ssh_cmd bash <<-ROLLBACK_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"

    docker compose -f ${COMPOSE_FILE} down --timeout 30
    docker compose -f ${COMPOSE_FILE} up -d --no-build

    echo ""
    echo "========== 服务状态 =========="
    docker compose -f ${COMPOSE_FILE} ps
ROLLBACK_EOF

  ok "回滚完成"
}

# ========== 查看远程状态/日志 ==========

remote_status() {
  step "查看服务状态"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} ps"
}

remote_logs() {
  local service="${1:-}"
  step "查看日志"
  if [[ -n "$service" ]]; then
    ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} logs -f --tail 100 ${service}"
  else
    ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} logs -f --tail 100"
  fi
}

# ========== 使用说明 ==========

usage() {
  cat <<'EOF'
=============== deploy.sh ===============
用法:
  ./scripts/deploy.sh deploy          完整部署（同步代码 + 构建 + 启动）
  ./scripts/deploy.sh sync            仅同步代码到服务器
  ./scripts/deploy.sh build           仅远程构建镜像（不重启）
  ./scripts/deploy.sh restart         重启所有服务（不重新构建）
  ./scripts/deploy.sh rollback        回滚（使用已有镜像重启）
  ./scripts/deploy.sh status          查看远程服务状态
  ./scripts/deploy.sh logs [service]  查看远程日志

配置项（在 .env 中填写）:
  DEPLOY_HOST       必填，SSH 地址（如 root@1.2.3.4）
  DEPLOY_DIR        远程项目目录（默认 /opt/notebooklm）
  DEPLOY_SSH_PORT   SSH 端口（默认 22）

示例:
  ./scripts/deploy.sh deploy
EOF
}

# ========== 入口 ==========

COMMAND="${1:-deploy}"
shift || true

case "$COMMAND" in
  deploy)
    preflight
    confirm "即将同步代码并部署到 ${REMOTE_HOST}:${REMOTE_DIR}，确认？"
    sync_code
    remote_deploy
    ;;
  sync)
    preflight
    sync_code
    ;;
  build)
    preflight
    step "远程构建镜像"
    ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} build --parallel"
    ok "构建完成"
    ;;
  restart)
    preflight
    step "重启服务"
    ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} restart"
    ok "重启完成"
    ;;
  rollback)
    preflight
    confirm "确认回滚？将使用上一次构建的镜像重启"
    remote_rollback
    ;;
  status)
    preflight
    remote_status
    ;;
  logs)
    preflight
    remote_logs "$@"
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
