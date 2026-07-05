# Plugin / Admin / Ops 开放 API 与后台运维 DeepSeek 计划 V2.0

## 执行原则

先稳后台权限、生产安全和运维基线，再谈开放 API 和插件。任何开放能力都不能绕过 Auth、Safety、State、Transaction、Projection、Journal。DeepSeek 开始每个 Batch 前先执行 `git status --short`，读懂已有未提交改动，不覆盖无关文件。

本模块改动风险高，涉及后台、配置、日志、AI、RAG、MCP 和数据库。每个工程 Batch 都必须有测试，不能只靠手动验证或前端隐藏。

## 现状依据

- 应用入口和 health：`src/server/main.py`
- 配置：`src/server/config.py`
- 日志：`src/server/log_config.py`
- DB 初始化：`src/server/db_adapter.py`
- Admin API：`src/server/router_admin.py`
- Admin UI：`src/client/src/pages/AdminDashboard.tsx`
- Auth：`src/server/router_auth.py`
- RAG：`src/server/rag_router.py`
- AI Gateway：`src/server/ai/gateway.py`、`src/server/ai/providers.py`
- MCP client：`src/server/ai/kp_mcp_client.py`
- KP MCP Server：`kp_mcp_server/`
- Agent tools：`src/server/agent/tools.py`
- 本地运维：`dev.py`、`docker-compose.yml`
- 当前测试：`tests/server/test_admin_auth.py`、`test_rag_security.py`、`test_db_isolation.py`、`test_db_adapter.py`、`test_ws_auth.py`

## Batch Ops-0：现状复核和后台权限基线

目标：

- 确认当前无 API key、插件注册、Webhook、多租户和备份恢复实现。
- 回归 Admin API 权限、RAG 权限、测试库隔离和 WS 权限。
- 输出 Admin/Ops/MCP/Open API 当前能力清单。

允许文件方向：

- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 只读检查 `src/server/`、`kp_mcp_server/`、`tests/server/`

建议命令：

```bash
rg -n "api_key|api key|plugin|webhook|tenant|backup|migration_versions|admin_audit" src tests kp_mcp_server --glob "!src/client/node_modules/**" --glob "!src/client/dist/**"
python -m pytest tests/server/test_admin_auth.py tests/server/test_rag_security.py tests/server/test_db_isolation.py tests/server/test_ws_auth.py -q
```

验收：

- 现状报告明确哪些能力已有、哪些不存在。
- 权限测试通过或列出真实失败。
- 不产生源码改动。

禁止事项：

- 不新增插件表。
- 不开放任何第三方 API。
- 不放宽 admin、RAG 或 WS 鉴权。

## Batch Ops-1：生产安全配置基线

目标：

- 增加环境模式，例如 `APP_ENV=development|test|production`。
- 非开发环境拒绝默认 `JWT_SECRET`。
- CORS 从硬编码 `*` 改为环境 allowlist，开发仍可方便启动。
- MCP 生产默认禁止 `0.0.0.0` 无鉴权暴露。
- health 返回 public/admin 分级，public 不暴露过细内部状态。

允许文件方向：

- `src/server/config.py`
- `src/server/main.py`
- `src/server/router_auth.py`
- `kp_mcp_server/config.py`
- 可新增 `tests/server/test_ops_config.py`

建议命令：

```bash
python -m pytest tests/server/test_ops_config.py tests/server/test_auth.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_admin_auth.py -q
```

验收：

- production + 默认 secret 启动检查失败或 health degraded。
- production CORS 必须来自 allowlist。
- public health 不返回密钥、DSN、完整 provider 错误。
- development 默认仍能本地启动。

禁止事项：

- 不破坏 `python dev.py` 的默认开发体验。
- 不把真实 secret 打进日志。
- 不用前端限制代替后端配置校验。

## Batch Ops-2：Admin 操作审计

目标：

- 新增 admin 操作审计模型和 helper。
- 覆盖账号改角色、房间改状态、素材上传删除、AI 配置修改、RAG reindex、spoiler rebuild。
- AdminDashboard 后续可查询审计，本批可先做后端和测试。

允许文件方向：

- `src/server/db_adapter.py` 或项目实际 migration 位置
- `src/server/router_admin.py`
- 可新增 `src/server/admin_audit.py`
- 可新增 `tests/server/test_admin_audit.py`

建议命令：

```bash
python -m pytest tests/server/test_admin_auth.py tests/server/test_admin_audit.py -q
```

验收：

- 高风险 Admin 操作写入 audit。
- audit 不包含 password_hash、owner_token、player_token、API key。
- player 不能读取 audit。

禁止事项：

- 不记录完整请求体中的敏感字段。
- 不改变现有 Admin API 的成功语义。
- 不把 audit 写入 public export。

## Batch Ops-3：敏感日志和 AI/RAG 脱敏

目标：

- 增加通用敏感字段脱敏 helper。
- AI call logs 的 `response_summary` 和 error message 不含 token、API key、完整 prompt。
- Admin AI logs 显示脱敏字段。
- RAG context preview 明确 admin-only，并可选截断内容。

允许文件方向：

- `src/server/log_config.py`
- `src/server/ai/gateway.py`
- `src/server/router_admin.py`
- `src/server/export.py`
- 可新增 `src/server/security/redaction.py`
- 可新增 `tests/server/test_redaction.py`

建议命令：

```bash
python -m pytest tests/server/test_redaction.py tests/server/test_admin_auth.py tests/server/test_archive.py -q
```

验收：

- token/API key/JWT/owner token/player token 在日志和 admin DTO 中被遮罩。
- AI logs 不保存完整 prompt。
- public export 不含敏感字段。

禁止事项：

- 不为了脱敏删除排障必需的 status/provider/duration。
- 不把脱敏只做在前端。
- 不记录 DeepSeek API key。

## Batch Ops-4：MCP 和 Agent 工具权限收口

目标：

- 盘点 KP MCP 7 个工具和 Agent tools 的读写能力。
- 给 MCP provider 调用增加服务间鉴权或内网绑定配置。
- 将 Agent 写入工具分级，`engine_save_clue` 默认禁写或改成 Engine/State 验证路径。
- MCP/Agent 工具调用写入 AI/tool audit。

允许文件方向：

- `kp_mcp_server/config.py`
- `kp_mcp_server/server.py`
- `src/server/ai/providers.py`
- `src/server/ai/kp_mcp_client.py`
- `src/server/agent/tools.py`
- 可新增 `tests/server/test_mcp_security.py`
- 可新增 `tests/server/test_agent_tool_permissions.py`

建议命令：

```bash
python -m pytest tests/server/test_mcp_security.py tests/server/test_agent_tool_permissions.py tests/server/test_ai_kp.py -q
python -m pytest tests/server/test_state_service.py tests/server/test_spoiler_guard.py -q
```

验收：

- MCP 无凭证或错误凭证在生产模式不可调用。
- MCP 仍可在开发 mock 模式运行。
- Agent 写入工具不能直接绕过 Engine/State。
- 工具调用有可审计记录。

禁止事项：

- 不让 MCP 直接连接主库写状态。
- 不把服务间 token 暴露到前端。
- 不降低 AI schema 校验和反剧透要求。

## Batch Ops-5：AdminDashboard 可读性和运维入口

目标：

- 后台增加必要的运维信息入口：health、脱敏配置、AI provider 状态、RAG 状态、审计列表。
- 修复后台中文文案乱码和错误提示。
- 保持现有页面结构，不重做整套 UI。

允许文件方向：

- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/shared/api.ts`
- 必要时 `src/server/router_admin.py`
- 可新增前端轻量测试

建议命令：

```bash
cd src/client && npm run build
python -m pytest tests/server/test_admin_auth.py -q
```

验收：

- Admin 可查看脱敏 health/config。
- Admin 可查看 audit 列表。
- 页面 build 通过。

禁止事项：

- 不在前端展示 secret、token、完整 DSN。
- 不重写 AdminDashboard 为全新架构。
- 不把 Ops 操作暴露给非 admin。

## Batch Ops-6：版本化 migration 和备份恢复设计

目标：

- 设计并实现最小 `migration_versions`。
- 将后续 schema 改动从纯 `CREATE TABLE IF NOT EXISTS` 迁移到可追踪迁移。
- 设计备份和恢复脚本，先支持手动运行和测试库保护。

允许文件方向：

- `src/server/db_adapter.py`
- 可新增 `src/server/migrations/`
- 可新增 `scripts/backup.ps1` 或 `scripts/backup.py`
- 可新增 `tests/server/test_migrations.py`
- 可新增 `tests/server/test_backup_safety.py`

建议命令：

```bash
python -m pytest tests/server/test_db_adapter.py tests/server/test_db_isolation.py tests/server/test_migrations.py -q
```

验收：

- migration 可重复执行且有 checksum/version 记录。
- 备份脚本不会默认覆盖非 test DB。
- 恢复流程需要显式确认目标数据库。

禁止事项：

- 不删除现有数据。
- 不使用破坏性 reset。
- 不在测试中连接生产库。

## Batch Ops-7：Open API 和插件设计包

目标：

- 只写设计，不实现第三方开放。
- 设计 API client、API key、scope、plugin manifest、plugin install、webhook subscription。
- 定义 external OpenAPI 生成方式和不开放接口清单。

允许文件方向：

- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Plugin-OpenAPI设计.md`

建议命令：

```bash
rg -n "ApiKey|PluginScope|Webhook|external OpenAPI|owner_token|player_token" docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维
```

验收：

- 每个 scope 有允许行为和禁止行为。
- Open API 不包含 Admin、raw_text、truth、private events、token。
- 插件写入必须走服务层和审计。

禁止事项：

- 不创建真实 API key。
- 不注册插件运行时。
- 不开放 Webhook。

## Batch Ops-8：回归验收

目标：

- 回归后台、RAG、AI、MCP、安全配置和核心跑团链路。

建议命令：

```bash
python -m pytest tests/server/test_admin_auth.py tests/server/test_rag_security.py tests/server/test_db_isolation.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_archive.py tests/server/test_spoiler_guard.py tests/server/test_room_security.py -q
python dev.py --check
cd src/client && npm run build
```

手动验收：

1. Admin 登录后进入后台。
2. Player 访问后台被拒绝。
3. Admin 修改房间状态并产生审计。
4. Admin 查看 AI logs、RAG 状态、Spoiler audits。
5. public health 不暴露敏感配置。
6. MCP mock 模式可用于开发，生产配置无鉴权不可暴露。
7. 创建房间、玩家加入、ready、开局、AI/规则裁决、投影、日志仍可完成。

禁止事项：

- 不跳过权限测试。
- 不把开发默认配置当生产安全。
- 不在 Open API 或插件设计未验收前开放第三方写接口。
