# AI-Keeper 核心系统 DeepSeek 计划 V2.0

## 执行目标

把 AI-Keeper 核心系统收紧为“统一 AI 网关 + 可校验建议 + Engine 权威执行 + Safety 过滤 + Journal 审计”的主链路。第一轮不扩展复杂 Agent 平台，不做模型市场，不做计费系统。

## 全局禁止事项

1. 不允许 AI 直接写数据库状态、JSON Patch、SQL 或角色数值。
2. 不允许 Player 请求包含未发现线索、隐藏 NPC、结局、truth、KP-only note。
3. 不允许把 API key、token、完整 prompt、隐藏真相写入 public event 或 public export。
4. 不允许用前端隐藏替代后端权限校验。
5. 不允许为了接入 AI 而绕过 RuleExecutor、StateService、ProjectionDispatcher。

## Batch AI-0：现状盘点与安全基线

### 目标

先用测试固定当前 AI 主链路和风险点，避免后续 DeepSeek 在多条 AI 路径之间误改。

### 允许改动

- `tests/server/test_ai_kp.py`
- `tests/server/test_mechanic_compiler.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_spoiler_guard.py`
- 新增 `tests/server/test_ai_gateway.py`
- 新增 `tests/server/test_ai_security.py`

### 任务

1. 盘点 `AIKP`、`AiGateway`、`MechanicCompiler`、`ResolutionPipeline`、`GameAgent` 的调用关系。
2. 为 `/api/rooms/{room_id}/ai-turn` 未授权触发增加失败测试。
3. 为 `generate_narrative` 返回 `NarrativePayload` 时 pipeline 能读取文本增加测试。
4. 为 DeepSeek 坏 JSON、schema_fail、provider fallback 增加 Gateway 测试。
5. 为 AI mutation 不直接落库增加端到端测试。

### 验收命令

```bash
python -m pytest tests/server/test_ai_kp.py tests/server/test_mechanic_compiler.py tests/server/test_resolution_pipeline.py tests/server/test_spoiler_guard.py tests/server/test_ai_gateway.py tests/server/test_ai_security.py -q
```

### 预期结果

风险测试先稳定复现，修复后全部通过。

## Batch AI-1：AI 调用入口鉴权

### 目标

修复房间 AI 调度入口权限，防止任意用户触发结算或读取 AI 状态。

### 允许改动

- `src/server/router_ai.py`
- `src/server/router_rooms.py` 中可复用的鉴权 helper
- `tests/server/test_ai_security.py`
- 相关房间权限测试

### 任务

1. `POST /api/rooms/{room_id}/ai-turn` 要求 Owner/Admin，或明确只允许 Host 操作。
2. `GET /api/rooms/{room_id}/ai-status` 要求 Owner/Admin/Room Player。
3. 未登录、错误房间玩家、无效 token 均返回 401/403。
4. 权限错误不能泄露模型配置细节。

### 验收命令

```bash
python -m pytest tests/server/test_ai_security.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py -q
```

### 禁止事项

- 不让普通 Player 随意触发全房间 queued action 结算。
- 不用 owner token 截断值当作身份凭据。

## Batch AI-2：Gateway 契约与返回类型收口

### 目标

让 `AiGateway` 成为 AI 调用主入口，并修复 `generate_narrative`、MCP 映射、fallback 结果类型的兼容问题。

### 允许改动

- `src/server/ai/gateway.py`
- `src/server/ai/providers.py`
- `src/server/ai/contracts.py`
- `src/server/engine/resolution_pipeline.py`
- `tests/server/test_ai_gateway.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. Pipeline 正确读取 `NarrativePayload`、dict、local fallback 三种返回。
2. 为 `generate_narrative` 增加 MCP tool 映射，或显式记录该任务不走 MCP 的原因。
3. Gateway 对所有 schema_fail 写入 fallback_chain 和 `ai_call_logs`。
4. `generate_narrative` 不返回空字符串；失败时给可解释 fallback。
5. `TASK_SCHEMAS` 和 public method 一致。

### 验收命令

```bash
python -m pytest tests/server/test_ai_gateway.py tests/server/test_resolution_pipeline.py -q
```

### 禁止事项

- 不让 provider 返回自由文本后直接进入 Player 投影。
- 不删除 local fallback。

## Batch AI-3：机制编译与规则执行边界

### 目标

强化“AI 编译建议，RuleExecutor 权威结算”的边界。

### 允许改动

- `src/server/ai/mechanic_compiler.py`
- `src/server/engine/rule_executor.py`
- `src/server/engine/resolution_pipeline.py`
- `tests/server/test_mechanic_compiler.py`
- `tests/server/test_rule_executor.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. 修复机制编译 prompt 和 fallback 文案乱码。
2. 增加 DeepSeek 常见字段别名、中文难度、非法枚举归一化测试。
3. 非法机制类型不能进入 RuleExecutor 执行敏感状态变化。
4. AI 建议 roll request 时，骰子、目标值、成功等级都由 RuleExecutor 计算。
5. 拒绝或 fallback 时 action 状态清晰，不留下 resolving 卡死。

### 验收命令

```bash
python -m pytest tests/server/test_mechanic_compiler.py tests/server/test_rule_executor.py tests/server/test_resolution_pipeline.py -q
```

### 禁止事项

- 不让 AI 返回的 roll 数字覆盖真实骰子结果。
- 不把玩家猜测直接写成 result fact。

## Batch AI-4：RAG 上下文最小化与真相锁定

### 目标

确保 AI 看到的上下文按 room、role、character、clue unlock 分层，不把未授权真相注入 Player 视角。

### 允许改动

- `src/server/ai/rag.py`
- `src/server/ai/rag_context.py`
- `src/server/ai/spoiler_control.py`
- `src/server/rag_router.py`
- `tests/server/test_rag.py`
- `tests/server/test_rag_search.py`
- `tests/server/test_rag_security.py`
- `tests/server/test_spoiler.py`

### 任务

1. RAG search 后增加可见性裁剪，不只依赖 room_id。
2. Player 视角排除 hidden truth、ending、未发现 hidden clue、未公开 hidden NPC。
3. Admin context-preview 标出每条 context 的 source 和可见性原因。
4. NPC graph、scenario chunk、event chunk 的 room/scenario 过滤行为有测试。
5. RAG query 不返回跨房间角色卡或其他房间事件。

### 验收命令

```bash
python -m pytest tests/server/test_rag.py tests/server/test_rag_search.py tests/server/test_rag_security.py tests/server/test_spoiler.py -q
```

### 禁止事项

- 不把完整世界书塞进 Player AI prompt。
- 不让 RAG 命中未发现线索后由 AI 委婉说出。

## Batch AI-5：输出反剧透与审计闭环

### 目标

让 public 叙事输出统一经过 SpoilerGuard，命中敏感项时 retry、fallback 和 audit 都可验证。

### 允许改动

- `src/server/engine/spoiler_guard.py`
- `src/server/engine/projection.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/router_admin.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_projection.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. public narrative、party event、player-visible projection 均执行输出审查。
2. retry prompt 不包含完整隐藏真相，只给禁止项和改写约束。
3. fallback 文案可读，并不会泄露敏感项。
4. `spoiler_audits` 记录 action_id、violations、retry_count、final_status。
5. Admin 可以查询 spoiler audits，Player 无权访问。

### 验收命令

```bash
python -m pytest tests/server/test_spoiler_guard.py tests/server/test_projection.py tests/server/test_resolution_pipeline.py tests/server/test_admin_security.py -q
```

### 禁止事项

- 不把被拦截原文发给 Player。
- 不在 audit 以外的公共日志保存隐藏真相。

## Batch AI-6：Agent 工具写入治理

### 目标

把可选 Agent 限定为实验增强，不允许工具绕过主链路写状态或线索。

### 允许改动

- `src/server/agent/game_agent.py`
- `src/server/agent/tools.py`
- `src/server/player/router_clues.py`
- `src/server/engine/state_service.py`
- `tests/server/test_ai_security.py`
- 新增 `tests/server/test_agent_tools.py`

### 任务

1. `engine_save_clue` 改为调用 Clue/State/Journal 服务链路，保留 source 和 action 引用。
2. 工具读 recent events 时使用 Journal 可见性 helper，不用粗糙 audience 过滤。
3. 工具执行结果写入审计，标明 tool_name、room_id、character_id。
4. Agent 未启用时不影响主链路。
5. Agent 启用时仍不能直接写 HP/SAN、地图位置、世界真相。

### 验收命令

```bash
python -m pytest tests/server/test_ai_security.py tests/server/test_agent_tools.py tests/server/test_clues.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不让工具层直接 `INSERT` 权威线索后不写事件。
- 不把 Agent 变成主裁决路径。

## Batch AI-7：文案、日志与配置可诊断

### 目标

修复 AI prompt、fallback、日志中的乱码和诊断不清问题，让 DeepSeek/MCP 问题可定位。

### 允许改动

- `src/server/ai/*.py`
- `src/server/narrative_provider.py`
- `src/server/main.py`
- `src/server/router_admin.py`
- `tests/server/test_ai_gateway.py`
- `tests/server/test_ai_kp.py`

### 任务

1. 修复模型可见系统 prompt 的 UTF-8 中文。
2. 修复用户可见 fallback 叙事。
3. AI health-check 返回 provider_order、provider_health、fallback 状态。
4. `ai_call_logs` 摘要做脱敏，不保存完整 prompt。
5. Admin AI logs 能按 room、task、provider、status 过滤。

### 验收命令

```bash
python -m pytest tests/server/test_ai_gateway.py tests/server/test_ai_kp.py tests/server/test_admin_security.py -q
```

### 禁止事项

- 不在测试或日志中打印真实 API key。
- 不把完整 prompt 长期存入数据库。

## Batch AI-8：端到端验收

### 目标

验证 AI-Keeper 核心系统能在安全边界内跑完主链路。

### 手动验收流程

1. Host 创建房间并选择结构化剧本。
2. Player 加入、ready、提交自然语言行动。
3. `MechanicCompiler` 输出机制，RuleExecutor 执行检定。
4. Gateway 可用时生成增强叙事，不可用时走 fallback。
5. SpoilerGuard 拦截未解锁真相，Player 只看到安全文本。
6. StateService 写状态，Projection 分发 Host/Player 视角。
7. Journal 能查到 action、resolution、state patch、projection、ai_call_logs。
8. Admin AI logs 能看到 provider、status、fallback_chain。

### 回归命令

```bash
python -m pytest tests/server/test_ai_kp.py tests/server/test_ai_gateway.py tests/server/test_mechanic_compiler.py tests/server/test_resolution_pipeline.py tests/server/test_spoiler_guard.py tests/server/test_rag_security.py tests/server/test_player_intent.py tests/server/test_event_log.py -q
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | AI-Keeper 依赖 | DeepSeek 注意点 |
| --- | --- | --- |
| Rule | 执行骰子、技能、SAN、战斗等权威规则。 | AI 只给机制建议和叙事，不覆盖规则结果。 |
| State | 写权威状态和 state_version。 | AI mutation 需要 State 校验后才能落库。 |
| Transaction | 串起一次裁决的来源和输出。 | AI 输出要带 action/transaction 引用。 |
| Projection | 分发 Host/Player 可见内容。 | AI public 文本先过 Safety，再投影。 |
| WorldBook | 提供真相、NPC、线索和 RAG 资料。 | AI 不能把未确认草稿当成世界事实。 |
| Clue | 管理线索获得、分享和归属。 | AI 建议释放线索后由 Clue 模块确认归属。 |
| Journal | 沉淀 AI 调用和结果证据链。 | 不记录密钥、完整 prompt 或未授权真相。 |
| Admin/Ops | 管 provider 配置、日志、健康检查。 | 管理能力不向普通 Player 暴露。 |
