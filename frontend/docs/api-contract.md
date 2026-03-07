# NotebookLM Frontend API Contract

## 1. 目标

这份文档面向前后端分离协作，目标有两个：

1. 明确当前前端已经使用或即将切换到的接口契约。
2. 给后端一个按难度和优先级拆分实现的落地方案，避免一上来就做高复杂度 AI/搜索链路。

当前前端已完成 API 层抽象，页面不再直接依赖 `mockData`。只要后端接口按本文档落地，并将环境变量从 `mock` 切到 `api`，前端即可直接切换到真实后端。

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

## 3. 推荐约定

### 3.1 基础约定

- 所有业务接口统一挂在 `/api`
- 编码统一 `application/json; charset=utf-8`
- 文件上传接口使用 `multipart/form-data`
- 时间字段统一返回 ISO 8601 字符串
- 认证方式建议 `Authorization: Bearer <token>`

### 3.2 响应 envelope

建议统一为：

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
- 失败时建议 HTTP 状态码正确，同时返回 `message`

### 3.3 错误码建议

| HTTP | 场景 | 前端处理 |
| --- | --- | --- |
| 400 | 参数错误 | 直接展示 message |
| 401 | 未登录/令牌失效 | 跳转登录页 |
| 403 | 权限不足 | 展示无权限提示 |
| 404 | 资源不存在 | 展示空态或返回首页 |
| 409 | 状态冲突 | 展示冲突信息并刷新 |
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
  "apiKey": "",
  "username": "张三"
}
```

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
      "content": "# Markdown...",
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

### 4.5 SourceSearchResult

```json
{
  "id": "sr-001",
  "title": "谷歌搜索技巧大全",
  "description": "系统总结了常用的高级搜索指令",
  "icon": "🔴",
  "url": "https://example.com/1",
  "selected": true
}
```

## 5. API 目录

## 5.1 Auth

### POST `/api/auth/login`

用途：
- 登录页提交用户名和密码

请求：

说明：
- 首轮对话时 `conversationId` 可省略，由后端创建并返回

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

后端难度：
- 低

实现建议：
- MVP 可先做固定账号或数据库账号密码验证
- 只要能返回 token 和用户信息，前端即可接入

### POST `/api/auth/logout`

用途：
- 设置页退出登录

请求：
- 无 body

响应：

```json
{
  "success": true
}
```

后端难度：
- 低

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

后端难度：
- 低

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

后端难度：
- 低

实现建议：
- 首页实际上不需要文章正文，只返回 summary 即可
- `query` 可以先不做数据库全文索引，先做 `LIKE`

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

后端难度：
- 低到中

实现建议：
- 先一次性返回 `articles + notes`
- 后续如果数据量大，再拆分子接口

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

后端难度：
- 低

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

后端难度：
- 低

### DELETE `/api/notebooks/:notebookId/notes/:noteId`

用途：
- 删除笔记

响应：

```json
{
  "success": true
}
```

后端难度：
- 低

## 5.4 Sources

### POST `/api/notebooks/:notebookId/sources/search`

用途：
- 右侧来源搜索栏执行 Web / Fast Research / Deep Research 搜索

请求：

```json
{
  "query": "crowd density estimation",
  "searchMode": "web",
  "researchMode": "fast"
}
```

响应：

```json
{
  "success": true,
  "modeLabel": "Web",
  "items": [
    {
      "id": "sr-001",
      "title": "谷歌搜索技巧大全",
      "description": "系统总结了常用的高级搜索指令",
      "icon": "🔴",
      "url": "https://example.com/1",
      "selected": true
    }
  ]
}
```

后端难度：
- 中

实现建议：
- 第 1 版可以同步返回结果，不必先做异步任务
- 如果未来 Deep Research 耗时很长，再升级成“提交任务 + 轮询任务状态”

### POST `/api/notebooks/:notebookId/sources/import`

用途：
- 将搜索结果导入当前笔记本，刷新来源文章列表

请求：

```json
{
  "sourceIds": ["sr-001", "sr-002"]
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

后端难度：
- 中

实现建议：
- 如果搜索结果是临时数据，需要在服务端保留搜索 session 或允许前端直接传 url/title 快照
- 当前前端按 `sourceIds` 设计，更适合后端自己维护搜索结果缓存

### POST `/api/notebooks/:notebookId/sources`

用途：
- 手动添加非文件类来源
- 覆盖网站 URL 添加、粘贴文字添加

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

后端难度：
- 低到中

实现建议：
- `web` 第 1 版可以只保存 URL 与标题，不强制立刻抓正文
- `text` 第 1 版直接落库原文即可
- 这个接口适合做成统一 JSON 接口，不要和文件上传混在 multipart 里

### POST `/api/notebooks/:notebookId/sources/upload`

用途：
- 添加文件类来源
- 覆盖 PDF、文档、图片、音频等本地文件上传

请求：
- `multipart/form-data`
- 字段名：`files`

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

后端难度：
- 中

实现建议：
- 第 1 版可以先只存文件元数据，不做解析
- 第 2 版再接 PDF/文档内容抽取
- 保持这个接口只处理二进制文件，不要把 `web/text` 也塞进来

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
    "apiKey": ""
  }
}
```

后端难度：
- 低

### PUT `/api/settings`

用途：
- 保存语言、外观、模型设置

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
  "modelProvider": "OpenAI",
  "modelName": "gpt-4o",
  "apiUrl": "https://api.openai.com/v1",
  "apiKey": "sk-***"
}
```

响应：

```json
{
  "success": true,
  "item": {
    "outputLanguage": "English"
  }
}
```

后端难度：
- 低

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

后端难度：
- 低

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

后端难度：
- 低

## 5.6 AI

### POST `/api/notebooks/:notebookId/articles/:articleId/summary`

用途：
- 笔记本页点击“AI 摘要”

响应：

```json
{
  "success": true,
  "summary": "本文介绍了基于 YOLO 的人群密度估计方法..."
}
```

后端难度：
- 中到高

实现建议：
- 第 1 版可直接拼 prompt 调 LLM
- 第 2 版再做缓存和摘要版本管理

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
    "reply": "基于文章内容，核心结论是..."
  }
}
```

后端难度：
- 高

实现建议：
- 前端只发当前用户最新一条 `message`，不要把完整 `messages` 历史放到前端组装
- 后端负责会话持久化、最近窗口裁剪、摘要压缩、RAG 检索和 system prompt 组装
- 第 1 版不强制做 RAG 检索，先把当前文章全文拼接给模型即可
- 第 2 版再补 citation、chunk 检索、会话持久化

## 6. 后端实现优先级建议

### P0：前端可基本切到真实后端

这些接口完成后，前端主流程就能跑通：

1. `POST /api/auth/login`
2. `POST /api/auth/logout`
3. `GET /api/auth/me`
4. `GET /api/notebooks`
5. `GET /api/notebooks/:notebookId`
6. `POST /api/notebooks/:notebookId/notes`
7. `PUT /api/notebooks/:notebookId/notes/:noteId`
8. `DELETE /api/notebooks/:notebookId/notes/:noteId`
9. `GET /api/settings`
10. `PUT /api/settings`
11. `PATCH /api/account/profile`
12. `POST /api/account/password`

特点：

- 难度整体低
- 主要是数据库 CRUD
- 完成后：首页、笔记本详情、笔记编辑、设置页都能联调

### P1：来源管理联调

1. `POST /api/notebooks/:notebookId/sources/search`
2. `POST /api/notebooks/:notebookId/sources/import`
3. `POST /api/notebooks/:notebookId/sources`
4. `POST /api/notebooks/:notebookId/sources/upload`

特点：

- 难度中等
- 需要处理外部检索、临时结果缓存、文件上传
- 建议先做同步搜索，先别引入复杂任务调度

### P2：AI 能力

1. `POST /api/notebooks/:notebookId/articles/:articleId/summary`
2. `POST /api/notebooks/:notebookId/chat`

特点：

- 难度最高
- 涉及 prompt、模型调用、超时、费用、缓存
- 不建议阻塞前端主业务流程

## 7. 实现难易度总结

| 模块 | 难度 | 原因 |
| --- | --- | --- |
| 登录/获取当前用户 | 低 | 标准认证接口 |
| 笔记本列表/详情 | 低 | 标准查询接口 |
| 笔记 CRUD | 低 | 标准增删改 |
| 设置与账户 | 低 | 单表或用户表扩展即可 |
| 搜索来源 | 中 | 涉及外部搜索或任务编排 |
| 导入来源 | 中 | 需要把搜索结果转为文章记录 |
| 文件上传 | 中 | 涉及对象存储/本地存储和解析链路 |
| AI 摘要 | 中到高 | 模型调用与缓存 |
| AI 对话 | 高 | 会话上下文、引用、延迟控制 |

## 8. 前端改造完成项

当前前端已经完成以下 backend-ready 改造：

- 所有页面主要数据入口都改为通过 `appApi` 调用
- 支持 `mock/api` 两套 provider 切换
- Vite 已支持 `/api` 代理
- 首页已通过 service 加载用户和笔记本列表
- 登录页已通过 service 登录
- 笔记本页已通过 service 加载详情、保存笔记、删除笔记、生成摘要、AI 对话
- 来源搜索/来源导入/文件上传已通过 service 调用
- 设置弹窗已通过 service 加载并保存

相关文件：

- [appApi.js](/Users/taless/Code/notebooklm/frontend/src/services/appApi.js)
- [HomePage.jsx](/Users/taless/Code/notebooklm/frontend/src/pages/HomePage.jsx)
- [LoginPage.jsx](/Users/taless/Code/notebooklm/frontend/src/pages/LoginPage.jsx)
- [NotebookPage.jsx](/Users/taless/Code/notebooklm/frontend/src/pages/NotebookPage.jsx)
- [SourcePanel.jsx](/Users/taless/Code/notebooklm/frontend/src/components/SourcePanel.jsx)
- [AddSourceModal.jsx](/Users/taless/Code/notebooklm/frontend/src/components/AddSourceModal.jsx)
- [SettingsModal.jsx](/Users/taless/Code/notebooklm/frontend/src/components/SettingsModal.jsx)

## 9. 建议的联调顺序

1. 后端先完成 P0 接口
2. 前端把 `.env` 改成：

```env
VITE_DATA_SOURCE=api
VITE_API_BASE_URL=/api
VITE_DEV_PROXY_TARGET=http://127.0.0.1:8080
```

3. 先验证登录、首页、笔记本详情、笔记保存
4. 再接来源搜索 / 导入 / 上传
5. 最后接 AI 摘要与对话

这个顺序可以最大程度降低联调阻塞。
