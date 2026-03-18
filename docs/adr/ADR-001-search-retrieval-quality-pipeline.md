# ADR-001: Search 链路

状态：Proposal  
日期：2026-03-15

# 一、Search 链路

## 1. 核心目标

Search 这条链路的目标，不是“找到最多链接”，而是：

**给用户一组值得导入 notebook 的候选 article slate。**

这里我会把目标拆成 4 个字：

- **准**：和任务真正相关
- **稳**：来源可信、质量高
- **广**：覆盖视角，不是一堆近重复结果
- **可导入**：后续 ingest 能吃得干净  ，适合继续 summary / chat

也就是说，Search 优化目标不是传统 search engine 的 CTR，而是 **import value**。

------

## 2. 难点挑战

### 难点 1：研究任务不是单 query

用户输入“帮我研究 xxx”时，本质上不是一个检索词，而是一个**任务图**。
它通常同时包含：

- overview 需求
- primary source 需求
- recent update 需求
- opposite / critical view 需求
- implementation / case study 需求

如果只跑一个 query，再 rerank，最后会得到一堆“看起来都像同一类文章”的结果。

### 难点 2：高质量 ≠ 高相关

很多结果会“语义相关”，但对研究没价值。
例如：

- SEO 文章
- 聚合转载
- 二手解读
- 没有作者/日期/引用的内容
- 标题匹配但正文空洞

### 难点 3：notebook 是 topic 容器

用户不是在“全局”搜索，而是在往某个 notebook 里加砖。
所以搜索结果不仅要相关，还要考虑：

- 和 notebook 已有内容是否重复
- 是否补齐 notebook 当前缺的视角
- 是否应该优先推荐 primary source / survey / benchmark / critique

### 难点 4：不同来源需要不同召回策略

网页、论文、PDF、官方报告，最优召回路径不一样。
我不会用“一把梭 web search”解决全部问题。

------

## 3. 我会优先考虑的方案 idea

### Idea A：把 Search 变成“query lattice”，不是单 query

我会把一个用户输入拆成一组查询家族，而不是一个 query。

例如用户输入：
“研究一下 AI agent 在企业知识管理里的应用和局限”

我会自动生成至少 6 类查询：

1. **overview**：AI agent enterprise knowledge management overview
2. **recent**：latest / 2025 / 2026 updates
3. **primary source**：官方产品文档、论文、技术报告、benchmark
4. **contrarian**：limitations / failure / risks / evaluation
5. **implementation**：architecture / case study / deployment
6. **adjacent terminology**：enterprise search / RAG / knowledge assistant / agentic retrieval

这样最终结果不是“Top 20”，而是一个**覆盖式 slate**。

### Idea B：维护 domain pack，但把它当 prior，不当 hard filter

我会做一层“高质量来源包”：

- 学术包：arXiv、OpenReview、ACL Anthology、期刊站点、实验室/高校
- 医学包：PubMed/PMC、NIH、WHO、FDA、指南站点
- 政策包：政府、标准组织、国际组织、研究机构
- 工程包：官方 docs、RFC、厂商 engineering blog、benchmark 项目页

但这些 pack 我不会写成死白名单。
它更像一个 **authority prior**，影响分数，不是硬拦截。

### Idea C：Search 结果要带“为什么推荐”

搜索结果展示不该只有 title / source / url / snippet。
我会给每张卡片加一个 `why_selected`：

- 这篇是 primary source
- 这篇补齐了“风险/局限”视角
- 这篇和 notebook 已有某文相似但更新
- 这篇预计解析质量高
- 这篇是领域高权威来源

这样用户导入决策会快很多。

### Idea D：把 ingestability 提前纳入排序

这是很多系统忽略的点。
我会在 Search 阶段就预测：

- 是 PDF 吗
- 是扫描件吗
- HTML 主体是否清晰
- 有无作者/日期/结构
- 是否容易抽取 toc / 正文

然后把 `ingestability_score` 纳入排序。
因为你不是在做“搜索引擎”，你是在做“研究工作台”。

### Idea E：deep 模式不只是多搜一点，而是换策略

我会做至少两档：

- **Fast**：召回 30 左右，深抓取 10–12，最终给 10–12 个候选
- **Deep**：召回 50–70，深抓取 20–25，做 query family 覆盖、来源多样化、seed expansion，最终保留 18–20 个候选

Deep 模式不是单纯把 `top_k` 从 10 调到 50。
它应该启用更重的 query expansion、相似文献扩展、更多 authority/diversity 约束。Exa 这类接口既能返回 contents/highlights，也能做 similar-links；Perplexity 则适合做带 domain/date 约束的 web-grounded 搜索。([Exa](https://exa.ai/docs/reference/search))

------

## 4. 我会怎么设计这条链路

## 4.1 输入

Search 的输入我会定义成：

```text
user_query
notebook_context {
  notebook_title
  notebook_description
  existing_articles[]
  existing_tags[]
}
search_mode = fast | deep
user_preferences {
  recency_bias
  source_type_preference
  language
}
```

------

## 4.2 阶段 A：任务理解（Task Parsing）

先把自然语言输入转成 `TaskSpec`：

```text
TaskSpec {
  intent: explore | compare | answer | literature_review | find_primary_source
  domain: cs | biomed | policy | finance | general | ...
  time_sensitivity: high | medium | low
  expected_source_mix: web / paper / pdf / official-doc
  primary_source_preference: high | medium | low
  coverage_facets: [overview, recent, primary, critique, implementation]
  notebook_novelty_requirement: high | medium | low
}
```

这里最关键的是两件事：

### 判断 1：是否强时效

如果是强时效任务，就提高：

- recent query 的比重
- date filter
- last-updated signals
- 新闻/官方更新源的权重

### 判断 2：是否强 primary-source 偏好

如果用户像在做研究，不像在做泛搜，我会提高：

- 论文、官方报告、标准文档
- 作者原文 / 实验室 / 官方博客
- 有 DOI / PMID / arXiv id 的内容

------

## 4.3 阶段 B：生成 query lattice

我不会直接 query rewrite 一次，而是生成一个 **查询格子**：

1. **Canonical Query**：贴近用户原意
2. **Terminology Expansion**：同义术语、上下位词、领域词
3. **Primary Query**：偏官方、论文、报告
4. **Recent Query**：偏更新、变化、最新
5. **Critical Query**：偏 limitation / challenge / failure
6. **Implementation Query**：偏架构、案例、部署
7. **Notebook-gap Query**：专门补 notebook 已有内容缺口

这一步最好和 notebook 已有文章做联动。
比如 notebook 已经有很多“overview”，那 Search 就应该更主动找：

- 方法论文
- benchmark
- 反例 / 局限
- 更新版 / 替代方案

------

## 4.4 阶段 C：多源召回（Multi-Source Recall）

我会用 **source-type router**：

### 路由 1：通用 web

适合：

- 概览
- 官方产品页
- 研究机构博客
- 新近信息
- 非学术 PDF / 报告

### 路由 2：学术 API

适合：

- 论文
- preprint
- biomedical literature
- citation graph 扩展

### 路由 3：seed expansion

当已经命中一篇强 seed 时，继续找：

- similar pages
- recommended papers
- references / cited-by
- version / preprint / supplement

Crossref 的 metadata / relationships 很适合做版本、preprint、supplement 这类归一；Semantic Scholar 的 recommendations 很适合从一个 seed paper 往外扩。([www.crossref.org](https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/relationships/))

------

## 4.5 阶段 D：归一化、去重、实体化

这一层非常关键，因为同一篇内容可能有：

- HTML 页面
- PDF 页面
- DOI landing page
- arXiv abs + pdf
- 镜像站
- 转发页

我会做两层 dedup：

### 第一层：硬 ID 去重

按这些字段合并：

- DOI
- PMID / PMCID
- arXiv id
- canonical URL

### 第二层：软相似去重

按这些信号合并：

- title normalization
- author overlap
- publish date
- url pattern
- semantic similarity

最终归一成 `CanonicalArticleCandidate`，并保留多个 artifact variant。

------

## 4.6 阶段 E：候选增强（Enrichment）

对 top N 候选做补全：

- title
- source / publisher / domain
- authors
- published_at / updated_at
- doc_type
- abstract / snippet / highlights
- DOI / arXiv / PMID
- 是否 primary source
- 是否已有 notebook duplicates
- parseability / ingestability 预测
- authority / credibility signals

这一步不是所有结果都重做。
我的策略是：

- 先对全部召回做轻量打分
- 只对 top 30 左右做 enrichment
- 只对 top 10–20 做深抓取 / full content preview

------

## 4.7 阶段 F：综合打分

我会显式定义一个多目标分数，而不是只靠 reranker 黑盒。

### 我会用的分数维度

```text
final_score =
  0.32 * topical_relevance
+ 0.16 * authority
+ 0.12 * credibility
+ 0.10 * professional_depth
+ 0.10 * recency_fit
+ 0.08 * novelty_to_notebook
+ 0.07 * ingestability
+ 0.05 * diversity_gain
```

### 每一项怎么想

- `topical_relevance`：语义相关 + 关键词命中 + highlight 支持
- `authority`：来源级别（官方/高校/期刊/实验室/权威媒体）
- `credibility`：作者、日期、引用、结构完整性、是否像原始内容
- `professional_depth`：内容不是“泛科普”，而是真有信息密度
- `recency_fit`：不是越新越好，而是和任务时间需求匹配
- `novelty_to_notebook`：和当前 notebook 不是近重复
- `ingestability`：后续能否被高质量 ingest
- `diversity_gain`：加入这篇后是否补齐视角

------

## 4.8 阶段 G：最终 slate 组装

最终不是简单按 score 排序，而是做 **coverage-aware slate building**。

我会按 bucket 选：

- 2–4 篇 overview / survey
- 4–6 篇 primary / official / paper
- 2–4 篇 recent update
- 2–3 篇 critique / limitation
- 2–3 篇 implementation / case study

然后做 notebook-aware 去重：

- 若和 notebook 已有内容太像，则降权
- 若能补空白维度，则升权

这一步很像“研究资料包编排”，不是普通搜索排序。

------

## 4.9 阶段 H：最终输出

我会把一条搜索结果输出成这种卡片：

```text
SearchCard {
  title
  source_name
  source_type_badge
  published_at
  authority_badge
  why_selected
  highlights[1..2]
  url
  artifact_type
  ingestability_hint
  similar_to_existing_article?
}
```

UI 上我会强制展示：

- 标题
- 来源
- 1 句 why selected
- 1–2 条 highlight
- 来源链接
- 类型 badge（paper / report / official / blog / pdf）
- 导入建议（推荐 / 可选 / 重复风险）

------

## 4.10 fallback 设计

### 结果太少

自动放宽：

- domain prior
- 同义词范围
- 时间过滤
- source mix 限制

### 结果太泛

自动收紧：

- 提高 primary source 权重
- 增加 domain filter
- 强化 notebook context
- 增加 critical / implementation query

### 结果太重复

触发 diversity expansion：

- similar paper expansion
- reference/citation expansion
- query family 重新配额

### 某个引擎异常

降级成：

- web 搜索 + 学术 API 双路中剩余路
- 先展示已有 metadata，延迟补完 highlights

------

## 5. 方案比较与取舍

### Search 方案对比

| 方案                                            | 优点                                 | 缺点                                    | 适用场景                 | 是否采用 |
| ----------------------------------------------- | ------------------------------------ | --------------------------------------- | ------------------------ | -------- |
| 单引擎搜索 + rerank                             | 简单，容易上线                       | 结果同质化，学术与官方源弱，coverage 差 | 轻量问答                 | 否       |
| 多源混合召回 + 显式打分 + slate diversification | 可控、覆盖好、适合 notebook 研究场景 | 工程复杂度高                            | 研究助手主链路           | **是**   |
| 纯 agentic deep research                        | 质量上限高，适合复杂任务             | 慢、重、结果可控性差                    | deep mode / 离线 teacher | 部分采用 |

### Search 技术选型（我会这样配）

| 模块            | 首选                         | 备选/补充           | 角色                            |
| --------------- | ---------------------------- | ------------------- | ------------------------------- |
| 通用 web recall | Exa                          | Perplexity Sonar    | 网页 / PDF / 高亮预读           |
| 时间敏感检索    | Perplexity Sonar             | Exa + recency logic | date/domain 受控召回            |
| 学术 recall     | arXiv / PubMed / Crossref    | Semantic Scholar    | 论文、元数据、关系              |
| seed expansion  | Exa similar / citation graph | 手工 query 扩展     | 从强 seed 向外扩                |
| rerank          | cross-encoder + LLM judge    | 规则分融合          | relevance / authority / quality |
| slate builder   | 自定义 diversity selector    | MMR/xQuAD 风格      | 控 coverage                     |

之所以这样配，是因为 Exa 能直接返回 contents / highlights，Perplexity Sonar 支持 domain/date filters；arXiv、PubMed、Crossref 都有官方接口；Crossref 能提供关系型 scholarly metadata，适合做 canonicalization。([Exa](https://exa.ai/docs/reference/search))

------

## 6. 我会怎么评估 Search 做得好不好

## 6.1 线上埋点

Search 这条链路我会把线上观测改成“系统健康 + 质量 proxy”优先，不再把 Import Rate / Click-through 这类强依赖真实用户规模的指标放在第一层。均值可以留着参考，但真正盯盘的是 p95 / p99，因为尾延迟更容易暴露 saturation；Google SRE 也明确把高分位响应时间当作更早的拥塞信号。 ([Google SRE][1])

我会保留这些日志点，但目的从“分析用户行为”改成“还原链路耗时和失败位置”：

- `search.task_parsed`
- `search.query_family_generated`
- `search.recall_started`
- `search.recall_done`（按 engine / source_type / query_family 统计）
- `search.canonicalized`
- `search.enrichment_started`
- `search.enrichment_done`
- `search.rerank_done`
- `search.slate_served`
- `search.fallback_triggered`

### 我真正关心的线上指标

- **Search E2E p50 / p95 / p99**
- **Recall fan-out p50 / p95**（按 web / paper / official source 分开看）
- **Partial failure rate**：多引擎里只成功一部分的比例
- **Enrichment timeout rate**
- **Canonicalization / dedup hit rate**
- **Deep→Fast fallback rate**
- **Empty slate / low-confidence slate rate**
- **Authority proxy@10**：Top10 结果里高权威来源占比
- **Diversity proxy@10**：source type / facet entropy
- **Notebook novelty proxy@10**：与当前 notebook 已有文章的平均相似度

------

## 6.2 离线 benchmark

实验项目里，Search 的主战场应该是离线 benchmark，不是线上行为转化。这个 benchmark 我会做成**任务级 benchmark**，不是 query-document benchmark；设计思路上接近 BEIR 这种 heterogeneous retrieval benchmark：任务要跨领域、跨 source type，同时把“效果”和“计算代价”一起看，因为 BEIR 也显示 re-ranking / late-interaction 往往更强，但计算成本更高。 ([arXiv][2])

### 数据集怎么建

从真实 notebook 创建流程中抽样，构造成：

- 用户任务
- notebook 背景
- 专家标注的“高价值候选集合”
- 同时采一些 hard negatives

### 标注维度

每个候选标：

- **relevance**（与任务/查询的相关程度）
- **authority**（来源权威性）
- **credibility**（可信度）
- **novelty to notebook**（相对当前 notebook 的新颖性）
- **coverage facet**（覆盖的检索面/维度）
- **ingestability**（可摄入性：能否被系统解析与使用）

### 离线指标

- **nDCG@10**（前 10 条 prediction 中，按位置折损后的「相关度」综合得分；越相关、越靠前，得分越高）
- **Recall@20**（前 20 条 prediction 中，标注为「好结果」的数量 ÷ 该任务全部好结果数量）
- **coverage@10**（前 10 条在主题/来源类型等维度上的覆盖情况，或多样性的一个度量）
- **authority-weighted nDCG**（前 10 条在加入「来源权威性」权重后的排序综合得分）
- **notebook-novelty@10**（前 10 条 prediction 中，相对当前 notebook 有新内容的结果所占比例）
- **parse-success@10**（前 10 条 prediction 中，能成功解析为可用卡片的结果所占比例）
- **latency / quality frontier**（同一批任务下，不同模式对应的「效果–耗时」点连成的曲线）
- **fallback-adjusted success rate**（触发降级的任务中，最终仍产出可用结果的任务所占比例）

### 最后的判断标准

如果一个版本的 Search：

1. 离线 relevance / coverage 更高
2. 相同预算下 p95 更低或不变
3. 同等 p95 下 authority / novelty / ingestability 更好
4. fallback 触发后仍能稳定给出非空、高置信 slate

我才会认为它真的有效。