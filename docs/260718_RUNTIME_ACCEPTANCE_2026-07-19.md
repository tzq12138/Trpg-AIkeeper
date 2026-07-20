# 260718 运行时第一批验收记录（2026-07-19）

## 目的

验证 `docs/260718` 中已落地的两项 P0 边界：

1. 公共舞台必须与房主控制台分离，且公共舞台不泄露精确资源、队列或导演信息。
2. 玩家输入必须先获得接收回执；显式非状态模式不得进入 AI 行动预览或改变世界状态。

## 隔离环境

为避免旧开发服务影响结论，本次没有使用旧的 `5173` 页面。实际浏览器验收使用：

- 前端：`http://127.0.0.1:5177`
- 后端：`http://127.0.0.1:3004`
- 测试房：`fd24020e`（剧本：`雾港失物局`）
- 测试角色：`验收玩家 / 陆遥`

旧 `5173` 在验证开始时仍加载旧版混合 HostStage；该事实已记录，不作为本轮代码结果。

## 自动化证据

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py -q` | 43 passed | 公共舞台鉴权、安全投影字段、Host HUD |
| `python -m pytest tests/server/test_action_drafts_v2.py -q` | 40 passed | 接收记录、加密、幂等、非状态隔离、原文绑定 |
| `npm run test -- --run tests/host-stage.test.ts` | 6 passed | 舞台/控制台分离与安全 UI 合同 |
| `npm run test -- --run tests/player-api.test.ts tests/player-action-composer.test.tsx` | 15 passed | 客户端动作信封和输入模式组件 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 构建 |

## 浏览器验收

### 公共舞台与控制台

1. 以本地管理员登录隔离实例，创建测试房并进入 `/host/fd24020e/stage`。
2. 公共舞台只呈现：房间标识、`等待调查员行动`、当前场景、调查员名和`情况稳定`、近期公开事件。
3. 公共舞台 DOM 中未出现：HP/SAN/MP/Luck 数字、队列、暂停、异常接管、导演台、逐字光标。
4. 打开 `/host/fd24020e/console` 后，原房主控制台仍包含队列、只读导演台、暂停与异常接管入口。
5. 玩家加入并开局后，公共舞台只显示 `陆遥 / 情况稳定`，没有显示 `11/11` 或 `60/60` 等精确值。

### 输入接收与模式切换

1. 玩家页显示十种输入类型：行动、发言、队伍讨论、规则问题、私密笔记、分享线索、使用物品、移动、战斗行动、安全边界。
2. 在行动输入框填入“我先提醒队友注意门外的脚印。”后切换到`发言`：原文保留，主按钮变为`记录发言`。
3. 提交该发言后：文本进入本地叙事流、输入框清空、状态回到`idle`；没有出现 AI 行动预览、确认卡、骰子或世界状态结算。
4. 后端定向测试同时证明此路径只写入加密 `player_action_submissions`，不创建 `actions` 或 `action_drafts`。

## 未覆盖项

- 4 名玩家的短窗口合并、断线/乱序/千事件恢复。
- 状态型行动从接收信封到真实 AI/规则结算的浏览器完整回合。
- 多人战斗的整轮声明状态机（当前仍是后续缺口）。
- 真实图文供应商和文本备用链的本轮实时调用。
- 公共 HUD 中团队目标、场景时间以及玩家“当前事项”工作台。

上述项目继续由 `260718_IMPLEMENTATION_MATRIX_2026-07-19.md` 的未完成条目驱动，不得因本记录的局部通过而标记为总目标完成。

## 后续自动化改造（同日）

以下改动在本记录初版之后完成；均有当前自动化证据，但**尚未在新的隔离浏览器实例复验**：

1. 多人战斗回合：锁定后保存 `combat-round-v1` 计划，按遭遇 DEX 而不是提交先后执行；组合声明最多两段，`system_skip` 只解释为 `idle/maintain_existing`，不代替玩家生成战术动作。
2. 轮末安全投影：轮末摘要只读取已释放的 `resolution_bundles.stage_projection`；公共舞台仅白名单显示标题、公开事实与当前局势。待选规则反应会阻塞下一轮声明。
3. 不可变回放：已完成动作的玩家回执从 `resolution_bundles` 的玩家投影和规则说明读取；动作表中的可变结果或回执被篡改后不会改变玩家回放。
4. 公共 HUD：公共舞台新增至多三条活跃团队目标，以及仅来自 `scene_variables.public_time/scene_time/time` 的场景时间；缺失时明确显示“时间未定”。
5. 跨页当前事项与非状态输入：调查、角色、装备、地图和回流页复用当前优先级卡；非状态输入给出不改变世界状态的模式化系统回执，私密笔记不回显正文。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_combat_round_planner.py tests/server/test_turn_manager.py tests/server/test_narrator_runtime.py -q` | 37 passed | 战斗计划、排序、锁定、轮次推进、公开摘要 |
| `python -m pytest tests/server/test_host.py tests/server/test_narrator_runtime.py tests/server/test_turn_manager.py tests/server/test_combat_round_planner.py -q` | 81 passed | 公共舞台、战斗摘要投影与回合结算 |
| `python -m pytest tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py -q` | 21 passed | 结果包回放与玩家脱敏投影 |
| `python -m pytest tests/server/test_events.py -q` | 5 passed | 新战斗锁定事件的 Python 协议登记 |
| `npm run test -- --run tests/player-terminal.test.tsx tests/player-input-modes.test.ts tests/player-action-composer.test.tsx` | 11 passed | 跨页当前事项、输入模式回执与编辑器 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |

## 本轮补充：战役回流安全投影

1. **当前场景**：回流页只显示玩家安全预览、已校验 citation、当前场景插图和已验证语义图中的可继续方向数；不显示条目号、原始文件名、`source_ref` 或后续节点正文。
2. **最近线索**：玩家自己的线索可显示原文；其他角色的线索只取已分享的 `public_version`，回流页标注为“队伍分享摘要”，不会读取或下发他人的私密原文。
3. **场景配图**：当前场景只有素材可见性为 `party`、`player` 或 `public` 时才携带图片标识并允许下载；AI 默认生成的 `host_only` 配图即便已确认绑定当前场景，也不会出现在玩家 DTO 或素材端点。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_campaign_v2.py::test_campaign_home_projects_only_the_current_solo_entry tests/server/test_campaign_v2.py::test_campaign_home_returns_recent_clues_without_leaking_other_players_original_text -q` | 2 passed | 当前场景脱敏、方向数与跨角色线索投影 |
| `python -m pytest tests/server/test_campaign_v2.py tests/server/test_scenario_asset_bindings.py -q` | 42 passed | 回流、公开/Host-only 场景图与地图底图、素材绑定、地图雾区/Token 与移动事件 |
| `python -m pytest tests/server/test_clues.py tests/server/test_rag_security.py tests/server/test_spoiler_guard.py -q` | 56 passed | 私密线索摘要、RAG 角色/版本过滤与防剧透守卫 |
| `python -m pytest tests/server/test_combat_round_planner.py tests/server/test_narrator_runtime.py tests/server/test_coc7_core_rules.py tests/server/test_events.py -q` | 58 passed | 整轮声明、确定性 CoC7 判定、规则解释、叙事与事件协议 |
| 剧本/导入批次（内容包、编译、黄金样本、地图、单人运行时、版本/迁移、PDF/XLSX） | 190 passed | 黄金夹具以来源锚点线索作为有 citation 的结局条件，正式导入→运行包→发布→开房→结局 E2E 已恢复 |
| 玩家平台批次（邀请/角色、房间、频道、申诉、Session 设置、多人循环与归档） | 224 passed | 多人房间、私密频道、角色/邀请、行动状态机、回流设置与循环脚本定向回归 |
| 基础设施批次（AI/Provider、RAG、规则、DB、投影、MCP、WebSocket） | 336 passed | 动态供应商、RAG 版本/权限、确定性规则、数据库适配、实时连接与 MCP 适配回归 |
| 审核台工作台完整套件 | 17 passed | 防剧透边界、引用候选、AI 场景配图建议、预览、采用与发布门禁 |
| `cd src/client && npm run test -- --run` | 123 passed | 全量 Vitest（39 个测试文件） |
| `cd src/client && npm run test -- --run tests/campaign-home-panel.test.tsx tests/host-stage.test.ts tests/player-current-priority.test.ts tests/player-action-composer.test.tsx` | 25 passed | 回流页展示、房主投影恢复、当前事项与回执文案 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |

本轮未重新打开浏览器；上述结论仅为定向自动化与构建证据。

## 全量门禁状态

- `python -m pytest tests/server -q` 于 664 秒后超时，未产生单进程汇总。随后按无重叠模块分为 8 个可观察批次执行，结果为 `42 + 56 + 145 + 58 + 190 + 224 + 336 + 17 = 1068 passed`，与收集数一致；单进程耗时仍应在后续 CI 中优化。
- 前端全量 Vitest 已通过；后端已覆盖行动/重连/Host、回流/地图/素材、线索/RAG/防剧透、战斗/叙事、剧本编译与审核台。
- 本轮遵循当前限制未重新打开浏览器；单人、四玩家、双供应商和弱网的浏览器验收仍需在允许浏览器操作时补做。
| `python -m pytest tests/server -q` | 未完成（604 秒超时） | 未取得全量结果，不能替代上述定向通过 |

下一次浏览器验收必须复验：四人整轮声明、公共舞台轮末摘要、目标/时间投影、跨页当前事项与私密笔记不回显。

## 后续自动化改造（二）

本段同样只有当前自动化证据，尚未宣称完成浏览器或真实供应商验收：

1. AI 整轮编排：`resolve_combat_round` 改为严格 `CombatRoundSuggestion` 契约。供应商只能对已公开的 `action_id` 提供冲突簇标题和建议依赖；计划器过滤未知/私密动作，保留未覆盖的默认公开簇，且永远不修改 DEX 排序、规则绑定、骰子或状态。
2. 缺席策略：玩家设置增加 `idle/maintain_existing` 预设；`TurnManager` 依据房间已有 `input_hint_seconds` 处理超时声明，幂等插入 `system_skip`。应用生命周期中的 worker 每 5 秒运行一次，并在所有声明齐备后调度既有结算。
3. 玩家可见入口：当前战斗页显示“缺席策略”控件；明确说明不会自动攻击、选目标、花资源或承担额外风险，主控设备之外不可修改。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_combat_round_planner.py tests/server/test_ai_gateway.py tests/server/test_narrator_runtime.py tests/server/test_turn_manager.py tests/server/test_turn_timeout_worker.py tests/server/test_player_action_settings_v2.py tests/server/test_host.py tests/server/test_events.py -q` | 146 passed | AI 受限编排、锁定/结算、超时 worker、玩家预设、公共投影与事件契约 |
| `cd src/client && npm run test -- --run tests/player-api.test.ts tests/absent-policy-control.test.tsx` | 12 passed | 玩家设置 API 与缺席策略安全文案 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建与页面接入 |

仍缺：真实动态供应商返回 `CombatRoundSuggestion` 的浏览器流程、四玩家超时/重连、以及弱网下 worker 与手动提交的竞态验收。

## 后续自动化改造（三）

本段为本轮当前工作区的新增自动化证据；未在本次会话重新操作浏览器，也未调用真实供应商。

1. **公共场景时间**：房主大厅可编辑唯一公开字段 `scene_variables.public_time`。接口仅允许房主/管理员调用，保留其他场景变量、递增场景版本，并写入不含幕后变量的系统审计；公共舞台投影读取同一字段。
2. **Host ACK 收紧**：每个 `TransactionStep` 均有持久化 `stepId`。延迟事件放行同时核对活动事务、已完成步骤序号与该步骤 ID；公共舞台仍无 ACK 或导演操作控件。
3. **物品转移**：同房角色可发起指定数量的请求，接收方明确接受/拒绝后才原子移动或拆分库存；物品被移除或数量不足时请求持久化为 `unavailable`。转移列表只给双方返回名称、数量和昵称，不包含物品描述；私密物品不进入队伍事件。
4. **当前事项**：行动页只轮询“是否有待接收物品”的布尔状态，优先级卡可直达背包；物品详情不进入叙事流或队伍频道。
5. **低风险撤回**：不要求确认的草稿不再即时提交；玩家可在 2 秒“撤回预览”窗口中编辑或丢弃，计时器才会自动确认，窗口结束后仍使用既有服务器可撤回规则。
6. **战斗声明**：声明阶段增加“本轮暂不主动行动”。接口只允许当前角色在未锁定的战斗轮写入 `system_skip/idle`，重复点击返回同一声明；不会代替玩家攻击、移动、选目标或消耗资源。已取消、超时和被拒绝的旧声明不会继续计入本轮提交，玩家可重新声明。
7. **确认信息**：正式确认卡按输入模式说明后续流程：战斗进入统一锁定与结算，物品先校验物品/目标条件，移动先校验路线与可见信息，NPC 对话不会先作为队伍讨论发送。文案不承诺成功，也不在确认前写世界状态。
8. **当前事项导航**：待接收物品可直接跳到背包；已公开的队伍待调查问题可直接跳到战役回流。终端与行动页复用同一优先级输入，避免主卡与行动页显示不一致；行动页只读取待办布尔值，不把物品细节或私密笔记放进叙事流。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_player_features.py tests/server/test_host.py tests/server/test_action_drafts_v2.py tests/server/test_player_action_settings_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_archive.py -q` | 161 passed | 背包转移、公开 HUD、事务 ACK、输入与动作/归档回归 |
| `cd src/client && npm run test -- --run tests/public-scene-time.test.ts tests/inventory-transfer-api.test.ts tests/player-input-modes.test.ts tests/player-api.test.ts tests/player-action-composer.test.tsx tests/player-inventory.test.tsx tests/team-message.test.ts tests/host-stage.test.ts` | 38 passed | 房主时间请求、玩家转移请求、输入、背包与舞台合同 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |
| `git diff --check` | passed | 补丁空白检查；Git 仍打印既有 LF→CRLF 预警 |

| `python -m pytest tests/server/test_turn_manager.py::test_player_can_declare_idle_for_current_combat_round tests/server/test_turn_manager.py::test_canceled_combat_declaration_no_longer_counts_as_submitted tests/server/test_turn_manager.py::test_expired_combat_turn_uses_player_absence_preset_once_and_never_invents_tactics -q` | 3 passed | 主动 idle、撤回后重声明、超时预设 |
| `cd src/client && npm run test -- --run tests/player-api.test.ts tests/player-input-modes.test.ts tests/player-action-composer.test.tsx` | 26 passed | idle 接口、模式化确认提示与确认卡 |
| `cd src/client && npm run test -- --run tests/player-current-priority.test.ts` | 6 passed | 私密转移和公开队伍问题的优先级及目标页 |

仍缺：双玩家浏览器验收物品请求/接收/私密可见性，公共时间投影浏览器验收，以及 1 Host + 4 玩家、弱网和真实供应商的完整验收。全量 `pytest` 在此前 604 秒超时，本记录不把定向结果表述为全量回归。

## 本轮补充：投影失败恢复

1. **不重算的恢复**：动作的规则结算、状态变化和结果包已完成后，若 Host/玩家/公共投影发送失败，系统将该结果包标记为 `projection_pending`；不会重新调用 AI、规则引擎或状态写入。
2. **最小房主操作面**：Host 控制台仅展示待恢复动作与角色标识，明确说明“重放只读取已保存的结果包，不会重新裁决或改写世界状态”。按钮调用房主鉴权的投影重放接口，不接受新的动作正文、结果或状态补丁。
3. **恢复后的安全边界**：重放仍经现有投影调度与防剧透安全网；队列接口不返回原始行动、叙事、判定或私密文本。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py::TestHostRESTEndpoints::test_owner_lists_projection_recoveries_without_private_action_text tests/server/test_host.py::TestHostRESTEndpoints::test_owner_can_replay_a_pending_projection_without_passing_new_content tests/server/test_resolution_pipeline.py::test_projection_failure_keeps_resolution_complete_and_replays_saved_bundle_only -q` | 3 passed | 房主权限、脱敏队列、仅重放保存结果及不改写已完成动作 |
| `cd src/client && npm run test -- --run tests/host-stage.test.ts` | 8 passed | 恢复队列仅显示最小标识和保存投影重放控件 |

仍缺：投影发送故障的真实浏览器复现与多供应商中断场景；本轮未重新打开浏览器。

## 本轮补充：回执与优先级可读性

1. **玩家回执**：输入阶段、回执状态与状态时间线统一显示中文玩家文案，不再把 `queued`、`resolving` 等内部枚举直接暴露到玩家界面；规则版本、骰点、状态前后和脱敏 citation 仍保留在展开区域。
2. **当前事项一致性**：行动页与终端使用同一优先级输入。公开队伍待调查问题会在行动页显示“查看队伍待调查问题”，直达战役回流；该入口只依赖公开待办布尔值。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `cd src/client && npm run test -- --run tests/host-stage.test.ts tests/player-current-priority.test.ts tests/player-action-composer.test.tsx` | 22 passed | 房主恢复队列、当前事项直达与玩家回执中文状态 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |

## 本轮补充：安全演出、视觉跳过、复核包与原骰重算

1. **演出控制**：Host Console 只可开始、暂停、推进、跳过视觉步骤和重放已保存的演出。`next` 只增加 `HostStore.current_step_index`；`skip-visual` 只跨越紧邻的 `scene_transition`，并按每个原始 `step_id` 逐项放行已保存的玩家投影；不会重新调用 AI、规则引擎或状态服务。
2. **公共舞台**：公共舞台从独立的 `/stage-presentation` 读取内容。该接口仅接受已发布 `ResolutionBundle.stage_projection` 中的公开叙事，Host 交易载荷中的骰点、状态差异、行动 ID 和幕后字段不会下发。
3. **复核包**：Host Console 每 5 秒或收到复核事件后读取只读 `HostReviewPacket`，显示原始行动、系统意图、Director/规则计划、状态差异和 citation；接口显式白名单字段，HMAC 签名与完整规则解释不下发到页面，页面也没有直接裁决入口。
4. **原骰重算**：Host 对待处理申诉只可把已完成 CoC7 技能检定的难度改为 `regular/hard/extreme`。服务端验证原 HMAC 回执、规则集和 d100 trace 后复用原骰计算结果；不接受客户端骰点，也不覆盖原 action、原结果包或世界状态。重算结果进入独立 `roll_recalculation` 审计补偿事务。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host.py tests/server/test_action_reviews_v2.py tests/server/test_coc7_core_rules.py tests/server/test_action_lifecycle_v2.py -q` | 96 passed，88.08s | Host 演出游标、公开投影、原骰重算、回执篡改拒绝与相关规则回归 |
| `python -m pytest tests/server/test_multiplayer_loop.py tests/server/test_reconnect.py tests/server/test_turn_manager.py tests/server/test_turn_timeout_worker.py -q` | 25 passed，22.71s | 多人循环、重连、回合锁定和超时 worker 自动化路径 |
| `python -m pytest tests/server/test_host.py tests/server/test_action_reviews_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py -q` | 100 passed，94.46s | 视觉跳过逐步释放、Host 复核包脱敏与演出/行动/重连回归 |
| `cd src/client && npm run test -- --run` | 39 files / 126 tests passed | 公共舞台白名单模型、视觉跳过、Host 复核包与前端既有回归 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |
| `git diff --check` | passed | 无空白错误；仅有既有工作树 LF/CRLF 转换警告 |

本段没有浏览器、多人或真实供应商证据；不得将上述自动化通过表述为完整运行时验收。

## 本轮补充：Host 离线自治策略

1. **房间策略**：Host 在大厅通过“Host 计划离线策略”保存 `host_required`、`conservative` 或 `delegated`。默认 `host_required`，因此旧房间和未配置房间在 Host 缺席时不会意外继续裁决。
2. **服务端路由**：生产 `ResolutionPipeline` 读取 Host WebSocket 连接状态；`delegated` 仅允许公开、可验证且可补偿的普通检定、已揭示范围移动、普通物品使用和低风险对话。战斗、秘密行动、幸运/孤注一掷、高风险或未知输入进入 `awaiting_host_exception`，不生成结果包或状态补丁。
3. **玩家反馈**：新增 `s2c_action_deferred`，只携带 `actionId`、`awaiting_host_exception` 状态和原因码。玩家页收到后立即刷新权威回执；Host 仍通过现有异常队列获取复核事件。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_host_autonomy.py tests/server/test_events.py tests/server/test_player_action_settings_v2.py tests/server/test_player_experience_v2_schema.py tests/server/test_action_lifecycle_v2.py -q` | 51 passed，74.81s | 白名单/拒绝策略、无状态写入、延后事件、房间设置和生命周期回归 |
| `cd src/client && npm run test -- --run` | 40 files / 128 tests passed | Host 离线策略、替代技能确认与现有页面回归 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |

本段没有浏览器、多玩家断线/重连或真实供应商证据；不得把自动化结果表述为 Host 离线实际桌游验收。

## 本轮补充：替代技能协商

1. **AI 只建议**：行动分析可返回最多两项 `alternative_skills`；候选仅随草稿持久化，不会直接改变 `skillName`、角色数值或规则结果。
2. **玩家选择**：确认卡显示建议技能和替代候选。存在候选时，玩家必须显式选定一个技能；确认按钮在未选定时禁用。
3. **服务端权威**：确认接口仅接受保存分析中的“建议技能 + 替代候选”。缺选或客户端自填其他技能均返回安全错误码；通过后才把选定技能写入正式 Action，`RuleExecutor` 仍从服务器角色卡读取对应技能值。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_configured_openai_provider.py -q` | 75 passed，102.29s | 候选持久化、缺选/非法选择拒绝、合法选择入账与既有行动/供应商回归 |
| `cd src/client && npm run test -- --run tests/player-action-composer.test.tsx` | 8 passed | 确认卡候选展示与未选择禁用 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |

本段没有真实供应商的候选质量、浏览器点击或多人技能协商证据；不得将自动化结果表述为完整体验验收。

## 本轮补充：组合行动与条件续接

1. AI 行动分析可起草最多两个 `composite_steps`。玩家确认卡展示两步、一次行动成本与第二步的失败策略，并允许在确认前交换顺序。
2. 规则引擎按顺序执行：第一步失败可以取消第二步、继续结算第二步，或暂停在玩家确认卡中询问是否继续。暂停后，`POST /api/player/actions/{action_id}/composite-choice` 只恢复待执行的第二步，已完成第一步不会再次掷骰。
3. 自动暂停仅允许第一步不存在待提交 mutation 的情况；有状态副作用的条件分支会转入 Host 异常队列，避免部分提交或状态重复。
4. 这实现的是“前序规则结果条件”；多人协作已另以持久化合同落实“邀请 → 全员回应 → 各自待确认草稿”，但外部事件触发的准备动作仍属于后续范围，未在本段声称完成。

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_resolution_pipeline.py tests/server/test_reconnect.py tests/server/test_turn_manager.py tests/server/test_host_autonomy.py -q` | 102 passed，156.05s | 两步确认、失败取消/继续、暂停选择、恢复不重放与行动/回合回归 |
| `cd src/client && npm run test -- --run` | 40 files / 130 tests passed | 组合步骤显示、顺序调整和玩家续接卡 |
| `cd src/client && npm run build` | passed | TypeScript/Vite 构建 |

本段没有浏览器、多人或真实供应商证据。
