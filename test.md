按这个顺序用就行。

先确保基础环境已经起好：
- PostgreSQL / Redis / MinIO / RocketMQ：用根目录的 [docker-compose.yml](/Users/taless/Code/notebooklm/docker-compose.yml)
- 后端用 `conda notebooklm`
- 后端环境文件参考 [backend/.env.example](/Users/taless/Code/notebooklm/backend/.env.example)

**1. 启基础设施**
```bash
cd /Users/taless/Code/notebooklm
docker compose up -d postgres redis minio rocketmq-namesrv rocketmq-broker
```

如果你还没迁移数据库，再跑：
```bash
cd /Users/taless/Code/notebooklm/backend
conda run -n notebooklm alembic upgrade head
``

**2. 启后端**
如果你的启动脚本还在，就用你自己的；否则最直接是：
```bash
cd /Users/taless/Code/notebooklm/backend
conda run -n notebooklm uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

**3. 写入 HTTP demo 数据**
这个脚本只负责造场景数据，不发请求：
```bash
cd /Users/taless/Code/notebooklm
conda run -n notebooklm python backend/scripts/seed_http_demo_data.py
```

它会输出一份 JSON manifest，里面是固定用户、notebook、article、search session 的 ID。  
这批 demo 账号是：
- `demo-http / demo-secret`
- `demo-nokey / demo-nokey-secret`

**4. 安装 Bruno CLI**
如果你本机还没装：
```bash
npm install -g @usebruno/cli
```

**5. 跑本地可回放请求**
我写的总入口脚本是 [run-http-scenarios.sh](/Users/taless/Code/notebooklm/scripts/run-http-scenarios.sh)。

先只 seed：
```bash
cd /Users/taless/Code/notebooklm
./scripts/run-http-scenarios.sh --seed-only
```

跑本地场景：
```bash
cd /Users/taless/Code/notebooklm
./scripts/run-http-scenarios.sh
```

运行结果会写到：
- [results/](/Users/taless/Code/notebooklm/api-collections/bruno/results)

**6. 跑需要真实 Provider 的请求**
如果你已经在设置里配好了真实 Exa 和 LLM，再加 `--live`：
```bash
cd /Users/taless/Code/notebooklm
./scripts/run-http-scenarios.sh --live
```

这会额外跑：
- [60-sources-live](/Users/taless/Code/notebooklm/api-collections/bruno/60-sources-live)
- [80-ai-live](/Users/taless/Code/notebooklm/api-collections/bruno/80-ai-live)

**7. 如果你想手动用 Bruno 打开**
collection 目录在：
- [bruno/](/Users/taless/Code/notebooklm/api-collections/bruno)

环境文件在：
- [Local.bru](/Users/taless/Code/notebooklm/api-collections/bruno/environments/Local.bru)

你可以直接用 Bruno Desktop 打开这个目录，然后按文件夹跑。

**你最常用的两条命令**
```bash
cd /Users/taless/Code/notebooklm
conda run -n notebooklm python backend/scripts/seed_http_demo_data.py
./scripts/run-http-scenarios.sh
```

如果你要，我下一步可以直接帮你整理成一份“从 0 到跑通”的最短 checklist，包括 `.env` 里 MinIO 和 LangSmith 该怎么填。