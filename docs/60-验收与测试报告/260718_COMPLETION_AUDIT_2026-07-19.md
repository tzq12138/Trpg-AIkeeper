# 260718 目标逐项完成审计（2026-07-19）

## 审计范围

本记录逐项核对 `G:\hermes-agent-workplace\D&D\CodeX-aikeeper\docs\260718` 的五份源文档：

1. `AIKP 接收玩家行动、通过 Engine 裁决并在 Host 展出的完整协议.md`
2. `AIKP玩家行动编排与Host演出系统_PRD_V1.0.md`
3. `AIKP_主持运行时_阶段测试报告_2026-07-19.md`
4. `AI_Keeper_UI_Brainstorm_Round1.md`
5. `AI_Keeper_UI_Brainstorm_Round2_Combat.md`

“已验证”只表示本次运行了对应自动化；它不替代真实浏览器、多人或真实供应商验收。

## P0 行动协议

| 原文要求 | 当前证据 | 结论 |
| --- | --- | --- |
| `PlayerActionEnvelope`、唯一 action ID、token 反查角色、即时 received 回执与幂等 | `router_actions_v2.py`、`player_action_submissions`；`test_action_drafts_v2.py` | 已有自动化证据 |
| 明确输入模式，讨论/OOC/规则问题/私密笔记不进入 Rule 或 State | `PlayerActionComposer.tsx`、`router_actions_v2.py`；`test_action_drafts_v2.py` | 已有自动化证据 |
| Intent 只建议、确认分级、歧义不自动执行 | `action_service.py`、草稿状态机；`test_action_drafts_v2.py` | 已有自动化证据 |
| RuleExecutor 使用服务器权威角色和物品，AI/客户端骰点不成为权威 | `resolution_pipeline.py`、`rule_executor.py`；`test_coc7_core_rules.py` | 已有自动化证据 |
| State-first、统一 `ResolutionBundle`、公共/私密投影隔离 | `resolution_pipeline.py`、`spoiler_guard.py`；`test_action_lifecycle_v2.py`、`test_resolution_pipeline.py` | 已有自动化证据 |
| Host ACK 只推进演出，不触发规则或状态写入 | `router_host.py`、`host_store.py`；`test_host.py` | 已有自动化证据 |
| 重连、投影失败重放与 AI fallback | `router_reconnect.py`、`replay_projection()`；`test_reconnect.py`、`test_resolution_pipeline.py`、`test_narrator_runtime.py` | 已有自动化证据 |

## P1 与公共舞台补齐

| 原文要求 | 当前状态 | 验证边界 |
| --- | --- | --- |
| Host Public Stage 可播放、暂停、下一步、跳过连续视觉步骤、重放演出；ACK 仅代表播放进度 | `HostStore.presentation_*`、`/presentation/play|pause|next|skip-visual|replay`、`HostPresentationControls` 已落地。`next` 只推进持久化游标；`skip-visual` 只能跳过连续 `scene_transition`，并逐个按原始 `step_id` 放行已保存的玩家投影；二者都不调用 AI、RuleExecutor 或 StateService。 | 自动化已验证；尚未进行真实浏览器交互。 |
| 公共舞台只能播放公开结果 | `/stage-presentation` 仅从 `release_status='released'` 的 `resolution_bundles.stage_projection` 读取 `narrativeText`；Host 原交易 payload、骰点、行动 ID、Host Console 内容不进入 DTO。 | 自动化已验证；尚未进行真实浏览器投影验收。 |
| 规则参数错误时可复用原骰重算 | 新增 `/action-reviews/{review_request_id}/recalculate`。首期只支持已完成 CoC7 `skill_check` 的 `regular/hard/extreme` 难度修正；HMAC 回执、规则集、原始 trace 和 d100 候选值均须验证。 | 自动化已验证；重算只建立审计补偿事务，不自动改写原 action、结果包或世界状态。 |
| 玩家复核、Host Review、补偿事务且不删历史 | `router_action_reviews.py` 返回白名单 `HostReviewPacket`：原始行动、意图契约、Director/规则计划、状态差异与 citation；`compensation_service.py` 保留补偿审计。HMAC 签名与完整 `rule_explanation` 不进入 REST DTO；`test_action_reviews_v2.py` 覆盖。 | 已有自动化证据；需在真实房间演练。 |
| Host 计划离线与意外离线的保守自治 | `host_autonomy_policy` 具有 `host_required`（默认）、`conservative`、`delegated` 三档；`ResolutionPipeline` 仅在 Host 未连接且策略白名单允许时继续。委托模式仅放行公开、可验证的普通检定、已揭示范围移动、普通物品使用与低风险对话；战斗、秘密行动、幸运/孤注一掷及任何高风险行动统一进入 `awaiting_host_exception`。 | 自动化已验证；尚未进行 Host 断线、重连与多人浏览器演练。 |
| 替代技能协商 | AI 草稿可给出最多两项 `alternative_skills`；确认卡要求玩家从“建议技能 + 候选技能”中显式选择。`confirm_action_draft()` 只接受已保存分析中的白名单，缺选或自填技能返回 `skill_selection_required` / `skill_selection_invalid`；选择写入正式 action 的 `skillName` 后才进入规则引擎。 | 自动化已验证；尚未在真实供应商与浏览器中验证候选质量。 |

## UI 与战斗设计

| 来源 | 当前状态 | 未证明项 |
| --- | --- | --- |
| UI Round 1：玩家当前事项、显式输入模式、手机导航、私密资料与转移 | 已有 `PlayerActionPage.tsx`、`PlayerTerminal.tsx`、`PlayerInventory.tsx` 和对应组件测试。 | 360/390/430px 真实视口、双玩家私密投影、资料抽屉与通知不打断编辑。 |
| UI Round 1：公共舞台只展示公开场景、简化状态、目标、时间和近期事件 | `HostStage.tsx`、`public_stage.py`；`test_host.py`、`host-stage.test.ts`。 | 真实舞台播放流程及控制交互。 |
| UI Round 2：整轮声明、锁定、DEX 排序、轮末安全摘要、缺席策略 | `combat_round_planner.py`、`turn_manager.py`、`turn_timeout_worker.py`；战斗与叙事测试。 | 四玩家协作/冲突、超时、重连、弱网和真实 AI 的浏览器验收。 |

## 本次自动化证据

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py tests/server/test_host.py tests/server/test_narrator_runtime.py tests/server/test_coc7_core_rules.py tests/server/test_action_reviews_v2.py -q` | 189 passed，178.71s |
| `cd src/client && npm run test -- --run tests/host-stage.test.ts tests/player-action-composer.test.tsx tests/player-input-modes.test.ts tests/player-current-priority.test.ts tests/combat-round-lock.test.ts tests/combat-round-summary.test.ts tests/player-terminal.test.tsx` | 7 files / 32 tests passed |
| `cd src/client && npm run test -- --run` | 39 files / 123 tests passed |
| `cd src/client && npm run build` | TypeScript 检查与 Vite 构建通过 |
| `python -m pytest tests/server/test_host.py tests/server/test_action_reviews_v2.py tests/server/test_coc7_core_rules.py tests/server/test_action_lifecycle_v2.py -q` | 96 passed，88.08s；覆盖安全演出、公开投影、原骰重算、签名拒绝与 CoC7/生命周期回归 |
| `python -m pytest tests/server/test_multiplayer_loop.py tests/server/test_reconnect.py tests/server/test_turn_manager.py tests/server/test_turn_timeout_worker.py -q` | 25 passed，22.71s；覆盖多人循环、重连、回合锁定与超时 worker 自动化路径 |
| `python -m pytest tests/server/test_host.py tests/server/test_action_reviews_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py -q` | 100 passed，94.46s；覆盖视觉跳过逐步释放、复核包脱敏、演出/行动/重连回归 |
| `python -m pytest tests/server/test_host_autonomy.py tests/server/test_events.py tests/server/test_player_action_settings_v2.py tests/server/test_player_experience_v2_schema.py tests/server/test_action_lifecycle_v2.py -q` | 51 passed，74.81s；覆盖离线策略白名单、异常入队、玩家延后事件、房间设置与生命周期回归 |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_configured_openai_provider.py -q` | 75 passed，102.29s；覆盖替代技能候选、选择白名单、确认入账与既有行动/供应商回归 |
| `cd src/client && npm run test -- --run` | 40 files / 128 tests passed |
| `cd src/client && npm run build` | TypeScript 检查与 Vite 构建通过 |
| `git diff --check` | 通过；仅报告既有工作树的 LF/CRLF 转换警告，无空白错误 |

此前的全量自动化记录继续保留在 `260718_RUNTIME_ACCEPTANCE_2026-07-19.md`：后端 1068 项以无重叠批次通过、前端 123 项通过、前端构建通过；单进程后端全量命令因运行时间超时，没有作为全量通过依据。

## 仍未完成的目标验证

阶段测试报告要求的单人完整流程、1 Host + 4 玩家、投影恢复、遭遇快捷动作、图文供应商与文本备用供应商浏览器验收尚未在本次继续工作中执行。此前限制不使用浏览器，因此本审计不将这些场景标记为已验收。

公共舞台控制与原骰重算已补齐；下一轮仍需要执行上述浏览器验收，并按源文档的 25 项核心验收逐项记录截图、事件序列、citation 与失败恢复证据。

## 本轮补充：组合行动与前序结果条件（自动化）

1. **确认契约**：AI 可起草最多两步 `composite_steps`；每一步包含玩家可读摘要、意图、受限参数与稳定 `step_id`。确认卡明确显示“同一回合，仅消耗一次行动”，支持在提交前调整两步顺序。确认接口只接受草稿中的两个 ID，非法顺序返回 `composite_order_invalid`。
2. **条件语义**：第二步的确定性条件是前一步的已提交规则结果。第一步失败后，策略可为 `cancel`（取消第二步）、`ask`（进入 `awaiting_player_choice`）或 `continue`（继续结算）；第一步成功则进入第二步。这个实现覆盖“前序结果条件”，不把尚未发生的外部事件伪装成已实现的准备动作。
3. **暂停与恢复**：`ask` 仅在第一阶段没有待提交状态 mutation 时允许自动暂停；否则安全地转入 Host 异常处理。暂停时保留第一阶段权威结果和待续步骤；玩家调用 `POST /api/player/actions/{action_id}/composite-choice` 后，只恢复第二步，第一步不会重掷或重放。
4. **权威边界**：每一步仍经 `MechanicCompiler` 与 `RuleExecutor`；AI 只能提供草稿。合并结果保留阶段状态，最终仍由同一 action、同一 `ResolutionBundle` 和 StateService 提交。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py tests/server/test_turn_manager.py tests/server/test_host_autonomy.py -q` | 102 passed，156.05s | 两步限制、确认顺序、失败取消、失败继续、等待玩家选择、恢复不重放第一步及现有行动/回合/重连回归 |
| `cd src/client && npm run test -- --run` | 40 files / 130 tests passed | 组合确认卡、顺序调整、失败续接卡与现有前端回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |

## 本轮补充：Host 遭遇救火 API 的理由与审计（自动化）

`POST /encounter/next-round`、`POST /encounter/resolve` 和 `POST /encounter/npc` 不再是无痕的常规控制路径。它们均要求非空 `reason`，并把操作、遭遇 ID、理由、Host 账号标识和目标 ID（如有）写为 `host_encounter_intervention` 系统事件；该事件不会进入玩家投影。Host 专用遭遇事件的数据库时间字段也统一转为 ISO 文本，避免后台投影任务序列化失败。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py -k 'manual_combat_advance_requires_reason_and_writes_audit or other_manual_encounter_operations_require_reason_and_write_audit' -q` | 2 passed | 三类救火接口拒绝无理由调用并写入系统审计 |
| `python -m pytest tests/server/test_host.py -q` | 62 passed，50.94s | Host 授权、公共舞台、救火投影及审计回归 |

## 本轮补充：玩家战斗输入回归自然语言（自动化）

遭遇开始和更新事件不再生成“攻击、闪避、防御、协助、逃跑”等会直接提交动作的常驻按钮；玩家只通过自然语言输入编写本轮声明，并由现有确认链处理。`s2c_tactical_prompt` 仍可显示临时按钮，但页面明确标注为“规则决定”，只用于规则已经要求玩家做出明确选择的场景；单人遭遇反应卡同样属于这个例外。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `cd src/client && npm run test -- --run` | 41 files / 135 tests passed | 玩家输入模式、战斗锁定、Host 只读遭遇面板与既有前端回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |
| `git diff --check` | passed | 无空白错误；仅有既有工作树的 LF/CRLF 转换警告 |

本段未重新打开浏览器，也未调用真实供应商；多人组合冲突、公共舞台阶段展示与真实模型拆分质量仍需要在允许浏览器操作时验收。

## 本轮补充：Director 主链与战斗锁定投影（自动化）

1. **真实 Director 链路**：`DirectorPlanDTO` 现在以严格的 `action_steps` 契约承接最多两步组合行动；`apply_director_plan()` 仍会经草稿参数白名单清洗，才交给确认和规则引擎。动态供应商返回的步骤不再只在旧行动分析降级链路中生效。
2. **超过两步的保护**：供应商若返回三步以上，网关不会静默截断或变成三次行动；它改为 `requires_player_clarification`，给出最多三项玩家可读的“主要事项”选项。玩家页明确提示“保留并重新分析”，选项只写回输入框并删除旧草稿，绝不自动确认或执行。
3. **战斗锁定阶段**：`combat_round_planner` 为公开声明生成与行动原文、目标、顺序无关的表面准备动作；私密行动不生成条目。该白名单同时进入 `s2c_combat_round_locked`、`GET /api/player/combat-round` 与玩家战斗卡，显示为“可观察到的准备”。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_ai_gateway.py tests/server/test_director_runtime.py tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py tests/server/test_turn_manager.py tests/server/test_combat_round_planner.py tests/server/test_narrator_runtime.py tests/server/test_host_autonomy.py -q` | 209 passed，262.57s | Director 两步契约、三步澄清、组合恢复、规则执行、回合锁定、安全公开准备动作与叙事回归 |
| `cd src/client && npm run test -- --run` | 40 files / 131 tests passed | 组合确认、主要事项澄清卡、玩家主界面及既有前端回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |
| `git diff --check` | passed | 无空白错误；仅有既有工作树的 LF/CRLF 转换警告 |

上述仍是自动化证据；真实浏览器、四玩家、弱网和真实供应商验收没有在本轮执行。

## 本轮补充：IntentContract 与战斗 REST 投影（自动化）

1. **完整意图合同**：`IntentContractDTO` 已由本地动作分析生成，并在动态 Director 计划返回时经长度、可见性和幕后引用净化后进入草稿；字段固定为目标、方法、对象、约束、资源、条件、可见性与歧义。Host Review Packet 只读同一份净化合同，便于复核而不暴露 Director 原始提示或隐藏证据。
2. **高风险歧义保护**：只要高风险行动的实体指向仍不明确，草稿即进入 `player_clarification_required`，不提供确认，也不会进入确认或规则结算。玩家卡把“放弃草稿”改为“修改描述”，避免误导为可直接执行。
3. **锁定战斗 REST 白名单**：`GET /api/player/combat-round` 现在由测试确认仅返回字符串形式的 `observablePreparations`；内部对象、行动 ID、私密行动和隐藏数值不会随着锁定投影泄露。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_ai_gateway.py tests/server/test_director_runtime.py tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_action_reviews_v2.py -q` | 148 passed，210.84s | Director 意图合同、歧义澄清、组合行动、确认、生命周期和 Host 复核 |
| `python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py tests/server/test_turn_manager.py tests/server/test_combat_round_planner.py tests/server/test_narrator_runtime.py tests/server/test_host_autonomy.py -q` | 72 passed，78.90s | 规则提交、重连、战斗锁定 REST/规划器、叙事和离线自治 |
| `cd src/client && npm run test -- --run` | 40 files / 132 tests passed | 意图合同确认卡、输入模式、战斗摘要和既有前端回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |
| `git diff --check` | passed | 无空白错误；仅有既有工作树的 LF/CRLF 转换警告 |

这一批仍未解除“不得使用浏览器”的限制，故不把真实供应商、单人完整流程、四玩家、弱网或可视验收标为完成。

## 本轮补充：源文档重点分组复验（自动化）

全量 `pytest tests/server -q` 可正常收集 1096 项，但在本机由外层超时停止时，子进程没有随包装命令结束，仍会占用 `aikeeper_test`。随后并行的 fixture `TRUNCATE` 会产生 PostgreSQL 死锁，继而引出账号和场景 fixture 的连锁失败。清理残留的测试子进程后，同一分组不修改业务代码即全部通过，因此该现象记录为**本地测试进程清理边界**，不是功能回归。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py tests/server/test_coc7_core_rules.py tests/server/test_multiplayer_loop.py tests/server/test_spoiler_guard.py -q` | 107 passed，61.51s | 公共舞台、Host 演出/恢复、CoC7 权威规则、多人循环和防剧透 |
| `python -m pytest tests/server/test_scenario_review_workbench.py tests/server/test_scenario_asset_bindings.py -q` | 27 passed，21.13s | 审核草稿、citation、AI 配图建议、素材绑定和玩家安全素材投影 |

执行全量套件时应避免在包装器强制终止后立刻发起新的 PostgreSQL 测试；先确认没有 `python -m pytest tests/server -q` 子进程与 `aikeeper_test` 活跃会话，再使用无重叠分组策略。本说明不改变本项目的生产运行逻辑。

## 本轮补充：锁定战斗的角色对话边界（自动化）

`AI_Keeper_UI_Brainstorm_Round2_Combat.md` 要求结算期间允许队伍讨论，却不接受新的角色喊话。为避免“先记录、后在草稿链失败”的错误体验，`speech_routing='npc_dialogue'` 的新发言会在 `action-submissions` 入口检查已锁定的战斗轮，并以 `speech_round_locked` 拒绝；不创建提交记录、不广播事件。此前已接收的相同 action ID 仍返回原回执，保证网络重试的幂等性；`party_chat` 不受影响。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py -k 'speech or party_chat_remains_available_after_combat_lock' -q` | 5 passed，3.10s | 对话路由、锁定前后、幂等重试和锁定中的队伍讨论 |
| `python -m pytest tests/server/test_action_drafts_v2.py -q` | 56 passed，94.87s | 动作草稿、输入路由、锁定边界与既有确认/幂等回归 |

## 本轮补充：公共舞台实时战斗投影（自动化）

公共舞台新增可选 `combatRound`，仅在活动遭遇中返回。合同固定为 `roundNumber`、`phase`、`submittedCount`、`totalPlayers`，并且只在结算/阻塞阶段附带一个经白名单确认的 `currentConflict`。它不包含行动 ID、玩家提交顺序、目标、规则数值、私密冲突、隐藏敌人或操作按钮；玩家状态继续只显示文字伤势。前端归一化会再次丢弃任何额外字段，防止未来服务端 DTO 漂移直接泄露到舞台。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py -q` | 58 passed，41.35s | 公共舞台、Host 演出/恢复与实时战斗投影白名单 |
| `cd src/client && npm run test -- --run tests/host-stage.test.ts` | 12 passed | 前端实时战斗合同归一化与附加字段丢弃 |
| `cd src/client && npm run test -- --run` | 40 files / 133 tests passed | 全量前端回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |

仍缺真实 1 Host + 4 玩家浏览器演练，以及敌方“已观察单位”安全投影；这两个缺口不会由当前 `combatRound` 伪造填补。

## 本轮补充：Director 上下文按玩家可见性收窄（自动化）

Director 运行时原本直接携带完整 `rooms` 行和最近事件，可能将 `owner_token`、Host 异常或其他调查员的私密事件传递给供应商。现在上下文只保留房间 ID、剧本/版本、状态和权威状态版本；最近事件复用 `EventLog.get_events_for_player()` 的既有 audience/角色过滤，因此只包含队伍公开事件、当前角色私密事件与已白名单的系统事件。裁决器仍保留剧本的隐藏事实约束，不把它混同为玩家输入可见数据。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_director_runtime.py -k excludes_room_tokens_and_other_player_private_events -q` | 1 passed | 房主令牌、Host 事件与其他玩家私密事件不进入 Director 上下文；当前玩家和队伍事件保留 |
| `python -m pytest tests/server/test_director_runtime.py tests/server/test_channel_security.py -q` | 43 passed，67.77s | Director 运行时和重连/通道 audience 过滤回归 |

此项没有调用真实供应商或浏览器；它证明发送前的上下文合同，而非供应商侧日志或浏览器可视验收。

## 本轮补充：已观察战斗单位与队伍事件隔离（自动化）

遭遇参与者新增 `public_visibility`、`public_label` 和 `last_observed_position`。敌对/NPC 单位默认 `hidden`，只有显式 `visible` 才能显示安全名称、八格伤势条、伤势词和距离；`lost` 只保留安全名称与最后观察位置。精确 HP、最大 HP、角色/NPC ID、敏捷、武器、具体位置、状态标签和隐藏单位均不出现在玩家 REST、公共舞台或 party 事件。调查员始终使用同样的简化状态卡。

`s2c_encounter_started` 与 `s2c_encounter_updated` 已拆成两份投影：party 只拿到 `encounter` 的类型/状态/轮次和 `publicUnits`；Host 使用同一事件类型但专用 audience 获取完整参与者。Host WebSocket 只接受包含完整 `participants` 的载荷，因此异步到达的队伍投影不会覆盖导演台。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py tests/server/test_turn_manager.py tests/server/test_solo_adventure_runtime.py -q` | 147 passed，146.90s | 公共舞台与玩家 REST 单位白名单、轮次、黑熊遭遇和 Host 回归 |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_resolution_pipeline.py tests/server/test_channel_security.py -q` | 72 passed，91.03s | 行动入口、结算投影与通道权限回归 |
| `cd src/client && npm run test -- --run` | 40 files / 134 tests passed | 舞台单位字段归一化、前端既有回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |
| `git diff --check` | passed | 无空白错误；仅既有工作树的 LF/CRLF 警告 |

当前安全门槛已落地：已确认的伤害 mutation 才可将隐藏敌人公开为匿名身影；已观察敌方单位在规则距离结算进入 `escaped` 时写入 `lost` 和安全距离。距离更新本身不会暴露隐藏单位；浏览器和多人验收仍保持未完成。

## 本轮补充：Host 遭遇面板只读化（自动化）

进行中的 `EncounterPanel` 保留 Host 所需的完整监控信息，但不再提供“下一回合”“强制结束”或“快速创建 NPC”按钮。面板明确说明普通战斗由玩家声明、规则引擎和 AI-KP 自动推进；需要人工介入时应进入异常队列。后端兼容 API 尚未移除，下一批需要把它们收为带原因与审计的显式救火接口。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `cd src/client && npm run test -- --run tests/encounter-panel.test.tsx` | 1 passed | 进行中遭遇不渲染直接推进、强制结束或新增 NPC 控制 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |

## 本轮补充：战斗目标标签与通用可见性触发（自动化）

1. **目标标签**：玩家战斗页的“当前可见”单位可在声明阶段点击；点击只在本地输入草稿写入最多两个 `[本轮行动 · 目标：…]` 标签，不调用行动接口、不生成攻击/观察快捷按钮。标签可以撤销；提交后、结算中、只读设备或已声明时统一禁用。只有标签没有自然语言动作时，提交会被本地拦截。
2. **发现与失去踪迹**：规则结算只有在敌方实际受到非零伤害 mutation 时才把未公开单位提升为匿名 `敌对身影 N`；仅距离 mutation 不会泄露隐藏单位。已观察敌方单位的距离按规则进入 `escaped` 后，投影降为 `lost`，只保留此前的安全距离标签，不使用 `current_position`、NPC 真名或精确生命。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_solo_adventure_runtime.py -k "encounter_damage_mutation_updates_the_target_not_the_actor or observed_enemy_becomes_lost_after_rule_moves_it_out_of_sight" -q` | 2 passed | 命中显形、隐藏单位距离更新不泄露、失去踪迹安全投影和 Host/party 载荷隔离 |
| `cd src/client && npm run test -- --run tests/combat-target-tags.test.ts` | 3 passed | 最多两个标签、撤销保留自然语言草稿、任意方括号文本不误识别 |
| `cd src/client && npm run build` | passed | 标签交互的 TypeScript 与 Vite 构建 |

以上没有调用浏览器或真实供应商；目标标签的移动端点击与多玩家锁定表现仍需浏览器验收。

## 本轮补充：StateService 与遭遇 mutation 隔离（自动化）

`ResolutionPipeline` 现在只把 `/character/*` mutation 交给 `StateService`。遭遇参与者的伤害、距离和状态 mutation 仍由专用遭遇结算在完成回执后处理，并通过独立的安全遭遇投影发布。这样混合结算不会把 NPC 标识、遭遇路径或精确伤害值夹带进 `s2c_state_patch` 的队伍载荷。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_solo_adventure_runtime.py tests/server/test_host.py -q` | 153 passed，115.26s | 状态服务 mutation 白名单、遭遇显形/失踪、公共舞台和 Host 投影回归 |
| `cd src/client && npm run test -- --run` | 42 files / 138 tests passed | 目标标签、玩家行动与公共舞台前端回归 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |

此项为自动化安全合同验证；不替代真实多玩家投影和弱网浏览器验收。

## 本轮补充：分组回归汇总与已知非目标失败

为避免本机外层超时残留 `pytest` 子进程并锁住 `aikeeper_test`，本轮按领域串行执行了后端回归。下表记录的是实际执行结果；它不是对“浏览器、真实供应商和弱网验收”的替代声明。

| 分组 | 结果 | 说明 |
| --- | --- | --- |
| 动作、AI、Director、规则与战斗 | 276 passed，240.49s | 覆盖草稿、裁决、叙事、CoC7 与战斗主链。 |
| 认证、房间、玩家、频道与线索 | 152 passed，1 failed，277.24s | 唯一失败见下文；其余行为通过。 |
| 战役、Host、迁移与 V2 | 135 passed，158.27s | 覆盖 Host、归档、迁移与 V2 数据链。 |
| 多人、重连、回合、事件与投影 | 51 passed，50.05s | 覆盖多人循环、事件投影与重连。 |
| 动态供应商、MCP 与 embedding | 68 passed，6.55s | 覆盖供应商配置、回退链和 embedding 接口。 |
| 导入、审核、多模态与黄金样本 | 104 passed，93.43s | 覆盖审核台、素材绑定与导入链。 |
| RAG、防剧透与归档 | 109 passed，115.42s | 覆盖引用、防剧透边界与归档。 |
| 引擎、状态、数据库、结局与媒体 | 120 passed，48.60s | 覆盖规则状态提交、数据层和结局。 |
| `tests/server/test_player_features.py -k "not accepting_transfer_moves_requested_quantity_atomically"` | 11 passed，1 deselected，7.91s | 排除下述既有不稳定排序断言后，其余玩家资料回归通过。 |
| `cd src/client && npm run test -- --run` | 42 files / 138 tests passed | 包含战斗目标标签、只读 Host 遭遇面板与既有前端用例。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建通过。 |
| `git diff --check` | passed | 无空白错误；仅输出既有工作树的 LF/CRLF 转换警告。 |

唯一失败为 `tests/server/test_player_features.py::TestInventoryTransfers::test_accepting_transfer_moves_requested_quantity_atomically`。该测试的查询按随机 UUID 的 `character_id, id` 排序，却把固定“接收方在前、发送方在后”的数组作为断言；多次运行因随机 UUID 字典序不同得到不同顺序。功能原子转移本身不在本轮改动范围内，故没有为使套件变绿而改变生产代码或该既有测试。后续若要修复，应将断言改为按角色语义索引，或明确指定业务排序，而不是依赖随机 UUID 顺序。

截至本节，离线自动化、前端测试、构建和空白检查已完成；此前明确未使用浏览器，因此真实单人通关、1 Host + 4 玩家、移动端、弱网/重连、投影可视化及图文/文本真实供应商验收仍是本目标的未完成门禁。

## 本轮补充：公共舞台六人上限（自动化）

`AI_Keeper_UI_Brainstorm_Round1.md` 将公共舞台的调查员状态定义为 P0 最多六人。此前投影会完整遍历 `HostHUD.players`，异常上游数据可让舞台卡片超过该上限。现在服务端在建立公开投影时只保留顺序中的前六名，前端 `normalizePublicStage()` 也再次截断，避免单侧遗漏或不可信 REST 载荷破坏公共舞台布局；这不改变房间成员、战斗人数或 Host 控制台数据。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py -q` | 63 passed，46.62s | 公共投影安全字段与七人输入仅输出六张玩家卡。 |
| `cd src/client && npm run test -- --run tests/host-stage.test.ts` | 14 passed | 前端对异常七人 REST 载荷同样只保留前六张公开卡。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

## 本轮补充：队伍开放问题生命周期（自动化）

`AI_Keeper_UI_Brainstorm_Round1.md` 的开放问题不再只是一张 `fact_status='hypothesis'` 卡。`evidence_cards` 新增可重跑的 `question_status`、关闭人、关闭时间和撤销截止时间字段；仅 `card_type='question'` 且 `visibility='party'` 的问题走该链。玩家先读取关闭预览，查看关联的队伍假说/争议资料，再显式确认关闭；关闭不删除任何卡或关系，回流首页不再展示该问题。原关闭人在十秒内点击“撤销关闭”会得到撤销语义，超过窗口或其他玩家仍可“重新打开”；“已有解释”只有已关联至少一条队伍假说才可标记。AI 与 Host 的通用事实确认接口不会自动触发关闭。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_campaign_v2.py -q` | 37 passed，52.24s | 关闭预览、确认门禁、关闭后首页过滤、十秒内撤销、窗口外重开、关联假说门禁与跨房间拒绝。 |
| `cd src/client && npm run test -- --run tests/player-api.test.ts tests/campaign-home-panel.test.tsx` | 19 passed | 客户端预览/关闭/解释/重开请求合同，以及待调查和已关闭问题卡的操作互斥。 |
| `cd src/client && npm run test -- --run` | 43 files / 144 tests passed | 全量前端回归。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |
| `git diff --check` | passed | 无空白错误；仅既有工作树的 LF/CRLF 警告。 |

这项尚未在真实手机浏览器中点击验收；自动化已证明数据权限与状态合同，不替代可视交互验证。

## 本轮补充：当前事项的真实待办数量（自动化）

玩家首页的优先级合同新增 `getPlayerPendingTaskCount()`，只汇总已存在的危险反应、行动确认、待接收物品、进行中裁决和公开队伍问题。行动页与非行动页终端都保持“一件主事项”，仅在还有其他真实待办时显示“另有 N 项待处理”；普通输入草稿不会被算成待办，未接入的协同邀请、私密结果或线索也不会显示虚假数量。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `cd src/client && npm run test -- --run tests/player-current-priority.test.ts tests/player-terminal.test.tsx` | 10 passed | 待办来源计数、自由输入排除、非行动页主事项和“剩余 N 项”显示。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

## 本轮补充：重连事件隔离与未读结果（自动化）

`/api/player/reconnect` 的全量快照和增量路径均改为复用 `EventLog.get_events_for_player`：Party 事件、当前角色私密事件和白名单系统事件才会进入响应，Host 事件与其他角色私密事件不会进入 REST 重连载荷。这样与 WebSocket catch-up 使用同一可见性边界。

玩家当前事项现识别四类已过滤事件：私密通知、本人发现线索、队伍共享线索和待回应的协同行动合同。浏览器只保存每个房间的数值已读序号；事件正文留在内存或后端日志。私密结果优先于公共线索，点击后进入调查日志并确认已读；协同行动邀请由合同/参与者数据链提供，界面只展示回应入口，不伪造可执行世界行动。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_reconnect.py tests/server/test_channel_security.py -q` | 18 passed | 首次快照、增量重连、Host/他人私密事件隔离和 WebSocket 可见性合同。 |
| `cd src/client && npm run test -- --run tests/player-notifications.test.ts tests/player-current-priority.test.ts tests/player-terminal.test.tsx tests/player-context-rail.test.tsx` | 17 passed | 事件白名单、数值水位、优先级顺序、日志入口和移动端当前事项。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

## 本轮补充：玩家假说的私密原稿与队伍副本（自动化）

普通玩家证据卡现在默认私密；只有开放问题仍默认进入队伍协作域。普通卡若需要分享，玩家先编辑队伍可见标题与摘要，服务端才创建独立的 `party` 副本。原私密卡不会被更新、其他玩家不会看到它，且请求体不能直接用 `visibility='party'` 绕过副本链。关闭开放问题时，测试夹具也改为链接已分享的队伍假说，保持“问题依据必须公开可协作”的边界。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_campaign_v2.py -q` | 40 passed，85.37s | 默认私密、拒绝直接公开、编辑后独立队伍副本、跨玩家投影、问题关闭/重开/解释、链接与房间隔离。 |
| `cd src/client && npm run test -- --run tests/campaign-home-panel.test.tsx tests/player-api.test.ts` | 21 passed | 分享端点请求合同、可编辑副本表单和既有回流卡。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

这项是离线合同验收；大屏的六人排版和多设备可视效果仍应在解除浏览器限制后验收。

## 本轮补充：调查资料四段详情与关联私人笔记（自动化）

Round 1 §10 的资料详情已完成最小闭环：玩家从证据板按需打开资料后，可看到摘要、当前已知、相关资料与本人笔记四段。只有摘要默认展开；其余段落折叠并显示真实条数。详情接口只查询当前玩家可见的卡与关联卡；其他玩家私人卡、正文及其笔记都不会返回。

“加入笔记”通过专用接口在同一数据库事务中创建加密 `player_notes` 与 `evidence_references` 关联。详情只解密当前角色自己的关联笔记，既不共享给他人，也不送入 Director/AI 上下文。认知标签仅从已有事实状态与来源字段得出“已确认 / 已证伪 / 玩家推测 / 存在争议”，没有证据时不伪造“亲眼观察”或 “NPC 证词”。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_campaign_v2.py -q` | 50 passed | 四段 DTO、可见关联资料、他人私密资料过滤、加密笔记关联。 |
| `cd src/client && npm run test -- --run` | 44 files / 161 tests passed | 四段折叠、真实数量、玩家安全标签、详情请求与关联笔记请求合同。 |

该记录仍是离线自动化验收；此前明确未运行浏览器，因此移动端抽屉/全屏查看器、两名玩家实际点击及视觉布局仍待浏览器许可后验证。

## 本轮补充：统一结算包的玩家事务追溯（自动化）

已释放的 `ResolutionBundle` 继续作为玩家归档的唯一剧情来源。行动所有者现在能在完成回执看到 `transaction_id` 与权威 `state_version`；同一字段也安全进入自己的归档 bundle 条目，和 action、规则 citation 一同追溯。其他玩家的条目仍只有公开叙事，不会得到其私有结果、citation 或事务号。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_archive.py -q` | 15 passed | 已释放 bundle 聚合、所有者事务号、跨玩家结果/依据/事务号隔离。 |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py -q` | 84 passed | 行动确认、状态优先、规则执行和结果包回归。 |
| `cd src/client && npm run test -- --run tests/player-action-composer.test.tsx` | 12 passed | 完成回执展示事务号与状态版本。 |

测试数据库使用函数级 `TRUNCATE` fixture，必须串行执行后端组；并发执行会造成锁竞争，不能将该运行器问题误判为应用回归。

## 本轮补充：共享假说协作与人工状态（自动化）

共享副本不再是静态卡片：任意玩家可以关联支持、矛盾或相关资料，并为队伍共享的玩家假说写评论；关系类型只接受这三种语义，不能借 `vote_for` 等字段把推理退化为投票。假说状态只允许 `discussing`、`disproved`、`shelved`，必须由玩家点击确认；服务端不会暴露 AI 或 Host 的自动改写入口。状态变更会复用安全的 `s2c_public_observation` 事件，公共舞台仅在底部记录标题与状态，不改变场景或世界状态。状态操作者在十秒内可以撤销，其他玩家不能代替撤销。创建假说时还能选择当前可见资料，后端会在同一事务中校验权限、建卡和写入 `related` 关系；玩家界面只列出最近队伍资料，并明确不提示“正确证据”。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_campaign_v2.py -k "shared_hypothesis_status or hypothesis_status_rejects or create_private_hypothesis_with_optional" -q` | 3 passed | 状态更新、十秒撤销、操作者限制、私密卡拒绝、舞台事件及原子创建关联。 |
| `cd src/client && npm run test -- --run tests/campaign-home-panel.test.tsx tests/player-api.test.ts` | 26 passed | 共享评论、关系语义、状态控件、撤销入口和公开关联资料选择。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

AI 依据已确认事实提出“可能证伪”但不改写状态的建议已接入：建议只读取关联且已确认的队伍卡，模型返回的事实 ID 会在网关和路由两次过滤；用户点击“填入已证伪”只更新本地选择，仍需点击“更新状态”才会写入。真实双玩家、公共舞台和手机可视验收仍未执行。

## 本轮补充：AI 可能证伪建议（自动化）

动态 AI 链新增 `suggest_hypothesis_disproof` 的结构化只读任务。它只把一张队伍共享玩家假说和与之关联的、已确认且队伍可见的事实发给供应商；模型只能返回 `possible_disproved` 或无建议，且 `factIds` 必须属于给定事实集合。路由即使面对绕过网关的实现也会二次过滤 ID，并只返回“需要玩家确认”的建议对象。没有关联已确认事实时不调用 AI；所有路径都不更新 `evidence_cards.hypothesis_status`。客户端将建议显示为只读卡，只能把“已证伪”填入状态选择，实际写入仍走既有玩家确认与十秒撤销链。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_ai_gateway.py -k "hypothesis_disproof_suggestion" -q` | 1 passed | 动态供应商任务、结构化响应和越界事实 ID 过滤。 |
| `python -m pytest tests/server/test_campaign_v2.py -k "ai_disproof_suggestion" -q` | 2 passed | 关联已确认事实筛选、只读建议、路由二次过滤与无事实不调用。 |
| `cd src/client && npm run test -- --run tests/player-api.test.ts tests/campaign-home-panel.test.tsx` | 28 passed | 建议请求、只读提示、公开依据名称与预填而非自动提交。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

## 本轮补充：玩家资料抽屉的待处理与最近发生（自动化）

`AI_Keeper_UI_Brainstorm_Round1.md` 要求手机端统一底部抽屉保留当前页面上下文，并在“待处理 / 最近发生”之间切换。行动页原有资料抽屉只有角色数值和跳转链接，且移动端高度限制为 `52dvh`。现在它接收当前角色已可见的最高优先事项和叙事流：待处理卡仅展示已有优先事项及其安全跳转；最近发生只显示最后五条当前玩家已可见事件。移动端抽屉上限改为 `min(70dvh, 560px)`，两个 tabpanel 保留在 DOM 中但仅展示选中的视图，避免切换丢失当前上下文。该变更不读取 Host、其他玩家私密事件或未确认世界状态。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `cd src/client && npm run test -- --run tests/player-context-rail.test.tsx` | 2 passed | 待处理跳转、当前玩家可见事件、五条上限和无待办空态。 |
| `cd src/client && npm run test -- --run` | 43 files / 141 tests passed | 全量前端回归。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

其他私密结果和线索待办尚没有统一的优先级来源，故该需求仍保留“部分实现”状态；协同行动邀请已进入统一优先级，但该抽屉不以占位消息伪造其余待办。

## 本轮补充：房间固定运行包快照（自动化）

`runtime_package_versions` 原本已经以递增版本保存编译结果，但房间只绑定剧本版本，Director、Narrator 与规则推进会在运行时读取同一剧本的“最新 ready 包”。这会让已经开团的房间在管理员重编译后悄然改变可用场景、线索依赖或结局判断。

现在 `rooms.runtime_package_version_id` 在新建房间、从剧本直接开房，以及两条大厅剧本切换路径中与 `scenario_version_id` 一起写入。Director、Narrator、通用场景推进、命名线索和结局判断优先读取该固定 ID；重新编译只会生成新包，不能改变已绑定房间。迁移对已有空绑定房间按当时最新 ready 包一次性补写快照；没有可用包的历史数据才保留兼容回退，避免无故阻断旧房恢复。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_rooms.py -q` | 23 passed，23.39s | 主开房、从剧本开房、专用切换和通用更新切换均绑定目标最新 ready 包。 |
| `python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py tests/server/test_resolution_pipeline.py -q` | 105 passed，154.09s | 固定包建房、Director 固定包上下文、Narrator 与规则推进、开局场景回归。 |

这项仍需要在浏览器中验证“旧房保持旧包、新房使用重编译包”的可视流程；本节只证明数据库与运行时合同。

## 本轮复核：客户端行动信封与重连续传（自动化）

`player_action_submissions` 已经是状态型输入的先持久化边界：服务器加密保存 `rawText`、输入模式、客户端动作 ID、序列号与状态版本，再允许进入分析。相同 action ID 与相同内容只返回已有接收结果；同一 ID 改写内容会被拒绝。重连仅解密并返回当前角色尚未完成的状态型输入，其他角色、队伍发言和私人笔记不会被混入待续行动。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_reconnect.py -q` | 70 passed，111.09s | 接收幂等、加密原文、模式隔离、原文匹配、锁定期边界、本人未完成输入恢复与跨玩家隔离。 |
| `cd src/client && npm run test -- --run tests/player-api.test.ts` | 19 passed | 前端请求保留动作 ID、原文、模式、序列、状态版本与设备标识；重连消费待续输入合同。 |

该项仍需在真实浏览器完成刷新、弱网、设备接管和重传可视验收；本节不以 API 测试替代这些场景。

## 本轮复核：Host ACK 与持久化演出（自动化）

Host 播放进度与世界权威状态保持分离。ACK / `presentation/next` 只在活动事务、完成步骤索引与持久化 `stepId` 全部匹配时释放已保存的玩家投影事件；事务不匹配、步骤伪造或越过当前进度均不会释放事件。播放、暂停、视觉步骤跳过与重放只更新 `host_states` 中的演出游标和版本，不调用 AI、规则引擎或 `StateService`，因此不能修改房间 `state_version`。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py -q` | 63 passed，35.87s | ACK 事务/步骤绑定、ReleaseGate、世界状态不变、延迟事件投递、播放/暂停/跳过/重放、持久化恢复与公开舞台安全投影。 |

仍需在真实浏览器确认 Host 控制台与公共舞台的播放节奏、断线恢复和双窗口显示；本节只验证服务端合同。

## 本轮补充：迁移包保留运行包快照（自动化）

房间迁移包的 `room.json` 已包含运行包版本；此前导入新房时未写回该字段，会使已迁移房间回到“按剧本版本取最新包”的漂移行为。现在导入会验证目标库中是否存在同一剧本且 `ready` 的运行包：存在则原样绑定，新房继续使用原快照；不存在则清空字段，避免写入悬空 ID，并保留旧数据兼容回退。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_room_migration_v2.py -q` | 6 passed，5.17s | ZIP 清单哈希、预检不写库、确认后新副本与 ID 重映射、令牌脱敏、全局重置门禁、可用快照保留与不可用快照回退。 |

私密笔记在迁移包中仍以密文保存；独立恢复密钥文件和完整恢复演练尚未在本轮取得证据，因此迁移/备份条目保持“部分实现”。

## 本轮补充：回流首页开放问题上限（自动化）

`AI_Keeper_UI_Brainstorm_Round1.md` 规定调查首页最多显示三条开放问题，并按队伍范围、最近更新排序，禁止 AI 按幕后重要程度重排。`campaign-home` 现只查询队伍可见且仍为 `hypothesis` 的问题，按 `updated_at DESC LIMIT 3` 返回；`CampaignUnresolvedQuestions` 仍对输入数组截断为前三项，防止代理或旧后端载荷绕过首页上限。该规则不自动关闭、证伪或解释问题，仍保留原有的事实权限边界。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_campaign_v2.py -q` | 33 passed，38.15s | 四条队伍问题按更新时间只返回最新三条。 |
| `cd src/client && npm run test -- --run tests/campaign-home-panel.test.tsx` | 4 passed | 前端异常四条输入也只渲染前三条。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建。 |

## 本轮补充：黄金样本套件可重复运行（离线验收）

`data/test_assets/六类黄金样本` 的实际目录包含 9 份模组，而不是名称中暗示的 6 份。黄金运行器现在会先在独立的 `aikeeper_golden_test` 数据库中重置剧本、账号、规则集、规则版本/文档和检索分片；此前第二次执行会保留 `golden-suite-coc7` 的唯一 slug 并返回 409，现已由回归测试覆盖。规则与分片被清理后，旧索引不会混入下一次验收。

同一套件还暴露了自动结算竞态的连接泄漏：竞争失败时 `_settle_turn_background()` 提前返回而未归还独占连接，9 个房间后恰好耗尽 10 个连接池配额。该函数现在在 `finally` 中归还动态连接；重跑的日志不再出现 `PoolError` 或 `ERROR`。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_golden_module_e2e.py -q` | 2 passed，1.62s | 正式路由导入/开房/动作/结局与规则支持数据重置。 |
| `python -m pytest tests/server/test_turn_timeout_worker.py -q` | 2 passed，1.10s | 回合竞争失败分支仍释放独占 PostgreSQL 连接。 |
| `python -m pytest tests/server/test_narrator_runtime.py -q` | 31 passed，22.61s | 自动结算的叙事与异常处理回归。 |
| `AIKEEPER_DEV_MODE=1 python scripts/run_golden_module_suite.py ...` | 9/9 模组完成，147.5s | 隔离 PostgreSQL、正式 FastAPI 路由、运行包、动作、房间结局、9 本规则书版本化索引、PDF/XLSX 角色卡解析。报告：`docs/loop_runs/2026-07-19-golden-module-suite-report.md`。 |

该结果使用确定性结构化/规则夹具，并不代表真实文本/图文供应商的召回或叙事质量；又因本轮仍未获浏览器许可，也不替代单人、4 玩家、移动端与弱网的可视验收。

## 本轮修正：组合行动不制造规则外中断（自动化）

Round 2 明确撤销“第一步失败后固定询问是否继续第二步”。组合行动仍是同一份声明、最多两个阶段；第二阶段由初始确认中已给出的 `cancel/continue` 策略及第一阶段的已提交结果决定，而不是在锁定回合中再向玩家发起一项规则外选择。

此前上游或历史动作可携带 `on_previous_failure=ask`，从而进入 `awaiting_player_choice`。现在草稿清洗会把该值降级为 `cancel`，执行层再次对历史持久化数据做相同归一化；第一阶段失败后第二阶段直接记录为 `canceled`，不会发送 `s2c_action_choice_requested`。旧选择端点保留，但对已自动结算的历史策略会返回 `composite_choice_not_pending`，不能绕过状态机。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_action_lifecycle_v2.py -q` | 29 passed，13.84s | 历史 `ask` 降级、失败后取消、无选择事件、选择端点拒绝绕过，以及既有两阶段规则执行。 |
| `python -m pytest tests/server/test_action_drafts_v2.py -k composite -q` | 1 passed，1.42s | 上游 AI 输出 `ask` 后，玩家草稿仍只暴露已清洗的 `cancel`。 |
| `python -m pytest tests/server/test_ai_gateway.py -k composite -q` | 1 passed，0.17s | AI 契约仍限制为最多两个主要步骤。 |

这不宣称跨玩家协作依赖或 Director 的第二阶段实时重编排已完成；它只消除了规格明确禁止的固定中途确认窗口。

## 本轮加固：组合阶段契约与供应商提示词一致（自动化）

上一项修复后，`ActionDraftStepDTO`、`DirectorActionStepDTO` 和两条 AI 提示词仍接受或提示 `ask`，会使供应商持续生成一个被执行层静默改写的过时语义。现在两个 DTO 只接受 `cancel/continue`；草稿分析和 Director 提示词也明确禁止回合中的“是否继续”询问。执行层仍兼容已经持久化的旧值，将其安全归一化为 `cancel`，所以历史动作不会卡在过时的选择状态。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_lifecycle_v2.py tests/server/test_action_drafts_v2.py -q` | 73 passed，104.80s | 两类 DTO 拒绝 `ask`、草稿净化、动作确认、历史动作降级与状态机回归。 |
| `python -m pytest tests/server/test_ai_gateway.py tests/server/test_configured_openai_provider.py -q` | 46 passed，2.07s | Director/叙事网关、供应商回退、Responses/Chat Completions 图文请求和配置提供商回归。 |
| `python -m pytest tests/server/test_multiplayer_loop.py tests/server/test_turn_manager.py tests/server/test_reconnect.py tests/server/test_channel_security.py tests/server/test_events.py -q` | 35 passed，38.28s | 多人声明、回合锁定、重连、事件去重与跨角色/Host 可见性隔离。 |
| `python -m pytest tests/server/test_campaign_v2.py tests/server/test_player_experience_v2_schema.py -q` | 55 passed，86.61s | 设备租约、回流数据结构、私密资料与队伍协作权限。 |

真实浏览器的四人战斗、弱网与设备接管仍是独立门禁；上述结果只证明服务端状态、权限和供应商无关契约。

## 本轮补充：重连规模与四人声明（自动化）

重连接口新增 1000 条队伍可见事件的回放验收：响应必须保持完整的 `last_sequence` 与 1000 条投影，并在服务端测量中不超过 3 秒。战斗回合新增四名调查员的同轮声明验收：前三名提交后不得锁定，第四名提交后才允许进入 `resolving`，计划顺序按遭遇 DEX 而非提交顺序生成。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_reconnect.py tests/server/test_turn_manager.py -q` | 26 passed，42.33s | 1000 事件重连、快照/增量可见性、未完成行动恢复、声明锁定、缺席策略与四人 DEX 规划。 |
| `git diff --check` | passed | 无空白错误；工作树既有 LF/CRLF 警告不影响结果。 |

这仍不是浏览器弱网压测：它验证的是同进程 FastAPI/数据库主链的容量与确定性，不代表前端渲染、WebSocket 延迟或真实设备网络。

## 本轮补充：八人回合规划压力（自动化）

在同一权威 `TurnManager` 中创建 8 名已就绪调查员、8 份战斗声明和 8 个遭遇参与者。只有全员声明后才允许锁定；规划器必须保留 8 个规则步骤和 8 个公开冲突簇，并在 500ms 的非 AI 接口目标内完成。该测试不调用 Director、Narrator、网络或浏览器，因此不把模型时延或客户端渲染混入规则层性能数据。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_turn_manager.py -k eight_player_combat_round_plans_within_non_ai_latency_target -q` | 1 passed，0.67s | 八人声明、全员锁定、规则步骤/公开簇完整性与非 AI 规划延迟。 |

## 本轮环境复核

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python dev.py --check` | Overall: ok | PostgreSQL、embedding、RAG、编译器、Redis 配置、MCP/DeepSeek/本地回退链均可用；Vite 前端在 `:5173` 响应。 |

这只验证本地依赖可达和服务健康，不替代真实供应商调用，也没有执行浏览器交互。

## 导入、检索、规则与迁移独立回归

为避免共享数据库夹具互锁，本轮按功能域独立串行执行；首次合并命令超时不作为测试失败，拆分后每个实际套件均完成。

| 功能域 | 命令 | 结果 | 说明 |
| --- | --- | --- | --- |
| 导入工作流 | `python -m pytest tests/server/test_scenario_import_workflow.py -q` | 16 passed，24.17s | 多模态导入、审核、发布、版本重编译、失败/可重试任务、可执行图与《向火独行》绑定房间。 |
| 导入边界与素材 | `python -m pytest tests/server/test_scenario_import_limits.py tests/server/test_golden_supporting_assets.py -q`；`python -m pytest tests/server/test_scenario_asset_bindings.py -q` | 13 passed | 文件大小上限、规则资料版本化入库、素材实体绑定和玩家安全素材投影。 |
| 版本化 RAG | `python -m pytest tests/server/test_rag_versioning.py tests/server/test_rag_security.py tests/server/test_rag_search.py tests/server/test_rag_router.py tests/server/test_rag_context.py tests/server/test_rag.py -q` | 52 passed，40.87s | 版本、权限过滤、检索、路由、上下文和 citation 链。 |
| CoC7 规则 | `python -m pytest tests/server/test_rules.py tests/server/test_coc7_core_rules.py -q` | 47 passed，0.27s | 规则集/规则文档和 CoC7 核心确定性规则。 |
| 房间、迁移与自治 | `python -m pytest tests/server/test_room_migration_v2.py tests/server/test_campaign.py tests/server/test_host_room_lifecycle.py tests/server/test_host_autonomy.py -q` | 40 passed，80.68s | 运行包迁移、战役数据、房间生命周期和 Host 离线自治。 |

上述 168 项与此前行动、战斗、重连、叙事和黄金样本回归互补；浏览器交互和真实供应商质量仍需在用户允许后单列验收。

## 舞台 ACK、防剧透与切换安全回归

| 功能域 | 命令 | 结果 | 覆盖 |
| --- | --- | --- | --- |
| Host 舞台 | `python -m pytest tests/server/test_host.py -q` | 63 passed，50.77s | ACK 绑定事务和步骤、ReleaseGate 延迟事件、仅演出不改世界状态、公开舞台与控制台隔离、重放不重复结算。 |
| 防剧透与投影 | `python -m pytest tests/server/test_spoiler_guard.py tests/server/test_projection.py tests/server/test_content_projection.py -q` | 33 passed，30.07s | 玩家/队伍/Host 投影分离、解锁边界、叙事重试与安全回退。 |
| V2 切换与归档 | `python -m pytest tests/server/test_v2_cutover.py tests/server/test_archive.py -q` | 19 passed，24.59s | 先校验 SHA-256 备份再清理、失败不清理、归档和恢复入口的隔离。 |

主协议的 `HostAckDTO` 要求已经由 `transactionId`、`stepId` 与 `stepIndex` 在服务端验证；其消息体不会被作为规则、状态或玩家私密内容的写入入口。

## AI 运行时与供应商回退回归

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_ai_gateway.py tests/server/test_configured_openai_provider.py tests/server/test_ai_routes.py tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py -q` | 118 passed，109.85s | 动态配置供应商、协议转换、敏感信息脱敏、失败回退、结构化 Director 计划、固定运行包上下文与 Narrator 只演绎已验证结果。 |

该套件使用确定性假供应商，不发送真实密钥或调用外部模型；真实文本/图文供应商的质量、超时呈现及浏览器阶段反馈仍须单列验收。

## 复核、补偿与事件审计回归

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_reviews_v2.py -q` | 9 passed，5.50s | 玩家申诉、Host 只读复核包、原骰重算、白名单补偿、并发补偿幂等和审计。 |
| `python -m pytest tests/server/test_state_service_consistency.py tests/server/test_events.py tests/server/test_channel_security.py -q` | 15 passed，10.29s | StateService 提交一致性、事件序列、频道身份隔离及安全写入边界。 |

## PRD P0/P1 功能需求追溯

下表仅证明服务端自动化合同；涉及视觉呈现、触屏可用性、真实供应商语义质量的项目仍不能据此宣称浏览器验收完成。

| 条目 | 当前自动化证据 | 结论 |
| --- | --- | --- |
| PAO-FR-1 | `test_action_drafts_v2.py::test_action_submission_is_received_before_ai_analysis_and_is_idempotent` | action ID 接收与幂等已覆盖。 |
| PAO-FR-2 | `test_action_drafts_v2.py` 的缺 token、跨角色、确认和取消用例 | 仅由玩家 token 反查角色链路已覆盖。 |
| PAO-FR-3 | `test_action_drafts_v2.py::test_confirming_stale_draft_requires_sync_and_creates_no_action` | base state version 冲突不会入账。 |
| PAO-FR-4/5 | `test_action_drafts_v2.py::test_action_submission_is_received_before_ai_analysis_and_is_idempotent` | 先回执、重复提交不重复执行。 |
| PAO-FR-6 | `test_action_drafts_v2.py` 的 speech、party chat、OOC、rule question、private note、safety 用例 | 输入模式隔离且不错误写入 action。 |
| PAO-FR-7/8/9 | `test_action_drafts_v2.py` 的完整 IntentContract、高风险确认与歧义澄清用例 | 意图合同、确认与高影响歧义门禁已覆盖。 |
| PAO-FR-10 | `test_action_drafts_v2.py::test_ai_analysis_failure_keeps_local_host_exception_fallback`；`test_ai_gateway.py` | AI 故障走结构化本地/Host 降级。 |
| PAO-FR-11/12/13/14 | `test_resolution_pipeline.py`、`test_action_lifecycle_v2.py`、`test_action_reviews_v2.py` | 规则路由只读取服务器权威值，拒绝客户端骰值和未校验 AI 机制建议。 |
| PAO-FR-15/16/17 | `test_action_lifecycle_v2.py::test_v2_pipeline_does_not_complete_or_project_when_state_persistence_fails`；`test_projection.py` | 成功提交后才投影，投影从统一结算包派生且公私分离。 |
| PAO-FR-18/19/20 | `test_host.py`、`test_content_projection.py` | Host Reveal 不含玩家私密 patch，舞台/控制台 DTO 分离，ACK 仅推进演出。 |
| PAO-FR-21/27 | `test_action_lifecycle_v2.py::test_v2_pipeline_records_completed_timeline_and_verifiable_rule_receipt`；`test_events.py` | action、transaction、state version、sequence 可追溯。 |
| PAO-FR-22 | `test_reconnect.py` 的 pending、非终态 V2 action 与可见事件用例 | 玩家重连恢复本人可见的行动和事件。 |
| PAO-FR-23 | `test_host.py` 的持久化演出、已播放步骤与 replay 用例 | Host 重连/重放不重复播放已确认步骤。 |
| PAO-FR-24/25/26 | `test_action_reviews_v2.py` | 申诉、原骰重算、补偿事务均走可审计服务层，不能删除历史。 |

## 当前前端回归

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `cd src/client && npm run test -- --run` | 45 files，164 tests passed | 玩家行动、输入模式、协同行动邀请、重连、地图、战斗、房主舞台、审核台、后台验收与重置工作流的组件/合同回归。 |
| `cd src/client && npm run build` | passed | TypeScript 检查与 Vite 生产构建。 |

## 待授权的浏览器与真实供应商验收

已将源文档的 25 条核心断言、单人、四玩家、Host ACK/恢复、主/备供应商、图文导入和 360/390/430px 视口整理为可复跑手册：`docs/260718_BROWSER_PROVIDER_ACCEPTANCE_RUNBOOK_2026-07-19.md`。手册现逐条标出“自动化通过；浏览器未验收”或“部分通过”，明确区分离线合同证据与真实浏览器/供应商验收；四人全流程、主备切换、弱网和移动视口仍未通过外部门禁。

## 协同行动合同与 MIMO 浏览器验收（部分完成）

协同行动已收敛为一项明确的人类同意合同：发起人邀请 1--3 名同房间队友，以共同意图建立待回应合同；任一拒绝、取消或超时都不会创建草稿；仅全员明确接受后才为每名参与者创建各自的高风险待确认草稿。该步骤不会创建 `actions`，也不会自动执行或结算。玩家页面将邀请加入当前事项，并提供单独的“接受 / 拒绝 / 取消邀请”入口。

| 证据 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_collaboration_contracts.py -q` | 7 passed，15.99s | 全员接受才产生关联草稿、拒绝/取消/超时、加入前行动冲突、四玩家参与者投影隔离与公共舞台不泄露共同意图。 |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py -q` | 87 passed，120.93s | 现有草稿持久化、确认、取消、状态机和规则结算未因合同草稿复用而回归。 |
| `cd src/client && npm run test -- --run` | 45 files，164 tests passed | 协同邀请组件、API 请求边界、玩家当前事项，以及既有前端组件合同。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 生产构建。 |

## 准备动作规则事件回归（2026-07-20）

玩家确认的准备动作现进入 `armed`，只由规则引擎产生的公开事件触发；AI、Host 和客户端均不能直接执行。黑熊遭遇的公开攻击声明已作为首个真实事件源。`protect_ally` 必须在确认时指定同房角色，内部规则行动保留该目标；刷新会恢复 `armed` 状态但不阻止新的普通行动。取消、完成、拒绝和超时都有独立审计终态。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_reconnect.py tests/server/test_prepared_rule_actions.py -q` | 26 passed | 重连恢复、唯一触发、伪事件拒绝、取消、盟友目标与拒绝收口。 |
| `python -m pytest tests/server -q` | 1184 passed，1394.58s | 全量后端回归。API 测试夹具现清理全局假供应商，防止跨文件污染行动分析。 |
| `cd src/client && npm run test -- --run` | 45 files / 167 tests passed | `armed` 的玩家状态显示与完整前端合同回归。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 生产构建。 |

仍未把旧浏览器会话当作本轮证据：后端重启后，需要以两名玩家验收布防、刷新、公开攻击触发、内部规则结算和可见性。其余白名单事件（进入近战、盟友受伤、遭遇开始）尚未绑定到真实规则引擎输出。
| 隔离浏览器运行 | 部分通过 | 当前前后端隔离实例加载了活动的 MIMO 配置；单人自然语言观察生成中风险确认卡，页面展示意图、可见目标、方法、置信度与“确认前不写入世界状态”。未点击确认。 |

浏览器验收未完成四名独立账号的协同行动接受流、完整结算、供应商切换、弱网和 25 条核心断言；这些仍保留为未通过门禁。旧的 `:5174` 实例在本轮返回过 405 且 HMR 失败，它不是本工作区当前前后端的验收对象，未用于本结论。详细操作与限制记录在 `docs/loop_runs/2026-07-19-collaboration-contract-mimo-browser-validation.md`。

补充复验中，新的隔离房 `d1790320` 已完成 1 Host + 4 位独立玩家的入房、全员准备和 Host 开局；舞台只显示公开场景与调查员，未显示协同邀请或草稿。由于临时验收后端退出后浏览器控制器拒绝重载本地验收页，本轮没有提交真实邀请或确认行动，未将该 UI 路径误记为通过。后端合同验收现覆盖四名玩家、两人受邀并全员接受后的关联草稿、同房未受邀玩家不可见，以及公共舞台不出现共同意图/合同 ID（7 passed，15.99s）；协同前端组件/API/当前事项复验为 32 tests passed（1.38s）。完整浏览器门禁仍未解除。

2026-07-20 的后续浏览器复验已在同一隔离房完成真实邀请、P2/P3 接受以及 P1 单独确认。该确认没有泄露 P4 或公共舞台，却暴露活跃场景行动被 `scene` 回合收集器等待全员提交的问题。根因和最小修复均已落库：场景行动不再绑定回合并直接调度，只有活跃战斗绑定新的 `combat` 回合；`test_action_drafts_v2.py`、`test_turn_manager.py`、`test_collaboration_contracts.py` 共 77 项和生命周期/结算 31 项定向回归通过。隔离后端未热重载，故修复后的浏览器结算、真实供应商调用和舞台投影仍保留为未验收门禁，详见 `docs/loop_runs/2026-07-19-collaboration-contract-mimo-browser-validation.md`。

同日补齐了协同行动的批次边界：全员确认后才创建一条 `collaboration_contract_batches` 记录，非战斗按合同参与顺序由唯一工作线程领取，战斗批次则交回已存在的回合锁定与 DEX 规划，不允许按确认先后提前结算。全部关联行动终态后批次和合同同步为 `completed`；任一成员在锁定前撤回会取消整组。当前自动化证据为 `tests/server/test_collaboration_contracts.py`、`tests/server/test_turn_manager.py`、`tests/server/test_resolution_pipeline.py`、`tests/server/test_action_drafts_v2.py` 与 `tests/server/test_action_state_machine_v2.py` 共 128 项通过。此项不代表已完成 Director 的跨玩家第二阶段实时重编排；该功能和重启后的浏览器/MIMO 验收仍是开放门禁。

## 全量自动化回归（2026-07-20）

`python -m pytest tests/server -q` 在本机 604 秒工具窗口内没有输出即超时；收集结果为 1,151 项。为区分“单例卡死”和“总时长超过窗口”，按收集量分为四组后顺序执行，结果为 **288 + 289 + 287 + 287 = 1,151 passed**（总测试执行时间约 22 分钟）。慢点主要是每例 PostgreSQL 初始化（约 2 秒）、AI 超时模拟、PDF/XLSX 解析和 1,000 事件重连压力，不是测试卡死。

该回归同时暴露并修正一项测试脆弱性：物品转交用随机 `character_id` 排序查询，却按固定“接收者、发送者”顺序断言，12 次复现中 4 次失败。业务事务实际均已原子完成；测试现改为比较角色与数量的有序集合，随后连续 12 次通过。前端全量 `npm run test -- --run` 为 **45 files / 164 tests passed**，`npm run build` 已通过。浏览器、真实供应商和弱网门禁仍按上节保留未完成状态。

## 准备动作规则事件补充（2026-07-20）

准备动作的白名单事件现均连接到确定性规则输出，而不是 AI、Host 或玩家文本：黑熊公开攻击声明、规则引擎创建单人黑熊遭遇、可见敌方从非近战距离进入 `engaged`，以及公开结算造成另一名玩家受伤。源行动必须已完成；内部反应接收明确的 `encounterId`，私密伤害不会触发“盟友公开受伤”。战斗轮计划只读取当前遭遇参与者的 `armed` 记录，避免房间中旁观角色进入 AI 上下文或玩家公开投影。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_prepared_rule_actions.py tests/server/test_combat_round_planner.py tests/server/test_turn_manager.py tests/server/test_action_state_machine_v2.py tests/server/test_reconnect.py -q` | 83 passed，81.17s | 四类规则事件、私密隔离、当前遭遇过滤、`armed` 重连、战斗轮和状态机。 |

这只更新自动化证据；本工作区后端尚未重启，四类事件的双人浏览器验收、真实供应商和弱网门禁仍未通过。

自动化最终复跑：`python -m pytest tests/server -q` 为 **1189 passed，1313.47s**；`cd src/client && npm run test -- --run` 为 **45 files / 167 tests passed**；`cd src/client && npm run build` 通过。此前一次全量执行曾因测试库并发 `TRUNCATE` 死锁而出现级联失败；随后在无其他 pytest 进程的干净复跑中通过，未将该环境性波动修改为业务逻辑变更。

## 审核台通用配图补充（2026-07-20）

审核台的 AI 配图不再只限于场景：它会从原文为缺少确认绑定的场景、NPC、物品和线索分别生成带 citation 的**未持久化建议**。管理员仍需编辑提示词、生成预览并明确采用，采用后才写入素材库、`scenario_asset_bindings` 和审核补丁。队伍可见预览只允许使用目标的 `public_description` 或该目标已确认的 `public` 防剧透边界；没有公开画面依据时后端拒绝预览，不回退到 AI 自由提示词。

质量报告同时新增非阻断的辅助素材待办：任一 NPC、物品或线索未绑定图片都会显示，管理员可补图或留理由标记为纯文字素材模式，避免半绑定剧本静默遗漏。自动化证据：`python -m pytest tests/server/test_quality.py tests/server/test_scenario_review_workbench.py tests/server/test_ai_gateway.py -q` 为 **62 passed**；`cd src/client && npm run test -- --run` 为 **45 files / 168 tests passed**；`cd src/client && npm run build` 通过。当前 `:5174` 仍提供旧前端，因此本节只记录自动化验证，真实供应商和浏览器验收仍未通过门禁。

随后执行本工作区完整后端回归：`python -m pytest tests/server -q` 为 **1194 passed，1570.17s**。该结果包含本节新增的质量、审核台、建议、预览和采用链测试；不替代真实图像供应商、重启后浏览器或玩家投影验证。
