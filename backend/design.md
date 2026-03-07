## 1. API 定义

### 1.1 通用约定

接口统一挂在 `/api`，鉴权继续用 `Authorization: Bearer <token>`，时间统一返回 ISO 8601。响应 envelope 继续保留 `success / item / items / message / meta`，错误码继续沿用当前约定的 `400/401/403/404/409/422/500`。这部分我不建议再改，因为前端已经围绕这个约定组织了处理逻辑。`GET /api/notebooks/:notebookId` 仍然是中心接口，当前阶段继续一次性返回 `articles + notes`，这样前端最容易从 mock 切到真实后端。

### 1.2 Auth / Settings / Account

`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/auth/me` 按标准认证接口做，不是本轮难点。`PATCH /api/account/profile` 继续只改用户名，`POST /api/account/password` 继续只改密码，这两条不需要额外设计复杂逻辑。

`GET /api/settings` 我建议改成**聚合视图**，而不是“数据库表一比一吐出”。原因是这里面有三类东西：一类是用户偏好，例如 `outputLanguage`、`themeColor`、`colorMode`；一类是模型设置，例如 `modelProvider`、`modelName`、`apiUrl`；还有一类是用户身份字段 `username`。`username` 不属于 settings，本质上来自 `users.name`。所以响应应该长这样：

```json
{
  "success": true,
  "item": {
    "outputLanguage": "中文",
    "themeColor": "ocean",
    "colorMode": "light",
    "modelProvider": "OpenAI",
    "modelName": "gpt-4o",
    "apiUrl": "https://api.openai.com/v1",
    "hasApiKey": true,
    "apiKeyMasked": "sk-***9f2a",
    "username": "张三"
  }
}
```

这里最关键的改动是：**不再返回原始 `apiKey`**。因为当前前端模型是把 `apiKey` 当普通文本字段，但真正后端实现时，明文回显会让后续日志、脱敏、局部更新都变脏。

`PUT /api/settings` 继续保留当前路由，但在语义上按 **merge-patch** 处理。也就是请求只带要改的字段；没带的不动。`apiKey` 的规则要写死：请求里没有 `apiKey` 就表示“不改”；带了非空 `apiKey` 就表示“替换”；带 `clearApiKey=true` 才表示“删除”。不要把空字符串同时解释成“未修改”和“清空”，否则前后端都会很难受。你之前质疑 `user_settings` 单表的问题，根源就在这里：**不是 settings 字段多，而是 `apiKey` 和普通设置字段的语义不同。**

### 1.3 Notebooks / Notes

我建议把 notebook 这一层补完整，而不是只停在读取。最小集合是：`POST /api/notebooks` 创建 notebook，`GET /api/notebooks` 列表，`GET /api/notebooks/:notebookId` 详情，`PATCH /api/notebooks/:notebookId` 修改标题、emoji、color。删除 notebook 这一期先不做，你前面已经明确了这一点。

`GET /api/notebooks/:notebookId` 仍然返回 `NotebookDetail`，但我要补一个关键解释：`articles[].content` 的来源不是永远都等于最终 `clean_markdown`，而是**优先返回 `clean_markdown`，没有的话回落到 `preview_markdown`**；`toc` 在正文还没准备好时就是空数组。这样你既不用把“导入后后台解析”的状态暴露给前端，也不会让用户导入后点进来看到一片空白。你前面说前端不需要感知异步导入状态变化，这个设计正好满足这个前提。

`POST /api/notebooks/:notebookId/notes`、`PUT /api/notebooks/:notebookId/notes/:noteId`、`DELETE /api/notebooks/:notebookId/notes/:noteId` 继续按当前契约做。这里我建议数据库里只存 `title`、`content_markdown`、`note_type`、`source_count`，不要把前端显示用的 `time` 文案落库；`time` 由响应层根据 `updated_at` 格式化即可。

### 1.4 Sources Search：同一路由，按 mode 决定同步还是异步

这里是本次设计的重点。我建议保留现有路由 `POST /api/notebooks/:notebookId/sources/search`，但把请求体从 `searchMode + researchMode` 收敛成一个字段 `mode`。因为当前后端只有 web 搜索，没有第二种搜索域，`searchMode=web` 这个字段只是 UI 概念，放在 API 里没有信息增量。请求改成下面这样：

```json
{
  "query": "crowd density estimation",
  "mode": "auto",
  "maxResults": 10,
  "freshnessHours": 24
}
```

`mode` 取值我建议只暴露三个：`fast`、`auto`、`deep`。`fast` 用于低延迟候选发现，`auto` 作为默认模式，`deep` 用于更重的来源发现。Exa 官方把这三档的质量与延迟分得非常清楚：`fast` 是低延迟档，`auto` 是默认平衡档，`deep` 是多秒级的高质量档；`instant` 虽然更快，但更适合 typeahead，不适合当前主搜索按钮。([Exa](https://exa.ai/docs/reference/search-best-practices))

这个接口的返回分两种形态。`fast` 和 `auto` 直接同步返回 `200`：

```json
{
  "success": true,
  "item": {
    "searchSessionId": "ss_01JXYZ",
    "mode": "auto",
    "modeLabel": "Web",
    "status": "completed",
    "execution": "sync"
  },
  "items": [
    {
      "id": "srr_01JXYZ",
      "title": "Deep Research 报告：基于 YOLO 的人群密度估计",
      "description": "......",
      "icon": "🔴",
      "url": "https://example.com/1",
      "selected": true
    }
  ],
  "meta": {
    "provider": "exa",
    "elapsedMs": 920
  }
}
```

`deep` 则立即返回 `202`，告诉前端这是异步任务：

```json
{
  "success": true,
  "item": {
    "searchSessionId": "ss_01JXYZ",
    "mode": "deep",
    "modeLabel": "Deep",
    "status": "queued",
    "execution": "async"
  },
  "message": "search accepted"
}
```

然后新增一个读取接口：`GET /api/notebooks/:notebookId/search-sessions/:searchSessionId`。这个接口返回 session 状态和结果；如果还没完成，`items` 为空；完成后 `items` 就是搜索结果卡片。这样你不用把同步和异步拆成两套产品，而是**一套搜索接口，两种执行模式**。这比“先做同步，以后再异步”的版本化说法更稳，因为它直接对齐了 provider 的能力边界。当前契约里虽然写了“先同步，deep 以后再升级任务制”，但那只是阶段性实现建议，不是最优最终设计。([Exa](https://exa.ai/docs/reference/evaluating-exa-search))

还有一个非常重要的实现细节：**搜索结果一定要在服务端落成 `search_session + search_results`，不能只回给前端。** 因为导入时不是用户把 URL 重传回来，而是只提交选中的结果 ID；而且你自己也已经指出 `sourceIds` 这个定义不够准。我的建议是：`searchSessionId` 用来指代整次搜索，`searchResultId` 用来指代每条结果，`searchResultId` 必须是服务端生成的全局唯一 ULID，而不是 provider 原始 ID。当前历史文档已经明确指出，search 阶段是“找什么”，import 阶段才是“进 notebook”，所以这两层一定要分开。

### 1.5 Sources Import：不再传 `sourceIds`，而是 `searchSessionId + searchResultIds`

`POST /api/notebooks/:notebookId/sources/import` 建议改成：

```json
{
  "searchSessionId": "ss_01JXYZ",
  "searchResultIds": ["srr_01JXYZ", "srr_01JXYA"]
}
```

这样改的原因很直接：导入动作本质上是在“某次搜索会话里，从候选结果中选择若干条加入 notebook”。只传 `sourceIds`，语义不完整；只传 URL 快照，前端又要背持久化和一致性。`searchSessionId + searchResultIds` 这对组合才是后端真正可以依赖的主键语义。

这个接口的执行流程应该写死成下面这样。先校验 session 归属和结果归属；再做 notebook 内去重；然后批量创建 article 占位记录；再创建异步 `jobs`；最后提交事务并返回新的 notebook detail。这里不应该直接在请求线程里抓网页、切 chunk、做 embedding。因为导入成功和索引完成不是同一个时刻，这一点你们自己的 history 里已经说得很清楚。

这个接口我建议继续返回 `NotebookDetail`，原因不是 REST 最优，而是当前前端最容易直接接上。只不过这里的 `articles[].content` 不再要求一定是完整正文，而是按上面说的规则返回 `clean_markdown` 或 `preview_markdown`。这样用户导入后立刻就能看到 article 卡片和一个可读预览，不需要额外引入“processing”状态给前端。这个“预览正文”来自搜索阶段已经存下来的 highlights，而 Exa 的 Search/Contents 文档都明确支持返回 query-relevant highlights 和 clean markdown，这正好可以拿来做导入后的即时可见内容。([Exa](https://exa.ai/docs/reference/search))

### 1.6 Manual Source 与 Upload

`POST /api/notebooks/:notebookId/sources` 只处理两类 JSON 输入。`sourceType=web` 时，接收 `url` 和可选 `title`；`sourceType=text` 时，接收 `title` 和 `content`。这条接口不需要搜索会话，因为 notebook 在提交时就已经确定了；所以它是**创建即确认**，可以直接写 article 并进入解析队列。

`POST /api/notebooks/:notebookId/sources/upload` 继续保留 `multipart/form-data` 和字段名 `files`，但产品范围要明确收窄成 `pdf/docx/txt/md`。当前契约还写了图片和音频，这部分我建议你直接从文档里删掉，因为本轮你已经明确不做。上传后同步返回 notebook detail，后端内部直接进入同一条 ingest pipeline，不要真的按旧契约只存元数据然后什么都不做。

### 1.7 Summary 与 Chat

`POST /api/notebooks/:notebookId/articles/:articleId/summary` 我建议用一个很干净的定义：请求体可为空，也允许可选传 `outputLanguage` 和 `forceRefresh`；响应统一放进 `item.summary`，不要再顶层单独放一个 `summary` 字段。当前契约里 summary 第一版就是 prompt 直出，这个方向没问题；我这次只是把响应 envelope 对齐了。

`POST /api/notebooks/:notebookId/chat` 继续保留 `conversationId`、`articleId`、`message` 这三个核心字段，其中 `conversationId` 可以为空，表示由后端新建会话。响应里我建议加上可选 `citations` 字段，但第一轮可以为空数组。你们当前契约里已经很清楚地说了：前端不要自己拼消息历史，后端负责会话持久化、窗口裁剪、摘要压缩、RAG 检索和 prompt 组装；这点我完全保留。

这里我再补一条落地规则：`summary` 和 `chat` 默认只在 `clean_markdown` 准备完成后开放。如果 article 还只有 `preview_markdown`，接口直接返回 `409 article_not_ready`。这不是因为技术做不到，而是因为如果你在 preview 上做 summary/chat，用户得到的其实是“搜索结果摘要的摘要”，质量很不稳定，后面会一直解释不清。

## 2. 数据库定义

这一版数据库我建议直接落成下面这些表：`users`、`notebooks`、`notes`、`search_sessions`、`search_results`、`articles`、`article_chunks`、`conversations`、`messages`、`summary_cache`、`jobs`。我**不建议**建 `user_settings`、`sources`、`article_summary`、`recommendation_cache`。原因分别是：用户设置天然 1:1 且总是一起读取，拆表收益很低；当前产品里“来源”最终就是 article，单独抽 `sources` 只会增加一次跳转；摘要是用户触发能力，不是持久化领域对象；相关推荐这期是聊天时实时检索，不是传统推荐系统。这个取舍会让你的系统明显更轻，也更符合你自己已经确认的产品边界。

### 2.1 `users`

```sql
users (
  id uuid primary key,
  email citext not null unique,
  name text not null,
  password_hash text not null,
  avatar_url text null,

  settings_json jsonb not null default '{}',

  llm_api_key_ciphertext text null,
  llm_api_key_last4 varchar(4) null,
  llm_api_key_updated_at timestamptz null,

  created_at timestamptz not null,
  updated_at timestamptz not null
)
```

`settings_json` 只放普通设置：`outputLanguage`、`themeColor`、`colorMode`、`modelProvider`、`modelName`、`apiUrl`。`apiKey` 单独加密存，不放 JSON。这样做是为了让 `GET /settings`、`PUT /settings`、日志脱敏、局部更新都简单。

### 2.2 `notebooks`

```sql
notebooks (
  id uuid primary key,
  user_id uuid not null references users(id),
  title text not null,
  emoji text null,
  color text null,
  created_at timestamptz not null,
  updated_at timestamptz not null
)
```

`sourceCount` 不落库，查询时按 `articles` 聚合。`date` 也不落库，响应层根据 `created_at` 格式化。

### 2.3 `notes`

```sql
notes (
  id uuid primary key,
  notebook_id uuid not null references notebooks(id),
  title text not null,
  content_markdown text not null,
  note_type text not null,
  source_count integer not null default 0,
  created_at timestamptz not null,
  updated_at timestamptz not null
)
```

`time` 是视图字段，不落库。`sources` 当前前端只是数量，不需要先做 note-article 关系表。

### 2.4 `search_sessions`

```sql
search_sessions (
  id uuid primary key,
  user_id uuid not null references users(id),
  notebook_id uuid not null references notebooks(id),

  query text not null,
  normalized_query text not null,
  mode text not null,                     -- fast | auto | deep
  execution_mode text not null,          -- sync | async
  provider_name text not null,           -- exa
  provider_request_json jsonb not null,

  status text not null,                  -- queued | running | completed | failed | expired
  mode_label text not null,
  result_count integer not null default 0,

  error_code text null,
  error_message text null,

  created_at timestamptz not null,
  completed_at timestamptz null,
  expires_at timestamptz null
)
```

这张表既是搜索审计表，也是异步 deep search 的状态表。**不需要再单独建 search_jobs 表。** 如果是同步模式，session 在一个请求里从 `running` 变 `completed`；如果是异步模式，worker 去推进它。

### 2.5 `search_results`

```sql
search_results (
  id uuid primary key,                           -- 全局唯一 searchResultId
  search_session_id uuid not null references search_sessions(id),

  provider_result_id text null,
  raw_url text not null,
  canonical_url text not null,
  url_hash char(64) not null,

  title text not null,
  description text null,
  author text null,
  published_at timestamptz null,
  domain text null,
  favicon_url text null,

  display_rank integer not null,
  preview_markdown text null,                   -- 来自 Exa highlights / summary
  raw_payload_json jsonb not null,

  created_at timestamptz not null
)
```

这里的 `preview_markdown` 是本次设计里非常值钱的一个字段。因为它可以在 import 之后立刻变成 article 的 `preview_markdown`，从而让 notebook detail 在全文还没准备好之前也有内容可显示。

### 2.6 `articles`

```sql
articles (
  id uuid primary key,
  user_id uuid not null references users(id),
  notebook_id uuid not null references notebooks(id),

  input_type text not null,                     -- search_result | url | text | file
  origin_search_session_id uuid null references search_sessions(id),
  origin_search_result_id uuid null references search_results(id),

  source_url text null,
  normalized_url text null,
  dedupe_key char(64) not null,

  source_title_raw text null,
  raw_text_input text null,

  file_name text null,
  file_ext text null,
  file_mime text null,
  file_size bigint null,
  file_storage_key text null,

  title text not null,
  author text null,
  published_at timestamptz null,
  language text null,

  preview_markdown text null,
  clean_markdown text null,
  toc_json jsonb null,
  content_hash char(64) null,

  parser_name text null,
  parse_status text not null,                  -- queued | fetching | parsing | ready | failed
  parse_error_tag text null,
  parse_error_message text null,
  parse_quality_score numeric(5,2) null,

  article_retrieval_text text null,
  article_tsv tsvector null,
  article_vector vector(<EMBED_DIM>) null,

  chunk_status text not null,                  -- not_started | running | ready | failed
  index_status text not null,                  -- not_started | ready | failed

  created_at timestamptz not null,
  updated_at timestamptz not null,
  ingested_at timestamptz null
)
```

这张表同时承载“来源输入信息”和“解析后的标准内容”。这是有意的，不是偷懒。因为当前产品里，一条来源最终就是 notebook 里的一篇 article；先拆两张表只会增加一层 join 和一层心智负担。

`article_retrieval_text` 是一个**确定性构造字段**，不是 `article_summary`。我建议用 `title + headings + clean_markdown 前 N 字符` 生成。这样检索层不依赖 LLM 摘要，行为更可控。

### 2.7 `article_chunks`

```sql
article_chunks (
  id uuid primary key,
  article_id uuid not null references articles(id),
  chunk_index integer not null,
  section_path text null,
  heading_title text null,
  token_count integer not null,
  chunk_text text not null,
  chunk_vector vector(<EMBED_DIM>) null,
  created_at timestamptz not null
)
```

这张表只做一件事：给 chunk-level retrieval 和 citation 用。不要把 UI 字段、状态字段、调试字段塞进来。

### 2.8 `conversations` 与 `messages`

```sql
conversations (
  id uuid primary key,
  user_id uuid not null references users(id),
  notebook_id uuid not null references notebooks(id),
  last_article_id uuid null references articles(id),
  rolling_summary text null,
  created_at timestamptz not null,
  updated_at timestamptz not null
)
messages (
  id uuid primary key,
  conversation_id uuid not null references conversations(id),
  role text not null,                          -- user | assistant | system
  content text not null,
  article_id uuid null references articles(id),

  model_provider text null,
  model_name text null,
  prompt_version text null,

  retrieval_mode text not null,                -- none | current_article | article | article_chunk
  retrieval_snapshot_json jsonb null,

  prompt_tokens integer null,
  completion_tokens integer null,
  created_at timestamptz not null
)
```

`retrieval_snapshot_json` 非常有价值，因为你后面查“为什么这一轮答成这样”，不需要重跑检索就能知道当时用了哪些文章或 chunk。

### 2.9 `summary_cache`

```sql
summary_cache (
  id uuid primary key,
  article_id uuid not null references articles(id),
  content_hash char(64) not null,
  prompt_version text not null,
  model_provider text not null,
  model_name text not null,
  output_language text not null,
  summary_text text not null,
  created_at timestamptz not null,
  expires_at timestamptz null
)
```

这一张表一定要把 `content_hash` 放进去。因为摘要缓存不是“按 article 记住一次就完事”，而是“按 article 当前内容版本记住一次”。你之前指出的那个问题是对的：没有 `content_hash`，缓存一定会脏。

### 2.10 `jobs`

```sql
jobs (
  id uuid primary key,
  job_type text not null,                      -- search_deep | article_ingest | article_reindex
  article_id uuid null references articles(id),
  search_session_id uuid null references search_sessions(id),

  dedupe_key text not null,
  payload_json jsonb not null,

  status text not null,                        -- pending_publish | queued | running | succeeded | failed | dead
  attempts integer not null default 0,
  max_attempts integer not null default 3,
  last_error text null,

  trace_id text null,
  created_at timestamptz not null,
  available_at timestamptz not null,
  started_at timestamptz null,
  finished_at timestamptz null
)
```

这张表必须保留。RocketMQ 是运输层，`jobs` 是业务真相层。你后面所有失败补偿、幂等、防重、人工修复、trace 串联，都靠它。

### 2.11 关键索引

```sql
create unique index uq_articles_notebook_dedupe
on articles(user_id, notebook_id, dedupe_key);

create index idx_search_results_session_rank
on search_results(search_session_id, display_rank);

create index idx_articles_notebook_created
on articles(notebook_id, created_at desc);

create index idx_articles_tsv
on articles using gin(article_tsv);

create index idx_articles_vector
on articles using hnsw(article_vector vector_cosine_ops);

create index idx_article_chunks_vector
on article_chunks using hnsw(chunk_vector vector_cosine_ops);

create unique index uq_summary_cache_key
on summary_cache(article_id, content_hash, prompt_version, model_provider, model_name, output_language);
```

## 3. 架构设计与技术选型

### 3.1 搜索 provider：初版只接 Exa，但必须抽象成 provider 层

我建议初版**只实现 Exa**，不要一开始接两个以上 provider。原因不是别的 provider 不行，而是你现在真正难的部分不在“多 provider 管理”，而在“search session / import / ingestion / retrieval / chat” 这一整条链路。Exa 的优势在于它不是只给你十条蓝链：`/search` 能搜并提取结果内容，`/contents` 能对 URL 提取 clean markdown、处理 JS-rendered 页面、PDF 和复杂布局，还支持 freshness 控制和每个 URL 的状态返回；这意味着你可以把“来源发现”和“URL 正文获取”都先建立在一套 provider 上，极大减少自建 crawler 的工作量。([Exa](https://exa.ai/docs/reference/search))

但我仍然建议你把它包进 `SearchProvider` / `ContentProvider` 适配层里，而不是让业务代码直接写 Exa SDK。原因很简单：provider 是会换的，甚至可能按 query type 走不同 provider；而 search session、search result、import、article 这些是你的产品领域模型，不应该被第三方 SDK 反向塑形。

### 3.2 为什么搜索必须做成“同一路由，按 mode 分 sync/async”

这是这次方案里最关键的技术判断。Exa 官方自己把搜索能力分成延迟等级：`fast` 面向速度敏感场景，`auto` 面向默认平衡，`deep` 面向综合研究；评测文档里给出了大致的延迟等级，`fast` 在亚秒级，`auto` 在约 1 秒级，`deep` 在多秒级。到了 2026 年 3 月的 changelog，Exa 又进一步把 `deep` 标成 4–12 秒，把 `deep-reasoning` 标成 12–50 秒。而 Exa 的 Research API 更是明确的异步流水线，需要先提交、再轮询。也就是说，这不是你主观愿不愿意做异步的问题，而是 provider 本身就已经把能力分成了“适合同步的”和“天然该异步的”两类。([Exa](https://exa.ai/docs/reference/evaluating-exa-search))

所以我不建议你把 `deep` 也硬塞进同步浏览器请求。最好的 API 不是两套，而是一套：`POST /sources/search`，根据 `mode` 决定返回 `200 completed` 还是 `202 accepted`。这样前端模型统一，后端行为正确，后面如果你真的要接 Exa Research 或别的长任务 provider，也不需要重构路由。

### 3.3 URL 导入：Exa Contents 做主路径，Trafilatura 做兜底

有了 Exa，就不应该继续把“网页导入 = 自己 `requests` 抓 HTML + Trafilatura 解析”当主路径。更合理的路径是：**搜索或 URL 导入先用 Exa `/contents` 获取 clean markdown**。Exa 文档明确说它能处理 JS-rendered pages、PDF、复杂 layout，并支持 full text、highlights、summary、subpage crawling 以及 `maxAgeHours` freshness；同时它还返回每个 URL 的 `statuses`，这对 worker 错误分类非常友好。([Exa](https://exa.ai/docs/reference/contents-best-practices))

Trafilatura 不需要删，但角色要从“主解析器”改成“provider fallback”。也就是：只有当 Exa `/contents` 失败、超时、返回质量过低，或者你明确想降低 provider 变量成本时，才退回到 direct fetch + Trafilatura。Trafilatura 仍然很有价值，因为它本身就支持从 HTML 提取正文并输出 Markdown。([Trafilatura](https://trafilatura.readthedocs.io/))

### 3.4 文件导入：MarkItDown 先行，Docling 处理复杂文档

本地文件上传不能依赖 Exa，因为文件不一定有公网 URL。这里我建议继续采用“MarkItDown 先行，Docling 兜底复杂文档”的策略。MarkItDown 官方就是“把各种文件转成 Markdown”的 Python 工具；Docling 则强调统一文档表示、支持多输入格式，并能导出 Markdown。这个组合很适合你当前缩小后的上传范围：`pdf/docx/txt/md`。([GitHub](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/README.md))

### 3.5 检索层：先用 PostgreSQL Hybrid，不额外引第二套搜索系统

这一点我仍然建议不改。PostgreSQL 自带全文检索类型和能力，`pgvector` 则可以把向量检索也放进同一套数据库。对你现在这个产品来说，article-level retrieval、chunk-level retrieval、source filter、notebook filter 都可以在一个库里先跑起来。这样你最早期的复杂度全放在产品链路，而不是放在基础设施上。([PostgreSQL](https://www.postgresql.org/docs/current/textsearch.html))

我这里还要补一个你上次觉得不够清楚的点：**我不再建议建 `article_summary` 作为检索字段。** 检索用 `article_retrieval_text`，它是确定性文本，不依赖 LLM；用户点击摘要时再走 `/summary`。这样“检索表示”和“用户可见生成内容”彻底分离，后面你调检索、调摘要、调缓存的时候不会互相污染。

### 3.6 异步执行：RocketMQ 负责传输，`jobs` 负责业务状态

你已经决定用 RocketMQ，这个选择在这里是成立的。RocketMQ 官方同时提供 Dashboard 和 Prometheus Exporter；Dashboard 适合看 Topic、Broker、消费状况和基本管理操作，Exporter 适合把指标接入统一监控。我的建议是：**API 写库成功后，先写 `jobs`，再投递 RocketMQ；worker 消费消息后推进 `jobs.status`。** 这样 MQ 负责送达和解耦，数据库负责真实状态和补偿。([rocketmq.apache.org](https://rocketmq.apache.org/zh/docs/deploymentOperations/04Dashboard/))

这里也顺带回答你之前那个监控问题：Grafana 不是多余，而是统一值班台；RocketMQ Dashboard 是专项操作台。前者看全链路，后者看队列细节，两者不是替代关系。

## 4. 具体实施计划

第一步先改文档和接口契约，不写业务代码。你要一次性改三件事：把 `sources/search` 改成 `mode` 驱动的同步/异步统一接口；把 `sources/import` 改成 `searchSessionId + searchResultIds`；把 `settings` 改成不回显原始 `apiKey`。这一步很关键，因为它决定后面 migration、service、前端调用是不是会返工。当前契约里 `sources/search` 还是“先同步，deep 以后再任务制”，`sources/import` 还是 `sourceIds`，`settings` 还在直接传 `apiKey`，这些都该在开工前一次改正。

第二步建表和基础索引，只做 migration，不做复杂业务。优先建 `users(settings_json + encrypted key)`、`notebooks`、`notes`、`search_sessions`、`search_results`、`articles`、`article_chunks`、`conversations`、`messages`、`summary_cache`、`jobs`。同时把 `pgvector`、全文检索和 HNSW/GIN 索引建好。做完这一步，你的数据边界就已经稳了。

第三步先完成 P0，但不要小看它。P0 的目标不是“把最简单的接口写完”，而是让前端从 mock 切到真实数据。你自己的 history 里也明确写了，P0 包括 auth、notebooks、notes、settings、account；同时 notebook detail 是中心接口，应该尽快可用。这个阶段最重要的不是优雅，而是**字段对齐、错误码对齐、每个接口都有 trace_id 和结构化日志**。

第四步做 Exa adapter 和搜索会话缓存。`fast/auto` 直接在 API 进程里调 Exa `/search`，请求里带 `highlights.maxCharacters`，拿到结果后写 `search_sessions + search_results`，并把 highlights 落成 `preview_markdown`；`deep` 则创建 `search_session` 和 `job`，由 worker 去跑。这里的验收标准不是“能搜”，而是“每次搜索都能复盘”，也就是你后面可以准确知道用户当时看到了哪些结果、选了哪些结果、导入了哪些结果。

第五步实现 import。import 的关键不是抓网页，而是把“候选结果”稳稳变成“notebook 里的 article”。具体做法是：先从 `search_results` 回查选中的卡片，再做去重，创建 `articles` 占位，拷贝 `preview_markdown`，写入 `jobs`，提交事务，返回 notebook detail，然后异步推进解析链路。到这一步，用户已经能看到导入的 article，也能看到一段预览内容，但真正的 `clean_markdown / toc / article_vector / chunks` 都还在后台补。

第六步实现统一 ingest pipeline。这一步必须把三种输入统一起来：`search_result/url` 走 Exa `/contents` 主路径，失败时回落到 direct fetch + Trafilatura；`text` 直接归一化成 markdown；`file` 走 MarkItDown，再在失败或复杂格式上切 Docling。得到正文后，做 markdown clean、toc extract、content_hash、article_retrieval_text、article_vector、heading-aware chunking、chunk_vector，最后原子替换旧 chunks 并把 `parse_status/chunk_status/index_status` 置到 ready。当前历史文档已经明确这条链路是 `fetch -> parse -> markdown clean -> toc extract -> chunk -> embed -> index`，我这里只是把 provider 和 fallback 路径补清楚了。

第七步做 `/summary` 和 `/chat`。`summary` 先按 `article_id + content_hash + prompt_version + model_provider + model_name + output_language` 查缓存，miss 后再调模型；`chat` 先做会话持久化和路由器，不要一开始就重 RAG。路由规则非常简单：当前文章问题走当前 article；“类似内容/相关资料”走 article-level retrieval；“出处/证据”再下沉到 chunk-level。你之前已经把这条边界说得很清楚了：不是每次聊天都检索，只有相关问题才触发 retrieval。当前 history 里也是这个方向。

第八步补齐观测、评测和压测。最少先有 API latency、search quality、parse/index health、retrieval latency、token/cost/error、RocketMQ/Redis health 这几类面板。压测场景则围绕登录到 notebook detail、note CRUD、`sources/search`、`sources/import`、`sources/upload`、`summary/chat` 这几条链。你自己的 history 已经把压测重点说出来了：真正关键的不是单纯 QPS，而是 provider 耗时、解析耗时、embedding 耗时、chunk 分布、retrieval 耗时和 LLM 首 token / 全量耗时。

这一版方案里，真正决定后续可迭代性的，不是“用了多少新组件”，而是五个定死的点：**搜索按 mode 自动 sync/async 分流；导入参数改成 `searchSessionId + searchResultIds`；用户设置放 `users.settings_json`，只把 `apiKey` 单独加密；article 用 `preview_markdown + clean_markdown` 双层内容解决导入后可见性；检索表示用 `article_retrieval_text`，不引入 `article_summary` 这种会混语义的字段。**

下一步最合理的是直接把这份方案落成 `backend/design.md` 和 `frontend/docs/api-contract.md` 的改写版。