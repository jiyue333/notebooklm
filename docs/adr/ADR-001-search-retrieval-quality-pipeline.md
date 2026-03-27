# 搜索链路重构（基于LangGraph）

请按照以下思路重构 @backend/app/modules/agent/search 链路，整体采用 **LangGraph** 实现新的搜索流程。

---

## 1. 流程概览

1. **接收输入**
2. **意图识别**（结合当前 notebook 内容）
    - 使用 repo 查询当前 notebook 的所有文章 summary，并结合用户 query 获取上下文。
    - 可预设一些状态，例如：
        - **2.1 搜索类型**：用户希望查看观点型、客观事实、探索型，或其它类型（留扩展点）。
        - **2.2 文章内容范围**：判断用户想要 overview、detail 还是其它（留扩展点）。
        - **2.3** 其它（预留拓展点）。
3. **根据意图识别输出重写 query**
4. **搜索引擎查询**
    - 使用 exa 和 tavily 作为外部服务。
    - 执行两次查询：
        1. 一次直接用重写后的 query 查询；
        2. 一次限定在用户偏好站点（用 repo 查询用户表获取偏好站点，作为参数加到检索请求）。
5. **内容打分（LLM 评分）**
    - 使用 lite LLM 一次性对上一步所有结果打分（输入格式：query + article1 highlight + article2 highlight ...，假定最多50篇，每篇500字符，合计约2.5万token）。
    - 分数标准（0-1分）包括：
        - `relevance_score`: 语义相关性/关键词匹配
        - `authority_score`: 域名权威、可信度、来源质量
        - `coverage_score`: 是否命中强制白名单（可直接指定，白名单1分，非白名单0.6分）
        - `freshness_score`: 发布时间/更新时间
        - `content_quality_score`: 正文长度、引用密度、是否原始来源
        - 其它预留扩展项
6. **归一化与过滤排序**
    - 各项分数归一化，每项可设权重（权重由意图识别环节给出，例如0.3、0.1、0.2、0.2、0.2）。
    - 计算总分：`score = a*0.3 + b*0.1 + ...`
    - 若得分高于0.6的文章超过10篇，直接返回前10篇；否则，将高于0.6者纳入结果集，回到第4步，直到10篇为止。
    - 去重处理：利用搜索引擎的 exclude path 特性，自动排重（查询到的文章都加入 exclude 列表）。
7. **构造最终返回结果**

---

## 2. 计划输出结构

- **现有情况分析**：xxxxx
- **流程图设计**：使用 Mermaid 绘制（见下例）
- **时序图**：用 Mermaid 绘制详细设计
- **模块职责说明**：
    - ### 前端
        - **职责**：xxxx
        - **输入**：
            ```plaintext
            class xxxxx
                attribute notebookid  # 当前用户 notebook id
                ...其它属性
            ```
    - ### step 1
        - **职责**：接收输入，初始化...
        - **输入**：xxxxxx
    - ### step 2
        ...
    - ### 其它扩展
        - **外围功能**、**用户偏好**、**新增用户偏好站点**等，均列明确说明

---

## 3. 拓展说明

- 若有外部功能或模型尚未实现，可直接引用函数名并标明未实现，专注完善 search 包的主要流程。
- 实现必须考虑可扩展性。
- 推荐使用 exa mcp 查询最佳实践。

---

## 4. 参考资料

- [exa API 文档](https://exa.ai/docs/reference/search-api-guide-for-coding-agents)
- [tavily Python 文档](https://docs.tavily.com/sdk/python/reference)
- langgraph 文档：用 doc-langchain mcp 获取最新用法


实施计划：[plan](/Users/taless/.cursor/plans/langgraph_search_refactor_6c77ae14.plan.md)







1. 左右边栏应该和边缘都要有一点点边距
2. 即使正文未解析完毕或者没打开文章，也要支持打开助手，解析过程中助手是灰色的
3. 收起侧边栏的时候，边栏再宽一点点。
4. 笔记本页顶部的布局图标不见了，请补回来，设置页要有，顶部也要有，和深色模式切换一样有两种方法。
5. 字体选择，你把中文和英文分开，默认英文times new roman 默认中文思源宋体。登陆页也是这个默认字体。
6. 文章标题修改不需要那个铅笔图标，把链接图标左移一点。
7. 标签需要存储。新建笔记本的时候，要支持标签

