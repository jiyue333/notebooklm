# Evals — Pipeline 基准评测模块

本模块为 NotebookLM 后端的离线评测框架，覆盖 **search / ingest / summary / chat** 四条核心
pipeline。每次运行会将结果写入本地报告文件，可选同步至 LangSmith 以进行跨版本对比。

---

## 目录结构

```
evals/
├── run.py             # 主入口，CLI + 评测调度
├── judges.py          # 各 pipeline 的本地评分函数
├── reporters.py       # 生成 report.json / report.md / report.html
├── langsmith_sync.py  # LangSmith dataset & experiment 同步（可选）
├── cases/             # 评测用例（JSONL 格式）
│   ├── search/
│   │   └── smoke.jsonl
│   ├── ingest/
│   │   └── smoke.jsonl
│   ├── summary/
│   │   └── smoke.jsonl
│   └── chat/
│       └── smoke.jsonl
└── runs/              # 运行产物（git-ignored）
    └── <bench_run_id>/
        ├── report.json
        ├── report.md
        └── report.html
```

---

## 快速开始

> **前提**：基础设施（DB、Redis、Kafka）和 Dev 服务均已启动，参见根目录 `AGENTS.md`。

```bash
# 在 backend/ 目录下执行
cd backend

# 运行 search pipeline 的 smoke 评测
.venv/bin/python -m evals.run search smoke

# 运行 ingest pipeline 的 stable 评测
.venv/bin/python -m evals.run ingest stable

# 一次运行全部四条 pipeline
.venv/bin/python -m evals.run all smoke
```

完整帮助：

```bash
.venv/bin/python -m evals.run --help
```

---

## Pipeline 说明

| pipeline  | 评测内容                         | 主要评分维度                                     |
|-----------|----------------------------------|--------------------------------------------------|
| `search`  | Agent 网络搜索结果质量           | 相关性、权威性、结果数量、required_domains 命中  |
| `ingest`  | 文档解析、分块与向量化入库       | Markdown 还原质量、分块数量、分块上下文完整性    |
| `summary` | 文章摘要生成质量                 | 覆盖度、准确性、长度合理性                       |
| `chat`    | Notebook 问答（grounded chat）   | 事实准确性、引用对应、回答完整性                 |

---

## Profile（评测档位）

Profile 决定使用哪份用例文件（`cases/<pipeline>/<profile>.jsonl`）以及默认重复执行次数。

| profile  | 默认重复次数 / case | 适用场景                          |
|----------|---------------------|-----------------------------------|
| `smoke`  | 5                   | PR 快速回归，要求 ≥ 5 条用例      |
| `stable` | 3                   | 分支稳定性验证                    |
| `full`   | 1                   | 发布前完整基准，用例覆盖最广      |

可以在 `cases/<pipeline>/` 下新建任意名称的 `.jsonl` 文件来扩展自定义档位。

---

## 环境变量

| 变量                  | 说明                                                       | 示例                               |
|-----------------------|------------------------------------------------------------|------------------------------------|
| `EVAL_CASE_IDS`       | 逗号分隔的 `case_id` 白名单，只运行指定用例               | `EVAL_CASE_IDS=s01,s03`            |
| `EVAL_MAX_CASES`      | 最多执行前 N 条用例（整数）                                | `EVAL_MAX_CASES=2`                 |
| `EVAL_REPEAT_OVERRIDE`| 覆盖每条用例的重复次数（整数），优先级高于 profile 默认值  | `EVAL_REPEAT_OVERRIDE=1`           |

示例：只跑前 2 条用例、每条执行 1 次：

```bash
EVAL_MAX_CASES=2 EVAL_REPEAT_OVERRIDE=1 .venv/bin/python -m evals.run search smoke
```

---

## 用例文件格式（JSONL）

每行一个 JSON 对象，代表一条独立的评测用例。

### search

```jsonc
{
  "case_id": "search_smoke_001",          // 唯一 ID，不可重复
  "query": "LangChain structured output", // 搜索查询词
  "mode": "fast",                         // 搜索模式："fast" | "auto"
  "max_results": 8,                       // 期望最多返回结果数
  "expected": {
    "min_results": 4,                     // 最少有效结果数
    "target_results": 6,                  // 期望结果数
    "required_domains": ["langchain.com"],// 必须出现的域名
    "pass_threshold": 0.62                // 通过分数线（0-1）
  },
  "rubric": { "focus": ["relevance", "authority"], "strict": false },
  "evidence": ["LangChain docs"],         // 预期来源说明（仅供人工参考）
  "tags": ["search", "smoke"]
}
```

### ingest

```jsonc
{
  "case_id": "ingest_smoke_001_html_structure",
  "artifact_type": "html",               // "html" | "pasted_text" | "url" | "unsupported_binary"
  "title": "Ingest HTML structure",
  "content": "<html>...</html>",         // 输入内容（url 类型填 URL 字符串）
  "expected": {
    "min_chunks": 1,                     // 最少分块数
    "min_chars": 60,                     // Markdown 最少字符数
    "expect_failure": false,             // 是否期望失败（用于负向用例）
    "error_tags": [],                    // 期望错误标签（expect_failure=true 时使用）
    "pass_threshold": 0.55
  },
  "rubric": { "require_heading": true }, // 是否要求输出包含标题
  "evidence": ["heading fidelity"],
  "tags": ["ingest", "smoke", "html"]
}
```

### summary / chat

字段结构与上述类似，具体参见 `cases/summary/smoke.jsonl` 和 `cases/chat/smoke.jsonl`。

---

## 报告输出

每次运行在 `runs/<bench_run_id>/` 下生成三份文件：

| 文件           | 说明                                               |
|----------------|----------------------------------------------------|
| `report.json`  | 完整结构化数据，包含所有用例结果、评分、延迟分布   |
| `report.md`    | Markdown 摘要，包含汇总指标和各用例结果表格        |
| `report.html`  | 带样式的 HTML 报告，方便浏览器直接查看             |

`bench_run_id` 格式：`<pipeline>-<profile>-<YYYYMMDDHHmmss>`，例如：
`search-smoke-20260329083457`

---

## 评分机制

评分由 `judges.py` 中的本地无 LLM 评分函数完成，不依赖外部 AI 服务，确保可重复性。

| pipeline  | 核心子评分（subscores）                                                   |
|-----------|---------------------------------------------------------------------------|
| `search`  | relevance · authority · result_count · domain_coverage · content_quality  |
| `ingest`  | markdown_length · chunk_count · chunk_context_integrity · error_tag_match |
| `summary` | coverage · accuracy · length_ratio                                        |
| `chat`    | factual_accuracy · citation_match · completeness                          |

所有子评分归一化到 `[0, 1]`，加权平均后与 `pass_threshold` 比较判断是否通过。

---

## LangSmith 集成（可选）

配置以下环境变量后，每次运行会自动同步 dataset 和 experiment 至 LangSmith：

```bash
LANGSMITH_API_KEY=ls__...
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_ENABLED=true
# 可选
LANGSMITH_WORKSPACE_ID=<workspace-id>
```

- 每次运行创建一个新的 experiment project，命名为 `notebooklm-eval-<bench_run_id>`
- 自动查找同 pipeline + profile 的上一次运行作为基线（baseline）进行对比
- 每条用例记录一个 `lite_model_judge` feedback 及各子评分

未配置时评测照常运行，仅跳过 LangSmith 同步。

---

## 新增用例

1. 在对应的 `cases/<pipeline>/<profile>.jsonl` 文件末尾追加一行 JSON
2. 确保 `case_id` 全文件唯一
3. `smoke` 档位要求 **至少 5 条**用例
4. 运行一次评测验证用例可正常执行

```bash
# 验证新用例
EVAL_CASE_IDS=<your_new_case_id> .venv/bin/python -m evals.run <pipeline> smoke
```
