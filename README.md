# =============== 项目简介 ===============

NotebookLM 是一个围绕搜索、导入和 AI 生成内容构建的研究工作台。当前仓库包含：

- `frontend/`：React + Vite 前端
- `backend/`：FastAPI API、worker、scheduler、evals
- `docker-compose.yml`：本地基础设施与观测栈
- `scripts/*.sh`：开发、生产、benchmark、在线造数统一入口

当前正式系统结构说明见：

- [system-architecture.md](/Users/taless/Code/notebooklm/docs/system-architecture.md)
- [observability-structure.md](/Users/taless/Code/notebooklm/docs/observability-structure.md)
- [test.md](/Users/taless/Code/notebooklm/docs/test.md)
- [scripts/README.md](/Users/taless/Code/notebooklm/scripts/README.md)

# =============== 开发模式启动 ===============

## 1. 准备根目录环境变量

```bash
cp .env.example .env
```

按需修改根目录 `.env`，后端和前端都会从这里读取配置。

## 2. 安装后端依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
cd backend
pip install -e .[dev]
cd ..
```

如果你要运行离线 benchmark 或 Ragas，再额外安装：

```bash
source .venv/bin/activate
cd backend
pip install -e .[dev,evals]
cd ..
```

## 3. 安装前端依赖

```bash
cd frontend
npm install
cd ..
```

## 4. 启动基础设施

```bash
docker compose up -d \
  postgres redis minio kafka kafka-exporter redis-exporter postgres-exporter node-exporter \
  otel-collector tempo loki promtail prometheus grafana
```

## 5. 执行数据库迁移

```bash
source .venv/bin/activate
cd backend
alembic upgrade head
cd ..
```

## 6. 启动开发模式

```bash
./scripts/dev.sh start
```

常用命令：

```bash
./scripts/dev.sh status
./scripts/dev.sh logs all
./scripts/dev.sh logs backend
./scripts/dev.sh stop
```

# =============== 目录说明 ===============

- `backend/app/modules/`：业务模块
- `backend/app/infra/`：基础设施能力
- `backend/app/modules/tracker/`：业务观测封装
- `backend/evals/`：在线造数、离线 benchmark、报告与 demo 资产
- `frontend/src/`：前端页面、组件、API 调用
- `docker/`：Prometheus、Grafana、Loki、Tempo 等配置
- `scripts/`：统一脚本入口

# =============== 观测与测试 ===============

开发模式常用入口：

- 前端：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8080/api`
- 健康检查：`http://127.0.0.1:8080/api/health`
- Metrics：`http://127.0.0.1:8080/api/metrics`
- Grafana：`http://127.0.0.1:3000`

运行 benchmark：

```bash
./scripts/benchmark.sh build-datasets all
./scripts/benchmark.sh run all
./scripts/benchmark.sh gate all
./scripts/benchmark.sh load-test search
```

运行在线造数与巡检：

```bash
./scripts/online.sh seed notebooks --count 3
./scripts/online.sh seed all --count 3
./scripts/online.sh inspect redis
./scripts/online.sh show search-samples
```
