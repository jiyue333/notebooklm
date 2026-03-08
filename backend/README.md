# NotebookLM Backend

按照 `backend/plan.md` 的步骤一搭建的后端基础工程。

当前范围：

- FastAPI 应用入口与健康检查
- Pydantic Settings 配置管理
- SQLAlchemy 2.0 async 会话与 Alembic 基础环境
- Redis、RocketMQ、对象存储、Exa、OpenAI-like、Telemetry 适配层骨架
- Worker 运行入口和任务处理占位

后续业务模块会在步骤 2 以后逐步补齐。
