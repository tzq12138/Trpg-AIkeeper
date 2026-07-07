# Plugin / Admin / Ops 开放 API 与后台运维 PRD V2.1

## 当前阶段说明

- 当前阶段为 `P0 控制面基线 + Admin 权限、生产安全、日志脱敏、MCP/Agent 治理与 Open API 设计风险识别版`。
- 本 PRD 通过，不等于允许对外开放第三方 API、发放 API key、注册插件、开放 Webhook 或让插件/MCP/Agent 直写状态。
- 当前代码以内部后台、开发运维、AI/RAG/MCP 辅助为主；Open API 与 Plugin 仍处于设计层。

## 1. 背景

AI-Keeper 的核心跑团链路越稳定，平台控制面越需要明确边界。当前仓库已经有可用的后台接口、RAG 管理、AI Gateway、KP MCP Server、健康检查和本地运维脚本，但这些能力仍偏开发态：

- 后台强能力已存在，但高风险操作审计不统一；
- `main.py` 已拒绝生产默认 `JWT_SECRET`，但 `CORS=*`、public health 细节、MCP 暴露策略仍需收紧；
- `ai_call_logs`、RAG 预览、MCP、Agent tools 已经触达敏感数据边界；
- `engine_save_clue` 暴露出“工具写入绕过业务链路”的真实风险；
- 数据库仍以初始化脚本为主，没有正式 migration / backup / restore 体系。

因此 24 模块的 v1 重点不是“把系统开放出去”，而是“先把控制面、安全面和运维面收稳”。

## 2. 目标

1. 固化 Admin / Ops / AI / RAG / MCP / Agent 的治理边界。
2. 建立 production 配置基线：secret、CORS、health 分级、MCP 暴露、日志脱敏。
3. 固化高风险后台操作的审计契约。
4. 为 migration / backup / restore 建立安全前置约束。
5. 为 future Open API / Plugin 定义 scope、DTO、禁止清单，但不实现第三方运行时。

## 3. 非目标

- 不在本轮发放真实 API key。
- 不实现插件注册中心、插件运行时、插件市场。
- 不实现 Webhook 订阅执行。
- 不实现多租户、付费、配额、正式监控告警平台。
- 不让 Admin/Ops 改写 Room / Rule / AI / State / Transaction 的业务真相边界。
- 不允许 Plugin / MCP / Agent 直接写数据库主状态。

## 4. 角色与权限

| 角色 | 诉求 | 权限边界 |
| --- | --- | --- |
| Admin | 账号、房间、剧本、素材、AI、RAG、审计管理 | 全局后台能力，但必须被 audit |
| Ops | 配置、部署、健康、日志、备份恢复治理 | 通过环境变量、脚本和受控后台能力操作，不直接改业务真相 |
| Developer | 本地开发、调试、验证 | 使用 `dev.py`、`/docs`、pytest、前端 build |
| InternalService | 内部服务间调用 | 必须有服务间身份，不借用前端 token |
| Host | 管理自己房间 | 不是 Admin，不读全局后台 |
| Player | 使用跑团主链路 | 不接触后台与运维面 |
| Future Auditor | 查审计与安全事件 | 只读，不写配置 |

## 5. 当前现状

### 已存在

- `src/server/router_admin.py`：后台 overview、rooms、accounts、characters、assets、AI、RAG、spoiler audits。
- `src/client/src/pages/AdminDashboard.tsx`：基础后台 UI。
- `src/server/main.py`：`/api/health`、组件初始化、生产默认 secret 启动拒绝。
- `src/server/ai/gateway.py`：AI provider 链与 `ai_call_logs`。
- `kp_mcp_server/`：7 个 MCP 工具。
- `src/server/agent/tools.py`：查询工具与 `engine_save_clue`。
- `tests/server/test_admin_auth.py`、`test_rag_security.py`、`test_db_isolation.py`、`test_ws_auth.py`：已有关键安全基线。

### 未存在

- `admin_audit_logs`
- `migration_versions`
- `backup_jobs`
- 第三方 `ApiClient` / `ApiKey`
- `PluginManifest` runtime
- `WebhookSubscription`
- 多租户与插件市场

## 6. 产品边界

### 本模块负责

- Admin 控制面与后台读写规范；
- Ops 配置、health、日志、migration/backup 的治理口径；
- AI/RAG/MCP/Agent 的运维和权限治理；
- 未来 external OpenAPI / Plugin 的准入规则。

### 本模块不负责

- AI 裁决内容本身；
- 规则结算逻辑；
- 世界真相写入；
- Projection 可见性判定本体；
- Journal 跑团事件归档本体。

## 7. 数据分层

| 层级 | 数据对象 | 产品含义 | 边界要求 |
| --- | --- | --- | --- |
| L0 | `RuntimeConfig` | 运行配置 | 不暴露 secret |
| L1 | `Principal` | 调用主体 | 不信任前端角色自报 |
| L2 | `AdminOperation` | 后台操作 | 必须可追责 |
| L3 | `AdminAuditLog` | 审计记录 | admin only，never export |
| L4 | `HealthReport` | 健康状态 | public/admin 分层 |
| L5 | `RedactionPolicy` | 脱敏规则 | 后端统一执行 |
| L6 | `AiOpsLog` | AI 运维日志 | 摘要化，不留 raw |
| L7 | `RagOpsAction` | RAG 运维操作 | owner/admin 分层 |
| L8 | `McpToolCall` | MCP 调用审计 | 服务间身份、不可直写状态 |
| L9 | `AgentToolCall` | Agent tool 权限/审计 | 写工具默认禁写或受控 |
| L10 | `MigrationVersion` | schema 版本 | 可追踪、可重复执行 |
| L11 | `BackupJob` | 备份恢复任务 | 高风险确认 |
| L12 | `ApiClient` | 未来外部调用方 | 本轮不实现 |
| L13 | `PluginManifest` | 未来插件声明 | 本轮不实现 |
| L14 | `WebhookSubscription` | 未来事件订阅 | 本轮不实现 |

## 8. DTO 契约

### 8.1 当前必须定义

- `OpsConfigSnapshotDTO`
- `PublicHealthDTO`
- `AdminHealthDTO`
- `AdminAuditLogDTO`
- `AdminAuditQueryDTO`
- `AdminAuditResultDTO`
- `RedactionRuleDTO`
- `AiProviderStatusDTO`
- `AiCallLogSafeDTO`
- `RagOpsStatusDTO`
- `McpToolStatusDTO`
- `McpToolCallAuditDTO`
- `AgentToolPermissionDTO`
- `AgentToolCallAuditDTO`
- `MigrationVersionDTO`
- `BackupJobDTO`
- `RestoreRequestDTO`
- `OpsApiErrorDTO`

### 8.2 仅设计

- `ApiClientDTO`
- `ApiKeyCreateRequestDTO`
- `ApiKeyCreatedDTO`
- `PluginManifestDTO`
- `PluginScopeDTO`
- `WebhookSubscriptionDTO`

### 8.3 关键规则

- `PublicHealthDTO` 只返回 `status/version/environment` 等安全摘要。
- `AdminHealthDTO` 允许返回组件细节与脱敏配置快照，但仅 Admin 可见。
- `AdminAuditLogDTO` 固定字段，不允许漂移成“整包 request dump”。
- `AiCallLogSafeDTO` 只返回 provider/status/task/duration/summary hash 或截断摘要，不返回 raw prompt/raw response。

## 9. 环境模式矩阵

| 配置项 | development | test | production |
| --- | --- | --- | --- |
| 默认 `JWT_SECRET` | 允许但告警 | 允许测试值 | 禁止启动或 health degraded |
| CORS `*` | 允许 | 允许本地测试 | 禁止 |
| MCP `0.0.0.0` 无鉴权 | 仅本地 mock/dev | 默认禁止 | 禁止 |
| `/docs` | 允许 | 可允许 | 默认关闭或仅内网/admin |
| public health 细节 | 简要 | 简要 | 简要 |
| admin health 细节 | admin only | admin only | admin only |
| secrets 写日志 | 禁止 | 禁止 | 禁止 |
| destructive fixture | 仅 test DB | 仅 test DB | 禁止 |

## 10. 核心需求

### 10.1 Admin 控制面

用户故事：

- 作为 Admin，我需要稳定地查看房间、账号、角色、素材、AI、RAG 状态。
- 作为平台负责人，我需要知道哪些操作是谁做的、改了什么、为什么改。

需求：

- `/api/admin/*` 保持 admin only。
- 高风险操作必须写 `AdminAuditLogDTO`。
- Admin API 默认返回脱敏 DTO，不透出 `password_hash`、token、raw prompt、绝对路径。

### 10.2 health 分层

用户故事：

- 作为外部调用者，我只能知道服务是否活着。
- 作为 Admin/Ops，我需要看到更细的组件级状态和脱敏配置。

需求：

- public health 与 admin health 分离。
- public health 不透出 DSN、provider key、完整错误栈、绝对路径。
- admin health 允许细节，但仍需脱敏。

### 10.3 配置与生产安全

需求：

- production 禁用默认 `JWT_SECRET`。
- production 禁用 `CORS=*`。
- MCP 在 production 下默认不能无鉴权暴露到 `0.0.0.0`。
- `/docs` 不能直接被当作 external OpenAPI。

### 10.4 Admin 审计

`AdminAuditLogDTO` 最低字段：

- `auditId`
- `actorAccountId`
- `actorRole`
- `action`
- `targetType`
- `targetId`
- `roomId?`
- `scenarioId?`
- `beforeSummary?`
- `afterSummary?`
- `reason?`
- `ipHash?`
- `userAgentHash?`
- `requestId?`
- `createdAt`

禁止写入审计：

- `password_hash`
- `owner_token`
- `player_token`
- JWT / account token
- API key / provider key / webhook secret
- raw prompt / raw response
- 完整 request body
- 本地绝对路径

### 10.5 日志脱敏

必须脱敏：

- `owner_token`
- `player_token`
- JWT
- API key
- provider key
- webhook secret
- DSN password
- `password_hash`
- raw prompt
- raw response
- RAG raw context
- local absolute path
- `original_file_path`

允许保留：

- `provider`
- `status`
- `durationMs`
- `task`
- `roomId`
- `actionId`
- `scenarioId`
- `errorClass`
- 摘要 hash / 截断摘要

### 10.6 MCP / Agent 治理

MCP 规则：

- 生产模式必须有服务间 token 或仅限 localhost/内网。
- MCP tool call 必须被 audit。
- MCP 不得直写主库状态。

Agent tools 规则：

- 权限档位固定为 `read_only / suggest_only / controlled_write / disabled`。
- `engine_save_clue` 第一轮默认 `disabled` 或 `suggest_only`。
- 如启用写入，必须经过 `Clue / State / Journal` 服务链。

### 10.7 migration / backup

需求：

- `migration_versions` 必须记录 `version/name/checksum/applied_at`。
- migration 要可重复执行，失败不能半应用。
- 禁止 silent destructive reset。
- backup 默认只读。
- restore 必须 `confirm + target DB`。
- production restore 必须二次确认。
- 测试不得连接生产库。

### 10.8 future Open API / Plugin 设计约束

`read:public`：不能读 `raw_text / truth / private events`。  
`read:room`：只能读授权房间 safe DTO。  
`write:intent`：必须有玩家授权与 rate limit，不能绕过 Player Intent。  
`write:message`：不能伪造系统消息或越 audience。  
`write:clue`：默认禁用，必须走 `Clue / State / Journal`。  
`admin:read` / `admin:write`：internal only。  
`ai:invoke`：internal only。  
`rag:write`：admin/owner only。  

## 11. 高风险 Admin 操作矩阵

| 操作 | 是否审计 | 是否要求 reason | 是否可撤销 |
| --- | --- | --- | --- |
| `account.role.update` | 是 | 建议 | 可通过再次修改修正 |
| `room.status.update` | 是 | 是 | 视状态而定 |
| `scenario.import/delete/archive` | 是 | 是 | 删除不可逆 |
| `asset.upload/delete/force_delete` | 是 | `force_delete` 强制 | 删除不可逆 |
| `ai.provider_config.update` | 是 | 是 | 可恢复上一配置 |
| `rag.reindex` | 是 | 可选 | 不适用 |
| `spoiler.index.rebuild` | 是 | 可选 | 不适用 |
| `mcp.config.update` | 是 | 是 | 可恢复上一配置 |
| `backup.restore` | 是 | 强制 | 高风险二次确认 |

## 12. `/docs` 与 external OpenAPI 边界

### Internal `/docs`

- 当前 FastAPI 自动生成文档。
- 服务开发使用。
- 生产默认关闭或只给 admin/internal。
- 不构成对外 API 承诺。

### external OpenAPI

- 未来必须由 allowlist routes + scope schema 生成。
- 不包含 Admin API。
- 不包含 raw scenario、raw events、truth、private events。
- 不包含 `owner_token` / `player_token`。
- 不包含 MCP 内部接口、AI provider 内部调用。

## 13. 验收标准

### 文档阶段

1. 明确哪些能力已存在，哪些尚未实现。
2. 明确当前阶段不是第三方开放版。
3. 明确数据分层、DTO 契约、环境矩阵、审计字段、脱敏规则、MCP/Agent 治理、migration/backup 安全策略。

### 工程阶段

1. Admin API 未登录 401、Player 403、Admin 200。
2. public health 不泄露 secret / DSN / provider key。
3. admin health admin only，且返回脱敏细节。
4. 高风险操作产生 audit。
5. logs / AI logs / export 不泄露 token / key / raw prompt / raw response。
6. `engine_save_clue` 不可 direct write。
7. production 下不允许无鉴权 MCP 公网暴露。
8. 仍未开放真实 API key / plugin runtime / webhook。
