# AI-Keeper 核心系统 DeepSeek 计划 V2.1

## 当前阶段目标

本轮不是把 AI-Keeper 做成完整自治 Agent 平台，而是把当前仓库里已经存在的 AI 主链路收紧为：

- 统一 Gateway
- 可校验建议
- Engine / Rule / State 权威执行
- Safety / SpoilerGuard 过滤
- Journal / Admin 审计

执行阶段口径以本目录文档和 `docs/20-核心链路/AI-Keeper核心链路架构.md` 为准，重点是：

- AI 永远停在建议层
- Player prompt 不进未授权 truth
- public / private narrative 不混用
- Agent 工具不能成为后门写入路径

## 代码现状前提

DeepSeek 执行前必须接受这些当前事实，不能按理想架构重写：

1. `src/server/router_ai.py` 当前 `/ai-turn`、`/ai-status` 基本无房间级鉴权。
2. `src/server/ai/contracts.py` 已有 `NarrativePayload`、`KpResponse`、mutation permission matrix，但仍偏模型层，未形成完整 DTO 分层。
3. `src/server/ai/gateway.py` 已有 `TASK_SCHEMAS`、provider order、fallback chain、`ai_call_logs`，但状态模型与日志脱敏仍偏粗。
4. `src/server/ai/rag_context.py` 当前主要按 quota + room 搜索拼上下文，缺少 final context filter。
5. `src/server/ai/rag.py` 会索引 scenario、event、clue、npc 等 raw chunk，不能默认等于 Player 可见 prompt。
6. `src/server/agent/tools.py` 当前 `engine_save_clue` 仍直接 `INSERT clues`，`recent events` 也仍用粗 `audience` 过滤。
7. `src/server/ai/ai_kp.py` 仍保留 legacy AIKP 逻辑，需要明确它和 `AiGateway` 的主辅关系。

## 全局禁止事项

1. 不允许 AI 直接写数据库状态、SQL、JSON Patch 或角色数值。
2. 不允许 Player prompt 包含未发现线索、hidden NPC、truth、ending、KP-only note。
3. 不允许 public event、public export、Player Journal 包含 API key、token、raw prompt、raw response、hidden truth。
4. 不允许用前端隐藏代替后端权限过滤。
5. 不允许为了接 AI 而绕过 RuleExecutor、StateService、ProjectionDispatcher、Journal。
6. 不允许把 private narrative 合并进 public narrative。
7. 不允许 Agent write tool 继续直接 `INSERT clues` 或类似裸写。

## Batch AI-0：现状盘点与安全基线

### 目标

先用测试固定当前 AI 主链路和核心风险，再做实现修改。

### 允许改动

- `tests/server/test_ai_kp.py`
- `tests/server/test_mechanic_compiler.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_spoiler_guard.py`
- 新增 `tests/server/test_ai_gateway.py`
- 新增 `tests/server/test_ai_security.py`

### 任务

1. 盘点 `AIKP`、`AiGateway`、`MechanicCompiler`、`ResolutionPipeline`、`GameAgent` 调用关系。
2. 为 `/api/rooms/{room_id}/ai-turn` 未授权触发增加失败测试。
3. 为 `generate_narrative` 返回 `NarrativePayload`、dict、fallback 三种类型增加解析测试。
4. 为坏 JSON、schema_fail、provider fallback 增加 Gateway 测试。
5. 增加以下安全基线测试：
   - `privateTexts` 缺少 `characterId` 不下发
   - AI mutation 不直接写 State
   - `ai_call_logs` 不含 raw prompt / token

### 测试命令

```bash
python -m pytest tests/server/test_ai_kp.py tests/server/test_mechanic_compiler.py tests/server/test_resolution_pipeline.py tests/server/test_spoiler_guard.py tests/server/test_ai_gateway.py tests/server/test_ai_security.py -q
```

## Batch AI-1：AI 调度入口鉴权

### 目标

修复房间级 AI 调度入口权限，阻止任意用户触发结算或读取敏感 AI 状态。

### 允许改动

- `src/server/router_ai.py`
- 可复用的房间鉴权 helper
- `tests/server/test_ai_security.py`
- 相关房间权限测试

### 任务

1. `POST /api/rooms/{room_id}/ai-turn` 仅允许 Owner / Admin / Host。
2. `GET /api/rooms/{room_id}/ai-status` 做 Player / Owner / Admin 分层返回。
3. 未登录、错误房间成员、无效 token 均返回 401 / 403。
4. Player 版 `ai-status` 只返回低敏状态：`enabled/mock/fallback/degraded`。
5. 任何错误响应都不得暴露 provider config、API endpoint、prompt 片段。

### 测试命令

```bash
python -m pytest tests/server/test_ai_security.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py -q
```

## Batch AI-2：Gateway 契约、状态模型与双轨收口

### 目标

让 `AiGateway` 成为 AI 调用主入口，并补齐状态模型、schemaVersion、返回类型收口与 legacy AIKP 主辅关系。

### 允许改动

- `src/server/ai/gateway.py`
- `src/server/ai/providers.py`
- `src/server/ai/contracts.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/ai/ai_kp.py`
- `tests/server/test_ai_gateway.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. 固化 Gateway 任务状态：
   - `success`
   - `schema_fail`
   - `provider_error`
   - `timeout`
   - `fallback_used`
   - `local_fallback`
   - `rejected_by_safety`
   - `empty_response`
2. 为所有 Gateway task 增加 `schemaVersion` 口径。
3. `NarrativePayload`、dict、local fallback 统一收口到单一内部结果对象，例如 `NarrativeResultDTO`。
4. `TASK_SCHEMAS` 与 public method 不一致时测试必须失败。
5. 明确 `AiGateway + ResolutionPipeline` 是主链路；legacy AIKP 只保留兼容层或结构化剧本辅助用途。

### 测试命令

```bash
python -m pytest tests/server/test_ai_gateway.py tests/server/test_resolution_pipeline.py tests/server/test_ai_kp.py -q
```

## Batch AI-3：机制编译、RuleExecutor 边界与 mutation 校验

### 目标

强化“AI 提建议，RuleExecutor 给权威结果，State 才能写状态”的边界。

### 允许改动

- `src/server/ai/mechanic_compiler.py`
- `src/server/ai/contracts.py`
- `src/server/engine/rule_executor.py`
- `src/server/engine/resolution_pipeline.py`
- `tests/server/test_mechanic_compiler.py`
- `tests/server/test_rule_executor.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. 修复 mechanic compiler prompt / fallback 乱码。
2. 补 skill / difficulty 别名、中文难度、非法枚举归一化测试。
3. `targetValue`、`roll`、`successLevel` 一律由 RuleExecutor 生成。
4. AI 返回 `roll=1`、`success=critical` 也不能覆盖服务端结果。
5. sensitive mutation 必须进入统一校验点，再由 Rule / State / Clue / Map 对应模块确认。
6. SQL / JSON Patch 类 mutation 直接拒绝。

### 测试命令

```bash
python -m pytest tests/server/test_mechanic_compiler.py tests/server/test_rule_executor.py tests/server/test_resolution_pipeline.py tests/server/test_ai_security.py -q
```

## Batch AI-4：RAG final context filter 与真相锁定

### 目标

确保 Player-facing AI 只读授权上下文，而不是直接读 raw RAG chunk。
这条是 P0 安全边界，不允许下沉成“后续优化”。

### 允许改动

- `src/server/ai/rag.py`
- `src/server/ai/rag_context.py`
- `src/server/ai/spoiler_control.py`
- `src/server/rag_router.py`
- `src/server/router_admin.py`
- `tests/server/test_rag.py`
- `tests/server/test_rag_search.py`
- `tests/server/test_rag_security.py`
- `tests/server/test_spoiler.py`

### 任务

1. RAG 检索后增加 `final context filter`，最小维度：
   - `viewer_role`
   - `room_id`
   - `scenario_id`
   - `character_id`
   - `source_type`
   - `visibility`
   - `unlock_state`
2. `source_type=scenario` 的 raw text 默认 internal / host，不直进 Player prompt。
3. `source_type=clue` 只允许 owned clue 或 shared `publicVersion`。
4. `source_type=event` 只允许 player-visible Journal view。
5. `source_type=npc` 过滤 hidden / truth / ai_only 字段。
6. Admin context preview 显示：
   - `included / excluded`
   - `sourceType`
   - `visibility`
   - `reason`
   - `unlockState`
7. 明确 `/rag/search` 的检索权限不等于“可进入 player-facing AI prompt 的权限”。

### 测试命令

```bash
python -m pytest tests/server/test_rag.py tests/server/test_rag_search.py tests/server/test_rag_security.py tests/server/test_spoiler.py -q
```

## Batch AI-5：输出侧反剧透与叙事边界

### 目标

让 public / private narrative 的结构边界和 `SpoilerGuard` 的输出审计真正闭环。

### 允许改动

- `src/server/engine/spoiler_guard.py`
- `src/server/engine/projection.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/router_admin.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_projection.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. `publicText` 只进 party / public projection。
2. `privateTexts` 必须按 `characterId` 分发，缺 recipient 不下发。
3. public narrative、party event、player-visible projection 全部经过 SpoilerGuard 或等价安全审查。
4. retry prompt 不得包含完整敏感真相原文，只允许 violation label / forbidden terms / rewrite constraints。
5. `spoiler_audits` 记录 `actionId`、`violations`、`retryCount`、`finalStatus`。

### 测试命令

```bash
python -m pytest tests/server/test_spoiler_guard.py tests/server/test_projection.py tests/server/test_resolution_pipeline.py tests/server/test_admin_security.py -q
```

## Batch AI-6：Agent 工具写入治理

### 目标

把 Agent 限定为实验增强层，不允许其绕过主链路写线索或状态。

### 允许改动

- `src/server/agent/game_agent.py`
- `src/server/agent/tools.py`
- `src/server/player/router_clues.py`
- `src/server/engine/state_service.py`
- `tests/server/test_ai_security.py`
- 新增 `tests/server/test_agent_tools.py`

### 任务

1. `engine_save_clue` 改为调用 Clue / State / Journal 服务链，不再直接 `INSERT clues`。
2. Agent `recent events` 读取复用 Journal / Timeline 可见性 helper。
3. 所有工具执行都写 `AgentToolCallAuditDTO`。
4. Agent 必须有 feature flag，默认关闭。
5. Agent 未启用时不影响主链路；启用后也不能直接写 HP / SAN / 地图位置 / 世界真相。

优先级说明：

- 如 Agent 默认关闭且生产不可触发，可按 P1 批次执行完整治理。
- 如 Agent 写工具当前可被触发，`engine_save_clue` 这类直接写库问题按 P0 风险修复。

### 测试命令

```bash
python -m pytest tests/server/test_ai_security.py tests/server/test_agent_tools.py tests/server/test_clues.py tests/server/test_event_log.py -q
```

## Batch AI-7：日志脱敏、编码治理与管理面诊断

### 目标

修复 AI prompt / fallback / 日志中的乱码与诊断不清问题，并锁死 `ai_call_logs` 的脱敏边界。

### 允许改动

- `src/server/ai/*.py`
- `src/server/narrative_provider.py`
- `src/server/router_admin.py`
- `tests/server/test_ai_gateway.py`
- `tests/server/test_ai_kp.py`
- `tests/server/test_admin_security.py`

### 任务

1. 修复模型可见 system prompt、fallback 文案、用户可见叙事的 UTF-8 中文。
2. `ai_call_logs` 的 `inputSummary` / `outputSummary` 增加长度限制与敏感词 / secret 扫描。
3. 如为调试保留 raw prompt / raw response，必须进 Admin/Ops `never_export` 路径，不进入普通 `ai_call_logs`。
4. AI health-check 仅 Admin 可用。
5. Admin AI logs 支持按 room / task / provider / status 过滤。

### 测试命令

```bash
python -m pytest tests/server/test_ai_gateway.py tests/server/test_ai_kp.py tests/server/test_admin_security.py -q
```

## Batch AI-8：端到端回归

### 目标

验证 AI-Keeper 能在安全边界内跑完整主链路。

### 手动验收流程

1. Host 创建房间并选择剧本。
2. Player 加入、ready、提交自然语言行动。
3. `MechanicCompiler` 输出机制建议。
4. `RuleExecutor` 执行权威规则。
5. Gateway 可用时生成增强叙事，不可用时走 fallback。
6. public narrative 命中敏感项时被 `SpoilerGuard` 拦截并降级。
7. AI mutation 只作为 proposal，经 Rule / State / Clue / Map 对应模块确认后才写入。
8. Projection 分发 Host / Player 视角。
9. Journal / Admin logs 能查到 action、AI task、provider、status、fallback chain。

### 回归命令

```bash
python -m pytest tests/server/test_ai_kp.py tests/server/test_ai_gateway.py tests/server/test_mechanic_compiler.py tests/server/test_resolution_pipeline.py tests/server/test_spoiler_guard.py tests/server/test_rag_security.py tests/server/test_player_intent.py tests/server/test_event_log.py -q
cd src/client
npm run build
```

## 与其他模块的接口关系

| 模块 | AI-Keeper 依赖 | 执行注意点 |
| --- | --- | --- |
| Rule | 掷骰、技能、SAN、战斗等权威规则 | AI 只给机制建议，不覆盖结果 |
| State | 权威状态写入与 `stateVersion` | AI mutation 只做 proposal |
| Transaction | 事务边界与来源链 | AI 输出要带 `actionId` / `transactionId` |
| Projection | Host / Player 投影 | public narrative 先过 Safety 再投影 |
| WorldBook | truth、NPC、结构化剧本、RAG 数据 | 未确认草稿不自动变世界事实 |
| Clue | 线索归属、分享、公共摘要 | AI 建议释放线索后仍由 Clue 模块确认 |
| Journal | 证据链与审计 | 不记录 raw prompt / raw response / token |
| Safety | 反剧透、DTO 边界、输出审查 | AI 不能自己决定谁能看到什么 |
| Admin/Ops | provider 配置、logs、health-check | 管理能力不向普通 Player 暴露 |
