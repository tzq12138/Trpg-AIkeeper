# AI-Keeper 核心系统 PRD V2.1

## 当前阶段

本 PRD 对应的是：

- `P0 主链路 + AI 安全建议层风险识别版`
- 不是 AI-Keeper 的最终生产安全完成版
- 重点是把 AI 永远限制在“可校验建议层”

当前已识别但未必已在代码中完全关闭的风险包括：

- AI 调度接口鉴权
- Gateway schema / fallback / 状态模型
- AI mutation 越权
- RAG 上下文泄露
- public / private narrative 投影混用
- Agent 工具绕过服务链写入
- `ai_call_logs` 脱敏不足
- prompt / fallback 中文乱码

## 背景

AI-Keeper 的价值不在于“AI 更聪明”，而在于：

- AI 能理解玩家意图
- AI 能提出机制建议
- AI 能生成叙事与战术提示
- AI 能检索知识和辅助结构化剧本

同时又不会：

- 直接改写权威状态
- 把猜测写成事实
- 把未发现真相塞进玩家上下文
- 把 private narrative 广播成 public narrative

当前仓库已经具备 `AiGateway`、DeepSeek / MCP / local provider、`MechanicCompiler`、`ResolutionPipeline`、RAG、`SpoilerGuard`、`ai_call_logs` 和实验态 Agent。第一轮产品目标不是做自主 Agent，而是收紧主链路和安全边界。

## 产品目标

1. 统一 AI 调用入口、契约、fallback 和审计。
2. 让 AI 输出永远只作为建议进入 Engine / Rule / State，而不是直接落权威状态。
3. 让 AI 输入上下文遵守玩家可见性边界，未发现 truth / clue / hidden NPC 不进入 Player prompt。
4. 让 public narrative 与 private narrative 有明确的结构化边界。
5. 让输出侧 `SpoilerGuard` 成为公共叙事的必经门。
6. 让 Agent 写工具不能绕过 Clue / State / Journal 主链路。

## 非目标

1. 不让 AI 独立主持完整战役并绕过 Engine。
2. 不在本模块完成模型市场、计费系统、插件生态。
3. 不把 AI 生成的 NPC / 场景 / 线索草稿自动变成世界事实。
4. 不把 Host-only 真相或 raw prompt 写入玩家日志。
5. 不在本轮做复杂自主多 Agent 运行时。

## 用户角色

| 角色 | 目标 | 不允许 |
| --- | --- | --- |
| Player | 提交意图、接收安全叙事、获取检定结果和公开信息 | 触发房间级 AI 结算、读取未发现真相 |
| Host / Owner | 触发结算、查看房间级 AI 降级状态、控制房间级策略 | 绕过 Engine 让 AI 直接改状态 |
| Admin | 配置全局 provider、查看 health / logs / context preview / spoiler audits | 把敏感 prompt、token、隐蔽真相暴露给普通玩家 |
| Engine | 调用 AI 建议并决定接收 / 修改 / 拒绝 | 信任未校验 AI JSON 直接执行 |
| AI-Keeper | 生成建议、叙事、知识回答和结构化草稿 | 直接写数据库或修改世界真相 |

## 数据分层模型

| 层级 | 数据对象 | 描述 | 边界 |
| --- | --- | --- | --- |
| L0 | `PlayerIntent` | 玩家输入的自然语言或结构化动作 | 不等于事实 |
| L1 | `AIRequestContext` | 送入 Gateway 的总上下文 | 已脱敏，不含 raw secret |
| L2 | `AIVisibleContextChunk` | 通过 final filter 的可见 chunk | 可解释为何可见 |
| L3 | `RAGRawChunk` | `document_chunks` 原始召回结果 | 不能直接进 Player prompt |
| L4 | `AIRawResponse` | provider 原始返回 | 不直接下发，不直接落状态 |
| L5 | `TypedAIContract` | 校验后的 `KpResponse` / `NarrativePayload` / `MechanicCompileResult` | 仍不是权威执行结果 |
| L6 | `MechanicSuggestion` | AI 对规则触发的建议 | 无权威骰值 |
| L7 | `RuleResult` | RuleExecutor 权威结果 | AI 不覆盖 |
| L8 | `AIMutationProposal` | AI 建议的状态变化 | 必须再校验 |
| L9 | `StatePatch` | State / Transaction 的权威状态输出 | 唯一落库口径 |
| L10 | `PublicNarrative` | 面向队伍或公共舞台的叙事 | 必须过 Safety |
| L11 | `PrivateNarrative` | 面向指定角色的私密叙事 | 必须带角色归属 |
| L12 | `AICallLog` | Gateway / provider 调用审计 | `never_export` |
| L13 | `SpoilerAudit` | 输出拦截审计 | `admin_only` |
| L14 | `AgentToolCallAudit` | Agent 工具读写审计 | 不能替代主证据链 |

## DTO 契约

### 1. `AIRequestContextDTO`

用于组织 Gateway 输入。

最低字段：

- `task`
- `roomId`
- `viewerRole`
- `characterId?`
- `actionId?`
- `contextChunks[]`

禁止字段：

- API key
- `owner_token`
- `player_token`
- 未过滤 truth / hidden clue / hidden NPC 原文

### 2. `AIVisibleContextChunkDTO`

用于表示“这条上下文为什么能给 AI 看”。

最低字段：

- `sourceType`
- `sourceId`
- `visibility`
- `reason`
- `roomId`
- `scenarioId`
- `characterScope`
- `unlockState`

这是 Admin context preview 的核心解释单元。

### 3. `MechanicSuggestionDTO`

最低字段：

- `triggeredMechanic`
- `skillName`
- `difficulty`
- `reason`

不得包含：

- 权威 `roll`
- `targetValue`
- `successLevel`

这些都必须由 RuleExecutor 计算。

### 4. `NarrativePayloadDTO`

最低字段：

- `publicText`
- `privateTexts`
- `keeperNotes?`

语义要求：

1. `publicText` 只允许进入 `party/public` projection。
2. `privateTexts` 必须以 `characterId` 为 key。
3. 缺少 `characterId` 的 private text 不得下发。
4. `publicText` 和 `privateTexts` 都要过 Safety，但审查策略可以不同。
5. `keeperNotes` 默认为 `host/admin/internal`，不得进入 Player projection、Player Journal 或 public export。

兼容说明：

- 当前代码中的 `NarrativePayload(public, perCharacter)` 可以通过 alias 兼容
- 但产品语义必须和 `publicText + privateTexts` 一一对应

### 5. `AIMutationProposalDTO`

最低字段：

- `type`
- `target`
- `payload`
- `permission`
- `sourceRefs`

禁止形式：

- SQL 语句
- JSON Patch
- 未经服务层校验的权威状态写入

### 6. `AIProviderResultDTO`

最低字段：

- `task`
- `provider`
- `status`
- `schemaVersion`
- `outputSummary`

### 7. `AICallLogDTO`

最低字段：

- `roomId`
- `task`
- `provider`
- `status`
- `durationMs`
- `fallbackChain`
- `inputSummary`
- `outputSummary`
- `errorClass?`

禁止字段：

- raw prompt
- raw response
- API key
- token
- 完整 hidden truth

补充边界：

- 普通 `AICallLogDTO` 只保存结构化 summary。
- 如为调试保留 raw prompt / raw response，必须进入单独的 Admin/Ops raw debug 路径。
- raw debug 路径必须满足 `admin_only + never_export + 单独权限校验`。

### 8. `AgentToolCallAuditDTO`

最低字段：

- `toolName`
- `roomId`
- `characterId`
- `actionId?`
- `allowed`
- `reason`
- `sourceRefs`
- `createdAt`

## Gateway 任务状态模型

当前文档固定以下任务状态：

- `success`
- `schema_fail`
- `provider_error`
- `timeout`
- `fallback_used`
- `local_fallback`
- `rejected_by_safety`
- `empty_response`

每次 Gateway 调用至少应记录：

- `task`
- `provider`
- `status`
- `durationMs`
- `fallbackChain`
- `schemaVersion`
- `inputSummary`
- `outputSummary`
- `errorClass`
- `roomId?`
- `actionId?`

## 核心流程

### 1. 玩家意图到规则结算

Player 提交自然语言意图后：

1. Engine 创建 action。
2. `ResolutionPipeline` 读取 action、角色、房间、场景。
3. `MechanicCompiler` 输出 `MechanicSuggestionDTO`。
4. `RuleExecutor` 产出权威检定结果。
5. AI 无权覆盖 `roll / targetValue / successLevel`。

### 2. RAG 上下文构造

RAG 可以先召回较宽集合，但进入 AI prompt 前必须执行 `final context filter`。
这条是 `P0 安全边界`，不是可推迟的体验优化项。

最小过滤维度：

- `viewer_role`
- `room_id`
- `scenario_id`
- `character_id`
- `source_type`
- `visibility`
- `unlock_state`

特定规则：

- `source_type=scenario` 的 raw text 默认 internal / host
- `source_type=clue` 只允许 owned clue 或 shared `publicVersion`
- `source_type=event` 只允许 player-visible Journal 视图
- `source_type=npc` 必须过滤 hidden / truth / ai_only 字段

### 3. AI 叙事生成与反剧透

AI 叙事生成分为：

- fallback narrative
- Gateway 增强 narrative

所有 public narrative 必须经过 `SpoilerGuard.review`。

若命中敏感项：

1. 先尝试带约束 retry。
2. retry 失败则使用安全 fallback。
3. 记录 `spoiler_audits`。

retry prompt 不得包含完整敏感原文，只能包含：

- `violation label`
- `forbidden terms`
- `rewrite constraints`

### 4. mutation proposal 到权威状态

AI mutation proposal 必须先进入统一校验点，例如：

- `MutationValidator`
- 或 `ResolutionPipeline` 内统一 validator

然后再交给对应模块执行。

规则如下：

| mutation 类型 | AI 可否建议 | 必须由谁确认 |
| --- | --- | --- |
| narrative only | 可 | Safety / Projection |
| roll request | 可 | RuleExecutor |
| HP / SAN / Luck | 可建议 | Rule / State |
| clue release | 可建议 | Clue / State / Journal |
| map move | 可建议 | Engine / Map / State |
| NPC reveal | 可建议 | NPC / Projection / Safety |
| truth / WorldBook 修改 | 不可直接建议落库 | Host / Admin / WorldBook |
| SQL / JSON Patch | 禁止 | 无 |

未通过校验的 mutation 只能作为 rejected suggestion 审计，不能写状态。

### 5. Agent 工具

Agent 是实验增强层，不是主裁决路径。

要求：

1. Agent 必须有 feature flag。
2. 默认关闭。
3. 启用后仍不能直接写 HP / SAN / 地图位置 / 世界真相。
4. 所有 write tool 必须走服务层并写 `AgentToolCallAuditDTO`。
5. recent events 读取必须复用 Journal 可见性 helper，不能只靠 `audience IN ('party','player')`。

## 接口方向

| 接口 | 当前状态 | 目标权限 | 说明 |
| --- | --- | --- | --- |
| `POST /api/rooms/{room_id}/ai-turn` | 已有，需加鉴权 | Owner / Admin / Host | 房间级 AI 结算触发入口 |
| `GET /api/rooms/{room_id}/ai-status` | 已有，需分层 | Player: 低敏；Owner/Admin: 详细 | Player 只拿 enabled/mock/fallback/degraded |
| `GET /api/admin/ai/config` | 已有 | Admin | 全局 AI 配置 |
| `PATCH /api/admin/ai/config` | 已有 | Admin | provider order / timeout / 全局策略 |
| `POST /api/admin/ai/health-check` | 已有 | Admin | provider 健康检查 |
| `GET /api/admin/ai/logs` | 已有 | Admin | AI 调用日志 |
| `POST /api/admin/ai/query` | 已有 | Admin | 管理端知识问答测试 |
| `POST /api/admin/rag/context-preview` | 已有 | Admin | 预览最终 AI 上下文 |
| `POST /api/rag/search` | 已有 | Admin / Owner / Room Player | 检索权限不等于 prompt 权限，仍需 final filter |

### `/ai-status` 返回边界

Player 视角只允许返回：

- `enabled`
- `mock`
- `fallback`
- `degraded`

不得返回：

- provider key
- prompt 内容
- 模型配置细节
- API endpoint

## AI / Ops 日志边界

以下内容属于 `Admin/Ops`，不属于 Player Journal，也不属于 public export：

- `ai_call_logs`
- raw prompt
- raw response
- provider trace
- token 用量明细
- `spoiler_audits`
- Agent 工具失败 / 拒绝审计

统一要求：

- `admin_only`
- `never_export`

分层要求：

- 普通 `AICallLogDTO` 只保留脱敏 summary。
- raw debug log 如存在，必须和普通 `ai_call_logs` 分 scope 或分路径处理，不能回灌到 `responseSummary`。

## legacy AIKP 与 AiGateway 关系

文档明确：

1. 主裁决链路以 `AiGateway + ResolutionPipeline` 为准。
2. `AIKP` 当前保留为兼容层或结构化剧本辅助层。
3. 新功能不得继续扩展第二套独立 prompt / schema。
4. 如同一任务同时支持 legacy AIKP 与 Gateway，必须在回执中说明优先级和 fallback 顺序。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| AI-FR-1 | `/ai-turn` 必须有房间级鉴权 | P0 |
| AI-FR-2 | `/ai-status` 必须按 Player / Owner / Admin 分层返回 | P0 |
| AI-FR-3 | Gateway 必须有统一状态模型和 schema 版本口径 | P0 |
| AI-FR-4 | AI 机制建议不能覆盖 RuleExecutor 权威结果 | P0 |
| AI-FR-5 | AI mutation proposal 不得直接落库 | P0 |
| AI-FR-6 | public narrative 必须经过 SpoilerGuard | P0 |
| AI-FR-7 | RAG 最终进入 prompt 前必须 final filter | P0 |
| AI-FR-8 | `ai_call_logs` 必须脱敏，不保留 raw secret | P1 |
| AI-FR-9 | Agent 写工具必须经服务层并产出工具审计 | P1 |
| AI-FR-10 | legacy AIKP 与 Gateway 主辅关系必须收口 | P1 |

## 验收标准

1. 未登录或错误房间身份不能调用 `/ai-turn`。
2. 普通 Player 不能触发全房间 queued action 结算。
3. Player 版 `/ai-status` 不返回 provider key、prompt、配置细节。
4. Gateway 返回坏 JSON 时进入 `schema_fail` 或安全 fallback，而不是直接写状态。
5. provider timeout 时进入 fallback，主链路不中断。
6. `ai_call_logs` 记录 provider、task、status、duration、fallbackChain，但不含 raw token / prompt。
7. AI 返回 `roll=1`、`success=critical` 也不能覆盖 RuleExecutor 权威结果。
8. AI 建议的 HP / SAN / clue / map 变更不能直接落库。
9. Player-facing RAG 不包含 truth / ending / 未发现 hidden clue / hidden NPC 真名。
10. public narrative 全部经过 SpoilerGuard；命中敏感项时有 retry / fallback / audit。
11. Agent write tool 不再直接 `INSERT clues`，并写工具审计。
12. 完整主链路能完成“玩家意图 -> AI/规则裁决 -> 状态变更 -> 安全投影 -> 日志沉淀”。
