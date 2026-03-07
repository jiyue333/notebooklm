# NotebookLM Frontend API Contract

## 1. 目标

这份文档面向当前仓库的前后端联调，目标只有两个：

1. 把前端已经接入或即将接入的接口契约固定下来。
2. 让契约与最新 [design.md](/Users/taless/Code/notebooklm/backend/design.md) 保持一致，避免 `sourceIds`、明文 `apiKey`、旧搜索模式这些已经过时的定义继续扩散。

当前前端已经完成 `mock/api` 双 provider 切换。只要后端接口按本文档落地，并把 `VITE_DATA_SOURCE=api`，前端就可以直接切到真实后端。

## 2. 前端切换方式

环境变量位于 [`.env.example`](/Users/taless/Code/notebooklm/frontend/.env.example)：

```env
VITE_DATA_SOURCE=mock
VITE_API_BASE_URL=/api
VITE_DEV_PROXY_TARGET=http://127.0.0.1:8080
VITE_API_TIMEOUT_MS=15000
```

切换规则：

- 本地纯前端开发：`VITE_DATA_SOURCE=mock`
- 后端联调：`VITE_DATA_SOURCE=api`
- 开发环境默认通过 Vite 代理把 `/api/*` 转发到 `VITE_DEV_PROXY_TARGET`

相关实现：

- [runtime.js](/Users/taless/Code/notebooklm/frontend/src/config/runtime.js)
- [appApi.js](/Users/taless/Code/notebooklm/frontend/src/services/appApi.js)
- [vite.config.js](/Users/taless/Code/notebooklm/frontend/vite.config.js)

## 3. 通用约定

### 3.1 基础约定

- 所有业务接口统一挂在 `/api`
- 编码统一 `application/json; charset=utf-8`
- 文件上传接口使用 `multipart/form-data`
- 时间字段统一返回 ISO 8601 字符串
- 认证方式使用 `Authorization: Bearer <token>`
- `GET /api/notebooks/:notebookId` 仍然是当前阶段的中心接口，继续一次性返回 `articles + notes`

### 3.2 响应 envelope

统一为：

```json
{
  "success": true,
  "item": {},
  "items": [],
  "message": "",
  "meta": {}
}
```

说明：

- 单对象返回时使用 `item`
- 列表返回时使用 `items`
- 失败时返回正确 HTTP 状态码，同时返回 `message`

### 3.3 错误码建议

| HTTP | 场景 | 前端处理 |
| --- | --- | --- |
| 400 | 参数错误 | 直接展示 message |
| 401 | 未登录/令牌失效 | 跳转登录页 |
| 403 | 权限不足 | 展示无权限提示 |
| 404 | 资源不存在 | 展示空态或返回首页 |
| 409 | 状态冲突，例如 article 未准备好 | 展示冲突信息 |
| 422 | 业务校验失败 | 表单字段报错 |
| 500 | 服务异常 | 展示通用错误 |

## 4. 前端实际使用的数据模型

### 4.1 User

```json
{
  "id": "user-001",
  "name": "张三",
  "email": "zhangsan@example.com",
  "avatar": null
}
```

### 4.2 Settings

```json
{
  "outputLanguage": "中文",
  "themeColor": "ocean",
  "colorMode": "light",
  "modelProvider": "自定义",
  "modelName": "gpt-4o",
  "apiUrl": "http://host.docker.internal:8317/v1/chat/completions",
  "searchProvider": "exa",
  "hasApiKey": true,
  "apiKeyMasked": "••••9f2a",
  "hasSearchApiKey": true,
  "searchApiKeyMasked": "••••7c1d",
  "username": "张三"
}
```

说明：

- 后端不再回显原始 `apiKey`
- 后端也不回显原始搜索引擎 key
- 前端模型页通过“留空不改 / 输入新值替换 / clearApiKey 清除”来表达修改语义
- 前端搜索页通过“留空不改 / 输入新值替换 / clearSearchApiKey 清除”来表达 Exa key 修改语义

### 4.3 NotebookSummary

```json
{
  "id": "nb-001",
  "title": "Smart Monitoring: Crowd Sensing, Edge Computing",
  "emoji": "👥",
  "color": "#5B6ABF",
  "date": "2026年2月8日",
  "sourceCount": 31
}
```

### 4.4 NotebookDetail

```json
{
  "id": "nb-001",
  "title": "Smart Monitoring: Crowd Sensing, Edge Computing",
  "emoji": "👥",
  "color": "#5B6ABF",
  "date": "2026年2月8日",
  "sourceCount": 31,
  "articles": [
    {
      "id": "art-001",
      "title": "Deep Research 报告：基于 YOLO 的人群密度估计",
      "type": "research",
      "author": "Deep Research",
      "date": "2026-02-08T14:30:00+08:00",
      "selected": true,
      "content": "# Markdown 或 preview markdown...",
      "toc": [
        { "id": "intro", "title": "1. 引言", "level": 1 }
      ]
    }
  ],
  "notes": [
    {
      "id": "note-001",
      "title": "YOLO 目标检测技术核心要点总结",
      "content": "## 核心要点",
      "type": "Briefing Doc",
      "sources": 8,
      "time": "65 天前"
    }
  ]
}
```

说明：

- `articles[].content` 当前阶段允许返回 `clean_markdown` 或 `preview_markdown`
- 前端暂时不感知异步解析状态变化，所以不要求在 `NotebookDetail` 中暴露 processing 状态

### 4.5 SearchSession

```json
{
  "searchSessionId": "ss_01JXYZ",
  "mode": "auto",
  "modeLabel": "Auto Research",
  "status": "completed",
  "execution": "sync"
}
```

### 4.6 SourceSearchResult

```json
{
  "id": "srr_01JXYZ",
  "title": "谷歌搜索技巧大全",
  "description": "系统总结了常用的高级搜索指令",
  "icon": "🔴",
  "url": "https://example.com/1",
  "selected": true
}
```

说明：

- `id` 是后端生成的 `searchResultId`
- 不再把 provider 原始 `sourceId` 直接暴露给前端

## 5. API 目录

## 5.1 Auth

### POST `/api/auth/login`

用途：

- 登录页提交用户名和密码

请求：

```json
{
  "username": "taless",
  "password": "secret"
}
```

响应：

```json
{
  "success": true,
  "token": "jwt-or-session-token",
  "user": {
    "id": "user-001",
    "name": "taless",
    "email": "taless@example.com",
    "avatar": null
  }
}
```

### POST `/api/auth/logout`

用途：

- 设置页退出登录

响应：

```json
{
  "success": true
}
```

### GET `/api/auth/me`

用途：

- 首页、笔记本页、设置页加载当前用户

响应：

```json
{
  "success": true,
  "user": {
    "id": "user-001",
    "name": "张三",
    "email": "zhangsan@example.com",
    "avatar": null
  }
}
```

## 5.2 Notebooks

### GET `/api/notebooks`

用途：

- 首页加载笔记本列表

查询参数：

- `query`：可选，服务端搜索关键字

响应：

```json
{
  "success": true,
  "items": [
    {
      "id": "nb-001",
      "title": "Smart Monitoring: Crowd Sensing, Edge Computing",
      "emoji": "👥",
      "color": "#5B6ABF",
      "date": "2026年2月8日",
      "sourceCount": 31
    }
  ]
}
```

### POST `/api/notebooks`

用途：

- 首页点击“新建笔记本”
- 前端通过弹窗表单填写 `title / emoji / color`

请求：

```json
{
  "title": "Untitled notebook",
  "emoji": "📒",
  "color": "#8B7355"
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "nb-101",
    "title": "Untitled notebook",
    "emoji": "📒",
    "color": "#8B7355",
    "date": "2026年3月7日",
    "sourceCount": 0,
    "articles": [],
    "notes": []
  }
}
```

### GET `/api/notebooks/:notebookId`

用途：

- 笔记本页加载详情
- 导入来源后刷新右侧来源文章/笔记

响应：

```json
{
  "success": true,
  "item": {
    "id": "nb-001",
    "title": "Smart Monitoring: Crowd Sensing, Edge Computing",
    "emoji": "👥",
    "color": "#5B6ABF",
    "date": "2026年2月8日",
    "sourceCount": 31,
    "articles": [],
    "notes": []
  }
}
```

### PATCH `/api/notebooks/:notebookId`

用途：

- 修改笔记本标题、emoji、color

请求：

```json
{
  "title": "新的标题",
  "emoji": "🧠",
  "color": "#3B82F6"
}
```

### DELETE `/api/notebooks/:notebookId`

用途：

- 删除笔记本

响应：

```json
{
  "success": true
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "nb-001",
    "title": "新的标题",
    "emoji": "🧠",
    "color": "#3B82F6"
  }
}
```

## 5.3 Notes

### POST `/api/notebooks/:notebookId/notes`

用途：

- 新建笔记

请求：

```json
{
  "title": "新笔记",
  "content": "## 内容",
  "type": "笔记",
  "sources": 0
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "note-101",
    "title": "新笔记",
    "content": "## 内容",
    "type": "笔记",
    "sources": 0,
    "time": "刚刚"
  }
}
```

### PUT `/api/notebooks/:notebookId/notes/:noteId`

用途：

- 编辑已有笔记

请求：

```json
{
  "title": "更新后的标题",
  "content": "更新后的 markdown",
  "type": "笔记",
  "sources": 3
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "note-101",
    "title": "更新后的标题",
    "content": "更新后的 markdown",
    "type": "笔记",
    "sources": 3,
    "time": "刚刚"
  }
}
```

### DELETE `/api/notebooks/:notebookId/notes/:noteId`

用途：

- 删除笔记

响应：

```json
{
  "success": true
}
```

## 5.4 Sources

### POST `/api/notebooks/:notebookId/sources/search`

用途：

- 来源搜索栏执行 Fast / Auto / Deep 搜索

请求：

```json
{
  "query": "crowd density estimation",
  "mode": "auto",
  "maxResults": 10,
  "freshnessHours": 24
}
```

`mode` 取值：

- `fast`：低延迟候选发现
- `auto`：默认平衡模式
- `deep`：更慢但更深入的来源发现

同步响应示例：

```json
{
  "success": true,
  "item": {
    "searchSessionId": "ss_01JXYZ",
    "mode": "auto",
    "modeLabel": "Auto Research",
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

异步受理示例：

```json
{
  "success": true,
  "item": {
    "searchSessionId": "ss_01JXYZ",
    "mode": "deep",
    "modeLabel": "Deep Research",
    "status": "queued",
    "execution": "async"
  },
  "message": "search accepted"
}
```

### GET `/api/notebooks/:notebookId/search-sessions/:searchSessionId`

用途：

- 轮询 deep search 会话结果

响应：

```json
{
  "success": true,
  "item": {
    "searchSessionId": "ss_01JXYZ",
    "mode": "deep",
    "modeLabel": "Deep Research",
    "status": "completed",
    "execution": "async"
  },
  "items": [
    {
      "id": "srr_01JXYZ",
      "title": "......",
      "description": "......",
      "icon": "🔴",
      "url": "https://example.com/1",
      "selected": true
    }
  ]
}
```

### POST `/api/notebooks/:notebookId/sources/import`

用途：

- 将某次搜索会话中选中的结果导入当前笔记本

请求：

```json
{
  "searchSessionId": "ss_01JXYZ",
  "searchResultIds": ["srr_01JXYZ", "srr_01JXYA"]
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "nb-001",
    "title": "Smart Monitoring: Crowd Sensing, Edge Computing",
    "sourceCount": 33,
    "articles": [],
    "notes": []
  }
}
```

说明：

- 不再传 `sourceIds`
- `searchSessionId + searchResultIds` 才是完整的导入语义

### POST `/api/notebooks/:notebookId/sources`

用途：

- 手动添加非文件类来源
- 当前仅覆盖网站 URL 添加、粘贴文字添加

请求示例 1：网站来源

```json
{
  "sourceType": "web",
  "url": "https://example.com/article",
  "title": "可选：用户自定义标题"
}
```

请求示例 2：粘贴文字来源

```json
{
  "sourceType": "text",
  "title": "用户粘贴的会议纪要",
  "content": "这里是用户粘贴的原始文字内容"
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "nb-001",
    "sourceCount": 34,
    "articles": [],
    "notes": []
  }
}
```

### POST `/api/notebooks/:notebookId/sources/upload`

用途：

- 添加文件类来源

请求：

- `multipart/form-data`
- 字段名：`files`

当前范围：

- `pdf`
- `doc`
- `docx`
- `txt`
- `md`

响应：

```json
{
  "success": true,
  "item": {
    "id": "nb-001",
    "sourceCount": 34,
    "articles": [],
    "notes": []
  }
}
```

说明：

- 当前不再宣称支持图片和音频
- 保持这个接口只处理二进制文件，不把 `web/text` 混进来

## 5.5 Settings / Account

### GET `/api/settings`

用途：

- 设置弹窗加载模型、主题、输出语言等设置

响应：

```json
{
  "success": true,
  "item": {
    "outputLanguage": "中文",
    "themeColor": "ocean",
    "colorMode": "light",
    "modelProvider": "自定义",
    "modelName": "gpt-4o",
    "apiUrl": "http://host.docker.internal:8317/v1/chat/completions",
    "searchProvider": "exa",
    "hasApiKey": true,
    "apiKeyMasked": "••••9f2a",
    "hasSearchApiKey": true,
    "searchApiKeyMasked": "••••7c1d",
    "username": "张三"
  }
}
```

### PUT `/api/settings`

用途：

- 保存语言、外观、模型设置

语义：

- 请求按 merge-patch 处理
- 不带 `apiKey` 表示不修改已保存 key
- 带非空 `apiKey` 表示替换 key
- `clearApiKey=true` 表示删除已保存 key
- `searchProvider` 当前只开放 `exa`
- 不带 `searchApiKey` 表示不修改已保存搜索 key
- 带非空 `searchApiKey` 表示替换搜索 key
- `clearSearchApiKey=true` 表示删除已保存搜索 key

请求示例 1：

```json
{
  "outputLanguage": "English"
}
```

请求示例 2：

```json
{
  "themeColor": "ocean",
  "colorMode": "dark"
}
```

请求示例 3：

```json
{
  "searchProvider": "exa"
}
```

请求示例 4：

```json
{
  "searchProvider": "exa",
  "searchApiKey": "exa_***"
}
```

请求示例 5：

```json
{
  "modelProvider": "OpenAI",
  "modelName": "gpt-4o",
  "apiUrl": "https://api.openai.com/v1",
  "apiKey": "sk-***"
}
```

请求示例 6：

```json
{
  "clearApiKey": true
}
```

请求示例 7：

```json
{
  "clearSearchApiKey": true
}
```

响应：

```json
{
  "success": true,
  "item": {
    "outputLanguage": "English",
    "themeColor": "ocean",
    "colorMode": "dark",
    "modelProvider": "OpenAI",
    "modelName": "gpt-4o",
    "apiUrl": "https://api.openai.com/v1",
    "searchProvider": "exa",
    "hasApiKey": true,
    "apiKeyMasked": "••••9f2a",
    "hasSearchApiKey": true,
    "searchApiKeyMasked": "••••7c1d",
    "username": "张三"
  }
}
```

### PATCH `/api/account/profile`

用途：

- 修改用户名

请求：

```json
{
  "username": "new-name"
}
```

响应：

```json
{
  "success": true,
  "item": {
    "id": "user-001",
    "name": "new-name",
    "email": "zhangsan@example.com"
  }
}
```

### POST `/api/account/password`

用途：

- 修改密码

请求：

```json
{
  "oldPassword": "old",
  "newPassword": "new",
  "confirmPassword": "new"
}
```

响应：

```json
{
  "success": true
}
```

## 5.6 AI

### POST `/api/notebooks/:notebookId/articles/:articleId/summary`

用途：

- 笔记本页点击“AI 摘要”

可选请求：

```json
{
  "outputLanguage": "中文",
  "forceRefresh": false
}
```

响应：

```json
{
  "success": true,
  "item": {
    "summary": "本文介绍了基于 YOLO 的人群密度估计方法..."
  }
}
```

失败约定：

- 如果 article 还没有可用正文，返回 `409`

### POST `/api/notebooks/:notebookId/chat`

用途：

- AI 助手问答

请求：

```json
{
  "conversationId": "conv-001",
  "articleId": "art-001",
  "message": "请总结一下文章的核心结论"
}
```

响应：

```json
{
  "success": true,
  "item": {
    "conversationId": "conv-001",
    "messageId": "msg-001",
    "reply": "基于文章内容，核心结论是...",
    "citations": []
  }
}
```

说明：

- 前端只发最新一条 `message`
- 后端负责会话持久化、窗口裁剪、检索和 prompt 组装
- `citations` 第一版可以为空数组

### POST `/api/notebooks/:notebookId/articles/:articleId/translate`

用途：

- 笔记本页点击“AI 翻译”

请求：

```json
{
  "targetLanguage": "English"
}
```

响应：

```json
{
  "success": true,
  "item": {
    "targetLanguage": "English",
    "translatedContent": "# Translated markdown..."
  }
}
```

## 6. 后端实现优先级建议

### P0：前端主流程联调

1. `POST /api/auth/login`
2. `POST /api/auth/logout`
3. `GET /api/auth/me`
4. `GET /api/notebooks`
5. `POST /api/notebooks`
6. `GET /api/notebooks/:notebookId`
7. `PATCH /api/notebooks/:notebookId`
8. `DELETE /api/notebooks/:notebookId`
9. `POST /api/notebooks/:notebookId/notes`
10. `PUT /api/notebooks/:notebookId/notes/:noteId`
11. `DELETE /api/notebooks/:notebookId/notes/:noteId`
12. `GET /api/settings`
13. `PUT /api/settings`
14. `PATCH /api/account/profile`
15. `POST /api/account/password`

### P1：来源管理

1. `POST /api/notebooks/:notebookId/sources/search`
2. `GET /api/notebooks/:notebookId/search-sessions/:searchSessionId`
3. `POST /api/notebooks/:notebookId/sources/import`
4. `POST /api/notebooks/:notebookId/sources`
5. `POST /api/notebooks/:notebookId/sources/upload`

### P2：AI 能力

1. `POST /api/notebooks/:notebookId/articles/:articleId/summary`
2. `POST /api/notebooks/:notebookId/chat`
3. `POST /api/notebooks/:notebookId/articles/:articleId/translate`

## 7. 前端已对齐的改造点

当前前端已经按本版契约完成以下适配：

- 来源搜索改为 `mode=fast|auto|deep`
- 来源导入改为 `searchSessionId + searchResultIds`
- 设置页不再回显原始 `apiKey`，支持“保留 / 替换 / 清除”
- 设置页新增了搜索引擎设置，当前只提供 `exa`，并支持配置 Exa API Key
- “添加来源”补齐了网站和粘贴文字入口
- 首页“新建笔记本”改为弹窗表单，并支持编辑/删除笔记本
- AI 摘要响应改为 `item.summary`
- AI 翻译入口已切成真实 API 调用流

相关文件：

- [appApi.js](/Users/taless/Code/notebooklm/frontend/src/services/appApi.js)
- [HomePage.jsx](/Users/taless/Code/notebooklm/frontend/src/pages/HomePage.jsx)
- [SourcePanel.jsx](/Users/taless/Code/notebooklm/frontend/src/components/SourcePanel.jsx)
- [AddSourceModal.jsx](/Users/taless/Code/notebooklm/frontend/src/components/AddSourceModal.jsx)
- [SettingsModal.jsx](/Users/taless/Code/notebooklm/frontend/src/components/SettingsModal.jsx)
- [NotebookPage.jsx](/Users/taless/Code/notebooklm/frontend/src/pages/NotebookPage.jsx)

## 8. 建议的联调顺序

1. 后端先完成 P0 接口
2. 再完成 `sources/search + searchSession poll + import`
3. 再补 `sources` 和 `sources/upload`
4. 最后接 `summary` 和 `chat`

这个顺序最符合当前前端已经存在的页面和交互。

## 9. 未来补充功能

这部分是已经进入前端交互、但仍可能继续扩展的能力：

1. 新建笔记本：使用弹窗表单填写 `title / emoji / color`
2. 笔记本编辑与删除：当前入口在首页卡片菜单，后续可以再补到更多页面
3. AI 翻译：当前按文章触发整篇译文，后续可以扩展段落级翻译或双语对照视图
