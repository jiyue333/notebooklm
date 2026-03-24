# 内容链路重构方案

本方案围绕 summary 和 chat 链路的重构，作为全新功能，原有代码可直接删除。依次给出背景、方案要点、核心流程和索引设计等内容。

## 背景

- **AI助手目标**：支持摘要、问答、推荐等能力。

## 总体设计

### 1. Summary链路
- **质量提升**：  
    - 按文章类型提取摘要核心内容，摘要后进行二次校验。
    - 长上下文采用 map-reduce 方式处理。
- **成本优化**：  
    - 压缩代码块、长表格、图片等噪音内容。
    - 根据文本长度动态选择模型。
    - 批量摘要任务走 batch API。
    - 使用 prompt caching（稳定前缀、变化后缀）。
- **稳定性与可观测性**：  
    - 构造小型数据集持续优化 prompt，提升可复现性和观测性。

### 2. Chat助手链路
- **Query Router**：  
    - 将用户 query 分类为以下 4 种场景，并指定检索范围、输出模式和工具：
        1. 文章问答
        2. 通用问题
        3. 文章推荐
        4. notebook 检索
- **Retrieval Planner**：  
    - 按场景定制检索策略。
    - 文章场景优先 article-level recall，再 chunk-level explain。
    - notebook 场景采用 hybrid retrieval。
    - 通用问题初始不查本地，若与用户内容强相关则补查。
- **Retrieval Engine**：  
    - 建议采用 Hybrid Retrieval = dense + sparse + rerank。
- **Web Search Broker**：  
    - 分为“联网判定层”和“搜索执行层”。
    - 判定条件：query 包含“最新、现在、趋势”等关键词，notebook 内证据不足，用户问题明显超范围，或显式要求联网。
    - 输出信号：`need_web_search`，并给出原因（freshness/insufficient_local_evidence/external_fact）。
- **Answer Generator**：  
    - 拼接本地/网络证据生成答案，输入结构包括 query、场景类型、本地和网络证据、回答约束（必须引用、不能编造、无依据则说明）。
- **Citation Verifier & Trace Logger**：  
    - 校验所有引用 id 是否真实、claim 和引用是否大致对齐。
    - 记录检索 topk、rerank 分数、联网与否、答案长度、延迟、用户反馈、平均引用数、联网占比、错误/超时率等关键指标。

## 技术栈

- **编排层**：LangGraph
- **检索层**：pgvector
- **模型**：embedding、chat、rerank均已在infra具备
- **网络搜索工具**：exa & tavily
- **评估观测层**：langsmith

## 索引设计

- **article index**
    - `dense_vector`
    - 可选：为 `title` + `summary` + `tags` 建 BM25/倒排索引（非必须）
    - 暂不强制要求 sparse_vector

- **chunk index**
    - 对 chunk 做轻量级上下文增强：
        - 若 chunk 脱离周边也易理解，可直接检索；
        - 如脱离上下文则补 notebook 标题、article 标题、章节标题/heading path。
        - 遇到“指代不清”chunk，用 lite_model 额外生成 1~2 句上下文。
    - 字段包括：`raw_text`、`contextualized_text`、`dense_vector`、`sparse_vector`（dense/sparse 均基于 contextualized_text）
    - 回答引用时展示 `raw_text` 或原文 span。

## 实施要求

- 以新功能实现，原有实现可以移除。
- 输出应包括输入输出定义、流程图等文档。
- 若依赖外部功能暂不完善，如 chunk 上下文增强，应在计划中补充标注。

## 参考资料

- [LangGraph & LangSmith（使用 doc-langchain mcp 查询）](https://python.langchain.com/docs/langsmith)
- [exa API 文档](https://exa.ai/docs/reference/search-api-guide-for-coding-agents)
- [tavily Python 文档](https://docs.tavily.com/sdk/python/reference)
- [pgvector 介绍与用法1](https://docs.langchain.com/oss/python/integrations/vectorstores/pgvector)
- [pgvector 介绍与用法2](https://github.com/pgvector/pgvector)


参考计划：[plan](/Users/taless/.cursor/plans/summary_chat_pipeline_refactor_3bc3e573.plan.md)