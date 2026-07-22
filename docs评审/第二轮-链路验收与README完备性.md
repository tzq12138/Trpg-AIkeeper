# 代码 ↔ 核心链路/验收文档 一致性 + README 完备性评审

> 评审对象：
> - 代码总结文档：`G:\hermes-agent-workplace\D&D\CodeX-aikeeper\README.md`（下称 **README**，引用格式 `README:行号`）
> - 设计文档库：`/tmp/docs-review/extracted/docs/`（下称 **docs/**，引用格式 `docs/路径:行号`）
> - 实际代码：`G:\hermes-agent-workplace\D&D\CodeX-aikeeper\`（下称 **code**，引用格式 `code:相对路径:行号`）
>
> 评审日期：2026-07-22。所有结论均给出文件/行号证据；标注【已验证】的条目已在代码中复核，标注【文档证据】的条目仅基于文档互证。

---

## 1. 概述

本轮评审覆盖三部分：①README 的 PlayerIntent 生命周期/状态机/核心状态权威表 与 `docs/20-核心链路/` 全部 9 份文档的一致性；②`docs/30-DeepSeek任务包/`（README + Batch-0~5）与 `docs/60-验收与测试报告/`（TEST_COVERAGE.md、COMPLETION_AUDIT、RUNTIME_ACCEPTANCE、IMPLEMENTATION_MATRIX、INPUT_ROUTING_VALIDATION、BROWSER_PROVIDER_RUNBOOK）对 README 目录树模块的覆盖情况；③README 作为"项目代码总结"的文档完备性。

**总体结论：**

1. README 的主链路顺序（Director→MechanicCompiler→RuleExecutor→StateService→Narrator→SpoilerGuard→Projection）与 20-核心链路中 8/9 份文档一致；唯一的恶性例外是 `KP_MCP_Design.md`，其 §4.1 调用流程是**先推叙事、后掷骰、再写状态**，且叙事不经 fact-ref 校验和 SpoilerGuard——README 没有声明该文档是"未按此实现的历史设计"，存在被后来者照图施工的风险（P0）。
2. README 的"行动状态机"和多处术语与代码权威定义不符：README 用 `resolved`，代码权威终态是 `completed`；README 的 6 状态简化机遗漏了代码中 14 个状态里的 8 个，包括安全关键的 `awaiting_host_exception`（P0）。
3. 验收覆盖存在三类黑洞：**export.py 与 global_reset.py 没有任何专属测试文件**（50-平台文档声称已建 `test_export.py`，实际不存在）；**RagTestPage.tsx 在全部文档中 0 次出现**；TEST_COVERAGE.md 停留在 SQLite 时代的 258 passed 口径，与现行 1194 passed/101 个测试文件的代码完全脱节（P0/P1）。
4. README 缺失 API 参考、DB schema（82 张表仅一句 `initialize()`）、运维、安全设计、贡献指南、CHANGELOG 六类文档，且 README 第 222-231 行的 docs 目录树漏列了实际存在的 4 个目录+1 个文件，未说明 docs 库"00-产品规范为唯一现行定义"的权威层级（P1）。

---

## 2. README ↔ 20-核心链路 一致性问题

### 2.0 链路顺序总对照

| 文档 | 链路顺序 | 与 README 3.2 是否一致 |
|---|---|---|
| README 3.2 | Director→MechanicCompiler→RuleExecutor→StateService→Narrator→SpoilerGuard→Projection | （基准） |
| `AI-Keeper核心链路架构.md:7-17` | Intent Gateway→Mechanic Compiler→Rule Executor→Engine Transaction→State Mutation→Projection Builder | ✅ 一致（无 Narrator/SpoilerGuard 的简化版，但规则先于叙事：`第41-46行`四阶段裁决中"叙事渲染"在"规则执行"之后） |
| `数据流.md:1` | 资产校验→机制编译→规则引擎→叙事渲染 | ✅ 一致 |
| `数据流bug+思考.md:122-190` | 掷暗骰数学裁决（阶段二）→RAG+叙事渲染（阶段三）→投影（阶段四） | ✅ 一致 |
| `规则导入.md:99-113` | Handler 掷骰算事实→编译突变→合流给大模型"看图说话" | ✅ 一致 |
| `AIKP 接收玩家行动…完整协议.md:693-705` | RuleResult→MutationValidator→StateService.apply_change→NarrativeComposer→Projection | ✅ 一致（State-first 原则） |
| `AIKP玩家行动编排与Host演出系统_PRD_V1.0.md:220-267, 655-711` | IntentCompiler→确认→MechanicCompiler→RuleExecutor→MutationValidator→StateService→ResolutionBundle→NarrativeComposer+SpoilerGuard→Projection | ✅ 一致 |
| `KP_MCP_Design.md:393-443` | **kp_resolve_turn 一次返回→narrative 直接推 Projection→rollRequests 再掷骰→stateMutations 再写库** | ❌ **严重冲突（见 P0-1）** |
| `soul.md` | 行为策略文档，无工程链路 | N/A |
| `剧本导入后的 RAG….md` | RAG 构建链路，非行动结算链路 | N/A（但有术语问题，见 P2-4） |

### P0-1：KP_MCP_Design.md 存在"先推叙事再掷骰"的恶性设计，README 未作隔离声明【文档证据】

`docs/20-核心链路/KP_MCP_Design.md:401-443` 的"新流程"伪代码：

```
# 新流程:
#   PlayerIntent + Context → kp_resolve_turn() → KpResponse
#     → narrative → ProjectionDispatcher 直接推      ← 第 403、416-420 行
#     → rollRequests → RuleExecutor 掷骰             ← 第 404、423-426 行
#     → stateMutations → Engine 分级写入             ← 第 405、428-434 行
```

问题有三层：

1. **时序颠倒**：narrative 在 RuleExecutor 掷骰之前推送（`KP_MCP_Design.md:416-426`）。LLM 在骰点结果产生之前生成叙事，叙事不可能引用权威骰点，直接违反 PRD §4.4"权威状态必须先持久化，再对外投影"（`PRD_V1.0.md:129-138`）、完整协议 §十二"结果必须先写 State，再让 AI 讲故事"（`完整协议.md:689-711`），也违反 README 3.2 的 Narrator 在 RuleExecutor/StateService 之后的顺序（`README:304-312`）。
2. **缺失校验环**：该流程中 narrative "Level 2 全权直接推"（`KP_MCP_Design.md:345`），没有 README 3.2 的 `validate_narration_result()` fact-ref 校验（`README:310-311`）和 SpoilerGuard 反剧透（`README:312`）。
3. **AI 直接产出状态变更**：`KpResponse.stateMutations` 由 LLM 直接生成并经 `permission: "direct"` 落库（`KP_MCP_Design.md:84-95, 355-389`），与 PRD §16.2"AI 机制建议不得包含权威"、核心链路架构.md"DeepSeek 实现红线：不允许让 AI 直接返回数据库写入命令"（`AI-Keeper核心链路架构.md:60`）冲突。

**这就是用户问询的"先推叙事再掷骰"类问题的实锤，且它不在 README 里，而在设计文档库里。** 实际代码未按此实现（code 的 ResolutionPipeline 顺序与 README 一致），但 README 和 docs 都没有任何"KP_MCP_Design §4.1 为废弃设计"的标注。docs 库总索引仅说"20-核心链路需与 M0 规范对照"（`docs/README.md` 推荐阅读顺序第 6 条），力度不足。

### P0-2：行动状态机三套词汇打架，README 选了与代码权威定义不符的一套【已验证】

| 来源 | 行动状态机 |
|---|---|
| README 3.3（`README:320-323`） | `idle → submitting → queued → resolving → resolved ↘ rejected / timeout` |
| PRD §12.2（`PRD_V1.0.md:521-535`） | `submitted → queued → resolving → resolved / rejected / timeout / cancelled` |
| 00-产品规范（`docs/00-产品规范/02-核心用户旅程与生命周期.md:52`） | `analyzing → awaiting_confirmation → queued → batched → resolving → completed`（+`canceled/rejected/timeout/awaiting_player_choice/awaiting_host_exception/sync_required`） |
| **代码权威**（`code:src/server/engine/action_state.py:1-17`） | 14 个状态：`analyzing, awaiting_confirmation, armed, queued, batched, resolving, awaiting_player_choice, awaiting_host_exception, completed, rejected, canceled, timeout, sync_required`；**终态为 `completed/rejected/canceled/timeout`，无 `resolved`** |

证据要点：

- 代码中 `resolved` 仅存在于遗留路径（`code:src/server/game_loop.py:60,65`、`code:src/server/models.py:86` 遗留枚举、encounter 状态），V2 权威状态机用 `completed`；读取侧大量 `status in ("completed", "resolved")` 双写兼容（如 `code:src/server/player/action_service.py:1431`、`router_player.py:1208`），证明词汇迁移只做到一半。
- README 3.2 第 313 行"写 actions(status='resolved')"与权威状态机不符。
- README 的 6 状态简化机遗漏了安全关键状态 `awaiting_host_exception`、`awaiting_confirmation`、`batched`、`armed`、`sync_required`——其中 `awaiting_host_exception` 是 Host 离线自治和 AI 降级的核心出口（见 3.1 节验收文档大量引用），读者按 README 无法理解验收报告。
- PRD 的 `cancelled`（双 l）与代码 `canceled` 也不一致（`PRD_V1.0.md:533` vs `action_state.py:12`）。

### P1-1：`host_exception` 术语三义混用【已验证】

README 3.2 第 305-306 行写：`低置信度(<0.6) → player_clarification_required → host_exception`，把 `host_exception` 当作一个状态/事件节点。实际：

- 代码中 `host_exception` 是 **resolution_route 枚举值**（`code:src/server/models.py:244`：`resolution_route: Literal["ai", "local", "host_exception"]`），不是行动状态、也不是事件类型。
- 行动状态是 `awaiting_host_exception`（`code:src/server/engine/action_state.py:9`；`code:src/server/player/action_service.py:1105` 的 `UPDATE actions SET status = 'awaiting_host_exception'`）。
- 玩家侧事件是 `s2c_action_deferred`（`code:src/server/events/events_registry.py:68`；`docs/60-验收与测试报告/260718_RUNTIME_ACCEPTANCE_2026-07-19.md:195`）。
- 20-核心链路的 9 份文档中 `host_exception` 一词 0 次出现（全库检索），文档统一用 `awaiting_host_exception`（`docs/00-产品规范/02-核心用户旅程与生命周期.md:52` 及 60 验收报告多处）。

README 自创了一个文档与代码都不存在的节点名，且把"路由值、状态、事件"三层语义压缩成一个词。

### P1-2：置信度阈值口径错误/不完整【已验证】

README 3.2 第 305 行声称"低置信度(<0.6) → player_clarification_required → host_exception"。代码实际是**两级阈值**：

- `code:src/server/ai/director.py:185`：`plan.confidence < 0.6` → 澄清分支；
- `code:src/server/player/action_service.py:236` 与 `:379`：`confidence >= 0.75` 才走 `"ai"/"local"`，否则一律 `host_exception`。

README 只写了 0.6 一级，且暗示"澄清→host_exception"是顺序流，遗漏了 0.6~0.75 区间直接进 `host_exception` 的主路径。

### P1-3：KP MCP Server 工具集设计（7 个）与实现（4 个）差距无任何说明【已验证】

- 设计：`KP_MCP_Design.md:25-336` 定义 7 个 tools：`kp_resolve_turn / kp_resolve_sanity / kp_resolve_combat_round / kp_structure_scenario / kp_query_rules / kp_health_check / kp_query_knowledge`；§5.1 文件结构含 `tools.py`、`context_builder.py`（`KP_MCP_Design.md:478-490`）。
- 实现：README 第 191 行写 `server.py # ASGI 应用（4 个 tool）`，与代码一致——`code:kp_mcp_server/server.py:39-71` 只有 `kp_structure_scenario / kp_analyze_director_action / kp_narrate_action / kp_health_check`，无 `tools.py`、`context_builder.py`。
- 设计的 7 个 tool 中 5 个（含"80% 调用量"的主结算 `kp_resolve_turn`）**从未实现**，且 tool 命名体系完全不同。`KP_MCP_Design.md:769-794` §8.3 还声明 `ai_kp.py`、`agent/game_agent.py` 将"被替换"、`agent/` 目录将"移除"，但 README 目录树中这些文件全部存在（`README:87,143-145`）。

README 未说明该文档是"未落地的候选设计"，读者无法判断 MCP Server 到底该有 4 个还是 7 个 tool。

### P1-4：README 3.5 权威表与 RAG 文档揭示的现状矛盾，README 把目标态写成现状【已验证】

- README 3.5（`README:335`）：HP/SAN/MP/Luck 权威来源 = `character_runtime_state` 表，"`xlsx_data` 仅作初始值"。
- `docs/20-核心链路/剧本导入后的 RAG….md:224-254` §5 明确指出：`RAGContextBuilder.characters_direct` 仍从 `characters.xlsx_data` 读取当前 HP/SAN，列为待修 P0-6（`同文件:1418-1420`）。
- 代码验证：`code:src/server/ai/rag_context.py:96` 仍在 `xlsx = self._json_val(char_row.get("xlsx_data"))`。

即：权威表对"Engine 写入口"成立，但对"AI 上下文读出口"不成立。README 没有任何附注，AI 仍可能看到旧状态——这正是 `数据流bug+思考.md:7-26` Bug 1"事实时差"的同类风险。

### P2-1：投影 audience 分类表述不精确【已验证】

README 3.2 第 314 行"ProjectionDispatcher 推送 4 条事件（host + player + party）"：

- 代码 audience 有 **4 个取值**：`host/player/party/system`（`code:src/server/engine/projection.py:15-22`），与 `数据流bug+思考.md:233` 的信封注释 `audience: "host" // host | player | party | system` 一致；README 漏掉 `system`。
- "4 条事件"的来源应是 party 事件拆成 host+player 两份（`projection.py:20-21`），README 未解释这个"4=1+1+2"的拆分逻辑。
- 完整协议 §十六列出一次结算可产生 5 类下行事件（`s2c_action_queued / s2c_reveal_transaction / s2c_state_patch / s2c_action_completed / s2c_public_observation`，`完整协议.md:946-952`），与 README 的"4 条"口径不同。
- 另外 RAG 文档 §6（`剧本导入后的 RAG….md:258-310`）指出 visibility 枚举在 `ContentProjectionService`（`player/host_only/keeper/internal`）与 `RAGStore`（`public/party/host_only/internal`）之间漂移，README 对 visibility 体系只字未提。

### P2-2：AI provider 默认顺序，README 与 KP_MCP_Design 口径不同且未说明迁移态

- README 环境变量表（`README:268`）：`AI_PROVIDER_ORDER` 默认 `mcp,deepseek,local`，与代码一致（`code:src/server/config.py:14,33`）。
- `KP_MCP_Design.md:727-742`：v1 默认 `deepseek,mcp,local`，Phase 3 才切到 `mcp,deepseek,local`（`KP_MCP_Design.md:791-794`）；§8.1 还把 MCP Server 称为"Hermes MCP"（遗留工作区命名）。

README 反映的是"Phase 3 迁移完成态"，文档是"迁移路线态"，两边都没有一句话说明当前处于哪个 Phase。另外 `KP_MCP_Design.md:300` 的 `kp_health_check` 返回示例 `"model": "deepseek-v4-pro"` 与 README 默认值一致，此项无冲突。

### P2-3：回合状态机过于简化，与验收口径不同

README 3.4（`README:327-329`）：`collecting → resolving → resolved`。代码 `turn_manager.py:1` docstring 与此一致，但代码另有 `blocked` 状态（`code:src/server/turn_manager.py:26,33`），且 V2 战斗回合在验收文档中以 `declaration/resolution/summary` 阶段 + `mode=combat` 描述（`260718_IMPLEMENTATION_MATRIX_2026-07-19.md:50`），`turn_manager.py:148-149` 也有 `collecting→declaration`、`resolving→resolution` 的阶段映射。README 未提 `blocked` 与阶段/模式二元结构。

### P2-4：其他文档内术语杂音（供记录，不影响 README 主链）

- `数据流.md:13` 阶段二建议用"GPT-4o-mini"做机制编译，与项目 DeepSeek 技术栈（README:13）不一致。
- `数据流.md:10` 声称资产校验失败返回 HTTP 400/403；`数据流bug+思考.md:137` 的时序图返回 202 Accepted；TEST_COVERAGE 审查记录（`TEST_COVERAGE.md:405`）确认已统一为 202。文档内部历史口径未清理。
- `剧本导入后的 RAG….md:161-198` 记录 `audience="ai"` 无过滤问题（P0-1 待修项，`同文件:1345-1354`）；代码验证 `code:src/server/ai/rag_context.py:64` 仍是 `audience="ai"`——**该已知 P0 安全问题至今未修，README 无任何提示**（此条升级为 P1 记录于此）。

---

## 3. 漏验收/漏测试清单（代码模块 × 任务包/验收报告覆盖情况）

### 3.1 正向核对：30-DeepSeek任务包声称的工作 → README 目录树

Batch-0~5 涉及的所有代码路径（`router_player.py`、`router_reconnect.py`、`host/router_host.py`、`host_store.py`、`hud_builder.py`、`events/events.py`、`events_registry.py`、`ai/gateway.py`、`providers.py`、`mechanic_compiler.py`、`contracts.py`、`spoiler_control.py`、`engine/spoiler_guard.py`、`resolution_pipeline.py`、`rule_executor.py`、`state_service.py`、`projection.py`、`rag.py`、`rag_context.py`、`router_clues.py`、`event_log.py`、`kp_mcp_server/kp_brain.py`、`scenario/quality.py`、`log_config.py`）在 README 目录树中**全部存在**，无"任务包做了但 README 漏列"的模块。✅

例外一条：Batch-1/2 的文件方向写 `src/client/src/shared/ws.ts`（`Batch-1:27`、`Batch-2:23`），README 目录树只列了 `src/client/src/ws.ts`（`README:152`）。代码验证 `code:src/client/src/shared/` 真实存在且含 **33 个模块**（ws.ts、player-api.ts、host-auth.ts、reset-workflow.ts、rag-acceptance.ts 等）——README 目录树**整个漏掉 `shared/` 层**，详见第 5 节 F-6。

### 3.2 用户点名模块的覆盖矩阵【均已验证】

| README 模块 | 30-任务包 Batch0-5 | 60-验收与测试报告 | 专属测试文件 | 结论 |
|---|---|---|---|---|
| `global_reset.py`（README:53） | ❌ 未出现 | ⚠️ 仅间接：`test_room_migration_v2.py` 附带"全局重置门禁"（`COMPLETION_AUDIT:410`）；`loop_runs/20260717-page-experience-acceptance.md:21` 以 4 条迁移测试充数；前端 `reset-workflow.ts` 有组件回归（`COMPLETION_AUDIT:557`） | ❌ **tests/server 无任何 *reset* 测试文件** | **漏独立测试** |
| `v2_cutover.py`（README:55） | ❌ 未出现 | ✅ `test_v2_cutover.py` 19 passed（`COMPLETION_AUDIT:513`） | ✅ 存在 | 覆盖（30 包外） |
| `room_migration.py`（README:54） | ❌ 未出现 | ✅ `test_room_migration_v2.py` 多处（`COMPLETION_AUDIT:404-412, 503`） | ✅ 存在 | 覆盖（30 包外） |
| `turn_timeout_worker.py`（README:58） | ❌ 未出现 | ✅ `test_turn_timeout_worker.py`（`COMPLETION_AUDIT:55, 433`；`RUNTIME_ACCEPTANCE:118,183`） | ✅ 存在 | 覆盖（30 包外） |
| `scenario/solo_runtime.py`（README:129） | ❌ 未出现 | ✅ `test_solo_adventure_runtime.py`（`COMPLETION_AUDIT:188, 212, 224`） | ✅ 存在 | 覆盖（30 包外） |
| `combat_round_planner.py`（README:52） | ❌ 未出现 | ✅ `test_combat_round_planner.py`（`COMPLETION_AUDIT:109-113, 609`；`RUNTIME_ACCEPTANCE:70-71`） | ✅ 存在 | 覆盖（30 包外） |
| `export.py`（README:38） | ❌ 未出现 | ❌ 60 主报告 0 次提及；仅 `docs/50-AI-Keeper-Platform/11-Journal日志与回放系统/回执-2026-07-06.md:38` 声称"public export 使用 public_version ✅ Clue-3"且其 DeepSeek 计划声称"新增 `tests/server/test_export.py`"（`11-Journal/DeepSeek计划.md:54`） | ❌ **tests/server 无任何 *export* 测试文件** | **验收证据悬空：文档声称的测试文件不存在** |
| `pages/AdminDashboard.tsx`（README:165） | ❌ 未出现 | ❌ 60 报告 0 次；仅 50-平台 `24-Plugin-Admin-Ops` 列为"部分已有、本轮只做最小增强"（`24-Plugin-Admin-Ops/功能列表.md:35,173`），无完成回执 | ❌ 无前端测试声明 | **漏验收** |
| `pages/RagTestPage.tsx`（README:169） | ❌ 未出现 | ❌ **全文档库 0 次出现**（全库检索 RagTestPage 仅命中代码 `code:src/client/src/pages/RagTestPage.tsx`、`App.tsx`） | ❌ | **完全无任务/验收记录** |

### 3.3 README 中从未出现在 30-任务包/60-验收报告的其他模块（抽样）

以下模块在 30-任务包（Batch 0-5）与 60-验收主报告中均无独立验收记录（部分在 50-平台或 loop_runs 中有痕迹）：

- `engine/retro_items.py`（README:68）：30/60 主报告未提及；仅 PRD/完整协议有机制设计。
- `engine/compensation_service.py`（README:72）：60 报告有测试引用（`COMPLETION_AUDIT:34, 551`），但 30 包无。
- `engine/prepared_rule_actions.py`（README:70）：60 有覆盖（`COMPLETION_AUDIT:577-586, 603-613`），30 包无。
- `engine/host_autonomy.py`（README:69）：60 有覆盖（`RUNTIME_ACCEPTANCE:191-203`），30 包无。
- `player/router_collaboration_contracts.py`（README:99）：60 有覆盖（`COMPLETION_AUDIT:564-595`），30 包无。
- `stt.py`（README:39）：TEST_COVERAGE 自认 PRD-08 语音"⚠️ 部分，无后端测试"（`TEST_COVERAGE.md:23,117-120`），之后无任何验收报告跟进。
- `router_migration.py`（README:47）与 `room_migration.py` 的 REST 层：验收均只到 service 层。
- `narrative_provider.py`、`campaign_archive.py`、`map_generator.py`、`scene_image_service.py`、`asset_binding.py`、`golden_suite.py` 等：30 包均无；60 有部分（素材绑定/黄金套件在 `COMPLETION_AUDIT:143, 424-437, 615-621` 有覆盖）。

**结构性结论**：30-DeepSeek任务包（Batch 0-5）是 6 月早期核心链路批次，其后的 v2 行动链、战斗轮、迁移/重置、单人冒险、协同合同等全靠 60-验收报告"事后追认"，**没有任何后续任务包承接**；docs/README.md 自己也承认"核心链路之外的平台能力统一沉淀在 40-平台补全，等 Batch 5 验收后再拆新的 DeepSeek 批次"——这批批次至今不存在。

### 3.4 验收报告"通过"声明 ↔ README 实现证据核对

| 验收声明 | 证据 | README 侧实现证据 | 核对结果 |
|---|---|---|---|
| TEST_COVERAGE：30/31 PRD 完成、258 passed（`TEST_COVERAGE.md:5, 47`） | 2026-06-25，PostgreSQL 迁移后口径 | README 目录树的现行模块（resolution_pipeline/state_service/director/narrator/v2 路由群）在其"服务端文件清单"（`TEST_COVERAGE.md:314-346`）中**全部缺席**；清单仍列 `database.py`(SQLite)、`events.py`、`projection.py` 平铺结构、`PlayerAction.tsx`（现行文件名 `PlayerActionPage.tsx`，README:160） | ❌ **TEST_COVERAGE.md 整体过期**，其"完成"无法映射到 README 现行代码 |
| COMPLETION_AUDIT：1194 passed（`COMPLETION_AUDIT:613, 621-622`） | 2026-07-20 分组回归 | 与 code 101 个测试文件规模相容【已验证】 | ✅ 可信，但注意其全部是**离线自动化**；25 条核心断言中 24 条标注"自动化通过；浏览器未验收"（`BROWSER_PROVIDER_RUNBOOK:79-103`） |
| RUNTIME_ACCEPTANCE：Host 离线自治、组合行动、缺席策略等"已实现" | 多处标注"部分实现"（`IMPLEMENTATION_MATRIX:22, 50-56`） | README 把对应模块（host_autonomy/combat_round_planner/turn_timeout_worker）作为既成模块列出，**无成熟度标注** | ⚠️ README 读者会高估完成度；README 缺少"自动化通过≠浏览器验收通过"的警示 |
| 黄金样本 E2E 9/9（`COMPLETION_AUDIT:424-437`） | `scripts/run_golden_module_suite.py` | README:211, 506 有对应 ✅ | ✅ 一致（README 未提 9 模组与报告位置 `docs/loop_runs/2026-07-19-golden-module-suite-report.md`） |

---

## 4. README 缺失的文档类型清单（逐类风险与建议）

### 4-1 无 API 参考文档（REST/WebSocket 端点清单）——风险：高

README 全文只有一个端点 `POST /api/player/intent`（README:297）。实际代码有 30+ 个 router（player 11 个 + host 2 个 + admin/auth/ai/map/archive/migration/rag/rooms/scenarios）。PRD §21.1（`PRD_V1.0.md:982-995`）和设计文档散见部分端点（如 KP_MCP_Design §8.2 的 5 个 admin 端点），但无任何统一 API reference；WebSocket 事件类型散落在 `models.py:13` 的注册表和 PRD §21.2（`PRD_V1.0.md:999-1012`）。
**建议**：新增 `docs/API参考.md` 或 README 附录，按 router 列出端点/鉴权/请求响应模型，并给 WebSocket 事件注册表（类型×audience×payload）一张总表。

### 4-2 无数据库 schema 文档——风险：高

README 仅有"数据库迁移通过 `db_adapter.initialize()` 自动执行（建表 + 索引）"一句（README:465）。代码验证 `code:src/server/db_adapter.py:1675` 的 `initialize()` 内含 **82 个 CREATE TABLE 语句**。`character_runtime_state`、`events`、`resolution_bundles`、`player_action_submissions`、`document_chunks` 等核心表的字段、索引、外键、生命周期全部无文档；迁移策略只有"幂等可重复执行"（README:488），无版本化/回滚口径（与 `rooms.runtime_package_version_id` 这类运行时绑定的交互更是空白）。
**建议**：至少为核心状态权威表（README 3.5 的 5 行）逐表补 schema 摘要与写入方矩阵。

### 4-3 无运维文档（监控/告警/备份/容量）——风险：中高

README 的运维内容只有"日志写 `log/YYYY-MM-DD/`，保留 7 天"（README:466）。无：`/api/health` 返回结构说明（KP_MCP_Design §9.3 设计过 AI 健康字段，`KP_MCP_Design.md:830-846`）、`ai_call_logs` 成本监控表（`KP_MCP_Design.md:800-821`，README 未提）、备份/恢复手册（room_migration ZIP 在 `COMPLETION_AUDIT:404-412` 被当作迁移工具，"恢复演练"自认未完成，`IMPLEMENTATION_MATRIX:75`）、容量/连接池（README:349 提到连接池 2-10 但无调优依据）、pytest 全量需 22-26 分钟且需防 TRUNCATE 死锁的操作注意（`COMPLETION_AUDIT:138-145, 599`）——这类"怎么安全跑测试"的知识只在验收报告里。
**建议**：补"运维与运行手册"一节，收编健康检查、测试运行纪律、备份恢复、日志保留。

### 4-4 无安全设计文档（威胁模型）——风险：中

README 5.5 有安全模块表（README:415-425），但只是模块罗列。威胁模型散落在 PRD §23 的 12 条（`PRD_V1.0.md:1048-1062`）、核心链路架构.md 红线（`AI-Keeper核心链路架构.md:57-63`）、KP_MCP_Design §9.2 审计约束。JWT 之外的 token 体系（`X-Room-Token`/`owner_token`/player_token）、`owner_token` 被 50-平台标记为"过强需收敛"（`50-AI-Keeper-Platform/01-Room团房间系统/功能列表.md:60`）、upload 四重校验、SSRF 防护、AI key 加密等，无统一威胁模型（谁、攻击什么、在哪一层挡）。
**建议**：补安全设计文档，至少含身份令牌矩阵 + AI 输出不信任边界 + 已知未修项（如 `audience="ai"` 无过滤，`rag_context.py:64`）。

### 4-5 无贡献指南/代码规范/分支策略——风险：中

仓库有 `AGENTS.md`、`CLAUDE.md`（README:238-239 仅列名），30-任务包 README 有"通用执行规则"（`30-DeepSeek任务包/README.md:16-23`）但那是给 DeepSeek 的批次纪律，不是贡献者指南。无分支策略、commit/PR 规范、测试纪律（测试库隔离、不得清空开发库只出现在任务包规则里）。
**建议**：README 增加"参与开发"小节，指向 AGENTS.md 并固化测试库纪律。

### 4-6 无 CHANGELOG/版本策略——风险：低-中

README 无版本号、无变更历史；`rulePackage: "coc7e@1.0.0"`（`PRD_V1.0.md:400`）、`runtime_package_versions`、`scenario_versions` 等**数据层**有版本概念，但应用自身无版本策略。升级方式只有"git pull + 重启"（README:487）。
**建议**：至少声明当前 M0 阶段与版本标记约定。

### 4-7 README 与 docs/ 目录的边界未说清——风险：高（文档治理）

README 第 222-231 行的 docs 树与实际 docs 库对比【已验证 `ls docs/`】：

| README 列出 | 实际存在但 README 漏列 |
|---|---|
| 00-产品规范、20-核心链路、25-深挖优势与设计原则、30-DeepSeek任务包、50-AI-Keeper-Platform、60-验收与测试报告、PRDs、设计前端、90-归档 | **`00-路线图/`、`10-现状盘点/`、`40-平台补全/`、`开发文档/`、`docs/README.md`（总索引）** |

更重要的是权威层级未声明：`docs/README.md` 明确"**00-产品规范是唯一现行定义**……20-核心链路需与 M0 规范对照"、`soul.md` 标注"候选行为策略"、`00-路线图` 标注"历史/候选路线"。README 把 docs 平铺罗列，读者会把 KP_MCP_Design（未落地设计）与 00-产品规范（现行宪法）当成同等效力——这正是 P0-1 类风险的治理根源。
**建议**：README docs 树补全 5 项，并加一句权威排序："冲突时 00-产品规范 > 验收报告 > 20-核心链路 > 其他"。

### 4-8 其他结构性缺失（附带）

- **无前端架构说明**：`src/client/src/shared/` 33 个模块在目录树中整体缺失（见 5.F-6）；`tests/` 前端 45 文件/167+ 用例的规模未提（`COMPLETION_AUDIT:613`）。
- **无错误模型汇总**：PRD §22 的 11 类错误（`PRD_V1.0.md:1028-1044`）在 README 无对应。
- **无 DTO/契约清单**：完整协议 §二十二列出 20+ DTO（`完整协议.md:1314-1363`），README 只有 3 处 DTO 名。

---

## 5. README 自身事实性问题

| # | README 表述 | 核查结果 | 级别 |
|---|---|---|---|
| F-1 | `DEEPSEEK_MODEL` 默认 `deepseek-v4-pro`（README:264） | 与代码一致（`code:src/server/config.py:8,27`）；且该模型**真实存在**（DeepSeek-V4 于 2026-04 发布，`deepseek-v4-pro` 为旗舰 API 模型名；旧 `deepseek-chat/reasoner` 2026-07-24 弃用）。**非错误** | ✅ 无误 |
| F-2 | 端口：BE 3001 / FE 5173 / KP 9100 / PG 5432 / Redis 6379（README:232-233, 274, 349-352） | 与 `dev.py:242,290-292,304`、`docker-compose.yml`、`config.py:10,13` 全部一致【已验证】 | ✅ 无误 |
| F-3 | "tests/server/（~100 个文件）"（README:200） | 实际 **101** 个【已验证】 | ✅ 基本准确 |
| F-4 | 行动状态机 `resolved`（README:313, 321） | 代码权威终态为 `completed`（`action_state.py:10,17`）；`resolved` 仅遗留路径 | ❌ P0（详见 2.P0-2） |
| F-5 | "低置信度(<0.6) → … → host_exception"（README:305-306） | 代码为 0.6/0.75 两级阈值；`host_exception` 是路由值非状态（详见 2.P1-1/P1-2） | ❌ P1 |
| F-6 | 前端目录树无 `shared/`（README:147-189） | `code:src/client/src/shared/` 存在且含 33 个模块（player-api.ts、host-auth.ts、reset-workflow.ts、ws.ts 等）；30-任务包 Batch-1/2 引用的 `shared/ws.ts` 即在此 | ❌ P1（目录树失真） |
| F-7 | "推送 4 条事件（host + player + party）"（README:314） | audience 实为 4 值含 `system`（`projection.py:15-22`），"4 条"未解释 | ⚠️ P2 |
| F-8 | 回合状态机 `collecting → resolving → resolved`（README:328） | 代码一致但遗漏 `blocked`（`turn_manager.py:26`） | ⚠️ P2 |
| F-9 | docs 树（README:222-231） | 漏 `00-路线图/`、`10-现状盘点/`、`40-平台补全/`、`开发文档/`、`docs/README.md` | ❌ P1（详见 4-7） |
| F-10 | "数据库迁移通过 `initialize()` 自动执行（建表+索引）"（README:465） | 属实但严重缩水：82 个 CREATE TABLE（`db_adapter.py:1675`），且无版本化迁移策略 | ⚠️ P2 |
| F-11 | `kp_mcp_server/server.py` "4 个 tool"（README:191） | 与代码一致【已验证】；但与 KP_MCP_Design 的 7-tool 设计差距未说明 | ⚠️ P1（详见 2.P1-3） |
| F-12 | 3.5 权威表"`xlsx_data` 仅作初始值"（README:335） | 对 Engine 写成立；但 AI 上下文构建仍读 `xlsx_data`（`rag_context.py:96`），README 无附注 | ⚠️ P1（详见 2.P1-4） |
| F-13 | `export.py` "公开导出（脱敏）"（README:38） | 50-平台功能列表标记其 public 口径为 **P0 风险**（`audience != 'player'` 粗过滤，`50-AI-Keeper-Platform/11-Journal日志与回放系统/功能列表.md:38,171,178`）；回执声称已修但对应测试文件不存在 | ⚠️ P1（脱敏口径无测试证据） |
| F-14 | "AI Provider 链路：`mcp → deepseek → configured_openai → local`"（README:356） | 与默认配置一致；但 KP_MCP_Design §8.1 环境示例为 `deepseek,mcp,local`，README 未说明 Phase 口径 | ⚠️ P2 |

未验证项（如实声明）：README 3.1 启动 11 步顺序（main.py lifespan 未逐步核对）、"psycopg2 连接池 2-10"、"Redis 事件缓存最近 200 条 / HUD TTL 60s"、前端 Bauhaus 设计系统等表述，本轮未取得代码证据，不判真伪。

---

## 6. 结论与行动建议

### 结论

README 对**现行代码**的总结大体可信（端口、模型名、目录结构主干、4-tool MCP、外部服务接口均与代码一致），主链路顺序与 20-核心链路 8/9 文档一致。但它有三个系统性缺陷：

1. **状态机与术语层与代码权威定义脱节**（`resolved` vs `completed`、`host_exception` 三义混用、阈值口径不全），且 README 使用的词汇恰好是代码中正在被淘汰的遗留词汇。
2. **文档治理缺位**：README 未声明 docs 库的权威层级，导致 `KP_MCP_Design.md` 这份含"先推叙事再掷骰 + AI 直写状态"恶性设计的文档与现行架构规范平级陈列，无任何"未按此实现"的隔离标注。
3. **验收闭环断裂**：30-任务包之后无新批次，60-验收报告自述"浏览器/真实供应商门禁未通过"；export.py、global_reset.py 无专属测试文件（其中 export.py 的测试文件被 50-平台文档声称已建但实际不存在），RagTestPage/AdminDashboard 无验收记录，TEST_COVERAGE.md 整体过期。

### 行动建议（按优先级）

**P0（本周）**
1. 在 README 3.2/3.3 修正行动状态机为代码权威版本（`action_state.py` 14 状态），或明确标注"简化视图，权威定义见 action_state.py"；全局将 `resolved` 标注为遗留状态。
2. 在 `KP_MCP_Design.md` 文首加"⚠️ 候选设计，§4.1 流程未按此实现；现行链路以 README 3.2 + 00-产品规范为准"的隔离声明；同步在 docs/README.md 推荐阅读顺序中降级该文档。
3. 为 `export.py`、`global_reset.py` 补专属测试（或删除 50-平台回执中"已新增 test_export.py"的不实声明并登记债务）；核实 export public 口径的 `audience != 'player'` 过滤是否仍为 P0 风险。

**P1（下个迭代）**
4. 修正 README：`host_exception`→`awaiting_host_exception`（并注明它是 resolution_route/状态/事件三层中的哪层）、补 0.75 阈值、audience 补 `system`、docs 树补 5 个漏列项、补 `src/client/src/shared/` 目录。
5. 修复或登记 RAG 文档 P0-1/P0-6：`rag_context.py:64` 的 `audience="ai"` 无过滤、`:96` 仍读 `xlsx_data`；在 README 3.5 权威表加"AI 读出口现状"附注。
6. 重写 TEST_COVERAGE.md（当前 SQLite 口径完全过期）或标注废弃，以 COMPLETION_AUDIT 的 1194 passed 为现行基线，并保留"浏览器/真实供应商门禁未通过"的显著提示。

**P2（持续）**
7. 补四类文档：API 参考（含 WS 事件注册表）、核心表 schema、运维手册（健康检查/测试纪律/备份恢复）、安全设计（令牌矩阵 + AI 不信任边界 + 未修项清单）。
8. 为 30-任务包追加 Batch-6+（v2 行动链、战斗轮、迁移重置、单人冒险、协同合同的正式任务化），改变"验收报告事后追认"的模式。
9. 术语统一工程：`canceled/cancelled`、`stateVersion/state_version` 分层约定、visibility 枚举平台化。

---

*评审完毕。本报告所有条目均可按所附文件/行号复核。*
