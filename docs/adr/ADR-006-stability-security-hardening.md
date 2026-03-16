# ADR-006: 稳定性与安全性加固

状态：Proposal  
日期：2026-03-14

## 背景

本 ADR 关注：

- PostgreSQL 运行稳定性
- Redis 缓存一致性
- Kafka 失败与幂等
- SQL / XSS / 加密 / secret lifecycle

当前仓库相关实现主要在：

- `backend/app/modules/jobs/publisher.py`
- `backend/app/infra/mq/producer.py`
- `backend/app/infra/mq/consumer.py`
- `backend/app/modules/ingest/articles/worker.py`
- `backend/app/infra/cache/cache_service.py`
- `backend/app/infra/security/credential_crypto.py`
- `frontend/src/pages/NotebookPage.jsx`

## 当前实现与现状判断

### 1. Kafka 消费端已经有一个正确方向，但还不够

当前 consumer 的优点：

- 手动 commit
- handler 异常时不 commit
- decode / no_handler 才 commit

这点是对的。

但当前仍有三个缺口：

1. producer 没显式配置 idempotence
2. consumer 没有“terminal job 跳过”保护
3. `publish -> mark_job_queued` 之间存在 crash gap

`backend/app/modules/jobs/publisher.py` 里甚至已经直接留了注释：

```python
# TODO 假如程序在这里崩溃了？
```

这不是理论问题，而是当前代码已知风险。

### 2. Job handler 还不具备严格幂等保护

worker handler 目前是：

- 收到消息
- 直接 `processor(payload["jobId"])`

而 `process_article_ingest()` / `process_search_deep()` 进入时没有先判断：

- job 是否已经 `succeeded`
- job 是否已经 `dead`
- job 是否已经被别的 worker 占有

这意味着：

- 重复投递
- 重试投递
- republish

都可能引发重复处理风险。

### 3. Redis 缓存是基础 cache-aside，但没有 stampede / versioning

当前缓存层有：

- `get_json`
- `set_json`
- `delete_keys`

并通过显式失效实现 cache-aside。

优点：

- 简单
- 可控
- summary cache 已基于 `content_hash`

问题：

- notebook detail / search session 仍可能抖动重建
- 没有 singleflight
- 没有版本号键
- cache-aside 本身不保证一致性

### 4. 凭据加密实现偏简化，缺少 rotation 能力

当前 `CredentialCrypto`：

- 用 `SECRET_KEY` 做 sha256
- 直接派生 Fernet key
- 单 key decrypt/encrypt

问题：

- 无 key id
- 无 rotation
- 无 DEK / KEK 分层
- `SECRET_KEY` 变更会直接导致历史密文不可解

### 5. 前端存在明确的 XSS 风险面

`frontend/src/pages/NotebookPage.jsx` 当前文章渲染使用：

- `ReactMarkdown`
- `remarkGfm`
- `rehypeRaw`

但没有配套 sanitization。

这意味着导入内容中的原始 HTML 会被解析进入渲染链路。对于来自网页抓取和文件解析的内容，这个风险不应忽略。

### 6. SQL 注入当前主要靠 ORM，制度化约束还不够

当前 SQLAlchemy ORM 用法总体是安全方向，但：

- 没有显式规则约束后续 raw SQL 的使用
- 没有围绕 query construction 的安全 lint / review guardrail

## 调研到的业界成熟方案

### 1. Kafka 生产端幂等与顺序保证是标准做法

Kafka 官方 producer 配置明确说明：

- `enable.idempotence=true` 可确保流里只写入一份消息
- 需要：
  - `acks=all`
  - `retries > 0`
  - `max.in.flight.requests.per.connection <= 5`

否则重试可能导致重复或乱序。  
参考：[Kafka producer config](https://kafka.apache.org/39/generated/producer_config.html)

### 2. 缓存 aside 天生不保证强一致

Azure Cache-Aside 模式明确指出：

- 它提升性能
- 但不保证 data store 与 cache 强一致
- 需要合理设置过期、淘汰、失效策略

参考：[Cache-Aside pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)

Redis 官方 eviction 文档也强调：

- `maxmemory-policy` 必须和 workload 匹配
- `allkeys-lru` 常是默认起点
- `allkeys-lfu` 适合热点访问明显的场景

参考：[Redis key eviction](https://redis.io/docs/latest/develop/reference/eviction/)

### 3. SQL 注入和 XSS 防护必须显式制度化

OWASP 对 SQL 注入的主张非常明确：

- prepared statements / parameterized queries
- allow-list input validation
- 不依赖字符串 escaping

参考：[OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)

OWASP 对 XSS 的主张也非常明确：

- 先用框架默认保护
- 超出框架保护边界时，必须做 output encoding / HTML sanitization
- HTML Sanitization 推荐 DOMPurify
- CSP 只能做附加层，不能代替主防线

参考：[OWASP XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)

### 4. 密钥管理必须支持生命周期与轮换

OWASP 对密码学存储和 secret management 的建议包括：

- 使用成熟算法与成熟库
- key rotation 预先设计
- 数据加密密钥与密钥加密密钥分离
- 尽量使用集中式 secret management
- 建立 rotation / revocation / audit 生命周期

参考：

- [OWASP Cryptographic Storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

## 决策

采用“Outbox/幂等 job dispatch + cache consistency guard + 渲染面 sanitization + 可轮换密钥管理”的方案。

## 决策细节

### 决策 1：把 job 发布改成 Outbox 风格

当前最关键的问题不是 consumer，而是：

- publish 成功
- 但在 `mark_job_queued()` 之前 API 崩溃

建议改成以下任一方案：

#### 方案 A：标准 transactional outbox

- DB 事务内写 `jobs` + `outbox_events`
- dispatcher 独立轮询 `outbox_events`
- 成功发送后标记 published

#### 方案 B：沿用 jobs 表，但显式加入 publish 状态机

例如：

- `pending_publish`
- `publishing`
- `queued`
- `running`
- `succeeded`
- `failed`
- `dead`

并确保：

- scheduler 只重发 `pending_publish` / `publishing timeout`
- producer publish 使用 `job.id` 作为稳定幂等键

建议优先方案 A，但若想控制改动面，可先落方案 B。

### 决策 2：Kafka producer 显式启用幂等配置

建议：

- `enable.idempotence=true`
- `acks=all`
- `retries` 保持开启
- `max.in.flight.requests.per.connection <= 5`

### 决策 3：consumer / processor 增加 job 状态幂等保护

在 processor 入口增加：

- 若 job 已 `succeeded`：直接跳过并记指标
- 若 job 已 `dead`：直接跳过
- 若 job 已 `running` 且 lease 未超时：跳过

并为 `attempts` 增加 backoff / next_available_at 语义。

### 决策 4：Redis cache 加上 anti-stampede 和 versioning

建议：

- notebook detail / search session 增加 singleflight
- 关键 cache key 支持 version token
- stale-while-revalidate 用于只读详情页
- summary cache 继续沿用 `content_hash` 设计

### 决策 5：文章渲染移除未受控 raw HTML

建议二选一：

1. 直接移除 `rehypeRaw`
2. 保留 `rehypeRaw`，但必须加 `rehype-sanitize` 或 DOMPurify 等等效机制

如果产品并不需要保留原始 HTML 语义，建议优先方案 1。

同时补充：

- 外链 `rel="noopener noreferrer"`
- CSP 作为额外层

### 决策 6：凭据加密升级为可轮换设计

建议：

- 引入 `key_id`
- 支持多把 active / retired key
- 解密时按 `key_id` 找旧 key
- 加密时只用 active key

实现路径：

- 短期：`MultiFernet` 或自定义 keyring
- 中期：DEK / KEK 分层
- 长期：接入 KMS / Vault / cloud secret manager

### 决策 7：制度化 SQL 安全边界

建议：

- 默认只允许 ORM / parameterized query
- 对 raw SQL 增加 code review checklist
- 若使用动态排序、动态表名、动态列名，必须 allow-list

## 具体落地建议

### Phase 1：先补真实薄弱点

1. 修复 job publish crash gap
2. producer 开启 idempotence 配置
3. processor 入口加 terminal-state short circuit
4. notebook article 渲染去掉未受控 raw HTML

### Phase 2：缓存与 secrets

1. notebook detail singleflight
2. search session singleflight
3. 凭据加密增加 key id 与 rotation
4. 引入 secret inventory 与 rotation runbook

### Phase 3：制度化安全治理

1. SQL raw query lint / checklist
2. XSS regression tests
3. secret rotation drills
4. DLQ / poison message handling

## 需要新增或调整的指标

建议新增：

- `mq.duplicate_job_skip_total`
- `mq.publish_gap_recovered_total`
- `mq.dlq_total`
- `cache.singleflight_total`
- `cache.stale_revalidate_total`
- `security.xss_sanitized_total`
- `security.secret_rotation_total`
- `security.secret_decrypt_legacy_key_total`

## 风险与权衡

- outbox 方案会增加发布链路复杂度
- 去掉 `rehypeRaw` 可能改变少数文章的展示效果
- key rotation 需要一次迁移与运维配套

但这些都是值得付出的复杂度，因为它们直接对应当前仓库的真实风险面。

## 验收标准

- 重复投递不会重复处理已完成 job
- Kafka publish/ack 异常不会导致 job 状态漂移
- notebook article 渲染链路通过 XSS regression case
- 凭据支持平滑轮换，不因单次 `SECRET_KEY` 切换整体失效

## 参考资料

- [Kafka producer config](https://kafka.apache.org/39/generated/producer_config.html)
- [Cache-Aside pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)
- [Redis key eviction](https://redis.io/docs/latest/develop/reference/eviction/)
- [OWASP SQL Injection Prevention](https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)
- [OWASP XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- [OWASP Cryptographic Storage](https://cheatsheetseries.owasp.org/cheatsheets/Cryptographic_Storage_Cheat_Sheet.html)
- [OWASP Secrets Management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
