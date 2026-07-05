# Plugin / Admin / Ops 开放 API 与后台运维 PRD V2.0

## 背景

AI-Keeper 的核心跑团链路越强，后台和运维边界越重要。Admin 能管理账号、房间、剧本、素材、AI、RAG 和安全审计；Ops 要保证配置、部署、健康、日志、备份和恢复可靠；Open API 和 Plugin 未来会把能力开放给外部集成和扩展，但这也会带来越权、剧透、数据泄露和不可审计写入的风险。

当前仓库已经有 Admin API、AdminDashboard、RAG 管理、AI Gateway、KP MCP Server、`/api/health`、Docker Compose、`dev.py`、日志配置和测试数据库隔离。当前没有第三方开发者平台、API key、插件注册、Webhook、多租户、正式备份恢复和生产监控。

## 目标

1. 固化当前 Admin/Ops 能力和真实缺口。
2. 建立生产安全基线：强 secret、CORS、MCP 暴露、日志脱敏、health 分级。
3. 为未来 Open API 和 Plugin 定义 scope、凭证、审计和禁止边界。
4. 把 AI、RAG、MCP、Agent tools 的管理能力纳入受控后台。
5. 给 DeepSeek 后续工程批次提供可执行的文件方向、测试命令和禁止事项。

## 非目标

- 不在本轮实现插件市场。
- 不开放第三方 API key。
- 不实现 Webhook、OAuth app、计费、多租户。
- 不重做 AdminDashboard 全套 UI。
- 不让插件或 MCP 直接写数据库状态。
- 不让 Admin/Ops 改写跑团规则、裁决、状态事务口径。

## 用户角色

| 角色 | 诉求 | 权限边界 |
| --- | --- | --- |
| Admin | 管理账号、房间、剧本、素材、AI、RAG、安全审计 | 当前唯一后台角色；所有高风险操作应审计 |
| Ops | 部署、配置、日志、备份、恢复、健康和告警 | 通过环境变量、脚本和受控后台操作，不直接篡改业务数据 |
| Developer | 本地启动、调试接口、跑测试 | 使用 `/docs`、`dev.py`、pytest、前端 build |
| Plugin Developer | 未来开发受控扩展 | 当前未开放；未来必须申请 API key 和 scope |
| Internal AI/MCP | 通过 MCP 和 provider 链辅助 AI-Keeper | 只能返回建议或结构化结果，不能越权落库 |
| Host | 通过受限后台或房间配置管理自己的房间 | 不是 Admin，不能访问全局后台 |
| Auditor | 未来查看审计记录和安全事件 | 只读，不改配置 |

## 范围

### v1 进入

- Admin API 和 AdminDashboard 当前能力盘点。
- `/api/health` 和运行组件健康口径。
- Settings、Docker Compose、`dev.py`、日志配置、本地开发命令。
- AI Gateway、AI logs、RAG 管理、Spoiler audit、KP MCP Server 的边界。
- 生产安全基线设计。
- 插件和开放 API 的权限模型设计，不实现市场。

### v1 不进入

- API key 实现。
- 插件 manifest 解析和插件运行时。
- 第三方 Webhook。
- 多租户隔离。
- 付费、配额、账单。
- 完整监控告警平台。
- 生产级备份调度服务。

## 当前接口分区

| 分区 | 当前接口 | 权限口径 | 说明 |
| --- | --- | --- | --- |
| Public health | `GET /api/health` | 当前公开 | 返回较多内部组件状态，生产应分级 |
| Auth | `/api/auth/register`、`/login`、`/me` | 登录态 | 手写 HS256 token，缺撤销 |
| Admin | `/api/admin/*` | admin only | 后台强能力集中 |
| Room/Host | `/api/rooms/*`、`/api/host/*` | owner/admin 或房间公开 DTO | 房间生命周期和 Host 操作 |
| Player | `/api/player/*` | player token 或账号 | 玩家行动、归档、加入 |
| RAG | `/api/rag/*` | admin/owner/player 按读写分级 | 内部受控 API 样板 |
| Scenario | `/api/scenarios/*` | admin/host/player 分接口 | 导入 admin-only，可用列表 host/admin |
| WebSocket | `/ws` | host owner token 或 player token | 实时投影入口 |
| MCP | `kp_mcp_server /mcp` | 当前无平台鉴权 | 内部 AI provider 服务 |

## 未来 Open API 分层

| 层级 | 调用方 | 凭证 | 能力 |
| --- | --- | --- | --- |
| Internal REST | 前端和服务内部 | account token、owner token、player token | 当前主要接口 |
| Admin API | AdminDashboard 和内部工具 | admin account token | 全局管理和审计 |
| Room API | Host/Player 客户端 | owner/player token | 房间内操作 |
| Plugin API | 未来插件 | API key + scope + 可选用户授权 | 受控扩展 |
| Public API | 未来公开内容 | 无登录或低权限 token | 只读公开内容 |

原则：

- 自动 `/docs` 是内部开发文档，不等于 external OpenAPI。
- external OpenAPI 必须按 scope 过滤接口和 schema。
- 所有写接口都要有调用主体、目标资源、scope、审计和限流。

## 插件权限模型方向

| Scope | 示例能力 | 默认 |
| --- | --- | --- |
| `read:public` | 读取公开模组、公开招募、公开战报 | 可申请 |
| `read:room` | 读取授权房间公开状态 | 需要房间 owner 授权 |
| `read:player:self` | 读取当前玩家自己的角色摘要 | 需要玩家授权 |
| `write:intent` | 代玩家提交 intent | 高风险，需要玩家授权和限流 |
| `write:message` | 发送队伍消息或通知 | 高风险，需要房间授权 |
| `write:clue` | 写线索 | 默认禁用，必须通过 Engine/State 验证 |
| `admin:read` | 读取后台信息 | 内部 only |
| `admin:write` | 改后台配置 | 内部 only，默认不开放 |
| `ai:invoke` | 调 AI provider 或 MCP 工具 | 内部 only，必须记录 AI call log |
| `rag:read` | 检索 RAG | 按房间成员权限裁剪 |
| `rag:write` | 重建索引 | admin/owner only |

## 数据模型方向

| 表 | 主要字段方向 | 说明 |
| --- | --- | --- |
| `admin_audit_logs` | `audit_id`、`actor_account_id`、`action`、`target_type`、`target_id`、`before`、`after`、`ip`、`created_at` | Admin/Ops 操作审计 |
| `api_clients` | `client_id`、`owner_account_id`、`name`、`status`、`created_at` | 未来开放 API 调用方 |
| `api_keys` | `key_id`、`client_id`、`key_hash`、`prefix`、`status`、`expires_at`、`last_used_at` | key 只存 hash 和短 prefix |
| `api_scopes` | `client_id`、`scope`、`resource_type`、`resource_id` | API 权限声明 |
| `plugin_manifests` | `plugin_id`、`name`、`version`、`author_account_id`、`entry_type`、`status`、`requested_scopes` | 插件注册和审核 |
| `plugin_installs` | `install_id`、`plugin_id`、`room_id`、`installed_by`、`granted_scopes`、`status` | 房间或平台安装 |
| `webhook_subscriptions` | `subscription_id`、`client_id`、`event_types`、`target_url`、`secret_hash`、`status` | 未来事件推送 |
| `migration_versions` | `version`、`name`、`applied_at`、`checksum` | DB 版本化 |
| `backup_jobs` | `job_id`、`scope`、`status`、`path`、`started_at`、`finished_at`、`error` | 备份恢复审计 |
| `ops_incidents` | `incident_id`、`severity`、`component`、`status`、`summary`、`created_at` | 未来告警和故障记录 |

## 生产安全基线

| 项目 | 当前状态 | 目标 |
| --- | --- | --- |
| `JWT_SECRET` | 有开发默认值 | 非开发环境必须强制自定义 |
| CORS | `allow_origins=["*"]` | 生产使用 allowlist |
| MCP 绑定 | 默认 `0.0.0.0:9100` | 生产默认 localhost 或内网，并增加服务间 token |
| Docker 密码 | 默认 `aikeeper123` | 生产必须使用外部 secret |
| 日志 | 普通文本 | 增加 token/API key/prompt 脱敏 |
| Health | 公开详细组件 | public 简要，admin 详细 |
| Upload | 基础文件写入 | 增加大小、MIME、文件头、路径、清理测试 |
| DB schema | 自动建表和 ALTER | 增加 versioned migration |
| Backup | 未实现 | 定期备份、恢复演练、测试库保护 |
| AI logs | 保存摘要 | 摘要不能含密钥、token、完整 prompt、未公开真相 |

## MCP 和 Agent 工具边界

KP MCP Server 当前工具：

- `kp_resolve_turn`
- `kp_resolve_sanity`
- `kp_resolve_combat_round`
- `kp_structure_scenario`
- `kp_query_rules`
- `kp_query_knowledge`
- `kp_health_check`

边界：

- MCP 只返回结构化建议或 AI 结果，不直接写主库。
- 后端必须继续做 schema 校验、反剧透、Engine/State 验证。
- MCP 服务生产环境不得无鉴权公网暴露。
- MCP 输入不应包含未授权玩家私密内容。

Agent tools 当前有查询工具、掷骰工具和 `engine_save_clue` 写入工具。写入工具必须进入高风险治理：默认禁用或改为提交建议，由 Engine/State/Journal 统一落库。

## 与核心模块关系

- User 决定账号、角色和 token。
- Safety 决定脱敏、CORS、secret、日志、公开 export、MCP 暴露边界。
- State 和 Transaction 决定状态写入，不允许 Plugin/MCP 直接改表。
- Projection 决定实时可见性，不允许 Webhook 或 Plugin 绕过过滤。
- Journal 记录事件、导出、审计和回放。
- AI-Keeper 通过 Gateway/MCP 获取建议，但最终写入必须经 Engine/State。
- Community 未来消费 Open API 的公开内容，但不获得内部 Admin 能力。

## 验收标准

### 文档阶段

- 明确当前无第三方插件系统、API key、Webhook 和多租户。
- 明确当前已有 Admin、RAG、AI、MCP、dev、Docker、health 能力。
- 明确生产安全风险和 P1 补强顺序。
- DeepSeek 计划每批都有测试命令和禁止事项。

### 工程阶段

- Admin API 权限测试通过。
- RAG 权限测试通过。
- test DB 隔离测试通过。
- health 能区分 public 和 admin 细节。
- 默认 secret、开放 CORS、无鉴权 MCP 在生产配置下被拦截。
- Admin 高风险操作有审计。
- AI/RAG/MCP 调用不泄露 token 和完整 prompt。

### 回归阶段

- 创建房间、玩家加入、ready、开局、AI 裁决、投影、日志仍能跑通。
- Open API 或插件相关改动不改变核心链路行为。
- 前端 AdminDashboard build 通过。
- 本地 `python dev.py --check` 仍能使用。
