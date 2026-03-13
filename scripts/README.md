# =============== scripts 总览 ===============

仓库当前只保留四个统一入口脚本：

- `./scripts/dev.sh`
- `./scripts/prod.sh`
- `./scripts/benchmark.sh`
- `./scripts/online.sh`

所有脚本都以仓库根目录为执行起点。`dev.sh`、`prod.sh`、`online.sh` 默认要求根目录存在 `.env`。

# =============== dev.sh ===============

作用：

- 启动本地开发模式的 `backend`、`worker`、`scheduler`、`frontend`
- 管理 PID、状态和日志查看

前置依赖：

- 根目录 `.env`
- `conda`，并存在 `notebooklm` 环境
- `frontend/node_modules`

常用命令：

```bash
./scripts/dev.sh start
./scripts/dev.sh status
./scripts/dev.sh logs all
./scripts/dev.sh logs backend
./scripts/dev.sh restart
./scripts/dev.sh stop
```

输入输出路径：

- 读取：根目录 `.env`
- 写入：`logs/*.log`
- 写入：`logs/*.pid`

env 关系：

- 只检查根目录 `.env`
- 应用运行时也统一从根目录 `.env` 读配置

# =============== prod.sh ===============

作用：

- 启动或停止生产模式的 `api`、`worker`、`scheduler`
- 统一管理 `run/*.pid` 和 `logs/*.log`

前置依赖：

- 根目录 `.env`
- 根目录 `.venv`

常用命令：

```bash
./scripts/prod.sh start all
./scripts/prod.sh start api
./scripts/prod.sh start worker
./scripts/prod.sh start scheduler
./scripts/prod.sh status
./scripts/prod.sh stop all
```

输入输出路径：

- 读取：根目录 `.env`
- 写入：`run/*.pid`
- 写入：`logs/backend.log`
- 写入：`logs/worker.log`
- 写入：`logs/scheduler.log`

env 关系：

- 只检查根目录 `.env`
- 应用进程统一从根目录 `.env` 读配置

# =============== benchmark.sh ===============

作用：

- 统一构造离线 dataset
- 统一运行 Search / Ingest / Summary / RAG benchmark
- 统一触发 baseline 门禁
- 统一运行 `k6` 压测入口

前置依赖：

- `python3` 或根目录 `.venv/bin/python`
- `backend/evals` 目录中的 `cases / datasets / predictions / baselines`
- 运行 `load-test` 时需要 `k6`

常用命令：

```bash
./scripts/benchmark.sh build-datasets all
./scripts/benchmark.sh run all
./scripts/benchmark.sh run ingest stable --with-bert-score
./scripts/benchmark.sh gate all
./scripts/benchmark.sh run rag stable --with-ragas --ragas-model gpt-4o-mini
./scripts/benchmark.sh load-test search
./scripts/benchmark.sh load-test chat --vus 5 --duration 1m
./scripts/benchmark.sh show reports
```

输入输出路径：

- 输入：`backend/evals/cases/*`
- 输出：`backend/evals/datasets/*`
- 输入：`backend/evals/reports/predictions/*`
- 输入：`backend/evals/reports/baselines/*`
- 输出：`backend/evals/reports/*.json`
- 输出：`backend/evals/reports/*.md`
- 输出：`backend/evals/reports/prometheus/*.prom`

env 关系：

- `run` 和 `gate` 默认不依赖根目录 `.env`
- `load-test` 会尝试加载根目录 `.env`
- `load-test` 优先读取：
  - `NOTEBOOKLM_BASE_URL`
  - `NOTEBOOKLM_API_TOKEN`
- 某些 k6 场景还需要你额外提供：
  - `NOTEBOOK_ID`
  - `ARTICLE_ID`
  - `SEARCH_SESSION_ID`
  - `SEARCH_RESULT_IDS`

补充说明：

- 默认 profile 是 `stable`
- `gate` 会自动追加 `--fail-on-regression`
- `demo` profile 主要用于通路验证，`stable` profile 用于回归和门禁

# =============== online.sh ===============

作用：

- 统一运行在线造数脚本
- 统一查看 Search 采样评审产物
- 手动触发或查看 Redis 巡检结果

前置依赖：

- 根目录 `.env`
- `NOTEBOOKLM_BASE_URL`
- `NOTEBOOKLM_API_TOKEN`
- `python3` 或根目录 `.venv/bin/python`

常用命令：

```bash
./scripts/online.sh seed notebooks --count 3
./scripts/online.sh seed search
./scripts/online.sh seed import
./scripts/online.sh seed chat
./scripts/online.sh seed summary
./scripts/online.sh seed all --count 3
./scripts/online.sh inspect redis
./scripts/online.sh show search-samples
./scripts/online.sh show redis-report
```

输入输出路径：

- 输入：根目录 `.env`
- 读取：`backend/evals/online_seed/*`
- 输出：`backend/evals/reports/search_samples/*`
- 输出：`backend/evals/reports/search_bad_cases/*`
- 输出：`backend/evals/reports/ai_reviews/*`
- 输出：`backend/evals/reports/ai_bad_cases/*`
- 输出：`backend/evals/reports/redis/*`

env 关系：

- 会主动加载根目录 `.env`
- `NOTEBOOKLM_BASE_URL` 和 `NOTEBOOKLM_API_TOKEN` 供在线造数脚本访问 API

补充说明：

- `search / import / chat / summary` 都支持不传 `--input` 的 one-click 模式
- 也可以继续传 `--input` 使用自定义 JSONL
- `seed all` 会先创建 notebook，再串行执行 search / import / chat / summary
