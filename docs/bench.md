下面给你一版收敛后的结构，直接按这个去写 benchmark 设计就够了。

为了便于理解，我把整套数据都围绕同一个例子来写：

- `case_001`：一个 notebook 任务
- `art_102`：一篇 canonical article
- `af_102_pdf`：这篇文章的一个 PDF artifact
- `a2`、`a3`：ingest 后的重要 anchor
- `rec_001`：一条 recommendation 测试

------

## 1. benchmark 数据链路与规则

### 数据链路

这套 benchmark 建议按这条链来组织：

```
case -> source_artifact -> ingest_gold -> search_recall / search_slate -> summary_focus -> recommendation
```

含义是：

- `case` 定义用户到底要补什么资料
- `source_artifact` 定义系统实际 ingest 的原件
- `ingest_gold` 定义“统一阅读体验”应该长什么样
- `search_recall` 测你有没有把该找回来的东西找回来
- `search_slate` 测你最后推给用户的文章值不值
- `summary_focus` 测有没有抓住文章最该记住的核心内容
- `recommendation` 测能不能从用户导入过的全部 notebook 里联想到相关文章

### 规则

**规则 1：ingest 是主 benchmark，不是可选项。**
凡是进入 benchmark 的文章，都必须有 `artifact` 和对应的 `ingest_gold`。如果 ingest 失败，这篇文章就不能算“可用来源”。

**规则 2：search 分成两部分，必须拆开记分。**

- `search_recall`：测召回能力，尤其是多数据源、预置站点、query expansion、source routing 的效果
- `search_slate`：测最终推送给用户的内容质量

**规则 3：summary 只测“核心内容提取”，不测大而全综述。**

- 观点文：抓作者核心观点
- 新闻文：抓核心事实
- 技术文：抓“用什么方法解决什么问题”
- 报告/论文：抓核心结论和边界

**规则 4：chat 只保留你最在意的 recommendation。**
重点测 Route 3：检索范围是“用户导入的所有 notebook 的所有文章”。

**规则 5：所有表通过 3 个核心 ID 串起来。**

- `case_id`
- `canonical_article_id`
- `artifact_id`
  如果涉及定位，再加 `anchor_id`。

------

## 2. 主表

下面这 7 张表，已经够你搭第一版 benchmark。

------

### 2.1 `cases.jsonl`

作用：定义一个 notebook 任务本身。

核心字段：

- `case_id`：任务 ID
- `notebook_title`：notebook 名称
- `notebook_goal`：这个 notebook 想解决什么问题
- `user_query`：用户原始需求
- `existing_article_ids`：当前 notebook 里已有文章
- `must_cover_facets`：这次搜索必须补到哪些视角
- `evaluation_switches`：这个 case 要不要跑 ingest/search/summary/recommendation

示例：

```json
{
  "case_id": "case_001",
  "notebook_title": "企业知识管理中的 AI 助手",
  "notebook_goal": "整理 AI agent 在企业知识管理场景中的应用、局限和失败案例。",
  "user_query": "帮我补充企业知识管理里的 AI agent 失败案例、系统限制和最近一年的评测资料。",
  "existing_article_ids": ["art_001", "art_002"],
  "must_cover_facets": ["primary", "critique", "implementation", "recent"],
  "evaluation_switches": {
    "check_ingest": true,
    "check_search_recall": true,
    "check_search_slate": true,
    "check_summary_focus": true,
    "check_recommendation": true
  }
}
```

------

### 2.2 `source_artifacts.jsonl`

作用：定义系统真正 ingest 的原件。

核心字段：

- `artifact_id`：artifact ID
- `canonical_article_id`：归属哪篇 canonical article
- `source_url`：来源地址
- `artifact_type`：`html | pdf | scanned_pdf | docx`
- `source_type`：`official | paper | report | news | blog`
- `published_at`：发布时间
- `snapshot_id`：抓取快照

示例：

```json
{
  "artifact_id": "af_102_pdf",
  "canonical_article_id": "art_102",
  "source_url": "https://example.org/reports/enterprise-agent-failures-2025.pdf",
  "artifact_type": "pdf",
  "source_type": "report",
  "published_at": "2025-11-03",
  "snapshot_id": "snap_2026_03_16_001"
}
```

------

### 2.3 `ingest_gold.jsonl`

作用：定义这份 artifact 经过 ingest 之后，用户应该看到的统一阅读结果。

核心字段：

- `artifact_id`
- `ingest_route_gold`：应该走哪条 ingest 路由
- `display_title_gold`：最终显示标题
- `must_drop_regions`：必须去掉的噪声区块
- `section_tree_gold`：期望章节树
- `anchor_contract`：关键跳转锚点
- `reader_acceptance_contract`：统一阅读体验验收规则

示例：

```json
{
  "artifact_id": "af_102_pdf",
  "canonical_article_id": "art_102",
  "ingest_route_gold": "report_pdf",
  "display_title_gold": "Evaluation Report on Failure Modes of Enterprise AI Agents",
  "must_drop_regions": ["cover_watermark", "download_footer"],
  "section_tree_gold": [
    {"section_id": "s1", "title": "Executive Summary", "level": 1, "required": true},
    {"section_id": "s2", "title": "Observed Failure Modes", "level": 1, "required": true},
    {"section_id": "s3", "title": "Limitations", "level": 1, "required": true}
  ],
  "anchor_contract": [
    {"anchor_id": "a2", "jump_label": "Observed Failure Modes", "target_hint": "page 5 section heading"},
    {"anchor_id": "a3", "jump_label": "Limitations", "target_hint": "page 7 section heading"}
  ],
  "reader_acceptance_contract": {
    "must_have_title": true,
    "must_have_jumpable_toc": true,
    "max_boilerplate_ratio": 0.05,
    "must_surface_reference_zone": true
  }
}
```

------

### 2.4 `search_recall_requirements.jsonl`

作用：测召回能力，不看你最后排第几，只看 topK 里有没有覆盖“语义上必须出现的材料”。

核心字段：

- `case_id`
- `top_k_for_eval`
- `pass_rule`
- `requirements`：一个 requirement 数组，每条 requirement 描述必须召回到什么语义内容

示例：

```json
{
  "case_id": "case_001",
  "top_k_for_eval": 20,
  "pass_rule": "所有 must requirement 都满足，且 should requirement 至少满足 1 项",
  "requirements": [
    {
      "req_id": "req_primary",
      "importance": "must",
      "semantic_requirement": "结果中至少有 1 篇一手资料，明确介绍企业知识管理场景下 AI agent 的产品能力、系统设计或官方实践。",
      "acceptable_source_types": ["official", "docs", "paper"]
    },
    {
      "req_id": "req_critique",
      "importance": "must",
      "semantic_requirement": "结果中至少有 1 篇明确讨论 enterprise knowledge agent 的 failure、limitation 或 risk。",
      "acceptable_source_types": ["report", "paper", "official", "news"]
    },
    {
      "req_id": "req_recent",
      "importance": "should",
      "semantic_requirement": "结果中至少有 1 篇 12 个月内的更新、发布或新评测。",
      "acceptable_source_types": ["news", "official", "report"]
    }
  ]
}
```

------

### 2.5 `search_slate_labels.jsonl`

作用：测“这篇文章值不值得被推给用户”。

核心字段：

- `case_id`
- `canonical_article_id`
- `artifact_id`
- `gold_include_level`：`must_include | good_to_have | optional | reject`
- `gold_facets`
- `gold_novelty_to_notebook`
- `gold_ingestability`
- `label_reason`

示例：

```json
{
  "case_id": "case_001",
  "canonical_article_id": "art_102",
  "artifact_id": "af_102_pdf",
  "gold_include_level": "must_include",
  "gold_facets": ["critique", "recent", "report"],
  "gold_novelty_to_notebook": 3,
  "gold_ingestability": 2,
  "label_reason": "这是一篇专门讨论企业知识管理 agent 失败模式的报告，能补当前 notebook 缺失的 critique 与 recent 维度。"
}
```

------

### 2.6 `summary_focus_gold.jsonl`

作用：只定义“这篇文章最该提取什么”，不要求全面摘要。

核心字段：

- `canonical_article_id`
- `artifact_id`
- `article_type_gold`
- `extraction_goal_gold`
- `must_capture_points`
- `must_avoid_points`
- `supporting_anchor_ids`
- `ideal_brief_summary`

示例：

```json
{
  "canonical_article_id": "art_102",
  "artifact_id": "af_102_pdf",
  "article_type_gold": "report",
  "extraction_goal_gold": "claim_limit",
  "must_capture_points": [
    "这篇文章评估的是企业知识管理场景中的 agent 失效模式",
    "至少提到一个核心 failure mode",
    "必须提到适用边界或局限"
  ],
  "must_avoid_points": [
    "不能把它写成泛泛而谈的 AI 风险综述",
    "不能发散到文章没有讲的监管建议"
  ],
  "supporting_anchor_ids": ["a2", "a3"],
  "ideal_brief_summary": "这份报告总结了企业知识管理 agent 的常见失效模式，重点指出跨知识源检索不稳定等问题，并明确说明其结论不覆盖高监管行业。"
}
```

------

### 2.7 `recommendation_cases.jsonl`

作用：只测 Route 3 recommendation，检索范围是用户导入过的所有 notebook 的所有文章。

核心字段：

- `rec_case_id`
- `query_text`
- `seed_article_id`
- `search_space_gold`
- `expected_article_ids`
- `expected_reason_facets`
- `must_cross_notebook`

示例：

```json
{
  "rec_case_id": "rec_001",
  "query_text": "我之前在哪个 notebook 里看过类似的企业知识管理 agent 失败案例文章？",
  "seed_article_id": "art_102",
  "search_space_gold": "all_imported_notebooks",
  "expected_article_ids": ["art_031", "art_044"],
  "expected_reason_facets": ["topic", "failure_mode", "enterprise_setting"],
  "must_cross_notebook": true
}
```

------

## 3. 可选表

主表已经够你启动第一版。下面两张是增强项。

### `ingest_deep_audit.jsonl`

用途：只给高难文档做细粒度 parse 审计。
适用场景：双栏 PDF、复杂表格、扫描件、OCR 混乱页。
典型字段：`artifact_id`、`block_id`、`page_no`、`block_type`、`order_index`、`bbox_hint`。

### `search_provider_snapshots.jsonl`

用途：保存每次 benchmark run 的 provider 原始返回，方便排查召回问题。
典型字段：`run_id`、`provider`、`query`、`returned_urls`、`latency_ms`、`raw_snippets`。

------

## 4. 高匹配数据集和参考网站

### 最匹配的数据集

**OmniDocBench**
最适合放在 ingest 主链路里。它面向真实场景文档解析，覆盖 1,355 个 PDF 页面、9 类文档、4 类布局、3 种语言，并提供 block、span、OCR、表格、公式和阅读顺序标注，很适合拿来校验统一阅读体验里的章节、顺序、表格和锚点能力。([GitHub](https://github.com/opendatalab/OmniDocBench?utm_source=chatgpt.com))

**DocLayNet**
适合做版面基础能力回归。它提供 80,863 个页面、6 类文档、11 类布局标签的人标页面级布局真值，适合检验标题、正文、表格、图注这类基础版面结构。([Hugging Face](https://huggingface.co/datasets/docling-project/DocLayNet?utm_source=chatgpt.com))

**WebMainBench**
如果你非常在意网页的正文抽取，这是最贴近的。它是专门做 end-to-end web main content extraction 的 benchmark，适合测 HTML 页面的正文保留、噪声去除和结构抽取。([GitHub](https://github.com/opendatalab/WebMainBench/?utm_source=chatgpt.com))

**BEIR**
适合做 search 的“基本盘”检查。它是 heterogeneous IR benchmark，覆盖多种检索任务，并提供统一评测框架，适合先验证你的多源召回和融合检索是否稳定。([GitHub](https://github.com/beir-cellar/beir?utm_source=chatgpt.com))

**BRIGHT**
适合测你说的那种“语义要求型召回”。它是 reasoning-intensive retrieval benchmark，包含 1,385 条真实世界查询，专门考察仅靠关键词不够、需要较强语义理解和推理的检索。([Bright Benchmark](https://brightbenchmark.github.io/?utm_source=chatgpt.com))

**MIND**
适合做 recommendation/article memory。它是新闻推荐数据集，包含约 16 万篇英文新闻、100 万用户和超过 1,500 万次 impression log，很适合参考它的 article-level recommendation 组织方式来设计你的 Route 3。([Microsoft Learn](https://learn.microsoft.com/zh-cn/azure/open-datasets/dataset-microsoft-news?utm_source=chatgpt.com))

### 参考网站

**Hugging Face Datasets**
最适合找数据和快速试数据。官方文档支持一行加载、流式处理和在线查看器，适合你快速筛 benchmark 候选集。([Hugging Face](https://huggingface.co/docs/datasets/index?utm_source=chatgpt.com))

**OpenDataLab**
如果你重点做文档解析和网页正文抽取，这个站很值得常看。它是开放数据集平台，站内可以直接找到 OmniDocBench 这类文档解析数据。([OpenDataLab](https://opendatalab.com/?utm_source=chatgpt.com))

**OpenAlex**
如果你后面会做论文、报告、技术资料的 seed 扩展和人工补标，这是很实用的源站。官方开发文档说明它提供开放的学术 works、authors、institutions 等目录，以及 API 和数据快照。([OpenAlex Developers](https://developers.openalex.org/?utm_source=chatgpt.com))

------

## 5. 最后给你的落地建议

第一版先只做这 5 件事：

- `cases.jsonl`
- `source_artifacts.jsonl`
- `ingest_gold.jsonl`
- `search_recall_requirements.jsonl`
- `search_slate_labels.jsonl`

等 ingest 和 search 跑顺了，再补：

- `summary_focus_gold.jsonl`
- `recommendation_cases.jsonl`

这样最符合你现在“工程优先、统一阅读体验优先”的目标。

下一步最合适的是，我直接把这 7 张表再压成一版“最小可用字段集”，每张表只保留 5 到 7 个字段，适合你开始手工标第一批 case。