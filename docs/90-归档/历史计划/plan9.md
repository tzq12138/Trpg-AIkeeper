# AI Gateway 与 Hermes MCP 接入计划

## Summary
- 新增统一 AI Gateway，所有 AI 调用都从这里走：剧本结构化、机制编译、AI主持叙事、Host资料库问答、战斗/追逐建议。
- v1 Provider 顺序：`DeepSeek -> Hermes MCP -> 本地模板/规则兜底`；后续 Hermes 稳定后可配置切到 `Hermes MCP -> DeepSeek -> 本地兜底`。
- Hermes 按 `docs/KP_MCP_Design.md` 设计为 MCP StreamableHTTP server，AI-Keeper 后端作为 MCP client 调用 `/mcp`。
- AI 权限做成全局默认 + 房间覆盖配置，Host/后台可勾选调整。
- 默认权限：叙事类可直接生效；HP/SAN/线索/物品/地图/战斗等状态类只能走 Level 1 校验后写入；禁止任意属性/技能/信用评级改写。

## Key Changes
- 新增 `AiGateway`：
  - 统一入口方法：`resolve_turn`、`structure_scenario`、`compile_mechanic`、`query_knowledge`、`resolve_sanity`、`resolve_combat_round`、`health_check`。
  - Provider 实现：`DeepSeekProvider`、`KpMcpProvider`、`LocalFallbackProvider`。
  - Provider router 根据配置顺序调用；失败自动切下一个 provider，并记录失败原因。
  - 现有 `AIKP`、`MechanicCompiler`、`structure_scenario()`、Host资料库问答都迁到 Gateway；旧逻辑保留为 fallback，不再直接散落调用 DeepSeek。

- Hermes MCP client：
  - 使用 MCP StreamableHTTP：`POST {KP_MCP_SERVER_URL}/mcp`。
  - 支持 `initialize`、`tools/list`、`tools/call`、`kp_health_check`。
  - 第一版调用工具：`kp_resolve_turn`、`kp_resolve_sanity`、`kp_resolve_combat_round`、`kp_structure_scenario`、`kp_query_rules`。
  - MCP 超时默认 30s；失败后切 DeepSeek/本地兜底，不阻塞跑团。
  - 若 Python MCP SDK 不稳定，只实现最小 JSON-RPC 2.0 client，限定上述方法，不做泛化 MCP 框架。

- 结构化合同：
  - 新增 Pydantic schema：`KpResponse`、`NarrativePayload`、`KpRollRequest`、`KpStateMutation`、`KpTacticalPrompt`、`KpCitation`。
  - `KpResponse` 字段固定：`narrative`、`rollRequests`、`stateMutations`、`tacticalPrompts`、`keeperNotes`、`citations`、`_error`。
  - 所有 provider 返回先过 schema 校验；非法 JSON、缺字段、未知 mutation type 都进入 fallback。
  - `keeperNotes` 只存数据库和 Host 审计，不发给玩家。

- 权限矩阵：
  - Level 2 direct：叙事文本、战术提示、场景切换、NPC反应、状态标签。
  - Level 1 validate：`san_loss`、`hp_loss`、`mp_loss`、`luck_change`、`gain_clue`、`gain_item`、`move_location`、`combat_suggestion`。
  - block：属性值、技能值、信用评级、任意 SQL/任意 JSON patch。
  - 后端对 validate mutation 执行掷骰、公式解析、查重、范围校验、目标存在校验；失败只拒绝该 mutation，不拖垮整次响应。

- 配置与 UI：
  - 新增全局 AI 配置：provider 顺序、DeepSeek 启用、Hermes URL、超时、权限勾选。
  - 新增房间 AI 覆盖配置：每个房间可覆盖 provider 顺序和权限矩阵。
  - Host/后台页面显示 AI 状态：当前 provider、最近错误、Hermes health、fallback 次数。
  - API key 只从环境变量读取，不在前端展示、不入库明文、不写日志。

- 审计与日志：
  - 新增 `ai_call_logs`：task type、provider、room/action/scenario、耗时、状态、错误、fallback 链路、响应摘要。
  - 默认不记录完整 prompt；只存摘要和引用 ID。开发模式可开启 raw debug，但必须脱敏。
  - `/api/health` 扩展 AI 状态：DeepSeek configured、Hermes reachable、当前 provider order。

## API / Interfaces
- 后端内部：
  - `AiGateway.resolve_turn(context) -> KpResponse`
  - `AiGateway.structure_scenario(raw_text) -> ScenarioKnowledgeGraph`
  - `AiGateway.query_knowledge(query, room_id, mode, sources) -> KnowledgeAnswer`
  - `AiGateway.compile_mechanic(intent, context) -> MechanicCompileResult`

- 配置 API：
  - `GET /api/admin/ai/config`
  - `PATCH /api/admin/ai/config`
  - `GET /api/rooms/{room_id}/ai-config`
  - `PATCH /api/rooms/{room_id}/ai-config`
  - `POST /api/admin/ai/health-check`

- 环境变量：
  - `DEEPSEEK_API_KEY`
  - `DEEPSEEK_MODEL`
  - `KP_MCP_SERVER_URL=http://127.0.0.1:9100/mcp`
  - `AI_PROVIDER_ORDER=deepseek,mcp,local`
  - `AI_TIMEOUT_SECONDS=30`

## Test Plan
- Provider：
  - DeepSeek mock 成功、失败、返回非法 JSON。
  - Hermes fake MCP server 支持 initialize/tools/call/health。
  - Provider 顺序按 `deepseek,mcp,local` fallback。
  - 后续改成 `mcp,deepseek,local` 不改业务代码。

- Schema 与权限：
  - 合法 `KpResponse` 可解析。
  - 非法 mutation type 被拒绝。
  - direct narrative/tactical prompt 可投影。
  - `san_loss/hp_loss/gain_clue/move_location` 必须由后端校验后写入。
  - block 类型永远不写入。

- 集成：
  - 剧本导入走 Gateway，失败回旧结构化 fallback。
  - 机制编译走 Gateway，失败回 Python regex/规则编译。
  - AI主持回合走 Gateway，失败回模板叙事。
  - Host资料库问答走 Gateway，失败返回 citations-only。
  - `ai_call_logs` 不包含 API key 或完整敏感 prompt。

## Assumptions
- `docs/KP_MCP_Design.md` 作为 Hermes 侧协议草案，但需要先修复文档编码，避免实现时复制乱码 prompt。
- v1 不让 Hermes 直接写数据库；所有权威状态写入仍由 AI-Keeper 后端执行。
- v1 先用 DeepSeek 作为主 provider，Hermes MCP 作为可接入备用；等 Hermes 稳定后只改配置顺序。
- MCP 先只实现所需 tools/call 子集，不做完整通用 MCP 平台。
