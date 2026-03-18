# ADR-003: Summary 链路

状态：Proposal  
日期：2026-03-15

# 三、Summary 链路

你说得对，这条链路比前两条简单一些。
但它仍然值得做得很“系统化”。

## 1. 核心目标

**针对单篇 article，生成一段简洁但高覆盖、结构清晰、事实一致的摘要。**

我会把它定义成：

> 一段面向“快速判断这篇值不值得继续读”的 canonical summary。

不是所有信息都压进去，重点是：

- 这篇讲什么
- 关键结论/方法/贡献是什么
- 证据或适用边界在哪里

------

## 2. 难点挑战

### 难点 1：一段话很容易写成“空话”

尤其长文章，如果直接整文总结，很容易变成：

- 高层废话
- 只复述标题
- 偏 abstract / 开头
- 漏掉最重要的信息

### 难点 2：不同文章类型应该用不同摘要模板

论文、报告、教程、新闻，理想摘要结构完全不同。

### 难点 3：ingest 质量会直接影响 summary 质量

如果 section 边界坏了，摘要就会偏。

------

## 3. 我会优先考虑的方案 idea

### Idea A：先做 article profiling / tag analysis，再摘要

你提到 tag 分析，我会认真做，而且它不是装饰，是**路由器**。

我会给每篇文章打这些 tag：

- `article_type`：paper / report / blog / tutorial / news / docs
- `evidence_style`：quantitative / qualitative / mixed
- `structure_quality`：high / medium / low
- `time_sensitivity`：evergreen / update-driven
- `density`：light / medium / heavy
- `dominant_sections`：method / result / opinion / instruction

这些 tag 决定：

- 用哪套 prompt
- 哪些 section 权重大
- 是否走分层摘要
- 是否要加“局限/边界”句子

### Idea B：先抽“证据骨架”，再写最终一段话

我不会直接从全文到 final summary。
我会先生成：

- 8–12 个 evidence bullets
- 每个 bullet 对应 source span / block id
- 再从 bullets 压成一段话

这样好处是：

- 覆盖更稳
- 后续可以做 factuality check
- 可以知道摘要的每句话“从哪来”

### Idea C：按长度和结构质量路由

我会分 4 档：

- **S**：短文 / 高结构，直接 section-aware summary
- **M**：中等长度，先 section micro-summary 再合并
- **L**：长文，分层摘要
- **X**：结构差 / parse 差，走保守摘要（abstract + intro + conclusion + captions）

### Idea D：生成多个候选，再 judge 选最优

如果你说“只要最好效果，不太考虑成本”，我会让 summary 走一个小型 best-of-N：

- 候选 1：claim-first
- 候选 2：contribution-first
- 候选 3：reader-first（更像读前导语）

然后用 judge 按 rubric 选：

- 覆盖
- 事实一致
- 清晰度
- 非冗余

------

## 4. 我会怎么设计这条链路

## 4.1 输入

```text
article {
  metadata
  block_graph
  toc_tree
  quality_profile
}
summary_policy {
  target_length = one_paragraph
  language
}
```

------

## 4.2 阶段 A：Article profiling

先做内容画像：

```text
ArticleProfile {
  article_type
  evidence_style
  structure_quality
  domain
  section_roles
  important_entities
  importance_distribution
}
```

### section_roles 我会特别做

例如把 section 标成：

- background
- problem
- method
- result
- limitation
- implication
- how-to
- opinion

这样摘要时才能知道该抓哪一类信息。

------

## 4.3 阶段 B：证据骨架提取

按文章类型给不同 section 配额。

### 例如学术论文

我会偏向：

- problem / question：15%
- method / setup：25%
- core result：35%
- limitation / implication：25%

### 例如报告/政策文

偏向：

- topic：20%
- key conclusion：35%
- basis / evidence：25%
- implication：20%

### 例如教程

偏向：

- what it teaches：25%
- key steps / idea：45%
- who it is for / limits：30%

这一层的输出是：

```text
evidence_bullets = [
  {text, block_ids, role, salience_score}
]
```

------

## 4.4 阶段 C：长度与质量路由

### Route S：短文 / 高结构

直接把高权重 blocks 喂给 summary prompt。

### Route M：中长文

先对 section 生成 micro-summaries，再全局合并。

### Route L：超长文

先 section -> cluster -> global paragraph
避免“长上下文直接吞”的注意力塌缩。

### Route X：解析质量差

只从这些位置取信息：

- abstract
- intro
- conclusion
- figure/table captions
- metadata

这样虽然保守，但稳定。

------

## 4.5 阶段 D：候选生成 + judge

我会用 2–3 个 summary prompt 变体生成候选，然后做 judge：

### Summary rubric

- fidelity 40%
- coverage 30%
- clarity 20%
- concision 10%

如果某个句子找不到足够强的证据支撑，就删或改弱。

------

## 4.6 阶段 E：最终输出

最终存：

```text
ArticleSummary {
  summary_text
  summary_type = canonical
  evidence_spans[]
  profile_tags[]
  confidence
  version
}
```

对用户展示只有一段话；
但系统里我会保留 evidence spans，后续 chat 可以直接复用。

------

## 4.7 fallback 设计

### parse 差

只做 conservative summary，不硬写细节。

### 文章太短

直接做 concise abstract-style summary。

### 类型识别不稳

回退到通用模板：

- 主题
- 核心内容
- 最重要结论/价值
- 适用边界

------

## 5. 方案比较与取舍

### Summary 方案对比

| 方案                                   | 优点                          | 缺点                     | 适用场景      | 是否采用 |
| -------------------------------------- | ----------------------------- | ------------------------ | ------------- | -------- |
| 整文直接摘要                           | 实现简单                      | 长文容易空泛、偏头部内容 | 短文          | 否       |
| 结构化分层摘要 + evidence 骨架 + judge | 质量稳、可控、便于 fact check | 设计复杂些               | 主方案        | **是**   |
| 纯 extractive 摘要                     | 忠实                          | 可读性差，不像产品摘要   | 法务/审计场景 | 部分采用 |

### Summary 技术选型（我会这样配）

| 模块               | 首选                          | 备选/补充          | 角色                     |
| ------------------ | ----------------------------- | ------------------ | ------------------------ |
| article profiling  | LLM / 小模型分类              | 规则标签           | 文章类型、结构、证据风格 |
| evidence selection | block salience scorer         | section heuristics | 先找骨架                 |
| summary generation | 高质量推理模型                | 中模型             | 生成 1 段摘要            |
| judge / verifier   | 第二模型或同模型第二遍        | NLI/规则           | fidelity / coverage 审核 |
| summary cache      | article_hash + prompt_version | 纯文本 cache       | 避免重复生成             |

------

## 6. 我会怎么评估 Summary 做得好不好

## 6.1 线上埋点

Summary 链路的线上观测，我会把重点放在 “是否稳定地产出一段可靠摘要”，而不是先看用户是否点赞。
 +- `summary.profiled`
 +- `summary.route_selected`
 +- `summary.evidence_extracted`
 +- `summary.candidate_generated`
 +- `summary.judge_done`
 +- `summary.finalized`
 +- `summary.fallback_triggered`

### 我最关心的线上指标

+- **Summary E2E p50 / p95 / p99**
 +- **Route mix**（S / M / L / X 四档路由的分布）
 +- **Evidence extraction latency p95**
 +- **Judge / verifier reject rate**
 +- **Unsupported-claim rate**（自动 grounding check 抓到的无支撑句占比）
 +- **Conservative-summary fallback rate**
 +- **Summary cache hit rate**
 +- **Compression ratio**（原文 token → summary token）
 +- **Context truncation rate**

------

## 6.2 离线 benchmark

Summary 的主战场也应该是离线 benchmark。我会做一个小而精的 gold set，比如 200 篇；自动评分部分优先走 grader pipeline：规则 grader 检查格式和引用完整性，模型 grader 判断 fidelity / coverage / clarity，必要时再用 multi-grader 聚合。OpenAI 的 eval / graders API 本身就支持 label-model grader、text-similarity grader 和 multi-grader 组合，这种形态很适合拿来做 Summary 的自动验收。

- 每篇配一段专家摘要
- 标注支持证据 span
- 标注文章类型和关键 section

### 观察指标

- **faithfulness**（摘要与原文一致、不捏造的程度）
- **coverage**（摘要对原文要点覆盖的程度）
- **clarity**（表述是否清晰易读）
- **concision**（是否简洁不啰嗦）
- **supported-sentence ratio**（摘要句子中有原文证据支撑的句子所占比例）
- **section coverage ratio**（摘要覆盖的章节数 ÷ 原文章节数）

### 打分方式

人工 rubric 为主，自动指标只做辅助。
我最信的一套总分会是：

```text
summary_score =
  0.40 * faithfulness
+ 0.30 * coverage
+ 0.20 * clarity
+ 0.10 * concision
```

### 有效性的最终判断

如果 summary 真有效，应该看到：

1. 用户更快决定“要不要继续读”
2. 后续聊天更聚焦
3. 用户更少抱怨“摘要没说重点”或“摘要说错了”

# 
