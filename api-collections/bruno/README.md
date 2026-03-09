# NotebookLM HTTP Scenarios

这套 collection 用于对正在运行的后端发送真实 HTTP 请求，不走 `pytest`。

## 目录说明

- `00-system` 到 `70-ai-local`：纯本地可回放场景
- `60-sources-live`、`80-ai-live`：需要你自己先在设置中配置真实 Exa / LLM
- `99-cleanup`：登出收尾

## Git 忽略

- `results/`：Bruno CLI 生成的运行报告
- 其余 `.bru`、`bruno.json`、`environments/Local.bru`、样例文件都应该纳入版本控制

## 先决条件

1. 后端服务已启动在 `http://127.0.0.1:8080`
2. 已执行 `backend/scripts/seed_http_demo_data.py`
3. Bruno CLI 已安装：`npm install -g @usebruno/cli`

## 运行

```bash
cd api-collections/bruno
bru run 00-system 10-auth 20-notebooks 30-notes 40-settings 50-sources-local 70-ai-local 99-cleanup --env-file environments/Local.bru --reporter-json results/local.json
```

如果要跑需要真实 Provider 的请求，再追加：

```bash
bru run 60-sources-live 80-ai-live --env-file environments/Local.bru --reporter-json results/live.json
```
