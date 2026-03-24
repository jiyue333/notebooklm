# 解析链路重构（Ingest Pipeline）

请按照以下设计重构 ingest 链路，实现将各种来源内容（网页、文字、文件等）统一转换为富文本并渲染，为用户提供一致的阅读体验。

## 方案概览

Ingest 任务分层结构如下：

- **接入层**（统一化）：负责内容归一化，调用 Apache Tika 并进行路由判断。
- **解析层**：全部采用 MINERU 解析。如果为文字内容，先将其存储为文件后上传，并统一转为 markdown 格式。
- **规范化层 & 渲染层**：使用 remark+LLM fallback（TOC 生成等辅助），具体包括规范化、增强及渲染流程。

## 核心步骤

1. **接入层：**
   - 使用 Apache Tika 提取内容元数据与正文，判定内容类型并路由后续处理。

2. **解析层：**
   - 全部内容调用 MINERU 进行解析。
   - 若为文字，则先保存为文件再进入 MINERU。
   - 所有内容统一输出为标准 markdown。

3. **规范化层与渲染层：**
   - **remark** 处理 markdown，支持以下功能：
     1. **AST 序列化**：将 markdown 转为 AST 并存储，后续功能有扩展点。
     2. **修复功能**：处理因解析器产生的显示错误，如：
        - 换行异常、段落断裂、标题级别、列表错乱、代码块未闭合、表格/链接格式、连续空行，以及 OCR 段落乱码等。
     3. **增强功能**：为阅读器增加信息，如自动生成 TOC（目录）、估算阅读时间、文档摘要（可直接调用 summary 链路，如 `get_document_summary()`）。
     4. **渲染功能**：用 remark 渲染为 HTML，交由前端显示。

---

## 实施要求

- 本方案按照新功能开发，原有 ingest 相关代码可全部移除。
- 请输出完整的计划文档，包括：
  - 输入输出定义。
  - 完整功能流程图。
  - 各层职责与扩展点说明。

- 如依赖外部功能（如 summary），目前未实现时可直接引用函数名并跳过实现，专注完善 ingest 包结构。

---

## 参考资料

- [MINERU API 文档](https://mineru.net/apiManage/docs)
- [remark 生态列表](https://github.com/remarkjs/awesome-remark?tab=readme-ov-file)

---

实施计划：[plan](/Users/taless/.cursor/plans/ingest_pipeline_refactor_311f3458.plan.md)
