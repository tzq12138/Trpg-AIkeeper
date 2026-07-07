# Plugin / Admin / Ops 开放 API 与后台运维 DeepSeek 计划 V2.1

## 当前阶段说明

- 当前阶段为 `P0 控制面基线 + Admin 权限、生产安全、日志脱敏、MCP/Agent 治理与 Open API 设计风险识别版`。
- 本轮工程不创建真实 API key，不注册 plugin runtime，不开放 webhook，不做多租户，不做生产监控平台。
- 本轮重点是：把后台权限、配置安全、日志脱敏、MCP/Agent 治理、migration/backup 设计和 future OpenAPI scope 收紧。

## 执行原则

1. 每个 Batch 开始前先执行 `git status --short`，确认工作区脏改动，不覆盖无关文件。
2. 先做后端权限与安全基线，再做 AdminDashboard 最小可读性增强，最后才做 Open API / Plugin 设计包。
3. 所有脱敏必须在后端 DTO / log / export 层完成，不能只靠前端遮罩。
4. 所有状态写入必须经过业务服务链，禁止 Plugin / MCP / Agent direct write 主库。
5. `/docs` 只是内部开发文档，不得当作 external OpenAPI 直接开放。

## 当前代码依据

- `src/server/main.py`
- `src/server/config.py`
- `src/server/router_auth.py`
- `src/server/router_admin.py`
- `src/server/ai/gateway.py`
- `src/server/ai/providers.py`
- `src/server/ai/kp_mcp_client.py`
- `src/server/agent/tools.py`
- `src/server/db_adapter.py`
- `src/client/src/pages/AdminDashboard.tsx`
- `kp_mcp_server/config.py`
- `kp_mcp_server/server.py`
- `dev.py`
- `docker-compose.yml`

## 全局硬规则

- `admin:read` / `admin:write` 仅内部使用，不给第三方 API key。
- `engine_save_clue` 第一轮默认 `disabled` 或 `suggest_only`。
- production 下不允许 `CORS=*`。
- production 下不允许无鉴权 MCP 暴露到 `0.0.0.0`。
- `owner_token`、`player_token`、JWT、API key、provider key、webhook secret、DSN password、raw prompt、raw response、RAG raw context 不得进入普通日志、admin DTO、public export。
- restore 必须 `confirm + target DB`；production restore 必须二次确认。

## Batch Ops-0：现状复核与权限基线

### 目标

- 核对当前仓库真实能力与未实现能力。
- 回归 Admin、RAG、test DB、WS 基础权限。
- 明确当前没有 API key、plugin registry、webhook、tenant、backup restore、plugin runtime。
- 明确 MCP 是内部 AI provider，不是开放插件系统。

### 允许改动

- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 只读检查 `src/server/`、`kp_mcp_server/`、`tests/server/`

### 建议命令

```bash
rg -n "api_key|plugin|webhook|tenant|backup|migration_versions|admin_audit" src tests kp_mcp_server
python -m pytest tests/server/test_admin_auth.py tests/server/test_rag_security.py tests/server/test_db_isolation.py tests/server/test_ws_auth.py -q
```

### 验收

- 形成“已存在 / 未存在”现状结论。
- 权限测试通过或准确列出失败项。
- 不产生源码改动。

### 禁止事项

- 不新增第三方 API 能力。
- 不放宽 admin / RAG / WS 鉴权。

## Batch Ops-1：生产配置与 health 分级

### 目标

- 固化 `APP_ENV=development|test|production`。
- 收紧 `JWT_SECRET`、CORS allowlist、MCP 绑定/鉴权、public/admin health。
- 只修配置基线，不重构整套配置系统。

### 允许改动

- `src/server/config.py`
- `src/server/main.py`
- `src/server/router_auth.py`
- `kp_mcp_server/config.py`
- 可新增 `tests/server/test_ops_config.py`

### 建议命令

```bash
python -m pytest tests/server/test_ops_config.py tests/server/test_admin_auth.py tests/server/test_ws_auth.py -q
```

### 验收

- production + 默认 secret 启动失败或 health degraded。
- production 禁止 `CORS=*`。
- public health 不返回 secret、DSN、provider key、完整 provider error。
- admin health 仅 admin 可见，返回脱敏组件详情。

### 禁止事项

- 不牺牲 `python dev.py` 的本地开发体验。
- 不把真实 secret 打进日志。

## Batch Ops-2：Admin 审计基线

### 目标

- 建立 `AdminAuditLogDTO`、审计 helper 和数据落点。
- 优先覆盖最高风险操作：角色修改、房间状态修改、AI 配置修改、素材删除、RAG reindex、spoiler rebuild、backup restore。
- 把审计字段口径写死，避免写成 request dump。

### 允许改动

- `src/server/router_admin.py`
- `src/server/db_adapter.py`
- 可新增 `src/server/admin_audit.py`
- 可新增 `tests/server/test_admin_audit.py`

### 建议命令

```bash
python -m pytest tests/server/test_admin_auth.py tests/server/test_admin_audit.py -q
```

### 验收

- 高风险 Admin 操作写入审计。
- 审计包含 `auditId/actorAccountId/actorRole/action/targetType/targetId/requestId/createdAt` 等最低字段。
- 审计中不出现 `password_hash`、`owner_token`、`player_token`、JWT、API key、raw prompt、raw response、完整 request body。

### 禁止事项

- 不改变现有 Admin API 成功语义。
- 不把 audit 暴露给 player/public。

## Batch Ops-3：日志脱敏与 AI/RAG 安全摘要

### 目标

- 建立后端统一 redaction helper。
- 收紧普通日志、AI logs、health DTO、export DTO。
- `AiCallLogSafeDTO` 只保留 provider/status/duration/task/summary hash 或截断摘要。

### 允许改动

- `src/server/log_config.py`
- `src/server/ai/gateway.py`
- `src/server/router_admin.py`
- `src/server/export.py`
- 可新增 `src/server/security/redaction.py`
- 可新增 `tests/server/test_redaction.py`

### 建议命令

```bash
python -m pytest tests/server/test_redaction.py tests/server/test_archive.py tests/server/test_admin_auth.py -q
```

### 验收

- token / key / raw prompt / raw response / RAG raw context 不进入普通日志和 public export。
- AI logs 保留排障所需的安全摘要字段。
- RAG context preview 保持 admin-only。

### 禁止事项

- 不只在前端遮敏。
- 不为脱敏删除必要的 provider/status/duration/errorClass。

## Batch Ops-4：MCP 与 Agent tools 治理

### 目标

- 为 MCP 增加生产模式服务间鉴权或内网限定。
- 为 Agent tools 建立 `read_only / suggest_only / controlled_write / disabled` 分级。
- `engine_save_clue` 第一轮默认 `disabled` 或 `suggest_only`，绝不 direct write。

### 允许改动

- `kp_mcp_server/config.py`
- `kp_mcp_server/server.py`
- `src/server/ai/providers.py`
- `src/server/ai/kp_mcp_client.py`
- `src/server/agent/tools.py`
- 可新增 `tests/server/test_mcp_security.py`
- 可新增 `tests/server/test_agent_tool_permissions.py`

### 建议命令

```bash
python -m pytest tests/server/test_mcp_security.py tests/server/test_agent_tool_permissions.py tests/server/test_spoiler_guard.py -q
```

### 验收

- production 下 MCP 无 token 或错误 token 不能调用。
- dev/mock 模式 MCP 仍可本地运行。
- `engine_save_clue` 不能 direct INSERT。
- MCP / Agent tool call 至少有最小 audit。

### 禁止事项

- 不让 MCP 直接连接主库写状态。
- 不把服务间 token 暴露给前端。
- 不降低 schema 校验和反剧透要求。

## Batch Ops-5：AdminDashboard 最小运维增强

### 目标

- 只补 health、audit、AI/RAG 状态和中文乱码修复。
- 不重做后台整体 UI 架构。

### 允许改动

- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/shared/api.ts`
- 必要时 `src/server/router_admin.py`

### 建议命令

```bash
cd src/client && npm run build
python -m pytest tests/server/test_admin_auth.py -q
```

### 验收

- Admin 可查看脱敏 health/config。
- Admin 可查看 audit 列表或明确本轮未做查询页的占位说明。
- 前端 build 通过，中文文案无乱码。

### 禁止事项

- 不展示 secret、token、完整 DSN。
- 不重做整套 AdminDashboard。

## Batch Ops-6：migration / backup 安全设计与最小实现

### 目标

- 建立 `migration_versions`。
- 给 backup/restore 建立安全约束与测试保护。
- 先做“可追踪、可确认、不会误伤”，不做生产级调度平台。

### 允许改动

- `src/server/db_adapter.py`
- 可新增 `src/server/migrations/`
- 可新增 `scripts/backup.ps1` 或 `scripts/backup.py`
- 可新增 `tests/server/test_migrations.py`
- 可新增 `tests/server/test_backup_safety.py`

### 建议命令

```bash
python -m pytest tests/server/test_db_adapter.py tests/server/test_db_isolation.py tests/server/test_migrations.py tests/server/test_backup_safety.py -q
```

### 验收

- `migration_versions` 记录 `version/name/checksum/applied_at`。
- migration 可重复执行，失败不半应用。
- restore 必须 `confirm + target DB`。
- 测试拒绝连接非 test DB。

### 禁止事项

- 不使用 silent destructive reset。
- 不默认覆盖现有数据库。

## Batch Ops-7：external OpenAPI / Plugin 设计包

### 目标

- 只做设计，不实现真实开放能力。
- 定义 `ApiClientDTO`、`PluginManifestDTO`、`PluginScopeDTO`、`WebhookSubscriptionDTO`。
- 写清 allowlist routes、scope 和禁止清单。

### 允许改动

- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Plugin-OpenAPI设计.md`

### 建议命令

```bash
rg -n "ApiClientDTO|PluginManifestDTO|WebhookSubscriptionDTO|external OpenAPI|owner_token|player_token" docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维
```

### 验收

- 每个 scope 有允许项和禁止项。
- 文档明确 external OpenAPI 不包含 Admin API、truth、private events、token、MCP 内部接口。
- 文档明确本轮不创建真实 API key，不注册 plugin runtime，不开放 webhook。

### 禁止事项

- 不新增真实 API key 表或运行时。
- 不开放 webhook。
- 不实现插件执行框架。

## Batch Ops-8：回归验收

### 目标

- 回归 Admin、RAG、AI、MCP、安全配置与跑团主链路。

### 建议命令

```bash
python -m pytest tests/server/test_admin_auth.py tests/server/test_rag_security.py tests/server/test_db_isolation.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_archive.py tests/server/test_spoiler_guard.py tests/server/test_room_security.py -q
python dev.py --check
cd src/client && npm run build
```

### 手动验收

1. Admin 登录并进入后台。
2. Player 访问后台被拒绝。
3. Admin 修改房间状态后产生审计。
4. Admin 查看 AI logs、RAG 状态、spoiler audits。
5. public health 不泄露敏感配置。
6. production 配置下无鉴权 MCP 不可公网暴露。
7. 创建房间 -> 玩家加入 -> ready -> 开局 -> AI/规则裁决 -> 投影 -> 日志链路仍可完成。

### 禁止事项

- 不跳过权限测试。
- 不把开发默认配置当作生产安全。
- 不在 Open API / Plugin 设计未验收前开放第三方写接口。
