# AI-Keeper 核心系统 PRD V2.0

## 背景

AI-Keeper 的价值不在于“AI 能写旁白”，而在于 AI 能在一个有状态、有权限、有证据链的 TRPG 世界中辅助主持。AI 必须被限制在建议层：理解玩家意图、提出机制建议、生成叙事、检索资料、辅助结构化剧本，但不能直接改写权威状态、不能把猜测变成事实、不能泄露未发现真相。

当前仓库已经具备 `AiGateway`、DeepSeek/MCP/local provider、`MechanicCompiler`、`ResolutionPipeline`、RAG、SpoilerGuard、`ai_call_logs` 和可选 Agent。第一轮产品目标是收紧主链路和安全边界，而不是追求复杂 AI agent 自主运行。

## 目标

1. 让 AI 调用有统一入口、统一 schema、统一 fallback 和统一审计。
2. 让 AI 输出只能作为建议进入 Engine/Rule/State，而不能直接落库。
3. 让 AI 输入上下文遵守玩家可见性，未发现线索和隐藏真相不进入 Player 视角。
4. 让 public 叙事经过 SpoilerGuard，命中敏感项时可重试、降级和审计。
5. 让 DeepSeek/MCP/local fallback 任一可用时，主跑团链路不中断。

## 非目标

1. 不让 AI 独立主持完整战役并绕过 Engine。
2. 不做完整模型市场、计费系统、插件生态。
3. 不把 AI 生成的 NPC、地点、线索直接当作世界事实。
4. 不把 Host-only 真相或 AI prompt 写入玩家日志。
5. 不在本模块实现完整 Session 0 安全工具。

## 用户角色

| 角色 | 权限目标 | 不允许 |
| --- | --- | --- |
| Player | 提交意图，接收安全叙事、检定结果、战术提示。 | 触发未授权房间 AI 结算，读取未发现线索。 |
| Host/Owner | 触发结算、查看 AI 降级状态、管理房间级 AI 策略。 | 绕过 Engine 让 AI 直接改状态。 |
| Admin | 配置全局 provider、查看 health/logs、做 RAG preview/reindex。 | 把敏感 prompt、token、隐藏真相公开。 |
| Engine | 调用 AI 建议并决定接受、修正、拒绝。 | 信任未校验 AI JSON 直接执行。 |
| AI-Keeper | 生成建议、叙事、检索答案和结构化草稿。 | 直接写数据库或改变世界真相。 |

## 核心流程

### 玩家行动裁决

Player 提交意图后，Engine 创建 action。`ResolutionPipeline` 读取 action、角色、房间和剧本，调用 `MechanicCompiler` 输出 `MechanicCompileResult`。随后 `RuleExecutor` 执行权威规则，AI 只能参与机制建议和叙事增强。状态变化必须由 `StateService` 写入。

### 叙事生成与防剧透

Pipeline 先生成可读 fallback 叙事。若 Gateway 可用，则调用 `generate_narrative` 增强文本。public 文本必须经过 `SpoilerGuard.review`。若命中未解锁敏感项，系统先尝试带约束重试，仍失败则使用安全 fallback，并写入 `spoiler_audits`。

### RAG 上下文

RAG 可检索规则、剧本、角色、事件、线索、NPC、素材。AI 调用前必须按 room、scenario、character、clue unlock 过滤。Player 视角不能注入 hidden truth、ending、未发现线索、隐藏 NPC 全量信息。

### Provider 与降级

`AiGateway` 按 provider_order 尝试 DeepSeek、Hermes MCP、local。每次调用记录 provider、任务类型、耗时、状态、fallback_chain 和脱敏摘要。模型失败不应破坏 action 状态或 world state。

### 剧本结构化

AI 可辅助从原文提取 scenes、npcs、clues、truth、endings。结构化结果必须经过质量报告、真相锁定和敏感索引构建，不能直接投给 Player。

### 可选 Agent

Agent 工具链目前是实验能力。工具可以查询 NPC、地点、线索、事件和角色，也能 roll/check 或保存线索。保存类工具必须纳入 Clue/State/Journal 链路后才能进入主线。

## 功能需求

| 编号 | 需求 | 优先级 | 验收 |
| --- | --- | --- | --- |
| AI-FR-1 | AI 调度接口鉴权 | P0 | 未授权请求不能触发 `/ai-turn` 或读取敏感 AI 状态。 |
| AI-FR-2 | Provider fallback | P0 | DeepSeek/MCP 失败后 local fallback 可用，并写日志。 |
| AI-FR-3 | 输出 schema 校验 | P0 | AI 坏 JSON、非法字段、非法枚举不会写状态。 |
| AI-FR-4 | 机制编译 fallback | P0 | 编译失败后用 Python fallback，action 不丢失。 |
| AI-FR-5 | AI 不直接落库 | P0 | HP/SAN/线索/地图状态只能经 Engine/State/Clue 写入。 |
| AI-FR-6 | 反剧透输出审查 | P0 | public 叙事命中 truth/hidden clue/hidden NPC 时被拦截。 |
| AI-FR-7 | RAG 上下文最小化 | P1 | Player 视角 AI 上下文不含未授权内容。 |
| AI-FR-8 | Gateway 返回类型兼容 | P1 | `NarrativePayload` 可被 pipeline 正确解析。 |
| AI-FR-9 | AI 调用日志脱敏 | P1 | 日志无 API key、完整 prompt、token、私密真相。 |
| AI-FR-10 | Agent 工具写入治理 | P1 | 工具写线索走统一服务链和事件日志。 |
| AI-FR-11 | Prompt 文案可读 | P1 | 模型可见 prompt 和用户可见 fallback 均为 UTF-8。 |

## 接口方向

| 接口 | 当前状态 | 目标权限 | 说明 |
| --- | --- | --- | --- |
| `POST /api/rooms/{room_id}/ai-turn` | 已有，需加鉴权 | Owner/Admin 或受控 Host 操作 | 触发 queued actions 结算。 |
| `GET /api/rooms/{room_id}/ai-status` | 已有，需加鉴权 | Room member/Owner/Admin | 返回 mock/failure/model 等低敏状态。 |
| `GET /api/admin/ai/config` | 已有 | Admin | 查看全局 AI 配置。 |
| `PATCH /api/admin/ai/config` | 已有 | Admin | 更新全局 provider_order、timeout、权限配置。 |
| `POST /api/admin/ai/health-check` | 已有 | Admin | 检查 provider 健康状态。 |
| `GET /api/admin/ai/logs` | 已有 | Admin | 查询 AI 调用日志。 |
| `POST /api/admin/ai/query` | 已有 | Admin | 管理端知识库问答测试。 |
| `POST /api/admin/rag/context-preview` | 已有 | Admin | 预览 AI 将看到的上下文。 |
| `POST /api/rag/search` | 已有 | Admin/Owner/Room Player | 需要按房间和角色权限过滤结果。 |

## 权限与写入边界

| 动作 | AI 可做 | 必须由其他模块做 |
| --- | --- | --- |
| 判断需要检定 | 建议 skill、difficulty、reason。 | RuleExecutor 掷骰和算成功等级。 |
| 造成 HP/SAN 变化 | 提出 mutation 或叙事建议。 | Rule/State 校验触发条件并落库。 |
| 释放线索 | 建议可能释放的 clue。 | Clue/State 确认归属并写事件。 |
| 生成叙事 | 生成 public/private 草稿。 | Safety/Projection 过滤和投影。 |
| 查询知识 | 读取授权 RAG chunk。 | User/Safety 决定可见范围。 |
| 结构化剧本 | 生成草稿 JSON。 | Module/WorldBook 确认入库和建敏感索引。 |

## 数据边界

1. Prompt 不包含 API key、owner_token、player_token。
2. Player 视角上下文不包含 truth、ending、未发现 hidden clue、未公开 hidden NPC。
3. `ai_call_logs.response_summary` 只保存脱敏摘要，不保存完整 prompt。
4. `keeper_notes` 默认只给 Host/Admin 审计，不进入 Player 事件。
5. AI 生成内容必须标记来源，未经确认不能成为权威事实。

## 验收标准

1. 无登录或错误房间身份不能触发 AI 结算。
2. DeepSeek 返回坏 JSON 时，action 仍能用 fallback 结算或被安全拒绝。
3. AI 建议扣 SAN 时，实际落库只发生在 Rule/State 校验后。
4. AI public 叙事命中未解锁真相时，Player 只看到安全 fallback。
5. RAG context preview 能显示引用来源，但 Player 请求不含未授权真相。
6. `ai_call_logs` 能定位 provider、task、状态、耗时、fallback 链路。
7. 完整主链路能完成“玩家行动 -> AI/规则裁决 -> 状态写入 -> 安全投影 -> 日志沉淀”。
