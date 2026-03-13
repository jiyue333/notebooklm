# NotebookLM 单服务器公网部署指南

## 1. 快速部署流程

如果你想先按一遍命令把服务跑起来，按下面顺序执行。

### 1.1 准备服务器并登录

先准备一台 `Ubuntu 24.04` 公网服务器，然后登录：

```bash
ssh root@<your-server-ip>
```

如果你不是 `root`，把下面命令里的 `sudo` 保留。

### 1.2 配置域名

在 DNS 控制台添加一条 `A` 记录：

- 主机记录：`note`
- 记录值：你的服务器公网 IP

等待解析生效后，在服务器上验证：

```bash
apt update && apt install -y dnsutils
dig note.example.com +short
```

输出应为你的服务器公网 IP。

### 1.3 安装系统依赖

```bash
apt update
apt install -y git curl nginx python3 python3-venv python3-pip ca-certificates gnupg lsb-release
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker
```

### 1.4 拉取项目代码

```bash
mkdir -p /srv/notebooklm
cd /srv/notebooklm
git clone <your-repo-url> .
mkdir -p logs run
```

### 1.5 创建基础设施配置并启动容器

先按本文 `8.1` 和 `8.2` 的内容创建：

- `/srv/notebooklm/.env.infra`
- `/srv/notebooklm/docker-compose.prod.yml`

然后启动：

```bash
cd /srv/notebooklm
docker compose --env-file .env.infra -f docker-compose.prod.yml up -d
docker compose --env-file .env.infra -f docker-compose.prod.yml ps
docker compose --env-file .env.infra -f docker-compose.prod.yml logs --tail=50 postgres
docker compose --env-file .env.infra -f docker-compose.prod.yml logs --tail=50 kafka
```

### 1.6 配置后端并执行迁移

```bash
cd /srv/notebooklm
python3 -m venv .venv
source /srv/notebooklm/.venv/bin/activate
python -m pip install --upgrade pip wheel
cd /srv/notebooklm/backend
pip install -e .
cd /srv/notebooklm
cp .env.example .env
chmod 600 .env
```

然后按本文 `9.2` 填好 `/srv/notebooklm/.env`，再执行迁移：

```bash
cd /srv/notebooklm/backend
source /srv/notebooklm/.venv/bin/activate
alembic upgrade head
```

### 1.7 构建并运行前端 Nginx 镜像

```bash
cd /srv/notebooklm
docker build -t notebooklm-frontend:latest ./frontend
docker rm -f notebooklm-frontend 2>/dev/null || true
docker run -d \
  --name notebooklm-frontend \
  --restart unless-stopped \
  -p 127.0.0.1:8081:80 \
  notebooklm-frontend:latest
docker ps --filter name=notebooklm-frontend
```

前端容器内部已经自带 Nginx，并且会把 Vite 构建产物直接服务在：

- `http://127.0.0.1:8081`

### 1.8 启用宿主机 Nginx 反向代理配置

仓库里已经准备好了可直接用的配置文件：

- [notebooklm.conf](/Users/taless/Code/notebooklm/deploy/nginx/notebooklm.conf)

如果你的实际域名不是 `note.example.com`，先改 `server_name`：

```bash
sed -i 's/note.example.com/<your-domain>/g' /srv/notebooklm/deploy/nginx/notebooklm.conf
```

然后启用它：

```bash
rm -f /etc/nginx/sites-enabled/default
ln -sf /srv/notebooklm/deploy/nginx/notebooklm.conf /etc/nginx/sites-available/notebooklm.conf
ln -sf /etc/nginx/sites-available/notebooklm.conf /etc/nginx/sites-enabled/notebooklm.conf
nginx -t
systemctl reload nginx
```

### 1.9 启动 API、Worker、Scheduler

```bash
cd /srv/notebooklm
chmod +x scripts/*.sh
./scripts/prod.sh start all
./scripts/prod.sh status
```

日志位置：

- `/srv/notebooklm/logs/backend.log`
- `/srv/notebooklm/logs/worker.log`
- `/srv/notebooklm/logs/scheduler.log`

实时看日志：

```bash
tail -f /srv/notebooklm/logs/backend.log
tail -f /srv/notebooklm/logs/worker.log
tail -f /srv/notebooklm/logs/scheduler.log
```

### 1.10 签发 HTTPS 证书

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d note.example.com
systemctl status certbot.timer
```

### 1.11 做上线验证

```bash
curl -I http://127.0.0.1:8081
curl -I https://note.example.com/
curl https://note.example.com/api/health
curl https://note.example.com/api/ready
./scripts/prod.sh status
docker compose --env-file /srv/notebooklm/.env.infra -f /srv/notebooklm/docker-compose.prod.yml ps
```

如果后续导入文件或粘贴图片，`MinIO` bucket 不需要手动创建；后端会在首次访问时自动创建 `notebooklm` bucket。

### 1.12 查看 Grafana 和 MinIO Console

本方案不把 `Grafana` 和 `MinIO Console` 暴露到公网，而是通过 SSH 隧道访问：

```bash
ssh -L 3000:127.0.0.1:3000 <your-user>@note.example.com
ssh -L 9001:127.0.0.1:9001 <your-user>@note.example.com
```

然后本机打开：

- [http://127.0.0.1:3000](http://127.0.0.1:3000)
- [http://127.0.0.1:9001](http://127.0.0.1:9001)

## 2. 适用范围

这份文档适用于下面这种目标：

- 只有一台公网 Linux 服务器
- 希望通过域名直接访问项目
- 希望把当前仓库里的主要依赖都部署起来
- 优先考虑部署方便、能跑通、性能尚可
- 暂时不优先考虑扩容、攻击防护、备份、容灾

本方案会部署这些组件：

- `frontend-nginx`
- `api`
- `worker`
- `scheduler`
- `postgres`
- `redis`
- `minio`
- `kafka`
- `kafka-exporter`
- `otel-collector`
- `tempo`
- `loki`
- `promtail`
- `prometheus`
- `grafana`

同时保留两个外部依赖：

- `Exa`
- OpenAI-compatible 模型服务

不在这台服务器上自托管：

- `Ollama`

原因很简单：同一台机器上再加本地模型，资源压力会明显变大，体验不稳定。


## 3. 最终拓扑

```text
Internet
   |
   `-- note.example.com ----------> host nginx
                                         |
                                         +--> /              -> 127.0.0.1:8081 (frontend nginx container)
                                         +--> /api/*         -> 127.0.0.1:8080
                                         `--> /notebooklm/*  -> 127.0.0.1:9000


Server internals
   |
   +-- docker run
   |    `-- notebooklm-frontend -> nginx serving dist on 127.0.0.1:8081
   |
   +-- scripts/prod.sh
   |    +-- api       -> FastAPI
   |    +-- worker    -> Kafka consumer
   |    `-- scheduler -> periodic tasks
   |
   `-- docker compose
        +-- postgres
        +-- redis
        +-- minio
        +-- kafka
        +-- kafka-exporter
        +-- otel-collector
        +-- tempo
        +-- loki
        +-- promtail
        +-- prometheus
        `-- grafana


Local-only admin access
   +-- ssh -L 3000:127.0.0.1:3000  -> Grafana
   `-- ssh -L 9001:127.0.0.1:9001  -> MinIO Console

External services
   +-- Exa API
   `-- OpenAI-compatible chat / embedding provider
```

### 3.1 这套拓扑的设计原则

- 前端打包进 `nginx` 镜像，宿主机不需要单独安装 Node.js。
- 宿主机 `nginx` 只负责一个公网入口和统一反向代理。
- 后端应用进程用脚本启动，因为你当前更关注简单直接。
- 状态型基础设施全部走 Docker Compose，便于启动、停止、迁移。
- 所有内部组件只绑定到 `127.0.0.1`。
- 公网只暴露一个域名：`note.example.com`。
- `MinIO API` 通过 `/${OBJECT_STORAGE_BUCKET}/...` 路径挂到同一个域名下，因为当前代码会生成 presigned URL；如果对象存储 endpoint 不可公网访问，浏览器下载文件会失败。


## 4. 服务器配置要求

### 4.1 推荐配置

| 档位     | CPU    | 内存  | 磁盘       | 适用情况           |
| -------- | ------ | ----- | ---------- | ------------------ |
| 最低可用 | 4 vCPU | 8 GB  | 100 GB SSD | 个人项目、轻量使用 |
| 推荐     | 8 vCPU | 16 GB | 150 GB SSD | 更稳、更适合长期用 |
| 更宽松   | 8 vCPU | 32 GB | 200 GB SSD | 文件较多、导入频繁 |

### 4.2 我建议你购买的配置

如果你只买一台服务器，我建议：

- Ubuntu 24.04 LTS
- `8 vCPU / 16 GB RAM / 150 GB SSD`
- 固定公网 IP

### 4.3 为什么这里比简化版要求更高

因为你现在要把下面这些也放进同一台机器：

- PostgreSQL
- Kafka
- MinIO
- Redis
- Grafana
- Prometheus
- Loki
- Tempo

虽然流量不大，但这些服务本身就会占用不少内存和磁盘。


## 5. 域名规划

### 5.1 只用一个公网域名

整个项目只使用一个公网域名：

- `note.example.com`

它承担三个职责：

- `https://note.example.com/`：前端页面
- `https://note.example.com/api/*`：后端 API
- `https://note.example.com/notebooklm/*`：MinIO 对象访问路径

其中 `notebooklm` 是这份教程约定的 bucket 名。

### 5.2 为什么一个域名是可行的

当前前端默认请求：

- `/api`

所以主站和 API 同域最省事。

而 MinIO 这层虽然也需要公网可访问地址，但它生成的 presigned URL 本质上是：

- `https://<endpoint>/<bucket>/<object>?signature=...`

所以只要：

- `OBJECT_STORAGE_ENDPOINT=note.example.com`
- Nginx 把 `/notebooklm/` 代理给 MinIO

同一个域名就能同时承载前端、API 和对象下载。

### 5.3 为什么 Grafana 和 MinIO Console 不用公网域名

因为这两个只是运维入口，不是主业务入口。

个人项目最省事的方案是：

- Grafana 只监听 `127.0.0.1:3000`
- MinIO Console 只监听 `127.0.0.1:9001`
- 需要查看时通过 SSH 隧道访问


## 6. 域名配置教程

下面假设你的根域名是 `example.com`。

### 6.1 DNS 记录

在域名 DNS 控制台中添加：

| 类型 | 主机记录 | 值                |
| ---- | -------- | ----------------- |
| `A`  | `note`   | 你的服务器公网 IP |

### 6.2 验证 DNS

```bash
dig note.example.com +short
```

应该返回你的服务器公网 IP。

### 6.3 防火墙 / 安全组

公网开放：

- `22/tcp`
- `80/tcp`
- `443/tcp`

不要开放：

- `5432`
- `6379`
- `9000`
- `9001`
- `29092`
- `3000`
- `3100`
- `3200`
- `4317`
- `4318`
- `8080`
- `9101`
- `9102`

这些都只保留本机访问。


## 7. 服务器初始化

### 7.1 安装基础软件

```bash
sudo apt update
sudo apt install -y git curl nginx python3 python3-venv python3-pip ca-certificates gnupg lsb-release
```

### 7.2 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

重新登录一次 shell。

### 7.3 前端不再需要单独安装 Node.js

前端镜像会在 `Dockerfile` 里完成 `npm ci` 和 `vite build`，所以服务器上不需要额外安装 Node.js。

### 7.4 创建部署目录

```bash
sudo mkdir -p /srv/notebooklm
sudo chown -R $USER:$USER /srv/notebooklm
cd /srv/notebooklm
git clone <你的仓库地址> .
mkdir -p logs
```


## 8. 基础设施部署

### 8.1 创建基础设施环境变量文件

在项目根目录创建 `.env.infra`：

```env
POSTGRES_DB=notebooklm
POSTGRES_USER=notebooklm
POSTGRES_PASSWORD=change-this-postgres-password

MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=change-this-minio-password

GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=change-this-grafana-password
```

### 8.2 创建基础设施 compose 文件

在项目根目录创建 `docker-compose.prod.yml`：

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    container_name: notebooklm-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: notebooklm-redis
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:RELEASE.2025-02-28T09-55-16Z
    container_name: notebooklm-minio
    restart: unless-stopped
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    ports:
      - "127.0.0.1:9000:9000"
      - "127.0.0.1:9001:9001"
    volumes:
      - minio_data:/data

  kafka:
    image: bitnami/kafka:3.8.0
    container_name: notebooklm-kafka
    restart: unless-stopped
    ports:
      - "127.0.0.1:29092:29092"
    environment:
      KAFKA_ENABLE_KRAFT: "yes"
      KAFKA_KRAFT_CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qk
      KAFKA_CFG_NODE_ID: 1
      KAFKA_CFG_PROCESS_ROLES: broker,controller
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093,EXTERNAL://:29092
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092,EXTERNAL://127.0.0.1:29092
      KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT,EXTERNAL:PLAINTEXT
      KAFKA_CFG_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE: "true"
      KAFKA_CFG_NUM_PARTITIONS: 1
      KAFKA_CFG_DEFAULT_REPLICATION_FACTOR: 1
      KAFKA_CFG_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_CFG_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_CFG_TRANSACTION_STATE_LOG_MIN_ISR: 1
      ALLOW_PLAINTEXT_LISTENER: "yes"
    volumes:
      - kafka_data:/bitnami/kafka
    healthcheck:
      test: ["CMD-SHELL", "/opt/bitnami/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list >/dev/null 2>&1"]
      interval: 15s
      timeout: 10s
      retries: 10

  kafka-exporter:
    image: danielqsj/kafka-exporter:v1.8.0
    container_name: notebooklm-kafka-exporter
    restart: unless-stopped
    depends_on:
      kafka:
        condition: service_healthy
    command:
      - "--kafka.server=kafka:9092"
      - "--web.listen-address=:9308"
    ports:
      - "127.0.0.1:9308:9308"

  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.122.1
    container_name: notebooklm-otel-collector
    restart: unless-stopped
    command: ["--config=/etc/otelcol-contrib/config.yaml"]
    ports:
      - "127.0.0.1:4317:4317"
      - "127.0.0.1:4318:4318"
    volumes:
      - ./docker/otel-collector/config.yaml:/etc/otelcol-contrib/config.yaml:ro

  tempo:
    image: grafana/tempo:2.7.2
    container_name: notebooklm-tempo
    restart: unless-stopped
    command: ["-config.file=/etc/tempo/config.yaml"]
    ports:
      - "127.0.0.1:3200:3200"
    volumes:
      - ./docker/tempo/config.yaml:/etc/tempo/config.yaml:ro
      - tempo_data:/var/tempo

  loki:
    image: grafana/loki:3.4.1
    container_name: notebooklm-loki
    restart: unless-stopped
    command: ["-config.file=/etc/loki/config.yaml"]
    ports:
      - "127.0.0.1:3100:3100"
    volumes:
      - ./docker/loki/config.yaml:/etc/loki/config.yaml:ro
      - loki_data:/loki

  promtail:
    image: grafana/promtail:3.4.1
    container_name: notebooklm-promtail
    restart: unless-stopped
    depends_on:
      - loki
    command: ["-config.file=/etc/promtail/config.yaml"]
    volumes:
      - ./docker/promtail/config.yaml:/etc/promtail/config.yaml:ro
      - ./logs:/workspace/logs:ro
      - promtail_data:/tmp

  prometheus:
    image: prom/prometheus:v3.2.1
    container_name: notebooklm-prometheus
    restart: unless-stopped
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--web.enable-lifecycle"
    ports:
      - "127.0.0.1:9090:9090"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    volumes:
      - ./docker/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus

  grafana:
    image: grafana/grafana:11.5.2
    container_name: notebooklm-grafana
    restart: unless-stopped
    depends_on:
      - prometheus
      - loki
      - tempo
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_PATHS_PROVISIONING: /etc/grafana/provisioning
    ports:
      - "127.0.0.1:3000:3000"
    volumes:
      - ./docker/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./docker/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana

volumes:
  postgres_data:
  redis_data:
  minio_data:
  kafka_data:
  tempo_data:
  loki_data:
  promtail_data:
  prometheus_data:
  grafana_data:
```

### 8.3 启动基础设施

```bash
cd /srv/notebooklm
docker compose --env-file .env.infra -f docker-compose.prod.yml up -d
docker compose --env-file .env.infra -f docker-compose.prod.yml ps
```

### 8.4 本机检查

```bash
docker compose --env-file .env.infra -f docker-compose.prod.yml logs --tail=50 postgres
docker compose --env-file .env.infra -f docker-compose.prod.yml logs --tail=50 kafka
docker compose --env-file .env.infra -f docker-compose.prod.yml logs --tail=50 grafana
```


## 9. 后端部署

### 9.1 创建 Python 虚拟环境

```bash
cd /srv/notebooklm
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip wheel
cd backend
pip install -e .
```

### 9.2 配置后端环境文件

```bash
cd /srv/notebooklm/backend
cp .env.example .env
chmod 600 .env
```

推荐 `.env` 如下：

```env
APP_NAME=NotebookLM Backend
APP_ENV=production
DEBUG=false
API_PREFIX=/api
HOST=127.0.0.1
PORT=8080
SECRET_KEY=<换成至少32位随机字符串>
AUTH_TOKEN_TTL_DAYS=30

DATABASE_URL=postgresql+asyncpg://notebooklm:change-this-postgres-password@127.0.0.1:5432/notebooklm
DATABASE_ECHO=false
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

REDIS_URL=redis://127.0.0.1:6379/0
REDIS_DECODE_RESPONSES=false

EXA_BASE_URL=https://api.exa.ai
EXA_DEFAULT_API_KEY=<你的 Exa Key>
SEARCH_INLINE_DEADLINE_MS=4500

LLM_DEFAULT_API_KEY=<你的 Chat 模型 Key>
EMBEDDING_DEFAULT_API_KEY=<你的 Embedding 模型 Key>
DEFAULT_CHAT_PROVIDER=openai_compatible
DEFAULT_CHAT_MODEL_NAME=<你的 chat model>
DEFAULT_CHAT_API_URL=https://<你的 OpenAI-compatible endpoint>/v1
DEFAULT_SEARCH_PROVIDER=exa
DEFAULT_EMBEDDING_PROVIDER=openai_compatible
DEFAULT_EMBEDDING_MODEL_NAME=<你的 embedding model>
DEFAULT_EMBEDDING_API_URL=https://<你的 OpenAI-compatible endpoint>/v1
EMBEDDING_OUTPUT_DIMENSIONS=1024
CHUNK_TARGET_TOKENS=600
CHUNK_OVERLAP_TOKENS=80
SUMMARY_CACHE_TTL_DAYS=30
SCHEDULER_FAILED_JOB_RETENTION_DAYS=14

KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:29092
KAFKA_TOPIC=notebook_async
KAFKA_CONSUMER_POLL_TIMEOUT_MS=1000
KAFKA_REQUEST_TIMEOUT_MS=10000
KAFKA_AUTO_OFFSET_RESET=earliest

OBJECT_STORAGE_ENDPOINT=note.example.com
OBJECT_STORAGE_ACCESS_KEY=<与你 .env.infra 中 MINIO_ROOT_USER 一致>
OBJECT_STORAGE_SECRET_KEY=<与你 .env.infra 中 MINIO_ROOT_PASSWORD 一致>
OBJECT_STORAGE_BUCKET=notebooklm
OBJECT_STORAGE_SECURE=true
OBJECT_STORAGE_REGION=
FILE_STORAGE_BACKEND=minio

LOG_LEVEL=INFO
LOG_JSON=true
API_METRICS_PORT=8080
WORKER_METRICS_PORT=9101
SCHEDULER_METRICS_PORT=9102

OTEL_ENABLED=true
OTEL_SERVICE_NAME=notebooklm-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318/v1/traces

LANGSMITH_ENABLED=false
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=notebooklm-backend
LANGSMITH_WORKSPACE_ID=
LANGSMITH_TRACING=false

CORS_ORIGINS=["https://note.example.com"]
```

### 9.3 数据库迁移

```bash
cd /srv/notebooklm/backend
source /srv/notebooklm/.venv/bin/activate
alembic upgrade head
```


## 10. 前端部署

### 10.1 构建并运行前端 Nginx 镜像

当前前端默认使用：

- `VITE_API_BASE_URL=/api`

因此主站和 API 同域时，不需要额外改动。

```bash
cd /srv/notebooklm
docker build -t notebooklm-frontend:latest ./frontend
docker rm -f notebooklm-frontend 2>/dev/null || true
docker run -d \
  --name notebooklm-frontend \
  --restart unless-stopped \
  -p 127.0.0.1:8081:80 \
  notebooklm-frontend:latest
```

前端容器会监听：

- `127.0.0.1:8081`


## 11. 用脚本管理 API / Worker / Scheduler

### 11.1 为什么这里改成脚本

可以用脚本，之前用 `systemd` 只是因为它更像标准守护进程管理。

但对你这个单服务器个人项目来说，脚本也完全能用，优点是：

- 上手更直接
- 改命令更方便
- 不用每次改完都 `daemon-reload`
- 更接近你本地开发时的习惯

需要明确的一点是：

- 脚本是启动器，不是完整的进程监督器

也就是说它能负责：

- 启动
- 停止
- 查看状态
- 写日志

但它不负责：

- 开机自动拉起
- 进程崩溃自动重启

对当前阶段，这个代价可以接受。

### 11.2 创建日志目录

Promtail 当前读取的是项目里的文件日志，所以要让三个进程把 stdout / stderr 写到：

- `/srv/notebooklm/logs/backend.log`
- `/srv/notebooklm/logs/worker.log`
- `/srv/notebooklm/logs/scheduler.log`

执行：

```bash
mkdir -p /srv/notebooklm/logs
touch /srv/notebooklm/logs/backend.log
touch /srv/notebooklm/logs/worker.log
touch /srv/notebooklm/logs/scheduler.log
```

### 11.3 使用仓库里的现成脚本

我已经把生产脚本统一收口到：

- [prod.sh](/Users/taless/Code/notebooklm/scripts/prod.sh)

先赋可执行权限：

```bash
cd /srv/notebooklm
chmod +x scripts/*.sh
```

### 11.4 启动进程

```bash
cd /srv/notebooklm
./scripts/prod.sh start all
```

### 11.5 查看状态

```bash
cd /srv/notebooklm
./scripts/prod.sh status
```

### 11.6 停止进程

```bash
cd /srv/notebooklm
./scripts/prod.sh stop all
```

### 11.7 查看日志

```bash
tail -f /srv/notebooklm/logs/backend.log
tail -f /srv/notebooklm/logs/worker.log
tail -f /srv/notebooklm/logs/scheduler.log
```


## 12. Nginx 配置

仓库里已经提供好了可直接使用的 Nginx 配置：

- [notebooklm.conf](/Users/taless/Code/notebooklm/deploy/nginx/notebooklm.conf)

这个文件已经包含：

- `/` -> `127.0.0.1:8081`
- `/api/` -> `127.0.0.1:8080`
- `/notebooklm/` -> `127.0.0.1:9000`
- SSE 需要的长连接超时和关闭缓冲

如果你的实际域名不是 `note.example.com`，先把这个文件里的 `server_name` 改成你自己的域名。

启用配置：

```bash
cd /srv/notebooklm
sudo ln -sf /srv/notebooklm/deploy/nginx/notebooklm.conf /etc/nginx/sites-available/notebooklm.conf
sudo ln -sf /etc/nginx/sites-available/notebooklm.conf /etc/nginx/sites-enabled/notebooklm.conf
sudo nginx -t
sudo systemctl reload nginx
```


## 13. HTTPS 配置

### 13.1 安装 Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 13.2 申请证书

```bash
sudo certbot --nginx \
  -d note.example.com
```

### 13.3 验证自动续期

```bash
sudo systemctl status certbot.timer
```


## 14. 上线检查

### 14.1 基础设施检查

```bash
docker compose --env-file .env.infra -f docker-compose.prod.yml ps
```

确认至少这些容器正常：

- `postgres`
- `redis`
- `minio`
- `kafka`
- `kafka-exporter`
- `otel-collector`
- `tempo`
- `loki`
- `promtail`
- `prometheus`
- `grafana`

### 14.2 后端检查

```bash
curl http://127.0.0.1:8080/api/health
curl http://127.0.0.1:8080/api/ready
```

应该看到：

- `status=ok`
- `ready` 返回 Kafka 连接信息

### 14.3 Grafana 检查

本机执行：

```bash
ssh -L 3000:127.0.0.1:3000 <你的服务器用户名>@note.example.com
```

然后浏览器打开：

- `http://127.0.0.1:3000`

默认用户名密码就是你在 `.env.infra` 里配置的：

- `GRAFANA_ADMIN_USER`
- `GRAFANA_ADMIN_PASSWORD`

确认这些 dashboard 可以看到数据：

- Kafka dashboard
- Search dashboard
- Ingest dashboard
- LLM dashboard

### 14.4 MinIO Console 检查

本机执行：

```bash
ssh -L 9001:127.0.0.1:9001 <你的服务器用户名>@note.example.com
```

然后浏览器打开：

- `http://127.0.0.1:9001`

用 `.env.infra` 里的：

- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`

登录后确认：

- 能正常进入控制台
- 后端导入文件后会自动创建 `notebooklm` bucket

### 14.5 主功能检查

浏览器打开：

- `https://note.example.com`

手工验证：

- 能打开首页
- 能注册和登录
- 能创建 notebook
- 能手动添加 text 来源
- 能上传文件
- 能搜索来源
- 能导入搜索结果
- 能看到 worker 处理后的文章正文
- 能进行 chat
- 能生成 summary

## 15. 关键说明

### 15.1 为什么 Redis 也部署

当前项目依赖 `Redis` 做缓存和运行时辅助能力，所以单机部署里也应该带上，不建议省掉。

### 15.2 为什么 MinIO 仍然能只用一个域名

因为对象 URL 最终会基于 `OBJECT_STORAGE_ENDPOINT` 生成，只要它指向 `note.example.com`，再由宿主机 `nginx` 把 `/notebooklm/` 反代到 `127.0.0.1:9000`，浏览器就能通过同一个域名访问对象存储。

### 15.3 为什么观测栈和 Console 仍然放内网端口

因为这些入口不是主业务路径。对个人项目来说，把它们限制在 `127.0.0.1` 再通过 SSH 隧道访问，更简单，也更不容易把运维入口直接暴露到公网。

### 15.4 为什么前端改成 Nginx 镜像

这样宿主机不需要再单独装 Node.js，也不需要手动维护 `frontend/dist`。前端镜像天然就包含构建产物，更新时只要重新 `docker build` 再替换容器即可。

## 16. 最终推荐参数

如果你现在马上部署，我建议：

- 服务器：`8C16G / Ubuntu 24.04 / 150G SSD`
- 域名：`note.example.com`
- 模型：
  - chat 用外部 OpenAI-compatible
  - embedding 用外部 OpenAI-compatible
- 本机部署：
  - `postgres`
  - `redis`
  - `minio`
  - `kafka`
  - `grafana/prometheus/loki/tempo`
- 进程管理：
  - `scripts/prod.sh`
- 入口：
  - `nginx + certbot`


## 17. 后续可以再做但现在不是必须的

- 把 API / worker / scheduler 也容器化
- 为 Grafana 单独加登录保护策略
- 补日志轮转
- 补数据库备份
- 把 Postgres / Kafka / MinIO 替换成托管服务

## 18. 参考资料

- [FastAPI Deployment Concepts](https://fastapi.tiangolo.com/deployment/concepts/)
- [Docker Compose Startup Order](https://docs.docker.com/compose/how-tos/startup-order/)
- [Docker Restart Policies](https://docs.docker.com/engine/containers/start-containers-automatically/)
- [Nginx Reverse Proxy Guide](https://docs.nginx.com/nginx/admin-guide/web-server/reverse-proxy/)
- [PostgreSQL Backup and Restore](https://www.postgresql.org/docs/current/backup-dump.html)
