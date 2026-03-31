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

CLI_PROXY_LOCAL_DIR="${CLI_PROXY_LOCAL_DIR:-$HOME/Documents/CliProxyAPI}"
CLI_PROXY_REMOTE_DIR="${CLI_PROXY_REMOTE_DIR:-/opt/CliProxyAPI}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-notebooklm-postgres}"
SITE_DOMAIN="${SITE_DOMAIN:-}"
MIHOMO_SUBSCRIPTION_URL="${MIHOMO_SUBSCRIPTION_URL:-}"
MIHOMO_MIXED_PORT="${MIHOMO_MIXED_PORT:-7890}"
MIHOMO_CONTROLLER_PORT="${MIHOMO_CONTROLLER_PORT:-9090}"

# ========== 远端服务分组 ==========

INFRA_SERVICES=(
  postgres
  postgres-init-miniflux
  pgadmin
  miniflux
  rsshub
  redis
  mihomo
  minio
  kafka
  redis-exporter
  kafka-exporter
  postgres-exporter
  node-exporter
  otel-collector
  tempo
  loki
  promtail
  prometheus
  grafana
)

APP_SERVICES=(
  backend
  worker
  scheduler
  frontend
  caddy
)

# ========== 工具函数 ==========

info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
ok()    { echo -e "\033[1;32m[OK]\033[0m    $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
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

  if [[ -z "$SITE_DOMAIN" ]]; then
    err "请在 .env 中设置 SITE_DOMAIN，例如 app.example.com"
    exit 1
  fi

  if [[ -z "$MIHOMO_SUBSCRIPTION_URL" ]]; then
    err "请在 .env 中设置 MIHOMO_SUBSCRIPTION_URL（建议使用 Clash 订阅 URL）"
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

# ========== 同步 ==========

remote_ensure_dirs() {
  step "确保远程目录存在"
  ssh_cmd "mkdir -p ${REMOTE_DIR} ${CLI_PROXY_REMOTE_DIR}"
  ok "远程目录已就绪"
}

sync_code() {
  step "同步代码到 ${REMOTE_HOST}:${REMOTE_DIR}"

  remote_ensure_dirs

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

  step "修补服务器 .env（将 127.0.0.1 替换为 host.docker.internal）"
  ssh_cmd bash <<-PATCH_EOF
    set -euo pipefail

    ENV_FILE="${REMOTE_DIR}/.env"
    if [[ ! -f "\$ENV_FILE" ]]; then
      echo "警告：\$ENV_FILE 不存在，跳过修补"
    else
      sed -i 's|http://127\.0\.0\.1:|http://host.docker.internal:|g' "\$ENV_FILE"
      sed -i 's|http://localhost:|http://host.docker.internal:|g' "\$ENV_FILE"
      echo "修补完成"
    fi
PATCH_EOF

  remote_patch_mihomo_config
}

sync_cli_proxy() {
  step "同步 CliProxyAPI 到 ${REMOTE_HOST}:${CLI_PROXY_REMOTE_DIR}"

  if [[ ! -d "$CLI_PROXY_LOCAL_DIR" ]]; then
    err "本地目录不存在: ${CLI_PROXY_LOCAL_DIR}"
    err "请在 .env 中设置 CLI_PROXY_LOCAL_DIR 指向正确路径"
    exit 1
  fi

  remote_ensure_dirs

  rsync -az --delete \
    -e "ssh ${SSH_OPTS}" \
    --exclude='.DS_Store' \
    --exclude='*.log' \
    --exclude='cli-proxy-api' \
    "${CLI_PROXY_LOCAL_DIR}/" "${REMOTE_HOST}:${CLI_PROXY_REMOTE_DIR}/"

  local local_auth_dir="${HOME}/.cli-proxy-api"
  if [[ -d "$local_auth_dir" ]]; then
    info "同步 auth 目录 ${local_auth_dir} ..."
    ssh_cmd "mkdir -p /root/.cli-proxy-api"
    rsync -az \
      -e "ssh ${SSH_OPTS}" \
      --exclude='.DS_Store' \
      "${local_auth_dir}/" "${REMOTE_HOST}:/root/.cli-proxy-api/"
    ok "auth 目录同步完成"
  else
    info "本地 auth 目录 ${local_auth_dir} 不存在，跳过"
  fi

  ok "CliProxyAPI 同步完成"

  remote_patch_cli_proxy_config
}

remote_patch_mihomo_config() {
  step "修补远端 Mihomo 配置"

  local escaped_subscription_url
  escaped_subscription_url="$(printf '%s' "$MIHOMO_SUBSCRIPTION_URL" | sed 's/[&|]/\\&/g')"

  ssh_cmd bash <<-MIHOMO_EOF
    set -euo pipefail

    CONFIG_FILE="${REMOTE_DIR}/docker/mihomo/config.yaml"
    if [[ ! -f "\$CONFIG_FILE" ]]; then
      echo "错误：未找到 Mihomo 配置文件 \$CONFIG_FILE"
      exit 1
    fi

    sed -i 's|__MIHOMO_SUBSCRIPTION_URL__|${escaped_subscription_url}|g' "\$CONFIG_FILE"

    if grep -q '^mixed-port:' "\$CONFIG_FILE"; then
      sed -i 's|^mixed-port:.*$|mixed-port: ${MIHOMO_MIXED_PORT}|g' "\$CONFIG_FILE"
    else
      printf 'mixed-port: %s\n' "${MIHOMO_MIXED_PORT}" >> "\$CONFIG_FILE"
    fi

    if grep -q '^external-controller:' "\$CONFIG_FILE"; then
      sed -i 's|^external-controller:.*$|external-controller: 0.0.0.0:${MIHOMO_CONTROLLER_PORT}|g' "\$CONFIG_FILE"
    else
      printf 'external-controller: 0.0.0.0:%s\n' "${MIHOMO_CONTROLLER_PORT}" >> "\$CONFIG_FILE"
    fi
MIHOMO_EOF

  ok "远端 Mihomo 配置已修补"
}

remote_patch_cli_proxy_config() {
  step "修补远端 CliProxyAPI 配置"

  ssh_cmd bash <<-CPA_EOF
    set -euo pipefail

    CONFIG_FILE="${CLI_PROXY_REMOTE_DIR}/config.yaml"
    if [[ ! -f "\$CONFIG_FILE" ]]; then
      echo "错误：未找到 CliProxyAPI 配置文件 \$CONFIG_FILE"
      exit 1
    fi

    if grep -q '^auth-dir:' "\$CONFIG_FILE"; then
      sed -i 's|^auth-dir:.*$|auth-dir: "/root/.cli-proxy-api"|g' "\$CONFIG_FILE"
    else
      printf 'auth-dir: "/root/.cli-proxy-api"\n' >> "\$CONFIG_FILE"
    fi

    if grep -q '^proxy-url:' "\$CONFIG_FILE"; then
      sed -i 's|^proxy-url:.*$|proxy-url: "socks5://127.0.0.1:${MIHOMO_MIXED_PORT}"|g' "\$CONFIG_FILE"
    else
      printf 'proxy-url: "socks5://127.0.0.1:%s"\n' "${MIHOMO_MIXED_PORT}" >> "\$CONFIG_FILE"
    fi
CPA_EOF

  ok "远端 CliProxyAPI 配置已修补"
}

# ========== CliProxyAPI ==========

start_cli_proxy() {
  step "启动 CliProxyAPI（${CLI_PROXY_REMOTE_DIR}）"

  local local_binary="${CLI_PROXY_LOCAL_DIR}/cli-proxy-api"
  local version=""
  if [[ -f "$local_binary" ]]; then
    version=$("$local_binary" --version 2>&1 | grep -oE 'Version: [^,]+' | sed 's/Version: //' || true)
  fi
  if [[ -z "$version" ]]; then
    err "无法从本地二进制读取版本号，请确认 ${local_binary} 存在"
    exit 1
  fi
  info "本地版本: ${version}，将在服务器上下载对应 Linux 版本"

  ssh_cmd bash <<-PROXY_EOF
    set -euo pipefail

    REMOTE_DIR="${CLI_PROXY_REMOTE_DIR}"
    BINARY="\${REMOTE_DIR}/cli-proxy-api"
    TARGET_VERSION="${version}"
    HEALTH_PATH="/v0/management/get-auth-status"

    ARCH=\$(uname -m)
    case "\$ARCH" in
      x86_64)  GO_ARCH="amd64" ;;
      aarch64) GO_ARCH="arm64" ;;
      *)
        echo "不支持的架构: \$ARCH"
        exit 1
        ;;
    esac

    CURRENT_VERSION=""
    if [[ -f "\$BINARY" ]] && file "\$BINARY" 2>/dev/null | grep -q "ELF"; then
      CURRENT_VERSION=\$("\$BINARY" --version 2>&1 | grep -oE 'Version: [^,]+' | sed 's/Version: //' || true)
    fi

    if [[ "\$CURRENT_VERSION" == "\$TARGET_VERSION" ]]; then
      echo "服务器已是 v\${TARGET_VERSION}，跳过下载"
    else
      echo "下载 CLIProxyAPI v\${TARGET_VERSION} (linux/\${GO_ARCH})..."
      DOWNLOAD_URL="https://github.com/router-for-me/CLIProxyAPI/releases/download/v\${TARGET_VERSION}/CLIProxyAPI_\${TARGET_VERSION}_linux_\${GO_ARCH}.tar.gz"
      curl -fsSL "\$DOWNLOAD_URL" -o /tmp/cliproxyapi.tar.gz
      tar -xzf /tmp/cliproxyapi.tar.gz -C "\$REMOTE_DIR" cli-proxy-api
      rm -f /tmp/cliproxyapi.tar.gz
      echo "下载完成"
    fi

    chmod +x "\$BINARY"

    CLI_PORT=\$(grep -E "^\s*port\s*:" "\${REMOTE_DIR}/config.yaml" 2>/dev/null | awk '{print \$2}' | tr -d '"' || echo "8317")
    CLI_PORT=\${CLI_PORT:-8317}
    echo "检查端口 \$CLI_PORT 是否被占用..."
    PORT_PID=\$(fuser "\${CLI_PORT}/tcp" 2>/dev/null | tr ' ' '\n' | awk 'NF { print; exit }' || true)
    if [[ -n "\$PORT_PID" ]]; then
      echo "停止占用端口 \${CLI_PORT} 的进程 PID=\${PORT_PID} ..."
      kill "\$PORT_PID" 2>/dev/null || true
      sleep 1
    fi

    OLD_PID=\$(pgrep -f "\${REMOTE_DIR}/cli-proxy-api" || true)
    if [[ -n "\$OLD_PID" ]]; then
      kill \$OLD_PID 2>/dev/null || true
      sleep 1
    fi

    cd "\$REMOTE_DIR"
    nohup ./cli-proxy-api >> "\${REMOTE_DIR}/cli-proxy-api.log" 2>&1 &
    NEW_PID=\$!
    sleep 1

    if ! kill -0 "\$NEW_PID" 2>/dev/null; then
      echo "错误：CliProxyAPI 启动后立即退出，请检查日志："
      tail -20 "\${REMOTE_DIR}/cli-proxy-api.log" || true
      exit 1
    fi

    for _ in {1..15}; do
      if curl -fsSL --max-time 3 "http://127.0.0.1:\${CLI_PORT}\${HEALTH_PATH}" >/dev/null 2>&1; then
        echo "CliProxyAPI v\${TARGET_VERSION} 已启动，PID=\$NEW_PID"
        echo "日志: \${REMOTE_DIR}/cli-proxy-api.log"
        exit 0
      fi
      if ! kill -0 "\$NEW_PID" 2>/dev/null; then
        echo "错误：CliProxyAPI 进程已退出，请检查日志："
        tail -50 "\${REMOTE_DIR}/cli-proxy-api.log" || true
        exit 1
      fi
      sleep 1
    done

    echo "错误：CliProxyAPI 启动后未通过健康检查，请检查日志："
    tail -50 "\${REMOTE_DIR}/cli-proxy-api.log" || true
    exit 1
PROXY_EOF

  ok "CliProxyAPI 启动完成"
}

# ========== 远端 Compose 原子操作 ==========

remote_compose_build() {
  step "远程构建镜像"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} build --parallel"
  ok "远程镜像构建完成"
}

remote_compose_down() {
  step "停止远程服务"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} down --timeout 30"
  ok "远程服务已停止"
}

remote_compose_down_volumes() {
  step "停止远程服务并删除 volumes"
  ssh_cmd bash <<-DOWN_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"
    docker compose -f ${COMPOSE_FILE} down --volumes --timeout 30
    docker image prune -f
DOWN_EOF
  ok "远程 volumes 已清理"
}

remote_bootstrap_postgres() {
  step "启动 PostgreSQL"

  ssh_cmd bash <<-POSTGRES_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"

    if [[ -f .env ]]; then
      set -a
      # shellcheck source=/dev/null
      source ./.env
      set +a
    fi

    PGUSER_VAL="\${POSTGRES_USER:-postgres}"
    PGPASSWORD_VAL="\${POSTGRES_PASSWORD:-postgres}"

    docker compose -f ${COMPOSE_FILE} up -d postgres

    for _ in {1..60}; do
      if docker exec -e PGPASSWORD="\$PGPASSWORD_VAL" ${POSTGRES_CONTAINER} \
        psql -U "\$PGUSER_VAL" -d postgres -tAc "SELECT 1" >/dev/null 2>&1; then
        echo "PostgreSQL 已就绪"
        exit 0
      fi
      sleep 2
    done

    echo "错误：等待 PostgreSQL 就绪超时"
    exit 1
POSTGRES_EOF

  ok "PostgreSQL 已启动"
}

remote_ensure_app_db() {
  step "确保主数据库存在"

  ssh_cmd bash <<-DB_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"

    if [[ -f .env ]]; then
      set -a
      # shellcheck source=/dev/null
      source ./.env
      set +a
    fi

    PGDB_VAL="\${POSTGRES_DB:-notebooklm}"
    PGUSER_VAL="\${POSTGRES_USER:-postgres}"
    PGPASSWORD_VAL="\${POSTGRES_PASSWORD:-postgres}"

    EXISTS=\$(docker exec -e PGPASSWORD="\$PGPASSWORD_VAL" ${POSTGRES_CONTAINER} \
      psql -U "\$PGUSER_VAL" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='\$PGDB_VAL'")

    if [[ "\$EXISTS" == "1" ]]; then
      echo "数据库 \$PGDB_VAL 已存在"
      exit 0
    fi

    echo "数据库 \$PGDB_VAL 不存在，开始创建..."
    docker exec -e PGPASSWORD="\$PGPASSWORD_VAL" ${POSTGRES_CONTAINER} \
      psql -U "\$PGUSER_VAL" -d postgres -c "CREATE DATABASE \"\$PGDB_VAL\";"
DB_EOF

  ok "主数据库已就绪"
}

remote_up_infra() {
  step "启动基础服务"

  local services
  services="${INFRA_SERVICES[*]}"

  ssh_cmd bash <<-INFRA_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"
    docker compose -f ${COMPOSE_FILE} up -d --force-recreate --remove-orphans ${services}
INFRA_EOF

  ok "基础服务已启动"
}

remote_up_app() {
  step "启动应用服务"

  local services
  services="${APP_SERVICES[*]}"

  ssh_cmd bash <<-APP_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"
    docker compose -f ${COMPOSE_FILE} up -d --force-recreate --remove-orphans ${services}
APP_EOF

  ok "应用服务已启动"
}

remote_up_all() {
  step "覆盖式启动全部 Compose 服务"

  ssh_cmd bash <<-UP_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"
    docker compose -f ${COMPOSE_FILE} up -d --force-recreate --remove-orphans
    echo ""
    echo "========== 服务状态 =========="
    docker compose -f ${COMPOSE_FILE} ps
UP_EOF

  ok "全部 Compose 服务已启动"
}

remote_restart_compose() {
  step "重启 Compose 服务"
  ssh_cmd "cd ${REMOTE_DIR} && docker compose -f ${COMPOSE_FILE} restart"
  ok "Compose 服务已重启"
}

# ========== 远端组合命令 ==========

remote_deploy() {
  remote_compose_build
  remote_compose_down
  remote_bootstrap_postgres
  remote_ensure_app_db
  remote_up_all
}

remote_clean_deploy() {
  remote_compose_down_volumes
  remote_compose_build
  remote_bootstrap_postgres
  remote_ensure_app_db
  remote_up_all
}

remote_recover() {
  remote_bootstrap_postgres
  remote_ensure_app_db
  remote_up_all
}

remote_rollback() {
  step "回滚（使用已有镜像重启）"

  ssh_cmd bash <<-ROLLBACK_EOF
    set -euo pipefail
    cd "${REMOTE_DIR}"
    docker compose -f ${COMPOSE_FILE} down --timeout 30
    docker compose -f ${COMPOSE_FILE} up -d --no-build --force-recreate --remove-orphans
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

remote_health() {
  step "服务健康检查"

  ssh_cmd bash <<-HEALTH_EOF
    set -euo pipefail

    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    NC='\033[0m'

    ok()   { echo -e "  \${GREEN}[OK]\${NC}    \$*"; }
    fail() { echo -e "  \${RED}[FAIL]\${NC}  \$*"; }
    warn() { echo -e "  \${YELLOW}[WARN]\${NC}  \$*"; }

    echo ""
    echo "========== Docker 容器状态 =========="
    cd "${REMOTE_DIR}"
    if [[ -f .env ]]; then
      set -a
      # shellcheck source=/dev/null
      source ./.env
      set +a
    fi
    docker compose -f ${COMPOSE_FILE} ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"

    echo ""
    echo "========== HTTP 健康检查 =========="

    check_http() {
      local name="\$1" url="\$2"
      if curl -fsSL --max-time 5 "\$url" >/dev/null 2>&1; then
        ok "\$name  (\$url)"
      else
        fail "\$name  (\$url)"
      fi
    }

    check_http "Backend API"   "http://localhost:8080/api/health"
    if [[ -n "\${SITE_DOMAIN:-}" ]]; then
      if curl -fsSL --max-time 5 -H "Host: \${SITE_DOMAIN}" "http://127.0.0.1/" >/dev/null 2>&1; then
        ok "Frontend / Caddy  (http://127.0.0.1/ Host=\${SITE_DOMAIN})"
      else
        fail "Frontend / Caddy  (http://127.0.0.1/ Host=\${SITE_DOMAIN})"
      fi
    else
      check_http "Frontend" "http://localhost:80"
    fi
    check_http "Miniflux"      "http://localhost:8085/healthcheck"
    check_http "Grafana"       "http://localhost:3000/api/health"
    check_http "Prometheus"    "http://localhost:9090/-/healthy"
    check_http "Mihomo"        "http://127.0.0.1:${MIHOMO_CONTROLLER_PORT}/version"

    echo ""
    echo "========== CliProxyAPI =========="
    CLI_PORT=\$(grep -E "^\s*port\s*:" "${CLI_PROXY_REMOTE_DIR}/config.yaml" 2>/dev/null | awk '{print \$2}' | tr -d '"' || echo "8317")
    CLI_PORT=\${CLI_PORT:-8317}
    CLI_PID=\$(pgrep -f "${CLI_PROXY_REMOTE_DIR}/cli-proxy-api" || true)
    if [[ -n "\$CLI_PID" ]]; then
      ok "进程运行中  PID=\$CLI_PID"
    else
      fail "进程未运行"
    fi
    if bash -lc "exec 3<>/dev/tcp/127.0.0.1/\${CLI_PORT}" >/dev/null 2>&1; then
      ok "TCP 端口 \${CLI_PORT} 监听正常"
    else
      fail "TCP 端口 \${CLI_PORT} 无响应"
    fi

    echo ""
    echo "========== 磁盘 / 内存 =========="
    df -h / | awk 'NR==2 {printf "  磁盘: %s 已用 / %s 总计 (%s)\n", \$3, \$2, \$5}'
    free -h | awk '/Mem:/ {printf "  内存: %s 已用 / %s 总计\n", \$3, \$2}'
HEALTH_EOF
}

remote_proxy_logs() {
  local lines="${1:-100}"
  step "查看 CliProxyAPI 日志（最近 ${lines} 行）"
  ssh_cmd "tail -n ${lines} ${CLI_PROXY_REMOTE_DIR}/cli-proxy-api.log 2>/dev/null || echo '(日志文件不存在)'"
}

# ========== 使用说明 ==========

usage() {
  cat <<'EOF'
=============== deploy.sh ===============
用法:
  ./scripts/deploy.sh deploy             完整部署（覆盖式同步代码 + 构建 + 确保主库 + 启动 Compose + 启动 CliProxyAPI）
  ./scripts/deploy.sh clean-deploy       清空所有 volumes 后全新部署（⚠️ 删除 volumes）
  ./scripts/deploy.sh recover            远程恢复服务（确保 PostgreSQL + 主库 + Compose + CliProxyAPI）
  ./scripts/deploy.sh restart            重启 Compose + CliProxyAPI
  ./scripts/deploy.sh rollback           回滚（使用已有镜像重启）
  ./scripts/deploy.sh sync               覆盖式同步代码和 CliProxyAPI
  ./scripts/deploy.sh sync-code          仅覆盖式同步项目代码
  ./scripts/deploy.sh sync-cli-proxy     仅覆盖式同步 CliProxyAPI
  ./scripts/deploy.sh build              仅远程构建镜像
  ./scripts/deploy.sh down               仅停止 Compose 服务
  ./scripts/deploy.sh ensure-db          仅确保 PostgreSQL 和主数据库存在
  ./scripts/deploy.sh up-infra           仅覆盖式启动基础服务
  ./scripts/deploy.sh up-app             仅覆盖式启动应用服务
  ./scripts/deploy.sh up-all             仅覆盖式启动全部 Compose 服务
  ./scripts/deploy.sh cli-proxy          覆盖式同步并重启 CliProxyAPI
  ./scripts/deploy.sh status             查看远程服务状态
  ./scripts/deploy.sh health             全面健康检查（Docker + HTTP + CLI proxy + 资源）
  ./scripts/deploy.sh logs [service]     查看 Docker 服务日志
  ./scripts/deploy.sh proxy-logs [lines] 查看 CliProxyAPI 日志（默认最近 100 行）

配置项（在 .env 中填写）:
  DEPLOY_HOST            必填，SSH 地址（如 root@1.2.3.4）
  DEPLOY_DIR             远程项目目录（默认 /opt/notebooklm）
  DEPLOY_SSH_PORT        SSH 端口（默认 22）
  SITE_DOMAIN            必填，生产环境域名（用于 Caddy 自动签发 HTTPS）
  MIHOMO_SUBSCRIPTION_URL 必填，Mihomo 的 Clash 订阅 URL
  MIHOMO_MIXED_PORT      Mihomo 本地混合代理端口（默认 7890）
  MIHOMO_CONTROLLER_PORT Mihomo 本地控制端口（默认 9090）
  CLI_PROXY_LOCAL_DIR    本地 CliProxyAPI 目录（默认 ~/Documents/CliProxyAPI）
  CLI_PROXY_REMOTE_DIR   远程 CliProxyAPI 目录（默认 /opt/CliProxyAPI）
  POSTGRES_CONTAINER     远程 PostgreSQL 容器名（默认 notebooklm-postgres）

示例:
  ./scripts/deploy.sh deploy
  ./scripts/deploy.sh recover
EOF
}

# ========== 入口 ==========

COMMAND="${1:-deploy}"
shift || true

case "$COMMAND" in
  deploy)
    preflight
    confirm "即将覆盖式部署到 ${REMOTE_HOST}:${REMOTE_DIR}，确认？"
    sync_code
    sync_cli_proxy
    remote_deploy
    start_cli_proxy
    remote_health
    ;;
  clean-deploy)
    preflight
    confirm "⚠️  即将清空服务器所有数据（volumes）并覆盖式重建到 ${REMOTE_HOST}:${REMOTE_DIR}，此操作不可逆！确认？"
    sync_code
    sync_cli_proxy
    remote_clean_deploy
    start_cli_proxy
    remote_health
    ;;
  recover)
    preflight
    remote_recover
    start_cli_proxy
    remote_health
    ;;
  sync)
    preflight
    sync_code
    sync_cli_proxy
    ;;
  sync-code)
    preflight
    sync_code
    ;;
  sync-cli-proxy)
    preflight
    sync_cli_proxy
    ;;
  build)
    preflight
    remote_compose_build
    ;;
  down)
    preflight
    remote_compose_down
    ;;
  ensure-db)
    preflight
    remote_bootstrap_postgres
    remote_ensure_app_db
    ;;
  up-infra)
    preflight
    remote_bootstrap_postgres
    remote_ensure_app_db
    remote_up_infra
    ;;
  up-app)
    preflight
    remote_bootstrap_postgres
    remote_ensure_app_db
    remote_up_app
    ;;
  up-all)
    preflight
    remote_bootstrap_postgres
    remote_ensure_app_db
    remote_up_all
    ;;
  restart)
    preflight
    remote_restart_compose
    start_cli_proxy
    remote_health
    ;;
  rollback)
    preflight
    confirm "确认回滚？将使用上一次构建的镜像重启"
    remote_rollback
    start_cli_proxy
    remote_health
    ;;
  status)
    preflight
    remote_status
    ;;
  health)
    preflight
    remote_health
    ;;
  logs)
    preflight
    remote_logs "$@"
    ;;
  proxy-logs)
    preflight
    remote_proxy_logs "$@"
    ;;
  cli-proxy)
    preflight
    sync_cli_proxy
    start_cli_proxy
    ;;
  --help|-h|help)
    usage
    ;;
  *)
    usage
    exit 1
    ;;
esac
