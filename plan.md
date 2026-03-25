# 规划

## 测评层面

### 1. LangSmith 驱动的本地评测工作台（覆盖 search / ingest / summary / chat）

- 整体架构只有一套：`LangSmith` 作为评测中枢，本地 `eval runner` 作为执行与展示层，不再拆成两套独立系统
- `LangSmith` 负责 `dataset / evaluator / experiment / baseline / pairwise compare / trace`，重点解决 prompt 迭代、LLM judge、版本对比和 bad case 回看
- 本地 `eval runner` 负责调用真实链路、收集阶段耗时与成本、聚合 `P50 / P90 / P95`、生成 `report.html`
- 第一版不做独立平台前后端，直接做本地 `eval` 脚本 + 静态 HTML 报告；这样实现行数最少，但后续仍可把同一份 `report.json` 接到页面
- 目标是 one-click 跑完整评测，也支持按链路单独跑
  固定 case -> 本地 eval runner -> 调真实链路 -> 采性能指标
                      -> 写 LangSmith trace / experiment
                      -> 跑 lite_model judge
                      -> 产出 report.html / report.json
- 命令形态统一为：

```bash
./scripts/eval.sh all smoke
./scripts/eval.sh search smoke
./scripts/eval.sh ingest smoke
./scripts/eval.sh summary smoke
./scripts/eval.sh chat smoke
```

- `all` 跑四条链路，`search / ingest / summary / chat` 跑单链路
- `smoke` 是第一版默认 profile，每条链路先固定 5 条 case，优先保证稳定可复现
- 每次 run 生成唯一 `bench_run_id`，统一输出 `report.json`、`report.md`、`report.html`

### 2. 评测数据集与执行方式

- 数据集以仓库内 JSONL 为准，不依赖线上流量，不依赖人工大规模标注；仓库文件是 source of truth，再由 runner 同步到 LangSmith dataset
- 每条链路先只维护 5 条固定 case，后续再扩展 `stable` / `full` profile
- search：5 条固定 query，覆盖学术检索、时效性、偏好站点、中文 query、对比型 query
- ingest：5 个固定 source artifact，覆盖 `html / pdf / scanned_pdf / pasted_text / long_markdown`
- summary：5 篇固定文章，覆盖短文、长文、报告、论文、中文内容
- chat：5 条固定问题，覆盖 notebook 内问答、跨文章总结、引用回答、是否需要联网、推荐相关文章
- 每条 case 只保存评测最小字段：输入、预期 facet / 路由、judge rubric、可选 evidence、标签
- runner 默认每条 case 执行 5 次，再聚合性能和质量指标
- 目录建议直接落地为：

```text
backend/evals/
  cases/
    search/smoke.jsonl
    ingest/smoke.jsonl
    summary/smoke.jsonl
    chat/smoke.jsonl
  run.py
  judges.py
  reporters.py
  runs/<bench_run_id>/
scripts/eval.sh
```

### 3. 通用指标设计

- 通用性能指标：成功率、端到端 `P50 / P90 / P95`、各阶段 `P50 / P90 / P95`、TTFB、token 消耗、成本估算、缓存命中率、retry 次数
- 通用质量指标：`lite_model` judge 平均分、分维度得分、通过率、标准差、case 级失败原因
- `P90 / P95` 只按“同一 profile 下全部 case × repeat”的聚合样本计算，不对单 case 单独算 `P95`
- judge 一律输出结构化 JSON：`score`、`subscores`、`pass`、`reason`
- 对开放式任务不追求唯一标准答案，只要求输出满足 rubric，且能解释为什么得分高或低

### 4. 分链路评测

- search：重点看 `intent_analysis / recall / score / expand_recall / finalize` 阶段延迟、去重命中率、空结果率、expand_recall 触发次数；质量由 `lite_model` 评 `relevance / authority / coverage / freshness / content_quality`
- ingest：重点看 `fetch_detect / parse / normalize / enhance / index` 阶段延迟、解析成功率、按 `input_type` 分桶成功率、chunk 数量、外部解析器失败率；质量由 `lite_model` 评 HTML/PDF 到 Markdown 的还原度、标题目录保真度、chunk 上下文完整性
- summary：重点看 `analyze / compress / direct_summarize / map_split / map_summarize / reduce_summarize / validate` 阶段延迟、缓存命中率、route 分布、retry 次数；质量由 `lite_model` 评关键点覆盖率、supported claim ratio、hallucination rate、长文压缩损失
- chat：重点看 `query_router / retrieval_planner / retrieval_engine / web_search_broker / answer_stream / citation_verifier` 阶段延迟、TTFB、总时延、citation 通过率、联网触发率；质量由 `lite_model` 评准确度、groundedness、引用有效性、联网判定合理性、推荐相关文章相关性
- 为了让评测结果可信，需要额外补齐几项埋点：chat 主 `astream` 路径的 token / cost、`answer_stream` 阶段耗时、MinerU 耗时与失败原因、remark 规范化修复命中、`notebook_title` 缺失率

### 5. 报告产物与 LangSmith

- `LangSmith` 不是可选增强，而是整条 prompt / judge / experiment 流水线的核心
- 默认查看入口是本地 `report.html`，不是 Grafana；`report.html` 负责总览与汇总，LangSmith 负责单 case 与版本分析
- `report.html` 需要提供总览卡片、链路切换 tabs、阶段延迟图、judge 得分图、失败 case 表格、与 baseline 的 diff
- `report.md` 用于归档和贴到 PR，`report.json` 用于二次分析和后续页面化
- 每个 case 都要保留输入、输出、阶段指标、judge reason、失败原因、可跳转的 LangSmith trace / experiment 链接
- runner 在执行前自动确保 LangSmith dataset 存在并同步最新 case；执行后自动创建或更新 experiment
- `lite_model` judge 优先落在 LangSmith evaluator 中，保证 prompt 改动、judge rubric 改动、baseline 对比都走同一条流水线
- 最终 HTML 报告基于本地聚合指标 + LangSmith experiment 结果共同生成，不单独维护第二套评测口径
- 每次 run 统一打上 `bench_run_id`、`pipeline`、`profile`、`case_id`、`app_version`、`prompt_version`，方便做版本对比和 bad case 回看

---

## 功能补全 & 视觉美化

### 1. 首页

**笔记本管理**

- 项目 logo：设计合适的 logo，至少三套备选方案，支持随时切换
- notebook 名字去重校验（创建 & 重命名时拦截）
- 新建笔记本弹窗完善：支持 tag 分类，首页支持按 tag 筛选笔记本
- 全局搜索：笔记本标题搜索 + 文章标题/内容搜索（当前仅本地 `includes` 过滤，需接后端搜索）
- 笔记本列表分区展示：「最近打开」（按访问时间排序，取最近 N 个）+ 「全部笔记本」，当前仅全量列表

**空状态 & 反馈**

- 零笔记本时展示引导插图和快速创建入口
- 搜索无结果时展示空状态提示
- 加载与错误状态使用独立样式，与正文标题区分（当前共用 `home-section-title`）

**顶栏**

- 头像点击弹出账户菜单（账户设置、退出登录）

### 2. 笔记本页面

**布局**

- 删除拖拽 resizer 和各面板边框线，改为固定比例布局
- 多布局模式切换按钮：三栏 / 左中双栏（隐藏右侧）/ 纯阅读（仅中栏）；左右面板各有收起/展开按钮
- 新建笔记本或进入空 notebook 时，自动弹窗添加来源表单。参考图片：[image.png](image.png)

**文章列表（左栏下半）**

- 在笔记本页面支持编辑标题（笔记本标题 + 文章标题均可内联编辑）
- 右键菜单增加「在新标签页打开」「复制链接」选项
- 文章列表展示解析状态标记（解析中 / 失败 / 就绪），失败时提供重试入口

**状态与容错**

- 页面加载失败时提供重试按钮
- 文章正文轮询等待期间展示骨架屏，替代当前空白等待

### 3. 来源与搜索

**搜索卡片**

- 搜索结果卡片美化：展示源链接 favicon（导入时持久化到数据库）。参考图片：[image1.png](image1.png)
- 结果列表视图（results）直接支持逐条勾选，无需先进入 discover 视图
- 搜索结果支持按相关度 / 时间 / 来源排序

**添加来源弹窗**

- 网站 / 粘贴文字支持用户输入标题，未输入时用 Lite Model 自动生成
- 弹窗遮罩增加半透明背景（当前为 transparent，视觉焦点弱）
- 移除弹窗的 `resize: both`，使用固定尺寸

**异步搜索**

- 接入 `getSearchSession` 轮询到 SourcePanel，支持 deep 模式的渐进式结果展示
- 搜索模式（fast / auto / deep）图标区分（当前 deep 与 search 图标复用）

### 4. 阅读功能

**渲染与展示**

- Markdown 阅读：当前 `react-markdown` + `remark-gfm` + `rehype-raw` 基础可用，优化代码块高亮（接入 syntax highlighter）
- PDF 阅读：优化 `react-pdf` 渲染性能（长文档虚拟滚动），PDF 模式下翻译不应切换到 Markdown 排版（当前行为跳跃）
- 文章内全文搜索：阅读区内 Ctrl/Cmd+F 搜索，高亮匹配项并支持上下跳转

**目录与导航**

- TOC 滚动联动：阅读区滚动时自动高亮当前章节（scroll spy），当前仅支持点击 TOC 跳转
- PDF 无 outline 时的目录生成优化（当前启发式匹配容易错页）
- 键盘导航：上下方向键切换文章，J/K 滚动阅读区

**高亮与批注**

- 选中文本弹出工具条：高亮（多色）、添加批注、复制、发送给助手
- 高亮持久化到后端（新增 highlights 数据模型）
- 高亮列表：左栏或侧边栏展示当前文章所有高亮和批注，点击定位原文
- 高亮数据接入助手上下文（替代当前 `recentHighlights` 空数组）

**阅读定制化**

- 字体切换（衬线 / 无衬线 / 等宽，当前工具栏已有入口但选项有限）
- 字号调节（当前 `fontSize` state 已有，确保 UI 滑块/按钮可控）
- 行距、页面宽度调节（当前 `pageWidth` state 已有，增加更多档位）
- 阅读进度指示（顶部进度条或百分比）

### 5. AI 助手

**基础能力**

- 当前文章为空也可以打开助手（notebook 级对话）
- 支持多对话管理：新建对话、切换对话、删除对话
- 对话持久化到后端（当前仅内存，刷新丢失），支持历史对话恢复
- 聊天输入改为 textarea，支持 Shift+Enter 换行、Enter 发送

**个性化**

- 支持用户自定义系统 prompt（如「用简体中文回答」「回答保持简洁」）
- 回答长度偏好设置（简洁 / 详细 / 自适应）
- 自动生成 notebook 图标和标题（基于已导入内容，用 Lite Model 生成）

**翻译**

- AI 逐段翻译：译文嵌入原文段落下方，支持折叠/展开
- 移除当前译文面板冗余占位文案（「已切换为译文视图」），直接在正文内交替展示
- 翻译目标语言支持在翻译按钮处快速切换

**引用与推荐**

- 引用证据点击跳转到原文对应段落并高亮
- 推荐文章卡片展示摘要 + favicon，点击直接切换到该文章
- 引用来源区分本地证据 `[n]` 和网络证据 `[Wn]`，样式差异化

### 6. 笔记功能

**编辑器升级**

- 当前为纯 textarea + 切换预览，升级为分屏编辑（左写右预览），或至少支持实时预览
- 工具栏：常用 Markdown 格式快捷按钮（加粗、标题、列表、链接、代码块）
- 笔记卡片「更多」按钮改为下拉菜单（编辑、删除、导出），替代当前直接删除

**笔记与内容关联**

- 从阅读区选中文本直接创建笔记（自动引用原文片段和来源）
- 笔记中引用文章片段时展示来源标记，点击可跳回原文
- 笔记支持 tag 标签，支持按标签筛选

**导出**

- 笔记导出为 Markdown 文件
- notebook 级别导出：所有笔记 + 高亮汇总为一个文档

### 7. 认证 & 账户

- OAuth 登录（Google / GitHub）：前端按钮已有，后端未接入
- 忘记密码 / 密码重置流程
- 头像上传（当前仅显示首字母）
- 登录页主题与主应用统一（当前登录页背景色写死浅色渐变，不跟随深色主题）

### X. 全局

**设计系统**

- 补全 CSS 变量体系：增加间距 scale（`--space-`*）、字号 scale（`--text-*`）、z-index 层级变量，减少硬编码 px
- 统一动效：集中定义 keyframes 和 transition duration/easing 变量，清理分散在各组件中的重复动画（`fadeIn` / `fadeInUp` / `modalSlideUp` 跨文件依赖）
- 深色模式全面覆盖：修复 HomePage 卡片菜单、部分阴影中的硬编码浅色值
- 错误与加载状态统一组件化（Spinner、ErrorBanner、EmptyState）

**主题与外观**

- 外观自动切换：`colorMode === 'auto'` 时监听 `prefers-color-scheme` 并响应变化
- 设置加载后同步服务端 `colorMode` 到本地 `ThemeProvider`（当前仅同步 accent，未同步明暗）
- 优化产品图标，统一圆角图标风格

**全局交互**

- 键盘快捷键体系：Esc 关闭弹窗（已有）、Cmd/Ctrl+K 全局搜索、Cmd/Ctrl+N 新建笔记等
- Toast 通知系统：操作成功/失败的轻量反馈（当前部分操作无反馈）
- 设置弹窗保存逻辑优化：当前按 Tab 保存（切 Tab 不自动保存），改为统一保存或切 Tab 时自动暂存

## 代码质量与优化

- 参考文章：[https://cloud.tencent.com/developer/article/2083713](https://cloud.tencent.com/developer/article/2083713)

### 1. Search 链路


| #   | 流程                       | 改进点                                                                                                        | 对应原则                  |
| --- | ------------------------ | ---------------------------------------------------------------------------------------------------------- | --------------------- |
| 1   | 入口(router)               | 搜索接口当前是同步阻塞式请求，整条搜索图执行完才返回；应改为 `创建会话 -> 入队 -> 立即返回 session_id -> 前端轮询/订阅结果`，避免长请求占满 worker                 | 3.3 异步 / 2.2 过载保护     |
|     |                          | 路由层缺少限流，用户可短时间重复点击触发多次搜索，直接放大对 Exa/Tavily/LLM 的压力；应加用户级 QPS / 并发数限制                                        | 2.3 流量控制 / 5.4 防刷     |
|     |                          | 入口未对 `query` 做长度上限、空白折叠、异常字符清洗，超长 query 会直接传给 LLM 和搜索引擎，增加成本与失败率                                           | 4.9 入参校验              |
|     |                          | `maxResults` 允许到 20，但内部实际只返回最多 10 条，接口契约与真实行为不一致，应统一入口约束与内部上限                                              | 4.7 最小惊讶              |
| 2   | 上下文加载                    | 每次搜索都实时读取 notebook 全量文章列表与摘要，缺少查询级缓存；可对 `existing_urls + summaries` 做短 TTL 缓存，减少重复 DB 压力                   | 3.2 缓存                |
|     |                          | Notebook 已有摘要较多时，当前只截取前 6~8 条，可能造成上下文偏差；应优先选择最近导入 / 最相关摘要，而非简单截断                                           | 4.1 充分必要              |
|     |                          | `preferred_sites` 仅做用户配置读取，没有进一步做合法性校验，应拒绝非法域名、过长列表、重复项过多等异常配置                                             | 4.8 避免无效请求 / 4.9 入参校验 |
| 3   | service 会话创建             | `start_agent_search()` 每次请求都新建 `SearchSession`，没有利用 `normalized_query` 做幂等复用；用户重试会重复跑整条链路                  | 2.10 幂等设计 / 4.6 用户重试  |
|     |                          | 建议引入 `Idempotency-Key`，或按 `user_id + notebook_id + normalized_query + mode + preferred_sites` 复用运行中会话      | 2.10 幂等设计             |
|     |                          | `execution_mode` 虽然有 `sync/queued` 字段，但当前固定走 `sync`，字段设计与实际行为不一致，建议真正启用异步执行模型                              | 4.5 统一原则 / 3.3 异步     |
|     |                          | `chat_model is None` 时直接报错，但图内其实已有 fallback 逻辑；应允许“无 LLM，仅搜索 provider”降级运行                                 | 2.1 降级兜底 / 2.6 最少依赖   |
| 4   | service 错误收尾             | 当前只对 `run_search_agent()` 包了异常处理，落库、更新状态、commit、缓存阶段异常会导致 session 停留在 `running`                            | 2.11 故障自愈 / 4.5 统一原则  |
|     |                          | 应把“结果保存 + 状态更新 + 缓存写入”纳入统一事务收尾，失败时明确写成 `failed` / `retryable_failed`                                       | 2.11 故障自愈 / 4.5 统一原则  |
|     |                          | 应补一个后台扫尾任务，定时清理长时间 `running` 的僵尸会话，避免前端长期轮询无结果                                                             | 2.11 故障自愈             |
| 5   | intent_analysis          | `_analyze_task_spec()` 依赖主 LLM 生成 query plan，但没有单独超时控制；若 planner 很慢，会拖住整条链路                                | 2.4 快速失败              |
|     |                          | query plan 生成完全交给 LLM，缺少规则兜底上的领域模板，如“官方文档型”“新闻型”“对比型”查询模板                                                  | 2.1 降级兜底 / 4.10 设计模式  |
|     |                          | 建议将 `search_type / time_sensitivity / authority_preference` 的推断部分规则化，LLM 只负责补充细节，降低模型不稳定带来的波动              | 2.7 简单可靠 / 2.6 最少依赖   |
| 6   | recall 规划                | `_plans_for_round()` 每轮都可能扩展查询，但没有基于“上一轮缺什么”动态调整，只是固定 round 模板，扩搜质量有限                                      | 4.1 充分必要              |
|     |                          | 当前 round 3+ 固定追加 `case study limitations`，对通用问题、中文问题、事实型问题并不一定合适                                           | 4.7 最小惊讶 / 2.7 简单可靠   |
|     |                          | 应根据上一轮结果分布动态补“权威源不足 / 新颖性不足 / 时间过旧 / 域名过度集中”等针对性扩搜                                                         | 4.3 内聚解耦 / 3.6 并发     |
|     |                          | 对已有文章只做域名/路径排除，无法避免同主题但不同 URL 的高重复结果；可引入基于标题/摘要的近重复过滤                                                      | 3.2 缓存 / 2.7 简单可靠     |
| 7   | recall provider 并发       | 当前一个请求会 fan-out 到多轮、多 query、双 provider，缺少总并发闸门，峰值时很容易压垮下游                                                  | 2.3 流量控制 / 2.2 过载保护   |
|     |                          | 建议对 Exa、Tavily 分别加 `asyncio.Semaphore` 或令牌桶，并设置每请求最大 provider 调用预算                                         | 2.3 流量控制              |
|     |                          | 应设置全链路 deadline，比如总预算 8s/15s，预算耗尽时直接停止扩搜，返回当前最优结果                                                          | 2.4 快速失败              |
|     |                          | 目前 provider 单次 timeout 为 30s，过长；建议按阶段使用更短超时，并结合 mode 配置不同预算                                                | 2.4 快速失败 / 2.2 过载保护   |
| 8   | recall provider 降级       | Exa/Tavily 某一个失败时当前可部分返回，但两个都失败就整条结果为空；可增加“使用最近成功缓存结果”的兜底                                                  | 2.1 降级兜底 / 3.2 缓存     |
|     |                          | 建议建立 provider 健康状态与熔断器，连续失败达到阈值后短时间不再请求该 provider，避免雪崩式无效调用                                                | 2.2 过载保护              |
|     |                          | `preferred_sites` 命中逻辑会在 round 1 额外多打一轮 provider，用户偏好域名过多时成本会明显上涨，应限制偏好站点数量                                | 4.8 避免无效请求 / 2.3 流量控制 |
|     |                          | 对 provider 返回的异常缺少统一错误分类，如 `timeout / rate_limit / auth / invalid_response`，不利于后续补偿处理                         | 4.5 统一原则              |
| 9   | recall 结果合并              | `_merge_candidates()` 主要按规范化 URL 去重，但未去掉 querystring、锚点、移动版/桌面版、镜像域名等变体，重复率仍可能偏高                           | 2.7 简单可靠 / 4.1 充分必要   |
|     |                          | 同 URL 只按 highlights 长短保留结果，可能把更权威的 provider 结果替换掉；建议用“provider 优先级 + 内容完整度 + 发布时间”综合决策                     | 4.1 充分必要              |
|     |                          | `seen_urls` 只记录 URL，不记录主题/语义重复，容易出现十条都讲同一件事的情况                                                             | 4.3 内聚解耦 / 2.7 简单可靠   |
| 10  | score LLM 打分             | `_llm_score_candidates()` 会对候选分批打分，但没有单独并发控制和预算控制；候选接近 50 时 LLM 成本和耗时都会明显增加                                | 2.3 流量控制 / 2.4 快速失败   |
|     |                          | 当前 relevance/authority/freshness/content_quality 混合“LLM + 规则”，但 `coverage_score` 只看 preferred site 命中，定义过窄 | 4.1 充分必要              |
|     |                          | 建议把 `coverage_score` 改为“是否补足不同维度信息”，如原理、案例、官方文档、近期动态，而不只是站点偏好                                              | 4.3 内聚解耦              |
|     |                          | LLM 打分失败时默认为空字典，最终大量依赖默认 0.55 等常数，结果可解释性较弱；应显式标记“规则评分模式”                                                   | 2.1 降级兜底 / 4.7 最小惊讶   |
|     |                          | 对 notebook summaries 的新颖性判断仅靠 token overlap，中文同义表达、不同语言、标题党内容都可能误判                                         | 4.1 充分必要              |
| 11  | score 选择策略               | `final_score >= 0.6` 是固定阈值，没有随 mode、query 类型、候选质量分布动态调整，容易出现“结果过少”或“混入低质量结果”                               | 4.1 充分必要              |
|     |                          | 当前达到 `target_count` 就停止，没有额外检查域名多样性、时效性、权威性是否满足最低要求                                                        | 2.7 简单可靠 / 4.1 充分必要   |
|     |                          | 建议增加二次筛选约束，如“至少 2 个不同域名”“至少 1 个高权威来源”“新闻型查询至少 1 个近期来源”                                                     | 4.3 内聚解耦              |
| 12  | finalize / 输出构造          | `whySelected` 与 tag 生成逻辑较硬编码，容易出现千篇一律的解释文案，用户难以理解差异                                                        | 4.7 最小惊讶              |
|     |                          | `authorityBadge`、`sourceTypeBadge` 主要靠域名规则判断，缺少更准确的来源分类，容易误标                                               | 4.1 充分必要              |
|     |                          | `importSuggestion` 只有 `duplicate_risk / recommended / optional` 三挡，可进一步区分“强推荐 / 背景阅读 / 仅补充视角”              | 4.7 最小惊讶              |
| 13  | 结果持久化(repo)              | `save_agent_search_results()` 先删旧结果再逐条插入并每条 `flush()`，批量效率较低，结果多时对 DB 压力偏大                                 | 3.5 批量 / 3.4 池化       |
|     |                          | `canonical_url` 直接写原始 URL，没有复用图内 `_normalize_url()` 的结果，导致存储层与计算层规范不一致                                     | 4.5 统一原则              |
|     |                          | `url_hash` 基于原始 URL 计算，若 URL 仅 querystring 不同会产生多条近重复数据                                                    | 2.10 幂等设计 / 4.5 统一原则  |
|     |                          | `expires_at=ts.replace(day=ts.day + 1)` 是脆弱实现，月底场景会出问题，应改成 `ts + timedelta(days=1)`                        | 2.7 简单可靠              |
| 14  | 结果读取(get_search_session) | `get_search_session()` 只在 `completed` 时返回结果，若异步化后处于 `running` 但已有部分结果，前端无法渐进展示                             | 3.3 异步 / 4.7 最小惊讶     |
|     |                          | 建议支持 `partial` 状态和阶段性结果读取，让用户在长搜索中先看到首批可用卡片                                                                | 2.1 降级兜底 / 3.3 异步     |
| 15  | 缓存                       | 目前只按 `search_session_id` 缓存最终响应，没有按查询维度复用结果，重复搜索收益不大                                                       | 3.2 缓存                |
|     |                          | 建议增加两级缓存：一级是 `search_session_id -> response`，二级是 `query_signature -> latest_completed_session`             | 3.2 缓存 / 2.10 幂等设计    |
|     |                          | 对 Exa/Tavily 的原始召回结果也可做分钟级缓存，避免同查询短时间内重复打 provider                                                         | 3.2 缓存 / 2.6 最少依赖     |
|     |                          | 需考虑缓存穿透与缓存雪崩，失败结果也应短 TTL 缓存，避免异常 query 被反复重打                                                               | 3.2 缓存 / 2.2 过载保护     |
| 16  | 安全与风控                    | 搜索 query 会直接发给外部 provider 和 LLM，应考虑对敏感信息、超长 token、潜在 prompt injection 片段做基础清洗或拦截                           | 5.x 低风险 / 4.9 入参校验    |
|     |                          | `preferred_sites` 如果允许任意配置，可能被用来定向打某些域名，应限制数量、长度和域名格式                                                      | 5.4 防刷 / 4.9 入参校验     |
|     |                          | 错误信息当前直接截取异常字符串，若下游报错携带敏感细节，可能被回写数据库；建议统一脱敏                                                                | 5.x 低风险 / 4.5 统一原则    |
| 17  | 架构与维护性                   | `graph.py` 同时承担编排、查询规划、provider 调用、打分、文案生成、响应组装，文件过大，后续改动风险高                                               | 4.2 单一职责 / 4.3 内聚解耦   |
|     |                          | 建议拆成 `planner.py / recall.py / scorer.py / presenter.py / provider_adapters.py`，让规则与编排分层                   | 4.2 单一职责 / 4.3 内聚解耦   |
|     |                          | 评分权重、authority pattern、阈值目前都硬编码在代码里，建议提到配置层或策略对象，便于实验与灰度                                                   | 4.4 开闭原则              |
| 18  | 跨阶段                      | 当前缺少统一的错误分类：可重试、不可重试、降级成功、部分成功、彻底失败，导致状态管理语义不清                                                          | 4.5 统一原则 / 2.11 故障自愈  |
|     |                          | 应给搜索链路建立显式状态机，如 `queued / running / partial / completed / failed / expired / cancelled`                    | 4.5 统一原则 / 3.3 异步     |
|     |                          | 对用户而言，最合理的体验是“优先返回可用结果，再逐步补齐”，而不是“全有或全无”，当前链路仍偏同步批处理思路                                                     | 2.1 降级兜底 / 3.3 异步     |


### 2. Ingest 链路


| #   | 流程                    | 改进点                                                                                               | 对应原则                 |
| --- | --------------------- | ------------------------------------------------------------------------------------------------- | -------------------- |
| 1   | 入口 (service)          | 前置校验 `IngestInput` 参数完整性，如 `FILE` 类型缺 `file_bytes` + `file_name` 应在入口就拒绝，而非深入 `fetch_content` 才报错 | 4.9 入参校验             |
|     |                       | `IngestInput` 显式声明 `notebook_title` 字段，去掉 `hasattr(ingest_input, "_notebook_title")` 的隐式契约        | 4.7 最小惊讶             |
|     |                       | 并发 ingest 同一内容时无互斥保护，两个请求同时通过 `content_hash` 去重检查会产生重复数据，需分布式锁或 DB unique constraint              | 2.10 幂等设计            |
| 2   | fetch                 | URL 拉取缺 SSRF 防护：未过滤 `localhost`/内网 IP/`file://` scheme，用户可探测内部服务                                  | 5.x 低风险              |
|     |                       | 文件下载是全量读入内存再判断 200MB 上限，应改 streaming + 预检 `Content-Length` 头，及早拒绝大文件                              | 2.4 快速失败             |
| 3   | detect                | Tika 服务不可用时无降级路径，整条链路直接断掉；可按文件扩展名做粗略 fallback 路由                                                  | 2.1 降级兜底             |
|     |                       | MIME 检测结果不在白名单内时默认路由到 `DocRoute.HTML`，应明确拒绝非支持类型（如可执行文件），避免传给 MinerU 引发非预期行为                      | 4.8 避免无效请求           |
| 4   | parse (MinerU)        | 无并发控制，大量源同时 ingest 时会向 MinerU 发起 N 个 batch，可能触发 API 限频；建议 `asyncio.Semaphore` 限流                  | 2.3 流量控制             |
|     |                       | 缺断路器：MinerU 连续 N 次失败后应临时熔断，避免持续发无效请求                                                              | 2.2 过载保护             |
|     |                       | MinerU 全面不可用时无兜底策略（如降级为 Tika 文本提取），PDF/Office/Image 类型永远返回 `None`                                 | 2.1 降级兜底             |
|     |                       | 相同文件重复 ingest 时 MinerU 会重新解析，可按 `content_hash` 缓存解析结果                                             | 3.2 缓存               |
|     |                       | MinerU 批量提交失败时当前不会影响 Job 创建，后续 worker poll 可能拿不到结果；提交结果应与 Job 状态强绑定，失败时直接标记可重试/失败                     | 2.11 故障自愈 / 4.5 统一原则 |
| 5   | normalize (remark)    | 每次调用都 fork Node.js 子进程，连续多篇 ingest 开销大；可改为常驻进程 + stdin/stdout 复用                                  | 3.4 池化               |
|     |                       | 相同 markdown 重复处理无缓存，可用 `content_hash → RemarkResult` 短期缓存                                         | 3.2 缓存               |
|     |                       | remark 渲染的 HTML 未经 sanitize 直接存库返回前端，原始 markdown 含 `<script>` 或 `onerror` 时存在存储型 XSS 风险           | 5.1 防 XSS            |
| 6   | enhance               | `generate_summary` 是非关键路径但阻塞主链路，失败也只 warning；应异步化/后台化，不拖慢 phase 3→4 推进                            | 3.3 流程异步             |
|     |                       | TOC LLM fallback 长期为 TODO，等于 TOC 为空时没有实际兜底                                                        | 2.1 降级兜底             |
|     |                       | `enhance` 与 `build_chunks` 之间无数据依赖，可 `asyncio.gather` 并行执行                                        | 3.6 并发               |
| 7   | index (chunk + embed) | `build_chunks` 未设置 `section_id` / `heading_title`，chunk 丢失了章节归属信息，TOC 和分块没有关联                     | 4.3 内聚               |
|     |                       | embedding batch 无 size 控制，长文档上千 chunk 一次性发送可能超出 API 限制                                            | 3.5 批量               |
| 8   | 跨阶段                   | 错误处理不统一：有的 catch-all → `None`，有的 catch-all → warning，有的直接抛出；缺少统一的错误分类（可重试 / 不可重试 / 降级）            | 4.5 统一原则             |
|     |                       | `pipeline.py` 有 5 处函数体内延迟 import，模块依赖关系不透明                                                        | 4.5 统一原则             |
|     |                       | ingest 失败后 `parse_status: "failed"` 就结束，没有重试队列或用户触发重试的机制                                          | 2.11 故障自愈            |


### 3. Summary 链路


| #   | 流程                   | 改进点                                                                                                                                                                          | 对应原则                 |
| --- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| 1   | 入口(router / service) | `/summary/stream` 名义上是流式接口，但当前要等 `generate_summary()` 全部完成后才一次性返回全文；长文应改为 `queued job + 轮询/订阅结果`，或至少支持段落级渐进输出                                                                | 3.3 异步 / 2.2 过载保护    |
|     |                      | 路由层当前把 `language` 固定传成 `zh`，而 `generate_summary()` 与缓存模型本身支持多语言，接口能力与实现能力不一致                                                                                                 | 4.5 统一原则 / 4.7 最小惊讶  |
|     |                      | 缺少摘要请求级并发限制和总超时预算，超长文章会长时间占用 SSE 连接与模型调用资源                                                                                                                                   | 2.3 流量控制 / 2.4 快速失败  |
| 2   | 缓存(service + repo)   | `get_cached_summary()` 只按 `article_id + content_hash + prompt_version` 取缓存，但 `save_summary_cache()` 实际写入了 `model_provider / model_name / output_language`；不同模型或输出语言可能串用同一条缓存 | 4.5 统一原则 / 3.2 缓存    |
|     |                      | `save_summary_cache()` 只追加不 upsert/去重，重复生成会写出多条相同缓存；后续 `scalar_one_or_none()` 存在多行命中风险                                                                                       | 2.10 幂等设计 / 2.7 简单可靠 |
|     |                      | 中文请求命中英文缓存时会走 `_translate_to_chinese()` 二次 LLM 翻译，但译文不单独缓存，重复请求会反复付费                                                                                                         | 3.2 缓存 / 2.6 最少依赖    |
| 3   | analyze_content      | `analyze_content()` 主要靠前 3000 字关键词和 `char / 4` 的粗略 token 估算判定 `article_type`，对研究报告、教程、新闻混合文档容易误分型                                                                            | 4.1 充分必要             |
|     |                      | `model_tier` 只按 token 数量分 `lite / standard`，没有结合真实模型上下文窗、代码比例、表格密度等因素做更稳妥的决策                                                                                                 | 4.1 充分必要 / 2.7 简单可靠  |
|     |                      | 缺少“分类不确定”或“低置信度”兜底路径，后续很难系统性优化阈值和分型规则                                                                                                                                           | 2.11 故障自愈 / 4.5 统一原则 |
| 4   | compress             | `compress_content()` 对代码块、长表格、图片使用固定压缩规则，代码文档或数据密集型文档可能在压缩阶段丢掉关键信息                                                                                                           | 4.1 充分必要             |
|     |                      | 压缩策略没有按 `article_type` 做差异化，例如 `code_heavy` 应保留更多代码上下文，表格文档应保留更多数据行                                                                                                          | 4.3 内聚解耦             |
|     |                      | 压缩结果不缓存，重试和重复摘要都会重复做同样的字符串处理，长文档场景下存在额外 CPU 开销                                                                                                                               | 3.2 缓存 / 3.4 池化      |
| 5   | summarize 路由         | 图里只按 `summary_map_reduce_threshold_tokens` 决定 `direct` 或 `map-reduce`，没有结合压缩后长度、结构复杂度、模型窗口做更稳妥的路由                                                                            | 4.1 充分必要             |
|     |                      | `validate_summary` 失败后的重试固定跳回 `direct_summarize`，长文第一次走 `map-reduce` 失败后会退回 direct，存在超长上下文和策略漂移问题                                                                            | 4.5 统一原则 / 2.7 简单可靠  |
|     |                      | `map_split()` 仅按固定字符数和段落边界切块，没有按标题/章节切分，跨段语义和结构信息容易断裂                                                                                                                        | 4.3 内聚解耦             |
| 6   | summarize 节点执行       | `direct_summarize / map_summarize / reduce_summarize` 都没有单独 timeout 与总预算控制，慢模型或长文会拖慢整条链路                                                                                     | 2.4 快速失败             |
|     |                      | 生成失败时当前常返回空字符串或拼接 `chunk_summaries`，缺少显式“降级成功/失败”标记，调用方难区分质量层级                                                                                                               | 2.1 降级兜底 / 4.7 最小惊讶  |
|     |                      | map 阶段 chunk 数量没有上限与并发预算，大文档在 `map-reduce` 路径上容易放大 LLM 调用次数与成本                                                                                                               | 2.3 流量控制 / 3.5 批量    |
| 7   | validate             | `validate_summary()` 只把 `title + summary` 发给 judge，没有把源文正文或压缩后的 evidence 发进去，几乎无法真正检查“摘要是否忠于原文”                                                                              | 4.1 充分必要             |
|     |                      | validator 返回非 JSON 或解析异常时，当前默认 `passed=True`，会把 judge 失效误判成校验通过                                                                                                              | 2.7 简单可靠 / 4.5 统一原则  |
| 8   | 持久化                   | `generate_summary()` 只有 `summary_text` 非空才落库，失败场景没有状态记录或补偿机制，重复请求会一直全量重跑                                                                                                     | 2.11 故障自愈 / 3.2 缓存   |
|     |                      | notebook 侧 `list_notebook_summaries()` 只读缓存不回补，摘要长期缺失时不会自动修复，search 上下文质量会持续下降                                                                                               | 2.11 故障自愈 / 4.3 内聚解耦 |


### 4. Chat 链路


| #   | 流程                   | 改进点                                                                                                        | 对应原则                 |
| --- | -------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------- |
| 1   | 入口(router)           | 聊天入口未像 search 那样先校验 notebook / article 是否存在且归属当前用户；当前 service 只是尽力读取标题，找不到也继续回答，容易产生“在错误上下文里回答”的隐性问题       | 4.9 入参校验 / 4.7 最小惊讶  |
|     |                      | `ChatRequest.message` 只做了 `min_length=1` 校验，缺少长度上限、空白折叠、异常字符清洗，超长问题会直接进入检索和模型调用                            | 4.9 入参校验             |
|     |                      | 聊天 SSE 路由缺少用户级限流与并发保护，重复发送或刷接口会同时放大本地检索、联网搜索和主模型压力                                                         | 2.3 流量控制 / 5.4 防刷    |
| 2   | 上下文初始化(service)      | `conversation_id` 无效或不属于当前用户时，当前逻辑会静默创建新会话而不是显式报错，用户体验与接口语义不一致                                             | 4.7 最小惊讶 / 4.5 统一原则  |
|     |                      | 只加载最近 6 条消息，`rolling_summary` 字段已建模但完全未使用，长对话会快速丢失更早上下文                                                    | 4.3 内聚解耦 / 4.1 充分必要  |
|     |                      | 用户消息会在回答生成前先写库，若中途断流或模型失败，会留下只有 user turn 的半条对话，缺少会话级状态或补偿                                                 | 2.11 故障自愈 / 4.5 统一原则 |
| 3   | 编排层(service / graph) | `chat/graph.py` 已定义完整 LangGraph，但 HTTP 主路径实际走 `service.py` 手工串行编排，线上链路与图编排已经分叉                             | 4.5 统一原则 / 4.2 单一职责  |
|     |                      | 主路径没有统一的 node-level timeout、全链路 deadline 和 cancel 传播，慢检索或慢联网会直接拖长 TTFB 和总时延                                | 2.4 快速失败 / 2.2 过载保护  |
|     |                      | 前置节点异常目前大多吞掉后继续生成回答，但没有把“降级成功 / 部分失败”显式返回给前端或落库                                                            | 2.1 降级兜底 / 4.7 最小惊讶  |
| 4   | query_router         | `query_router_node()` 先走简单关键词规则，再走 lite_model 分类，规则较脆，对含糊问题和多意图问题容易误路由                                     | 4.1 充分必要             |
|     |                      | router 的 LLM 路由没有单独 timeout 与熔断策略，lite_model 抖动时会拖住整条链路的首包时间                                               | 2.4 快速失败 / 2.2 过载保护  |
|     |                      | `tools_needed` 与 `web_search_broker` 的契约不一致：broker 检查 `"web_search"`，但 router 的 `_TOOLS_MAP` 实际从不产出该标记     | 4.5 统一原则             |
| 5   | retrieval_planner    | `RetrievalPlanSpec` 里规划了 `dense_top_k / sparse_top_k / rerank_top_n`，但后续执行并未完整消费，规划和执行存在脱节                 | 4.5 统一原则 / 4.3 内聚解耦  |
|     |                      | 当前策略主要按 route 粗粒度决定 `chunk_only / article_then_chunk / hybrid`，没有结合问题难度、历史轮次、证据充分度动态调参                     | 4.1 充分必要             |
|     |                      | planner 没有针对“大 notebook”“无索引 notebook”“推荐类问题”设置更保守的 retrieval 预算，容易把低价值问题也拉满检索成本                           | 2.3 流量控制 / 4.1 充分必要  |
| 6   | retrieval_engine     | `retrieval_engine_node()` 内部重新创建 DB session，而不是复用请求 session，增加连接开销，也让链路事务边界更分散                             | 3.4 池化 / 4.5 统一原则    |
|     |                      | `notebook_search` 会先取 notebook 下全部已索引 article_id，再做全量 hybrid retrieval；大 notebook 下检索范围过宽，成本和时延都会明显上升      | 3.7 存储设计 / 2.3 流量控制  |
|     |                      | 检索失败或无结果时当前直接返回空 evidence，缺少更轻量的降级路径，如 article summary 检索、article recall-only 或显式告知证据不足                    | 2.1 降级兜底 / 2.11 故障自愈 |
| 7   | web_search_broker    | 联网决策目前主要依赖 freshness 关键词和本地分数阈值，`WEB_BROKER_SYSTEM` prompt 并未真正接入，判定逻辑较粗                                   | 4.1 充分必要 / 4.5 统一原则  |
|     |                      | `_execute_search()` 使用全局默认 Tavily / Exa key，而不是当前用户配置；多用户场景下权限边界和配额统计都不清晰                                  | 2.6 最少依赖 / 4.5 统一原则  |
|     |                      | 联网搜索没有查询缓存、限流、熔断与总预算控制；重复问题会重复打外部 provider，且与 local evidence 没做去重融合                                        | 3.2 缓存 / 2.3 流量控制    |
| 8   | answer 生成            | 主 SSE 路径直接 `model.astream()`，绕过了 `answer_generator_node()`；图定义的节点与真实运行路径不一致                                       | 4.5 统一原则 / 4.2 单一职责  |
|     |                      | prompt 直接拼接原始 `local_evidence` 与 `web_evidence` 文本，没有做 prompt injection 防护，恶意网页内容或文章内容可能污染回答               | 5.x 低风险 / 4.9 入参校验   |
|     |                      | 当前只有 snippet 级截断，没有统一 context budget，历史对话、local evidence、web evidence 叠加后容易挤压真正回答空间                        | 3.5 批量 / 4.1 充分必要    |
| 9   | citation_verifier    | `citation_verifier_node()` 只校验引用编号是否在 evidence 范围内，不校验回答 claim 是否真的被对应证据支持                                 | 4.1 充分必要             |
|     |                      | 非法引用会从 `verified_citations` 中被丢弃，但回答正文不会被重写或重编号，前端看到的 answer 与 evidence 可能不一致                              | 4.7 最小惊讶 / 4.5 统一原则  |
|     |                      | 缺少基于 citation coverage 的反馈闭环，例如“低覆盖时二次生成”或“回答改写为无引用模式”，当前校验更像事后统计而非质量控制                                    | 2.11 故障自愈 / 4.1 充分必要 |
| 10  | 持久化 / 会话状态           | `append_message()` 不会更新 `Conversation.updated_at / last_message_at / current_article_id`，会话元数据随聊天推进而失真     | 4.5 统一原则 / 2.7 简单可靠  |
|     |                      | `rolling_summary` 字段已建模但未参与任何读写流程，长对话压缩与恢复能力处于半成品状态                                                        | 4.3 内聚解耦             |
| 11  | 安全                    | 对外部网页证据和本地文章片段缺少敏感信息过滤与安全分级，可能把不该暴露的上下文直接送入模型与前端                                                           | 5.x 低风险 / 4.9 入参校验   |


### 5. 代码质量 & 技术债

- Chat graph（`chat/graph.py`）已定义但未接入 HTTP 路径，`stream_message` 手动编排节点，应统一走 LangGraph
- `tools/`（exa_search / web_search LangChain tool）已定义但全仓库无 import，清理或接入
- `retrieval_planner` 输出的 `dense_top_k` / `sparse_top_k` 未传入 `HybridRetrievalRequest`，实际 top 由 settings 控制
- `ingest/index.py` 中 `embed_chunks` 使用 `resolve_embedding_runtime_config(None)`，多用户场景下未区分用户 embedding 配置
- `ingest/enhance.py` 中 LLM 生成 TOC 标记为 TODO 未实现
- `settings/service.py` 中 `_publish_reindex_jobs` 异常被 `except Exception: pass` 吞掉，重索引任务可能静默丢失
- `config.py` 中 `grok_`*、`search_use_llm_task_parser`、`redis_inspection_*`、`api_metrics_port` 已定义但未使用，清理或实现
- `notes/__init__.py` 仍写 "placeholders"，与已有实现不一致
- `web_search_broker` 使用全局默认 API key 而非用户配置的 key
- Kafka consumer 当前在 handler 异常后仍 commit offset，偏向 at-least-once，但缺少失败重试和退避机制
- 异步任务基础设施没有死信队列（DLQ），失败的 ingest 任务缺少隔离与重投通道
- Job 状态机虽然已有 `max_attempts`、`dead` 等状态，但 worker 侧重试逻辑未完整对接，状态设计与实际消费流程脱节

