# AGENTS.md

## Cursor Cloud specific instructions

### 项目概述

本项目是一个 AI 驱动的研究助手，支持搜索、导入、阅读、摘要和讨论文档。详细技术栈见 `docker-compose.yml` 和 `backend/pyproject.toml`。

### 基础设施服务

开发环境需要 Docker 运行四个核心服务（数据库、缓存、消息队列、对象存储），在 `docker-compose.yml` 中定义。使用以下命令启动前四个核心服务：

```bash
docker compose up -d $(docker compose config --services | head -n 5 | grep -E 'redis|kafka|minio|pg')
```

Docker 守护进程需要手动启动：`sudo dockerd &>/tmp/dockerd.log &`。本环境使用 `fuse-overlayfs` 存储驱动和 `iptables-legacy`。

### 启动开发服务

所有四个应用进程（backend, worker, scheduler, frontend）通过 `scripts/dev.sh` 管理：

```bash
scripts/dev.sh start    # 启动所有服务
scripts/dev.sh stop     # 停止所有服务
scripts/dev.sh status   # 查看状态
scripts/dev.sh logs [backend|worker|scheduler|frontend|all]
```

端口分配：Backend=8080, Frontend=5173, Worker metrics=9101, Scheduler metrics=9102。

### 数据库迁移

```bash
cd backend && uv run alembic upgrade head
```

### Lint / Test / Build

| 检查项 | 命令 |
|--------|------|
| 后端 lint | `cd backend && uv run ruff check .` |
| 前端 lint | `cd frontend && npx eslint .` |
| 后端测试 | `cd backend && uv run pytest` |
| 前端构建 | `cd frontend && npm run build` |

### 注意事项

- `.env` 文件从 `.env.example` 复制而来，位于项目根目录，被 backend 和 frontend（通过 Vite `envDir`）共同读取。
- `tools/remark-processor/` 是一个独立的 Node.js 工具，需要单独 `npm install`。
- LLM 功能（摘要、聊天、搜索任务解析）默认配置使用 Ollama，如未安装 Ollama 则 AI 功能不可用，但核心 CRUD 功能正常。可在 `.env` 中配置 OpenAI/Anthropic API key 替代。
- `libmagic1` 是系统依赖（python-magic MIME 检测），环境中已预装。
- 后端开发依赖（ruff, pytest, mypy）需要 `uv sync --dev --extra dev` 安装。
