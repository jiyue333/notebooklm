# ADR-002: Ingest 链路

状态：Proposal  
日期：2026-03-15

# 二、Ingest 链路

## 1. 核心目标

Ingest 的目标不是“把内容转成 markdown”。

**真正目标是：把异构来源转成统一、可阅读、可跳转、可引用、可用于后续 AI 的 Canonical Article。**

我会坚持一个原则：

> **Markdown 是渲染层，不是事实层。**
> 真正应该存的是 block graph + provenance + anchor map。

------

## 2. 难点挑战

### 难点 1：HTML、PDF、扫描件、本地文档差异极大

- HTML 有 boilerplate、导航、广告、评论区
- PDF 有多栏、页眉页脚、脚注、公式、表格
- 扫描件还会有 OCR 问题
- 某些“文章页”其实是动态渲染

### 难点 2：你要统一阅读体验，但不能丢 source fidelity

尤其是 PDF。
用户很多时候仍然想看原文版式、页码、图表位置。

### 难点 3：没有 toc 的文章也要可跳转

这是纯 parser 很难做好的地方。
你需要的不只是 heading extraction，而是**section segmentation + section naming + anchor binding**。

### 难点 4：后续 Summary / Chat 依赖 ingest 质量

一旦 ingest 把结构打坏：

- summary 会失真
- chat 检索会碎
- section jump 会错
- 引用定位会乱

所以 ingest 其实是系统的地基。

------

## 3. 我会优先考虑的方案 idea

### Idea A：用 parser ensemble，不信单 parser

我不会指望一个 parser 统一搞定所有文档。
我会做 **type-aware parser ensemble**：

- HTML：主体抽取 + DOM heading 利用
- 学术 PDF：版面解析 + refs/citation sidecar
- 复杂公式/中英混排 PDF：另一路 parser
- 扫描件：OCR / VLM 路由

Docling 适合做多格式统一解析和导出统一表示；GROBID 更强在学术 PDF 的 header / references / citation parsing；Jina Reader / Trafilatura 适合 HTML 主体抽取；Unstructured 适合作为广谱 fallback；MinerU 对复杂科技 PDF、表格、公式、OCR 场景也很有价值。([docling-project.github.io](https://docling-project.github.io/docling/))

### Idea B：先生成多个 parse candidate，再选最优/做融合

特别是 PDF，我会允许：

- body parse 来自 A
- metadata / references 来自 B
- toc 来自 C 或 LLM repair

而不是“一次 parse 定生死”。

### Idea C：显式做 parse quality scoring

我会给每篇 ingest 生成 `QualityProfile`，包括：

- title match
- heading ladder consistency
- broken sentence rate
- reading order confidence
- table retention
- equation corruption
- reference extraction confidence
- toc confidence

这样后续 summary / chat 能知道自己站在什么地基上。

### Idea D：生成 synthetic TOC，不强依赖原文 toc

没有 toc 的文档，我会自己造一棵“读者 toc”。

做法不是强行猜 h1/h2，而是：

1. 先分 section boundary
2. 再给 segment 命名
3. 最后绑定 jump anchor

### Idea E：PDF 保留原始视图，但同时生成结构化 sidecar

你的要求里“pdf 文件类型直接展示”我很认同。
所以 PDF 我会做：

- 原 PDF viewer 保留
- AI 生成的 TOC side panel
- page / paragraph anchor 映射
- 可搜索的提取文本 sidecar

这样既保真，又能让 AI 工作。

------

## 4. 我会怎么设计这条链路

## 4.1 输入

```text
selected_source {
  url | uploaded_file | external_id
}
source_metadata_from_search
notebook_id
article_context
```

------

## 4.2 阶段 A：获取与指纹

先把原始 artifact 固化：

- 下载 raw file / raw html
- 记录 HTTP metadata / content-type
- 计算 content hash
- 存储 source url / fetched_at / headers
- 建立 artifact variants

这一层之后，系统里至少有：

- raw_html / raw_pdf / raw_docx
- normalized text candidate
- extracted metadata candidate

------

## 4.3 阶段 B：Canonicalization 与版本归一

我会先判断：

- 这是不是 notebook / 全局里已存在的文章？
- 是不是同一篇文章的不同版本？
- 是不是 HTML + PDF 的两个入口？

归一依据：

- DOI / PMID / PMCID / arXiv id
- canonical URL
- title + authors + date
- Crossref relationships / metadata

Crossref 的 relationships 很适合做 preprint / version / supplement / references 这类关系归一。([www.crossref.org](https://www.crossref.org/documentation/schema-library/markup-guide-metadata-segments/relationships/))

------

## 4.4 阶段 C：文档类型路由

我会先走一个便宜的 `DocumentRouter`：

### 路由 1：网页文章

- 静态 HTML
- 动态渲染页面
- 博客 / 新闻 / docs

### 路由 2：学术 PDF

- 双栏论文
- 含公式 / 表格 / 图表 / references

### 路由 3：普通 PDF / 报告

- 政策报告
- whitepaper
- 长报告

### 路由 4：扫描件 / OCR

- 图片型 PDF
- 乱码 PDF
- 字体嵌入异常

### 路由 5：Office / 其他格式

- docx
- pptx
- epub
- txt / md

------

## 4.5 阶段 D：多 parser 候选生成

### HTML 路径

我会先尝试：

1. DOM-based main content extraction
2. Readability / Trafilatura 风格主体抽取
3. 对复杂动态页，走 browser-rendered HTML -> Markdown/JSON 路线

如果结构脏，再补一层 LLM cleanup，但 cleanup 只做**修复**，不做原文重写。

### PDF 路径

我会并行跑两类候选：

- **body-first parser**：拿正文结构、表格、图像、公式、阅读顺序
- **scholarly-sidecar parser**：拿 title / abstract / authors / refs / citations

在这里，Docling + GROBID 是一个很好的组合；Docling 本身支持多格式、统一表示和 Markdown/JSON 导出，GROBID 则对 scholarly metadata、references、citation contexts 特别有帮助。([docling-project.github.io](https://docling-project.github.io/docling/))

### 扫描件路径

我不会对整篇都跑最贵 OCR/VLM。
我会先做“疑难页检测”：

- 文本层异常
- 字符覆盖率低
- 版面置信度低
- 乱码率高

只对可疑页走重型 OCR / VLM。

------

## 4.6 阶段 E：Parse Quality Judge

每个 parse candidate 都打分：

```text
parse_score =
  0.20 * structure_integrity
+ 0.15 * reading_order
+ 0.15 * heading_quality
+ 0.10 * sentence_integrity
+ 0.10 * table_fidelity
+ 0.10 * reference_quality
+ 0.10 * metadata_consistency
+ 0.10 * anchorability
```

### 我会重点检查

- 标题是否和 source metadata 大体一致
- heading 是否形成合理层级
- 是否大量断句/粘连
- 表格有没有被打散成垃圾文本
- 参考文献区是否被识别
- section 边界是否自然
- 页面锚点能不能落回原文

------

## 4.7 阶段 F：融合与修复

这里我不会盲信最优单一路径，而是允许融合：

- metadata 用 GROBID
- body 用 Docling / HTML extractor
- toc 由 parser heading + LLM repair 共同生成
- references 由 scholarly parser 单独挂 sidecar
- figure / table caption 独立保留

LLM 在这里的角色不是“从头编一份文档”，而是：

- 纠正 section tree
- 修 heading 命名
- 修局部断句
- 去 boilerplate
- 把 block 归类

------

## 4.8 阶段 G：TOC 生成与跳转绑定

这是你特别在意的，我会单独设计。

### 情况 1：原文有高质量 toc / heading

直接使用，但仍然做一致性校验：

- heading 文本
- 层级
- 覆盖率
- anchor 顺序

### 情况 2：原文没有 toc，或 heading 不可信

生成 **synthetic TOC**：

#### 步骤 1：section segmentation

用这些信号切段：

- 版面变化
- heading candidate
- 编号模式（1 / 1.1 / I / A）
- 语义主题突变
- 段落长度分布
- 章节过渡句

#### 步骤 2：section naming

给每段起一个“读者可理解”的标题。
我会优先用：

- 原文首句概括
- 领域术语短语
- parser 候选 heading
- LLM 生成的短标签

#### 步骤 3：anchor binding

每个 toc node 必须能跳到：

- PDF：页码 + 区域
- 非 PDF：block_id / DOM anchor

### 一个很重要的产品细节

当 toc 是系统生成的，我会明确标 `Generated TOC`。
这能降低用户对“跳得不准”的心理落差。

------

## 4.9 阶段 H：构建 BlockGraph

我会把最终结果存成：

```text
BlockGraph {
  nodes: [
    heading,
    paragraph,
    list,
    quote,
    code,
    table,
    figure,
    equation,
    footnote,
    citation
  ]
  edges: [
    parent_of,
    next,
    refers_to,
    cites,
    anchored_to_page_region
  ]
}
```

每个 block 至少带：

- `block_id`
- `type`
- `text`
- `section_id`
- `page_no` / `anchor`
- `source_span`
- `confidence`

------

## 4.10 阶段 I：渲染与索引产物

### 面向阅读

- **PDF**：原始 PDF viewer + AI TOC + 搜索 + anchor jump
- **非 PDF**：统一 reader view（markdown-like 富文本样式）+ toc

### 面向 AI

- block embeddings
- section summaries
- citation/reference graph
- entity/tag extraction
- article-level vector
- notebook-level article synopsis vector

这一步其实已经在为后面的 article chat / notebook chat 铺路。

------

## 4.11 fallback 设计

### parser 质量差

- 保留原始视图
- 降级成 page-level toc
- 标识低置信度
- summary 改走更保守模板

### 表格/公式很差

- 单独重跑可疑页面
- 用 image/table sidecar 替代正文内粗暴展开

### HTML 太脏

- 回退到 browser-rendered extraction
- 再不行，保留原文 + 仅做 section-level indexing

------

## 5. 方案比较与取舍

### Ingest 方案对比

| 方案                                          | 优点                         | 缺点                             | 适用场景     | 是否采用 |
| --------------------------------------------- | ---------------------------- | -------------------------------- | ------------ | -------- |
| 单 parser + markdown-first                    | 简单，开发快                 | 很脆，toc/表格/公式/跳转都容易坏 | demo         | 否       |
| parser ensemble + quality judge + block graph | 质量稳，可解释，适合研究产品 | 工程复杂                         | 主方案       | **是**   |
| 全量 VLM / OCR 解析                           | 鲁棒性高                     | 太慢太重，不必要                 | 疑难文档兜底 | 部分采用 |

### Ingest 技术选型（我会这样配）

| 模块                   | 首选                                | 备选/补充                    | 角色                               |
| ---------------------- | ----------------------------------- | ---------------------------- | ---------------------------------- |
| HTML 主体抽取          | Jina Reader / Trafilatura           | Readability / browser render | 取主文、heading、clean text        |
| 多格式统一解析         | Docling                             | Unstructured                 | 统一输出结构                       |
| 学术 PDF metadata/refs | GROBID                              | 其他 scholarly parser        | title / abstract / refs / citation |
| 复杂科技 PDF           | MinerU                              | 重型 OCR/VLM                 | 表格、公式、复杂布局               |
| 质量选择               | 自定义 parse judge                  | LLM judge                    | 选最优 candidate                   |
| TOC 生成               | heading + segmentation + LLM repair | 规则补丁                     | jumpable toc                       |

这些选择背后的能力边界来自官方文档：Docling 支持多格式和统一文档表示；GROBID 强在 scholarly metadata / references / citation contexts；Jina Reader 针对 HTML-to-Markdown/JSON；Unstructured 提供通用分区；MinerU 擅长复杂科技 PDF、公式、表格与 OCR。([docling-project.github.io](https://docling-project.github.io/docling/))

------

## 6. 我会怎么评估 Ingest 做得好不好

## 6.1 线上埋点

Ingest 我也不会优先盯用户行为，而是盯 “文档在系统里是否被稳定转成可消费对象”

+- `ingest.fetch_started`
 +- `ingest.fetch_done`
 +- `ingest.type_routed`
 +- `ingest.parse_candidate_generated`
 +- `ingest.parse_scored`
 +- `ingest.parse_selected`
 +- `ingest.block_graph_built`
 +- `ingest.toc_generated`
 +- `ingest.anchor_bound`
 +- `ingest.fallback_triggered`

### 我最关心的线上指标

+- **Ingest E2E p50 / p95 / p99**
 +- **Fetch latency p95**（按 html / pdf / uploaded file 分开）
 +- **Parser route distribution**（每类文档到底走了哪条 parser lane）
 +- **Primary parse success rate**
 +- **Secondary parser / OCR fallback rate**
 +- **Synthetic TOC generation success rate**
 +- **Anchor binding success rate**
 +- **BlockGraph completeness proxy**（heading / paragraph / table / figure 保留率）
 +- **Parser disagreement rate**（多个 parse candidate 差异过大时的占比）
 +- **Reparse rate**（首次 ingest 后又被打回重跑的比例）
 +- **Artifact cache hit rate**

------

## 6.2 离线 benchmark

实验阶段 Ingest 的核心仍然是离线集：做一个精而不大的文档集，先 300 篇就够，但类型一定要故意拉开：

- 新闻/博客 HTML
- 技术文档 HTML
- 学术双栏 PDF
- 报告型 PDF
- 扫描件 PDF
- 中英混排 / 含公式 / 含复杂表格

### 标注内容

- 标题
- metadata
- toc tree
- section boundaries
- reading order
- table region / figure caption
- citation/reference block
- jump anchor gold

### 指标

- title accuracy
- heading / toc F1
- reading order score
- anchor jump accuracy
- table retention score
- reference extraction score
- summary support coverage

### 最后的判断标准

如果 ingest 变好，必须同时体现在：

+1. parse / toc / anchor 相关离线分数更高
 +2. p95 ingest 耗时没有明显劣化
 +3. OCR / VLM fallback 没有被无意义放大
 +4. summary / chat 的下游 benchmark 有同步提升
 \+ 否则说明你只是把解析做得更 “花”，没有把地基做稳