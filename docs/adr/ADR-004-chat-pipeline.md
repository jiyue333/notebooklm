# ADR-004: Chat 链路

状态：Proposal  
日期：2026-03-15

# 四、Chat 链路

## 1. 核心目标

Chat 这条链路的核心目标，不是“做一个万能问答框”，而是：

**在用户阅读单篇 article 的上下文里，先判断用户到底在问哪一类问题，再在正确的 scope 内给出有证据边界的回答。**

我会把你的四种场景显式拆开，而不是混成一个统一 RAG：

1. **article-grounded**：对当前文章内容提问
2. **general**：通用类问题
3. **recommendation**：问“我在哪里看过类似文章吗”
4. **notebook-research**：围绕当前 notebook 主题做研究型问答

Chat 的第一原则是：**先定 scope，再决定检不检索、检索到哪一级对象。**

## 2. 难点挑战

### 难点 1：四种问题表面长得很像

同一句“这个方法靠谱吗？”可能是：

- 问当前文章的作者结论
- 问用户所有笔记里有没有类似论证
- 问这个 topic 在当前 notebook 里的综合结论
- 或者只是一个通用常识问题

如果 route 错了，后面 retrieval 再强也会答偏。

### 难点 2：推荐型问题不是 chunk retrieval

“我在哪看过类似文章”本质上是**article-level memory retrieval**，不是从 chunk 里找答案。
它要求系统记住每篇文章的大意、主题、方法、立场、来源和 notebook 归属。

### 难点 3：研究型问题不是 extractive QA

在 notebook 范围内做研究问答，往往需要：

- 先在 article 级别缩小候选
- 再回到 section / block 级别取证
- 最后做 multi-document synthesis

这和“在一篇文章里找一句原话”完全不是一回事。

### 难点 4：阅读场景要求很强的可解释性

用户正在读文章时，最不能接受的是：

- 回答说得像真的，但不知道来自哪
- scope 偷偷切换了（明明问当前文章，却答成通用常识）
- 推荐型回答只给标题，不解释“为什么像”

## 3. 我会优先考虑的方案 idea

### Idea A：把 Chat 做成四条 lane，不做一个大一统 prompt

我不会做“统一系统提示词 + 一个 retriever + 一个 answerer”。
我会做一个 **scope router**，先把问题分到四条 lane，再走不同的 retrieval / answer policy。

### Idea B：检索粒度动态切换

不同 lane 对应不同 retrieval unit：

- article-grounded：`block / section / citation-span`
- general：`无检索 or 轻检索`
- recommendation：`article synopsis / article graph`
- notebook-research：`article shortlist -> section evidence -> synthesis`

### Idea C：把“阅读位置”当成强先验

用户正在文章里提问时，我会利用：

- 当前 section
- 当前 page / anchor
- 最近高亮内容
- 最近引用过的 block

也就是说，当前阅读位置是一个很强的 routing 和 reranking prior。

### Idea D：推荐型问答用“文章记忆层”，不要直接 chunk ANN

我会给每篇文章预先生成：

- article synopsis
- tags / entities / methods / claims
- source / authors / year / notebook id
- 与其他文章的相似边

推荐型问题先在**文章层**召回，再必要时下钻到 section。

### Idea E：研究型问答要有“证据板”，不是只拼长上下文

notebook-research 我不会直接把 10 篇文章塞进长上下文里。
我会先做：

1. article shortlist
2. section evidence extraction
3. evidence clustering（按主题 / 观点 / 方法 / 证据类型）
4. synthesis

这样回答更像“在 notebook 内做一轮小综述”。

## 4. 我会怎么设计这条链路

## 4.1 输入

```text
chat_input {
  question
  current_article_id
  current_notebook_id
  reading_cursor {page, section_id, block_id}
  recent_highlights[]
  recent_chat_turns[]
}
```

此外系统侧会准备三层索引：

- **block / section index**：给 article-grounded 和 notebook-research 用
- **article synopsis index**：给 recommendation 用
- **notebook topic index**：给 notebook-research 做 article shortlist 用

## 4.2 阶段 A：Scope Router

先做问题分类：

```text
ChatRoute {
  article_grounded
  general
  recommendation
  notebook_research
  ambiguous
}
```

### 我会用的判断信号

- 提问里有没有“这篇 / 本文 / 作者 / 这里 / 上面 / 图里 / 第几节”
- 有没有“我之前在哪看过 / 类似文章 / 类似观点 / 还有哪些”
- 有没有“在这个 topic / 这个 notebook / 综合来看 / 这一方向上”
- 当前阅读位置和问题实体是否强相关

### 如果分类不够确定

我不会立刻追问用户。
我会：

1. 选一个主 route
2. 用一个 shadow route 做浅检索
3. 在回答里显式说明采用的假设

例如：“我先按‘当前文章问答’来回答；如果你想找你所有 notebook 里相似的文章，我再补一层推荐结果。”

## 4.3 阶段 B：按 route 选择检索范围

### Route 1：article-grounded

检索范围严格限制在**当前 article**。
我会采用三层召回：

1. **cursor-local recall**：当前 section / 临近 blocks / 当前页
2. **article-wide semantic recall**：全文 block / section 检索
3. **citation-side recall**：相关 reference / figure / table / footnote

这样做的原因是：很多阅读中提问其实是在问“当前看到的这段到底什么意思”，不是在问整篇全文。

### Route 2：general

这条 lane 默认**不检 notebook / article**，避免把一般常识问题错误地“本地化”。
回答策略是：

- 直接用模型知识作答
- UI 上显式标记 `General answer`
- 如果和当前文章高度相关，再补一句“顺带结合当前文章，这里对应的是……”

也就是说，general lane 允许**不带本地证据**，但必须把这一点说清楚。

### Route 3：recommendation

检索范围是**用户导入的所有 notebook 的所有 article**。
这里我不会做 chunk 检索，而是：

1. 先在 article synopsis index 召回 20–30 篇候选
2. 用 metadata / tags / entities / methods / source type 做 rerank
3. 做跨 notebook 去重和多样化
4. 给出 3–5 篇“最像”的结果，并解释“像在哪里”

推荐理由我会固定生成 2 类：

- **topic similarity**：主题接近
- **angle similarity**：方法 / 结论 / 证据形态 / 来源类型接近

### Route 4：notebook-research

检索范围限制在**当前 notebook**。
这里我会做两阶段检索：

1. **article shortlist**：先找 5–8 篇最相关文章
2. **evidence retrieval**：再在这些文章里抽 section / block 证据

然后把证据按主题聚类，最后再 synthesis 成答案。

## 4.4 阶段 C：每条 lane 的回答协议

### article-grounded 的回答协议

输出必须包含：

- 简洁回答
- 来自当前文章的证据锚点（section / page / block）
- 如果答案只在局部成立，要明确边界

我会把它做成“先证据，后归纳”的风格，尽量避免凭印象总结整篇。

### general 的回答协议

输出必须包含：

- 通用回答
- 明确标记“未使用当前 notebook / article 作为证据”
- 如果用户问题可能也能转成 article-grounded / notebook-research，则给一个补充入口

### recommendation 的回答协议

输出不是一段大综述，而是：

1. 先给 1 句总判断
2. 再给 3–5 篇推荐文章
3. 每篇都带 `why similar`
4. 标出 article 属于哪个 notebook

推荐回答里，我会更像“给你找资料”，而不是“替你总结所有资料”。

### notebook-research 的回答协议

输出是一个小型 synthesis：

- 先给综合结论
- 再给 2–4 个 evidence clusters
- 每个 cluster 绑定到 notebook 内的 article / section
- 如果不同文章冲突，显式展开“支持观点 A 的证据”和“支持观点 B 的证据”

也就是说，这条 lane 不是普通 QA，而是 **notebook-scoped mini review**。

## 4.5 阶段 D：验证与 fallback

### fallback 1：article-grounded 证据不足

如果当前 article 找不到足够证据：

- 明确说“这篇文章里没有足够证据直接回答”
- 可选地降级到 general answer
- 或提示可切 notebook-research

### fallback 2：recommendation 相似度不够高

如果找不到真正相似的文章：

- 不硬推
- 返回“弱相关候选”
- 解释相似度弱在哪

### fallback 3：notebook-research 证据冲突

如果 notebook 内资料冲突：

- 不强行给单一结论
- 改成“现有材料显示存在分歧”
- 明确各自证据来源

### fallback 4：route 不稳定

如果 router 置信度低：

- 主 route 正常执行
- shadow route 只做浅检索
- 最终回答显式写出假设

## 4.6 最终输出形态

我会让 Chat 输出至少包含这些结构字段：

```text
ChatResponse {
  route
  answer
  evidence_spans[]
  related_articles[]
  confidence
  fallback_used?
}
```

UI 上我会显式展示 route badge：

- `From this article`
- `General answer`
- `From your notebooks`
- `Research in this notebook`

这会极大减少“系统到底是基于哪层知识在答”的混乱感。

## 5. 这些方案的优缺点和适用场景

### Chat 方案对比

| 方案 | 优点 | 缺点 | 适用场景 | 是否采用 |
|------|------|------|----------|----------|
| 单一 RAG chat（一个 retriever + 一个 answerer） | 实现简单 | scope 混乱，article / notebook / corpus 容易串 | demo | 否 |
| 四路由 chat + 分层检索 + 证据约束回答 | 解释性强，回答边界清晰，适配你的四种场景 | 工程复杂，索引层更多 | 主方案 | **是** |
| 全 agent deep research chat | 质量上限高 | 延迟大，可控性弱 | notebook-research 的 deep mode | 部分采用 |

### Chat 技术选型（我会这样配）

| 模块 | 首选思路 | 角色 |
|------|----------|------|
| Scope Router | 快速分类器 / 小模型路由 | 判断 question 属于哪条 lane |
| Article Retriever | block + section hybrid retrieval | 当前文章问答 |
| Recommendation Retriever | article synopsis ANN + metadata rerank | 跨 notebook 找相似文章 |
| Notebook Research Retriever | article shortlist + section evidence retrieval | notebook 内研究问答 |
| Answer Composer | 高质量模型 + 结构化输出 | 统一生成回答 |
| Verifier | grounding / contradiction checker | 降 hallucination，决定 fallback |
| Chat State | reading cursor + recent highlights + recent citations | 利用阅读上下文 |

## 6. 我会怎么评估这条链路做得好不好

## 6.1 线上埋点

Chat 线上我也优先盯系统指标，而不是点赞率。

- `chat.route_selected`
- `chat.retrieval_started`
- `chat.retrieval_done`
- `chat.answer_generated`
- `chat.verified`
- `chat.fallback_triggered`
- `chat.response_served`

### 我最关心的线上指标

- **Chat E2E p50 / p95 / p99**
- **First-token latency p50 / p95**
- **Route latency p95**
- **Retrieval latency p95**（按四条 lane 分开）
- **Cross-notebook retrieval p95**
- **Evidence coverage rate**（回答中带证据锚点的句子占比）
- **Verifier reject rate**
- **Insufficient-evidence fallback rate**
- **Wrong-scope proxy**（高熵 route / dual-route 触发比例）
- **Answer truncation rate**

## 6.2 离线 benchmark

Chat 的离线 benchmark 我会直接按四种 lane 建集，而不是混成一个 QA 集。自动评估层我也会优先走 grader pipeline：规则 grader 查 route / schema / citation completeness，模型 grader 查 faithfulness / scope correctness / recommendation relevance / synthesis quality；OpenAI 的 graders 支持 label-model、text-similarity 和 multi-grader，很适合把这些维度编成一个统一打分器。

### 数据集怎么建

- **article-grounded 集**：问题 + 当前 article + gold evidence spans
- **general 集**：问题 + 不应使用 article/notebook 证据的标记
- **recommendation 集**：问题 + gold similar articles + 相似原因
- **notebook-research 集**：问题 + notebook 内 gold article set + gold evidence clusters

### 离线指标

- route accuracy
- evidence recall@k
- citation precision
- answer faithfulness
- scope correctness
- recommendation nDCG@5
- notebook synthesis coverage
- latency / quality frontier

对于 retrieval 相关部分，我会故意做成 task-level、heterogeneous 的评测风格，而不是单一 QA 集；这和 BEIR 这种 benchmark 的思想一致：跨任务、跨领域看鲁棒性，同时把效果与算力代价放在一起看。

### 最后的判断标准

如果一个版本的 Chat：

1. route accuracy 更高
2. evidence recall 与 citation precision 更高
3. notebook-research 的 synthesis 质量更稳
4. recommendation 的相关性更高
5. p95 没有因为 verifier / multi-hop retrieval 失控

我才会认为它真的有效。
