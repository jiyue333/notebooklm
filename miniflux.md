# ADR-007: RSS 订阅源集成（Miniflux + RSSHub）

> 状态：Proposal  
> 作者：NB-LM Team  
> 日期：2026-03-27

---

## 1. 背景与动机

### 1.1 项目愿景

本项目致力于打造 **AI 时代的个人信息阅读器**，帮助用户提高专注力和信息消化效率。当前产品的核心工作流为：

```
信息来源 → 导入 Notebook → AI 解析/摘要/分块 → 深度阅读/Chat → 笔记输出
```

### 1.2 现有来源的痛点

| 来源方式 | 优势 | 痛点 |
|---------|------|------|
| **网络搜索**（Exa/Tavily） | 即时可用，覆盖广 | 质量参差不齐；偏好站点机制收效甚微；被动——用户必须主动搜索 |
| **手动上传**（PDF/文档/URL/文本） | 精确可控 | 过于被动；面对上百篇/天的阅读量，只能作为稀有来源的补充 |

核心缺失：**缺少一个主动推送、高质量、持续更新的内容来源通道。**

### 1.3 为什么选择 RSS

- **主动性**：RSS 是订阅制，内容会自动推送到用户面前，无需主动搜索。
- **高质量**：用户自主选择信源（如 arXiv、个人博客、技术周刊），天然过滤了低质量内容。
- **标准化**：RSS/Atom 是成熟的开放标准，生态丰富。
- **可扩展**：通过 RSSHub，几乎任何网站都可以转化为 RSS 源。

### 1.4 技术选型

| 组件 | 选型 | 角色 |
|------|------|------|
| **Miniflux** | 自托管 RSS 阅读器（Go，单二进制） | 提供 RSS 抓取、存储、去重、API 能力 |
| **RSSHub** | 开源 RSS 生成服务 | 将不提供 RSS 的网站转化为 RSS 源（知乎、CSDN、博客园等） |

选择 Miniflux 而非自研 RSS 引擎的理由：
- 成熟稳定，支持 RSS/Atom/JSON Feed，内建抓取调度、HTTP 缓存、错误重试。
- 完善的 REST API（50+ 端点），支持 Feed/Entry/Category 全量 CRUD。
- Docker 一键部署，共用已有的 PG 数据库实例。
- 我们只需做 **薄封装层**——将 Miniflux 作为"RSS 引擎"，在其上构建产品层。

---

## 2. 用户故事与产品场景

### 2.1 核心用户故事

**作为一名研究者，我希望订阅高质量信源，每天收到一份新文章简报，快速扫一眼 AI 摘要就能决定是否深入阅读，并能一键将文章导入 Notebook 进入深度研究流程。**

### 2.2 典型使用场景

#### 场景 A：首次设置订阅

1. 用户在首页顶栏或设置中进入 **"订阅源"** 页面。
2. 搜索框输入 `https://rsshub.app/zhihu/people/excited-vczh/activities`，系统通过 Miniflux `POST /v1/discover` 自动发现 Feed。
3. 用户确认订阅，选择分类（如"技术博客"），Feed 开始后台抓取。
4. 也可以直接粘贴标准 RSS 地址（如 `https://blog.pragmaticengineer.com/rss/`）。

#### 场景 B：每日简报浏览

1. 用户打开应用，首页顶部出现 **"今日简报"** 卡片——"您有 23 篇新文章"。
2. 点击进入简报视图：按分类折叠展示近 24 小时的新 Entry。
3. 每篇文章一行：标题 + 来源 Feed 名 + AI 摘要（1-2 句话） + 发布时间。
4. 用户快速扫读，对感兴趣的文章点击展开查看详情或标记星标。

#### 场景 C：将 RSS 文章导入 Notebook

1. 用户看到一篇关于 "LLM Inference Optimization" 的文章，觉得和自己的 "AI Research Notes" 主题相关。
2. 点击文章右侧的 **"导入到笔记本"** 按钮，选择目标 Notebook。
3. 系统创建 Article 记录（`input_type = "rss_entry"`），触发标准 Ingest Pipeline。
4. 文章进入 Notebook 后，与搜索导入/上传导入的文章完全一致——可以生成 AI 摘要、Chat 提问、做笔记。

#### 场景 D：基于订阅源创建新 Notebook

1. 用户发现订阅源中连续出现 "WebAssembly" 相关文章，想系统研究。
2. 点击 **"创建 Notebook 并导入"**，输入标题 "WebAssembly Deep Dive"。
3. 系统创建 Notebook，同时将选中的 RSS 文章批量导入。

---

## 3. 产品设计

### 3.1 设计原则

> **弹窗优先，零新页面**。个人产品应尽量克制页面数量，非核心功能用弹窗承载，降低用户心智负担。整个应用只保留两个页面：首页（`/home`）和 Notebook 阅读页（`/notebook/:id`）。

RSS 订阅功能的所有交互均以 **卡片 + 弹窗** 形式融入现有页面：

- 首页：订阅源以卡片形式与 Notebook 卡片共存。
- 订阅内容浏览：点击订阅源卡片 → 弹窗双栏阅读器。
- 添加订阅：弹窗。
- RSS 设置：设置弹窗新增 Tab。
- 导入到 Notebook：弹窗中操作。

### 3.2 核心设计问题：首页卡片共存

现有首页结构是纯 Notebook 卡片网格：

```
┌─────────────────────────────────────────────────────────┐
│  搜索笔记本、文章或标签...           [⚙] [⊞] [☀] [D] │
├─────────────────────────────────────────────────────────┤
│  最近打开                                               │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │
│  │ + 新建  │ │ NB 卡片 │ │ NB 卡片 │ │ NB 卡片 │      │
│  │ 笔记本  │ │         │ │         │ │         │      │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘      │
└─────────────────────────────────────────────────────────┘
```

引入 RSS 后，首页需要同时承载两种内容实体。经过深入分析，提出以下方案：

#### 方案：Tab 视图切换（推荐）

在首页标题区域增加一个轻量的 Tab 切换器，让用户在 **"笔记本"** 和 **"订阅源"** 两个视图之间切换。两个视图共享同一个页面、同一个搜索栏、同一套顶栏。

```
┌──────────────────────────────────────────────────────────┐
│  Logo   搜索笔记本、文章或标签...    [📡 2] [⚙] [☀] [D] │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  [📓 笔记本]  [📡 订阅源]        ← Tab 切换（下划线）    │
│                                                          │
│  ─── 当 Tab = 笔记本 时（现有逻辑不变）───               │
│                                                          │
│  最近打开                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│  │ + 新建   │ │ AI Res.. │ │ WebAs..  │                 │
│  │ 笔记本   │ │ 3 个来源 │ │ 7 个来源 │                 │
│  └──────────┘ └──────────┘ └──────────┘                 │
│                                                          │
│  ─── 当 Tab = 订阅源 时 ───                              │
│                                                          │
│  我的订阅                                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│  │ + 添加   │ │ 📰       │ │ 📰       │                 │
│  │ 订阅源   │ │ Pragm..  │ │ arXiv    │                 │
│  │          │ │ 3 篇未读 │ │ 12 篇新  │                 │
│  └──────────┘ └──────────┘ └──────────┘                 │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**为什么选择此方案**：

- **零额外页面**：始终在 `/home`，只是视图内容切换。
- **心智模型清晰**：笔记本和订阅源是两种不同的信息容器，Tab 切换是用户最熟悉的模式。
- **互不干扰**：Notebook 的搜索、标签筛选、创建流程完全不受影响。
- **渐进式引导**：首次使用时，订阅源 Tab 显示空状态引导；用户在体验上毫无突兀感。
- **未读提示自然融合**：Tab 标签上可附带未读计数 badge（如 `📡 订阅源 ·3`），既不占首屏空间，又能有效提醒。

**Tab 切换的实现**：

- 新增 `homeTab` state（`'notebooks'` | `'feeds'`），默认 `'notebooks'`。
- Tab 区域渲染在现有 `home-content` 内、标签筛选条上方。
- 切换 Tab 时，下方内容区整体替换——笔记本网格或订阅源网格。
- URL 不变（仍然是 `/home`），Tab 状态可选持久化到 localStorage。

### 3.3 订阅源卡片设计

订阅源卡片与 Notebook 卡片在视觉上保持同级，但通过颜色/图标区分身份：

```
┌─────────────────────────┐     ┌─────────────────────────┐
│ ╔═══════════════════╗   │     │ ╔═══════════════════╗   │
│ ║  📰 (Feed icon)   ║   │     │ ║  📓 (NB icon)     ║   │
│ ║  渐变色：暖橙调   ║   │     │ ║  渐变色：主题蓝   ║   │
│ ╚═══════════════════╝   │     │ ╚═══════════════════╝   │
│                         │     │                         │
│ Pragmatic Engineer      │     │ AI Research Notes       │
│ 3 篇未读 · 技术博客     │     │ 2026年3月27日 · 3 个来源│
│ [AI/ML]                 │     │ [深度学习]              │
└─────────────────────────┘     └─────────────────────────┘
   ↑ 订阅源卡片                    ↑ Notebook 卡片
   点击 → 打开阅读弹窗              点击 → /notebook/:id
```

**卡片信息层级**：
- 头部区域：Feed favicon 或默认图标 + 暖色渐变背景（区别于 Notebook 的主题色渐变）
- 标题：Feed 名称
- 副信息：未读篇数 · 分类名称
- 标签区：Feed 分类标签（复用现有 `.home-card-tags` 样式）

**与 Notebook 卡片的视觉区分**：
| 维度 | Notebook 卡片 | 订阅源卡片 |
|------|-------------|-----------|
| 头部渐变色 | 主题色（蓝/绿/紫…） | 暖橙色系 `#E8713A` → `#F5A623` |
| 图标 | 📓 书签或 emoji | 📰 Feed favicon（fallback 📡） |
| 副信息 | 日期 · N 个来源 | N 篇未读 · 分类名 |
| 点击行为 | 路由跳转到阅读页 | 打开弹窗阅读器 |
| 右键/⋮ 菜单 | 编辑/删除笔记本 | 刷新/取消订阅/编辑分类 |

### 3.4 订阅源阅读弹窗（FeedReaderModal）

点击订阅源卡片后，打开一个 **全屏弹窗**（参考图片的双栏布局），不离开首页：

```
┌──────────────────────────────────────────────────────────────────┐
│  Pragmatic Engineer               🔍  ☆  🔗  ✕                 │
├──────────────────────┬───────────────────────────────────────────┤
│ All Articles    Q :  │                                           │
│                      │  My template for a quarterly              │
│ ● Trump's 'graci... │  review + plan                            │
│   World | Guardian   │                                           │
│   31 min ago         │  📰 · 2025/12/23 05:52:54                │
│                      │                                           │
│   Family seeks an... │  [文章正文 HTML 渲染区域]                  │
│   World | Guardian   │                                           │
│   33 min ago         │  It's almost a new year and               │
│                      │  that often calls for some sort           │
│   16 Best Heat Pr... │  of annual planning...                    │
│   WIRED              │                                           │
│   40 min ago         │                                           │
│                      │                                           │
│   Bluesound Pulse... │                                           │
│   WIRED    1h ago    │       [导入到笔记本]  [打开原文]           │
│                      │                                           │
│   ...更多文章        │                                           │
│                      │                                           │
├──────────────────────┴───────────────────────────────────────────┤
│  共 47 篇 · 23 篇未读              [全部标记已读]  [刷新]        │
└──────────────────────────────────────────────────────────────────┘
```

**弹窗结构**：

- **尺寸**：宽度 90vw（max 1200px），高度 85vh，居中显示，带半透明遮罩。
- **顶栏**：Feed 名称 + 搜索 + 星标过滤 + 外链 + 关闭按钮。
- **左栏（~320px）**：文章列表，每条显示标题 + 来源名 + 时间 + 缩略图（如有）。未读文章左侧有圆点标记。点击切换右栏内容。
- **右栏（flex 1）**：选中文章的正文渲染。顶部显示标题、发布时间。底部有操作按钮。
- **底栏**：统计信息 + 批量操作（全部标记已读、手动刷新）。

**关键交互**：
- 点击文章：右栏加载正文，同时标记该 Entry 为已读（调用 Miniflux API）。
- **"导入到笔记本"按钮**：弹出 Notebook 选择器（复用现有的 NotebookModal 组件模式），选择后执行导入。
- **"打开原文"**：`window.open(entry.url, '_blank')`。
- 滚动到底部自动加载更多（分页）。
- `Esc` 关闭弹窗。

### 3.5 添加订阅源弹窗（AddFeedModal）

从首页订阅源 Tab 的 "+ 添加订阅源" 卡片触发：

```
┌────────────────────────────────────────┐
│  添加订阅源                        ×   │
│                                        │
│  Feed URL                              │
│  ┌──────────────────────────────────┐  │
│  │ https://                         │  │
│  └──────────────────────────────────┘  │
│  [自动发现]                            │
│                                        │
│  或通过 RSSHub 生成：                   │
│  ┌──────────────────────────────────┐  │
│  │ 搜索网站名称（如：知乎、CSDN）   │  │
│  └──────────────────────────────────┘  │
│  热门推荐：                            │
│  [知乎热榜] [GitHub Trending]          │
│  [Hacker News] [arXiv CS.AI]          │
│                                        │
│  分类：[技术博客 ▾]                    │
│                                        │
│  □ 启用全文抓取（crawler 模式）        │
│                                        │
│              [取消]  [订阅]            │
└────────────────────────────────────────┘
```

### 3.6 Notebook 详情页集成

在现有 **添加来源** 弹窗（`AddSourceModal`）中，新增 **"从订阅源导入"** 入口：

```
┌────────────────────────────────────────┐
│  添加来源                          ×   │
│                                        │
│  🔍 在网络中搜索新来源                 │
│     [Fast Research ▾]           [▶]   │
│                                        │
│  ─────── 或 ───────                    │
│                                        │
│  📰 从订阅源导入     ← 新增入口        │
│                                        │
│  或拖放文件                            │
│  PDF、图片、文档、音频...              │
│  [上传文件] [云端硬盘] [复制的文字]    │
└────────────────────────────────────────┘
```

点击后弹出 RSS 文章选择面板（复用 FeedReaderModal 的文章列表部分），支持勾选多篇后批量导入到当前 Notebook。

### 3.7 设置弹窗集成

在设置弹窗中新增 **"RSS"** Tab（插入到"搜索"之后、"账户"之前）：

```
设置
[语言] [外观] [聊天模型] [Embedding] [搜索] [📡 RSS] [账户]

Miniflux 服务地址
  ┌────────────────────────────────────┐
  │ http://miniflux:8085               │
  └────────────────────────────────────┘

API Token
  ┌────────────────────────────────────┐
  │ ••••••••h2Ww                       │
  └────────────────────────────────────┘

RSSHub 实例（可选）
  ┌────────────────────────────────────┐
  │ https://rsshub.app                 │
  └────────────────────────────────────┘

[测试连接]                        [保存]
```

### 3.8 导航入口汇总

| 入口位置 | 形式 | 说明 |
|---------|------|------|
| 首页 Tab 切换 | `[📓 笔记本] [📡 订阅源]` | 切换首页视图，订阅源 Tab 带未读 badge |
| 首页订阅源网格 | `+ 添加订阅源` 卡片 | 打开 AddFeedModal |
| 首页订阅源卡片 | 点击 Feed 卡片 | 打开 FeedReaderModal |
| 顶栏 | 📡 图标按钮（带未读 badge） | 快捷切换到订阅源 Tab |
| Notebook 添加来源弹窗 | "从订阅源导入" 按钮 | 打开文章选择面板 |
| 设置弹窗 | "RSS" Tab | 配置 Miniflux/RSSHub 连接 |

---

## 4. 技术架构

### 4.1 系统架构

```
                    ┌──────────────────┐
                    │   Frontend       │
                    │   React SPA      │
                    └──────┬───────────┘
                           │ /api/feeds/*
                           ▼
                    ┌──────────────────┐
                    │   Backend API    │
                    │   FastAPI        │
                    │                  │
                    │  modules/feeds/  │  ← 新增模块
                    └──────┬───────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       ┌────────────┐ ┌────────┐ ┌────────────┐
       │ Miniflux   │ │ 本地DB │ │ Scheduler  │
       │ (Docker)   │ │ PG     │ │ (已有)     │
       │            │ │        │ │            │
       │ RSS 抓取   │ │ feeds  │ │ 简报生成   │
       │ Entry 存储 │ │ 表     │ │ 定时同步   │
       └──────┬─────┘ └────────┘ └────────────┘
              │
              ▼
       ┌────────────┐
       │ RSSHub     │
       │ (可选自托管)│
       └────────────┘
```

### 4.2 模块职责边界

| 模块 | 职责 | 不负责 |
|------|------|--------|
| **Miniflux** | RSS/Atom 解析、调度抓取、Entry 去重、HTTP 缓存 | AI 处理、用户认证、Notebook 逻辑 |
| **Backend `modules/feeds/`** | 封装 Miniflux API、本地 Feed 关联、简报生成、导入桥接 | RSS 协议解析、抓取调度 |
| **Scheduler（已有）** | 定时触发简报生成、定时同步 Miniflux Entry | — |
| **Worker（已有）** | 处理 Article Ingest Job（RSS 导入复用现有 pipeline） | — |
| **Frontend** | RSS 订阅管理 UI、简报浏览、导入操作 | — |

### 4.3 Miniflux 交互层设计

后端通过 `httpx` 与 Miniflux REST API 通信，封装为 `MinifluxClient`：

```python
class MinifluxClient:
    """Miniflux API 薄封装。"""

    def __init__(self, base_url: str, api_token: str): ...

    # Feed 管理
    async def discover(self, url: str) -> list[dict]: ...
    async def create_feed(self, feed_url: str, category_id: int | None = None, crawler: bool = False) -> int: ...
    async def list_feeds(self) -> list[dict]: ...
    async def get_feed(self, feed_id: int) -> dict: ...
    async def refresh_feed(self, feed_id: int) -> None: ...
    async def delete_feed(self, feed_id: int) -> None: ...

    # Entry 查询
    async def get_entries(self, *, status: str = "unread", limit: int = 50,
                          after: int | None = None, category_id: int | None = None) -> dict: ...
    async def get_entry(self, entry_id: int) -> dict: ...
    async def update_entries_status(self, entry_ids: list[int], status: str) -> None: ...
    async def toggle_bookmark(self, entry_id: int) -> None: ...

    # Category 管理
    async def list_categories(self) -> list[dict]: ...
    async def create_category(self, title: str) -> dict: ...
    async def delete_category(self, category_id: int) -> None: ...
```

关键设计决策：
- **API Token 认证**：使用 Miniflux 的 `X-Auth-Token` 头，Token 存储在用户的加密设置中。
- **共享 Miniflux 用户**：MVP 阶段为单租户模式，所有用户共用一个 Miniflux admin 账户。多租户可在后续版本通过 Miniflux 的 User API 实现。
- **错误处理**：Miniflux 不可用时，RSS 功能优雅降级，不影响现有搜索/上传流程。

---

## 5. 数据模型

### 5.1 新增数据库表

#### `rss_feeds` — 用户订阅源关联表

```sql
CREATE TABLE rss_feeds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    miniflux_feed_id INTEGER NOT NULL,           -- Miniflux 侧 Feed ID
    title           TEXT NOT NULL,                -- 显示标题（可用户自定义）
    feed_url        TEXT NOT NULL,                -- RSS 地址
    site_url        TEXT,                         -- 站点主页
    category_name   VARCHAR(128),                 -- 分类名称（冗余存储，减少 API 调用）
    icon_data       TEXT,                         -- Feed favicon Base64（缓存）
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,-- 是否启用
    crawler_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (user_id, miniflux_feed_id)
);

CREATE INDEX idx_rss_feeds_user ON rss_feeds(user_id);
```

#### `rss_digests` — 简报记录表

```sql
CREATE TABLE rss_digests (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    digest_date     DATE NOT NULL,                -- 简报日期
    entry_count     INTEGER NOT NULL DEFAULT 0,   -- 包含文章数
    summary_text    TEXT,                          -- AI 生成的简报摘要
    entry_ids_json  JSONB NOT NULL DEFAULT '[]',  -- Miniflux Entry ID 列表
    status          VARCHAR(16) NOT NULL DEFAULT 'pending', -- pending/generating/ready/failed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (user_id, digest_date)
);
```

### 5.2 现有表扩展

#### `articles` 表

新增 `input_type` 值：`"rss_entry"`

新增列（可选，用于 RSS 来源追溯）：

```sql
ALTER TABLE articles ADD COLUMN rss_feed_id UUID REFERENCES rss_feeds(id) ON DELETE SET NULL;
ALTER TABLE articles ADD COLUMN rss_entry_id INTEGER; -- Miniflux Entry ID
```

#### `user_settings_json`

新增 RSS 相关设置字段：

```json
{
  "minifluxUrl": "http://miniflux:8080",
  "minifluxApiToken": "<encrypted>",
  "rsshubUrl": "https://rsshub.app",
  "digestTime": "08:00",
  "digestLanguage": null
}
```

### 5.3 数据流

```
Miniflux (RSS 抓取)
    │
    │  定时同步 (Scheduler, 每 15 分钟)
    ▼
rss_feeds 表 (本地关联)
    │
    │  GET /v1/entries?status=unread&after=...
    ▼
Miniflux Entries (远程数据，不持久化到本地)
    │
    │  用户点击 "导入到笔记本"
    ▼
articles 表 (input_type="rss_entry")
    │
    │  触发 Job → Kafka → Worker
    ▼
标准 Ingest Pipeline (fetch → parse → chunk → embed)
```

关键设计决策：
- **Entry 不在本地持久化**：Miniflux 已经存储了所有 Entry 数据（标题、内容、URL 等）。我们通过 API 按需查询，避免数据重复和同步复杂度。
- **只有导入到 Notebook 的文章才进入本地 DB**：导入时创建 Article 记录，走标准的 Ingest Pipeline。
- **Feed 元数据本地缓存**：`rss_feeds` 表缓存 Feed 标题、favicon 等，减少对 Miniflux API 的频繁调用。

---

## 6. API 设计

### 6.1 新增后端 API

所有端点挂载在 `prefix=/api` 下，按 RESTful 风格设计。

#### Feed 管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/feeds/discover` | 自动发现 URL 的 RSS 订阅 |
| `GET` | `/feeds` | 列出当前用户的所有订阅源 |
| `POST` | `/feeds` | 添加订阅源 |
| `DELETE` | `/feeds/{feed_id}` | 取消订阅 |
| `PUT` | `/feeds/{feed_id}/refresh` | 手动刷新某个 Feed |
| `GET` | `/feeds/categories` | 列出分类 |
| `POST` | `/feeds/categories` | 创建分类 |
| `DELETE` | `/feeds/categories/{category_id}` | 删除分类 |

#### Entry 浏览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/feeds/entries` | 获取文章列表（支持分页、状态过滤、分类过滤） |
| `GET` | `/feeds/{feed_id}/entries` | 获取某个 Feed 的文章列表 |
| `GET` | `/feeds/entries/{entry_id}` | 获取单篇文章详情 |
| `PUT` | `/feeds/entries/status` | 批量更新文章已读/未读状态 |
| `PUT` | `/feeds/entries/{entry_id}/bookmark` | 切换星标 |

#### 简报

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/feeds/digest` | 获取今日简报 |
| `GET` | `/feeds/digest/{date}` | 获取指定日期简报 |

#### 导入桥接

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/notebooks/{notebook_id}/sources/import-rss` | 将 RSS Entry 导入到 Notebook |

#### 请求/响应示例

**添加订阅源**

```
POST /api/feeds
{
    "feedUrl": "https://blog.pragmaticengineer.com/rss/",
    "categoryName": "技术博客",
    "crawler": false
}

→ 201
{
    "success": true,
    "item": {
        "id": "uuid-...",
        "minifluxFeedId": 42,
        "title": "The Pragmatic Engineer",
        "feedUrl": "https://blog.pragmaticengineer.com/rss/",
        "siteUrl": "https://blog.pragmaticengineer.com",
        "categoryName": "技术博客",
        "isActive": true
    }
}
```

**获取 Entry 列表**

```
GET /api/feeds/entries?status=unread&limit=20&categoryName=技术博客

→ 200
{
    "success": true,
    "items": [
        {
            "entryId": 888,
            "feedId": "uuid-...",
            "feedTitle": "The Pragmatic Engineer",
            "title": "LLM Inference Optimization",
            "url": "https://...",
            "author": "Gergely Orosz",
            "publishedAt": "2026-03-27T10:00:00Z",
            "readingTime": 8,
            "status": "unread",
            "starred": false,
            "aiSummary": "本文讨论了大语言模型推理优化的三种主流方法...",
            "contentPreview": "前 200 字..."
        }
    ],
    "meta": { "total": 47, "unread": 23 }
}
```

**导入 RSS Entry 到 Notebook**

```
POST /api/notebooks/{notebook_id}/sources/import-rss
{
    "entryIds": [888, 889, 890]
}

→ 200
{
    "success": true,
    "item": { ... notebook detail ... },
    "meta": { "importedCount": 3, "skippedDuplicate": 0 }
}
```

### 6.2 导入桥接逻辑

```python
async def import_rss_entries(session, user_id, notebook_id, entry_ids):
    """将 Miniflux Entry 导入为 Notebook Article。"""
    client = build_miniflux_client(user_id)

    articles = []
    for entry_id in entry_ids:
        entry = await client.get_entry(entry_id)
        dedupe_key = f"rss:{entry['feed_id']}:{entry['hash']}"

        # 去重检查
        if await article_exists_by_dedupe_key(session, user_id, notebook_id, dedupe_key):
            continue

        article = Article(
            user_id=user_id,
            notebook_id=notebook_id,
            input_type="rss_entry",
            dedupe_key=dedupe_key,
            title=entry["title"],
            source_url=entry["url"],
            author=entry.get("author"),
            published_at=parse_datetime(entry["published_at"]),
            preview_markdown=html_to_markdown_excerpt(entry["content"], max_chars=300),
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
            rss_feed_id=local_feed_id,
            rss_entry_id=entry_id,
        )
        session.add(article)
        await session.flush()

        # 创建 Ingest Job（复用现有 pipeline）
        job = await create_article_ingest_job(session, article_id=article.id, ...)
        articles.append(article)

    await session.commit()
    # 发布 Job 到 Kafka
    await publish_jobs(session, jobs)

    # 标记 Miniflux Entry 为已读
    await client.update_entries_status(entry_ids, status="read")
```

---

## 7. AI 摘要策略

RSS 文章导入 Notebook 后，走标准的 Ingest Pipeline → Summary Pipeline，与搜索导入/手动上传的文章体验完全一致。

AI 简报功能（每日自动摘要）作为远期 Phase 3 规划，MVP 阶段不实现。

---

## 8. 基础设施

### 8.1 Docker Compose 扩展

在 `docker-compose.yml` 中新增 Miniflux 服务：

```yaml
  miniflux:
    image: miniflux/miniflux:2.2.8
    container_name: nblm-miniflux
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      DATABASE_URL: "见 .env 模板，指向共用 PG 实例的 miniflux 数据库"
      RUN_MIGRATIONS: 1
      CREATE_ADMIN: 1
      ADMIN_USERNAME: ${MINIFLUX_ADMIN_USER:-admin}
      ADMIN_PASSWORD: ${MINIFLUX_ADMIN_PASSWORD:-miniflux123}
    ports:
      - "8085:8080"
    healthcheck:
      test: ["CMD", "/usr/bin/miniflux", "-healthcheck", "auto"]
      interval: 15s
      timeout: 5s
      retries: 5
```

Miniflux 使用独立的数据库（`miniflux`），共享已有的 PG 实例。需在 `.env` 中新增：

```env
# =============== Miniflux ===============
MINIFLUX_DB=miniflux
MINIFLUX_ADMIN_USER=admin
MINIFLUX_ADMIN_PASSWORD=miniflux123
MINIFLUX_API_URL=http://miniflux:8080
MINIFLUX_API_TOKEN=

# =============== RSSHub ===============
RSSHUB_URL=https://rsshub.app
```

### 8.2 RSSHub（可选自托管）

RSSHub 在 MVP 阶段使用公共实例 `https://rsshub.app`。若需自托管：

```yaml
  rsshub:
    image: diygod/rsshub:latest
    container_name: nblm-rsshub
    restart: unless-stopped
    ports:
      - "1200:1200"
    environment:
      NODE_ENV: production
      CACHE_TYPE: redis
      REDIS_URL: redis://redis:6379/
```

---

## 9. 前端组件

### 9.1 路由

**不新增路由**。所有 RSS 功能通过弹窗承载，复用现有 `/home` 和 `/notebook/:id` 页面。

### 9.2 新增组件

| 文件路径 | 组件 | 说明 |
|---------|------|------|
| `components/FeedReaderModal.jsx` | FeedReaderModal | 订阅源阅读弹窗（双栏：文章列表 + 正文） |
| `components/AddFeedModal.jsx` | AddFeedModal | 添加订阅源弹窗 |
| `components/FeedCard.jsx` | FeedCard | 首页订阅源卡片 |
| `components/ImportRssModal.jsx` | ImportRssModal | Notebook 内导入 RSS 文章弹窗 |

### 9.3 现有组件修改

| 文件路径 | 修改内容 |
|---------|---------|
| `pages/HomePage.jsx` | 新增 `homeTab` state、Tab 切换 UI、订阅源网格渲染 |
| `pages/HomePage.css` | 新增 Tab 样式、订阅源卡片暖色渐变 |
| `components/AddSourceModal.jsx` | 新增"从订阅源导入"入口按钮 |
| `components/SettingsModal.jsx` | 新增"RSS"Tab 及配置表单 |

### 9.3 API Service 扩展

在 `appApi.js` 中新增 `feeds` 命名空间：

```javascript
export const appApi = {
    // ... 现有 auth, notebooks, notes, sources, settings, ai ...
    feeds: {
        discover: provider.discoverFeeds,
        list: provider.listFeeds,
        create: provider.createFeed,
        remove: provider.deleteFeed,
        refresh: provider.refreshFeed,
        listEntries: provider.listFeedEntries,
        getEntry: provider.getFeedEntry,
        updateEntriesStatus: provider.updateEntriesStatus,
        toggleBookmark: provider.toggleEntryBookmark,
        listCategories: provider.listFeedCategories,
        createCategory: provider.createFeedCategory,
        removeCategory: provider.deleteFeedCategory,
        getDigest: provider.getDigest,
        importToNotebook: provider.importRssToNotebook,
    },
};
```

---

## 10. 实施计划

### Phase 1：基础 RSS 订阅（MVP）

**目标**：用户可以添加、管理 RSS 订阅源，在弹窗中浏览文章，将文章导入到 Notebook。

- 基础设施：Docker Compose 新增 Miniflux 服务。
- 后端 `modules/feeds/`：MinifluxClient、Feed CRUD API、Entry 查询 API、导入桥接 API。
- 数据库：`rss_feeds` 表 Alembic 迁移、`articles` 表扩展。
- 前端：HomePage Tab 切换（笔记本/订阅源）。
- 前端：FeedCard 订阅源卡片组件。
- 前端：FeedReaderModal 双栏阅读弹窗。
- 前端：AddFeedModal 添加订阅弹窗。
- 前端：AddSourceModal 新增"从订阅源导入"入口。
- 前端：SettingsModal 新增"RSS"Tab。

### Phase 2：RSSHub 集成与体验优化

**目标**：降低订阅门槛，优化浏览体验。

- 后端：RSSHub 路由搜索 API（通过 RSSHub Radar 规则匹配网站）。
- 前端：AddFeedModal 增加 RSSHub 推荐和搜索。
- 前端：热门订阅推荐（预设优质源列表）。
- 体验优化：Feed favicon 缓存、Entry 预读、未读计数 badge。

### Phase 3：AI 简报（远期）

**目标**：用户每天收到 AI 生成的简报，快速扫读订阅内容。

- 数据库：`rss_digests` 表迁移。
- Scheduler 扩展：定时简报生成任务。
- 后端：Entry 快速摘要生成（Lite LLM）。
- 前端：首页简报入口卡片。

### Phase 4：高级特性（远期）

- 多租户 Miniflux 用户隔离。
- 智能推荐：基于用户 Notebook 主题，自动推荐相关 RSS 源。
- OPML 导入/导出：兼容现有 RSS 阅读器的订阅列表迁移。
- RSS Entry 全文搜索。
- 订阅源健康监控（解析错误率、更新频率异常告警）。

---

## 11. 与现有系统的集成点

| 现有模块 | 集成方式 | 变更程度 |
|---------|---------|---------|
| `modules/sources/router.py` | 新增 `import-rss` 端点，逻辑与 `import_sources_endpoint` 类似 | 低——新增端点，不修改现有端点 |
| `modules/notebooks/models.py` (Article) | 新增 `input_type="rss_entry"` 及 2 个可选列 | 低——Alembic 迁移 |
| `modules/jobs/publisher.py` | 无变更，RSS 导入复用现有 Job 发布 | 无 |
| `workers/handlers/` | 无变更，Ingest Pipeline 按 `source_url` 抓取并解析 | 无 |
| `modules/settings/` | 扩展 `SettingsUpdateRequest`，新增 RSS 配置字段 | 低 |
| `workers/run_scheduler.py` | 新增简报生成定时任务 | 低——添加一个新的定时回调 |
| `frontend/src/pages/HomePage.jsx` | 新增 Tab 切换、订阅源网格、弹窗触发 | 中——新增 Tab 逻辑和 Feed 数据加载 |
| `frontend/src/components/AddSourceModal.jsx` | 新增"从订阅源导入"按钮 | 低——UI 新增一个入口 |
| `frontend/src/services/appApi.js` | 新增 `feeds` 命名空间 | 低——纯新增 |
| `docker-compose.yml` | 新增 `miniflux` service | 低——独立 service |

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Miniflux 服务不可用 | RSS 功能不可用，但不影响现有功能 | 健康检查 + UI 降级提示；RSS 模块独立，不耦合核心流程 |
| 公共 RSSHub 实例限流 | 部分 Feed 添加失败 | 支持自托管 RSSHub；用户也可直接粘贴标准 RSS 地址 |
| AI 摘要成本过高 | 大量 Entry 消耗 Token | 使用 Lite LLM（低成本模型）；设置每日 Entry 上限；摘要缓存 |
| Miniflux 数据库膨胀 | 磁盘占用增长 | Miniflux 内建 `CLEANUP_ARCHIVE_UNREAD_DAYS` 参数自动清理旧 Entry |
| 多用户 Feed 隔离 | MVP 单租户可能暴露其他用户的 Feed | Phase 4 迁移到 Miniflux 多用户模式；MVP 阶段可通过后端 `rss_feeds` 表做逻辑隔离 |

---

## 13. 附录

### A. Miniflux API 关键端点速查

| 端点 | 方法 | 用途 |
|------|------|------|
| `/v1/discover` | POST | 自动发现 Feed |
| `/v1/feeds` | GET/POST | Feed 列表/创建 |
| `/v1/feeds/{id}` | GET/PUT/DELETE | Feed 详情/更新/删除 |
| `/v1/feeds/{id}/refresh` | PUT | 手动刷新 |
| `/v1/entries` | GET | Entry 列表（支持丰富过滤） |
| `/v1/entries/{id}` | GET/PUT | Entry 详情/更新 |
| `/v1/entries` | PUT | 批量更新 Entry 状态 |
| `/v1/entries/{id}/bookmark` | PUT | 切换星标 |
| `/v1/entries/{id}/fetch-content` | GET | 抓取原文 |
| `/v1/categories` | GET/POST | 分类列表/创建 |
| `/v1/export` | GET | OPML 导出 |
| `/v1/import` | POST | OPML 导入 |

### B. RSSHub 常用路由示例

| 网站 | RSSHub 路由 | 生成的 Feed URL |
|------|------------|----------------|
| 知乎用户动态 | `/zhihu/people/{id}/activities` | `https://rsshub.app/zhihu/people/excited-vczh/activities` |
| CSDN 博客 | `/csdn/blog/{id}` | `https://rsshub.app/csdn/blog/username` |
| 博客园 | `/cnblogs/{id}` | `https://rsshub.app/cnblogs/cate/108697` |
| GitHub Trending | `/github/trending/{lang}/{since}` | `https://rsshub.app/github/trending/daily` |
| Hacker News | `/hackernews/best` | `https://rsshub.app/hackernews/best` |
| arXiv | `/arxiv/search_query=cs.AI` | `https://rsshub.app/arxiv/search_query=cs.AI` |
| 微信公众号 | `/wechat/mp/{id}` (需配置) | 需自托管 RSSHub + 配置 |

### C. 现有 Article `input_type` 值

| 值 | 说明 | 来源 |
|---|------|------|
| `search_result` | 从网络搜索导入 | sources/router.py `import_sources_endpoint` |
| `url` | 手动添加 URL | sources/router.py `create_source_endpoint` |
| `text` | 手动粘贴文本 | sources/router.py `create_source_endpoint` |
| `file` | 上传文件 | sources/router.py `upload_sources_endpoint` |
| **`rss_entry`** | **从 RSS 订阅导入（新增）** | **feeds/router.py `import_rss_endpoint`** |
