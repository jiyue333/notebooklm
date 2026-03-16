# =============== 项目简介 ===============

NotebookLM 是一个围绕搜索、导入和 AI 生成内容构建的研究工作台。当前仓库包含：

- `frontend/`：React + Vite 前端
- `backend/`：FastAPI API、worker、scheduler
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

