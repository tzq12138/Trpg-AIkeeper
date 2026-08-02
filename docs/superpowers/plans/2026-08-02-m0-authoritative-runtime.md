# M0 权威运行时与多人治理实施计划

> 执行要求：使用 superpowers:executing-plans 按顺序完成本计划；所有行为改动遵循 superpowers:test-driven-development，先观察 RED，再写最小实现，最后做相关回归。

**目标：** 完成已确认决策 1–60 的程序落实，在当前分支通过自动化验证，并以浏览器完成 1 房主 + 4 玩家《玻璃雨夜》至可刷新验证的真实结局，最后非强制推送到远端 main。

**架构约束：** 版本化结构化状态是当前权威；event 只承担审计、事务证明和恢复边界；AI 输出是建议或派生叙事。沿用现有 V2 action、StateService、ResolutionPipeline、projection、runtime package 与 campaign archive，只新增逐次 action 同意和事实揭示两类最小记录。

**技术栈：** FastAPI、PostgreSQL/pgvector、React、TypeScript、Vite、pytest、Vitest。

**执行方式：** 用户已要求直接在 codex/260730-runtime-contracts 上实施；不创建额外 worktree，不使用子代理。数据库测试顺序运行，避免共享测试库并发造成假失败。

**提交约定：** 每个 Task 的提交步骤先用 git status 和 git diff 核对范围，再仅 git add 该 Task“文件”清单中实际修改或新增的路径；文中的 commit 命令不代表可以省略精准暂存。若计划中的“实际入口”与仓库发现不同，以调用链定位到的真实现有文件为准，不创建重复路由或平行实现。

---

## Task 1：建立 AI-only 房间权威策略

**文件：**

- 修改：tests/server/test_rooms.py
- 修改：tests/server/test_host_autonomy.py
- 修改：tests/server/test_action_drafts_v2.py
- 修改：tests/server/test_glass_rain_golden_flow.py
- 修改：src/server/router_rooms.py
- 修改：src/server/engine/host_autonomy.py
- 修改：src/server/player/action_service.py
- 修改：src/server/engine/resolution_pipeline.py

### Step 1：写失败测试

通过真实房间创建和 action API 验证：

- 从 runtime_policy.session_mode=ai_only 的运行包创建房间后，无需直接 UPDATE，合法公开行动不会因为 Host 离线进入 awaiting_host_exception。
- 低置信或高影响歧义进入 player_clarification_required，不请求 Host。
- Director 无效、Narrator 故障和规则建议异常分别得到确定性拒绝、澄清或模板叙事；状态完整性失败暂停房间。
- 删除黄金测试手工设置 delegated 的语句后仍通过，且 awaiting_host_exception 计数为零。

运行并观察 RED：

~~~powershell
python -m pytest tests/server/test_rooms.py tests/server/test_host_autonomy.py tests/server/test_action_drafts_v2.py tests/server/test_glass_rain_golden_flow.py -q
~~~

### Step 2：最小实现

- 创建房间时读取已固定 runtime package 的 session_mode。
- AI-only 模式成为房间运行绑定的一部分，不能静默修改。
- decide_host_autonomy 接收 session mode；AI-only 不返回 deferred_host_review。
- Host 例外分支按原因映射为玩家澄清、Engine 拒绝/降级或房间暂停。
- 非 AI-only 房间保留原策略。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_rooms.py tests/server/test_host_autonomy.py tests/server/test_action_drafts_v2.py tests/server/test_glass_rain_golden_flow.py -q
git diff --check
git commit -m "fix: make AI-only rooms engine authoritative"
~~~

---

## Task 2：编译、冻结并确认风险契约

**文件：**

- 新增：tests/server/test_room_risk_contract.py
- 修改：tests/server/test_module_compiler.py
- 修改：tests/server/test_campaign_v2.py
- 修改：tests/server/test_room_security.py
- 修改：tests/server/test_reconnect.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：src/server/scenario/module_compiler.py
- 修改：src/server/router_rooms.py
- 修改：src/server/player/router_campaign_v2.py
- 修改：src/server/player/router_player.py
- 修改：src/server/player/action_service.py
- 修改：data/golden_modules/02-short-team-glass-rain/module.json

### Step 1：写失败测试

- 编译器规范化风险类别、排除标签、隐藏检定、安全替代和不可逆控制规则，并生成稳定 SHA-256。
- 相同语义不同键顺序得到相同哈希，内容变化得到不同哈希。
- 房间创建和启动固定契约版本及哈希。
- Session Zero 风险确认必须提交当前哈希；空值、错误值、旧值均拒绝。
- 活跃房间新玩家未确认当前契约前不能提交机械 action。
- 越界风险在秘密内容进入响应前停止，只返回无剧透标签。

运行并观察 RED：

~~~powershell
python -m pytest tests/server/test_room_risk_contract.py tests/server/test_module_compiler.py tests/server/test_campaign_v2.py tests/server/test_room_security.py tests/server/test_reconnect.py -q
~~~

### Step 2：最小实现

- rooms 增加冻结契约 JSON、版本和哈希。
- session_zero_confirmations 增加契约版本和哈希，兼容其他步骤。
- runtime package 加入 allowlist 规范化 risk_contract。
- Session Zero API 返回无剧透摘要、版本和哈希并校验确认值。
- action 提交前检查当前角色是否确认当前哈希。
- 迟到/重连 recap 只含公共范围。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_room_risk_contract.py tests/server/test_module_compiler.py tests/server/test_campaign_v2.py tests/server/test_room_security.py tests/server/test_reconnect.py -q
git diff --check
git commit -m "feat: freeze room risk contracts"
~~~

---

## Task 3：收紧意图、私密频道、澄清和超时

**文件：**

- 新增：src/server/engine/action_policy.py
- 新增：tests/server/test_action_policy.py
- 修改：tests/server/test_action_drafts_v2.py
- 修改：tests/server/test_channel_security.py
- 修改：src/server/player/action_service.py
- 修改：真实的 action-draft router 入口
- 修改：src/server/models.py

### Step 1：写失败测试

- “我偷偷去地下室”不能产生 private move、状态写入或随机数，返回公开重提选项。
- “我在心里害怕”可作为 private non-mechanical 内容，不改变世界状态。
- “我已经拿到钥匙”不会直接增加 inventory 或发现 clue。
- 目标、资源、检定、风险或安全解释不同返回 2–3 个澄清选项，确认前无副作用。
- 可逆装饰歧义可保守处理但预览披露推断。
- 调查超时取消且不耗资源；战斗超时只产生固定防御、保持或安全撤退。
- 一名玩家等待澄清不阻塞另一名玩家的非冲突 action。

运行并观察 RED：

~~~powershell
python -m pytest tests/server/test_action_policy.py tests/server/test_action_drafts_v2.py tests/server/test_channel_security.py -q
~~~

### Step 2：最小实现

- action_policy 仅接收已规范化意图、当前状态和风险契约，返回 allow、clarify、reject 或 timeout-safe-effect。
- 秘密关键词与机械影响分开判断，不因关键词授予 private 状态写权限。
- AI 只贡献澄清候选，Engine 过滤最终选项。
- draft 到期原子写 timeout，禁止随机抽取和资源 delta。
- 确认 draft 时再次执行 policy，防止状态变化后绕过。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_action_policy.py tests/server/test_action_drafts_v2.py tests/server/test_channel_security.py tests/server/test_player_action_settings_v2.py -q
git diff --check
git commit -m "fix: enforce player intent and private-channel policy"
~~~

---

## Task 4：逐次 PvP 同意、群体决定与离线保护

**文件：**

- 新增：src/server/engine/action_consent.py
- 新增：src/server/player/router_action_consents.py
- 新增：tests/server/test_action_consents.py
- 新增：tests/server/test_player_lifecycle_governance.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：实际 router 注册入口
- 修改：src/server/player/action_service.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/host/router_host.py
- 修改：src/server/player/router_player.py
- 修改：src/server/player/router_collaboration_contracts.py

### Step 1：写失败测试

- PvP 伤害、夺取资源、限制行动和他人状态变化必须生成目标玩家逐次 consent。
- 房间开关、旧 consent 和房主均不能代答。
- 目标拒绝或到期后原 action 终止且状态、资源不变。
- NPC 在已接受风险契约内不要求 PvP consent；越界仍需风险确认。
- 可逆路线按活跃玩家多数；重大共享资源、结局、放弃队友和扩大风险需全体受影响玩家同意。
- 弃权、平票或未达阈值产生无效果或更安全结果。
- 离线角色只可防御、跟随或安全撤退；不消耗稀缺资源、不作不可逆选择、不接收秘密揭示。
- 房主移除只终止访问，不接管角色或私人数据。

### Step 2：最小实现

- 新增 action consent 表，唯一键绑定 action、受影响角色和 consent kind。
- 只有被影响角色当前身份可响应；响应幂等。
- 必需 consent 完成前不抽骰、不写 state delta。
- 复用 collaboration contract 的参与者校验，不把长期合同当逐次 PvP 同意。
- 角色进入 protected_inactive，并在合法重连后恢复控制。
- 高影响房主操作写生命周期 audit event。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_action_consents.py tests/server/test_player_lifecycle_governance.py tests/server/test_collaboration_contracts.py tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py -q
git diff --check
git commit -m "feat: require affected-player action consent"
~~~

---

## Task 5：强化并发、状态版本和资源冲突

**文件：**

- 新增：tests/server/test_action_concurrency.py
- 修改：src/server/player/action_service.py
- 修改：src/server/engine/state_service.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/turn_manager.py
- 修改：src/server/combat_round_planner.py

### Step 1：写失败测试

- 同角色同幂等键的并发确认只创建一个 action。
- 不同角色使用不相关资源的同版本 action 都可完成。
- 两个 action 消耗同一唯一物品或影响同一目标时串行；第二个重新验证后失败或重新确认。
- 场景或风险上下文变化后旧确认返回 sync_required 或新澄清，不覆盖新状态。
- same-turn 场景推进保持现有不误报 stale 的行为。

### Step 2：最小实现

- 从已验证 params 和 intent contract 生成稳定 conflict keys，不信任客户端自报。
- 共享 conflict key 使用事务锁；非冲突 action 不扩大为全房间串行。
- 状态版本变化时重跑无副作用 validation；语义改变要求重新确认。
- 冲突结果写 action status event 和脱敏原因。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_action_concurrency.py tests/server/test_action_drafts_v2.py tests/server/test_multiplayer_loop.py tests/server/test_turn_manager.py -q
git diff --check
git commit -m "fix: serialize conflicting room actions"
~~~

---

## Task 6：可验证 event、checkpoint 和只读恢复

**文件：**

- 新增：src/server/engine/runtime_integrity.py
- 新增：tests/server/test_runtime_integrity.py
- 修改：tests/server/test_event_log.py
- 修改：tests/server/test_archive.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：src/server/events/event_log.py
- 修改：src/server/router_archive.py
- 修改：src/server/models.py
- 修改：src/server/engine/resolution_pipeline.py

### Step 1：写失败测试

- event 自动绑定 action、提交后 state version 和规范化 payload hash。
- checkpoint 绑定 state version、最大 event sequence、schema version、snapshot hash 和不变量报告。
- checkpoint JSON 不含 player_token、账号身份、原始安全文本。
- 篡改快照后恢复被拒绝，房间进入 read_only_recovery，原状态未被删除。
- dry-run 返回差异但不写状态。
- 自动恢复只接受验证成功 checkpoint；逐行错误必须让事务整体回滚。
- 人工修复缺提案、dry-run token、双确认或理由时拒绝；成功时审计并通知。
- read_only_recovery 拒绝机械 action，但允许读取、导出和恢复检查。

### Step 2：最小实现

- 使用稳定 JSON 编码计算 hash；expected hash 用独立手算 fixture。
- 只快照运行态 allowlist，凭据不经 checkpoint 恢复。
- 替换忽略逐行错误的恢复循环，验证和写入使用单一事务。
- 实际 apply 校验 dry-run token、checkpoint hash 和当前 state version。
- 无法证明状态一致时暂停，不静默继续。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_runtime_integrity.py tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_state_service_consistency.py -q
git diff --check
git commit -m "feat: verify runtime checkpoints and recovery"
~~~

---

## Task 7：Engine 事实揭示账本与知识投影

**文件：**

- 新增：src/server/engine/reveal_ledger.py
- 新增：tests/server/test_reveal_ledger.py
- 修改：tests/server/test_director_runtime.py
- 修改：tests/server/test_campaign_v2.py
- 修改：tests/server/test_spoiler_guard.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/engine/spoiler_guard.py
- 修改：src/server/ai/director.py
- 修改：src/server/player/router_campaign_v2.py
- 修改：src/server/events/event_log.py

### Step 1：写失败测试

- 未满足条件的隐藏事实提议被拒绝，玩家响应和 event 无秘密文本。
- 合法 reveal 在 narration 前与状态版本同事务写入；事务失败时 reveal 和 narration 均不可见。
- public、player-self、other-player、director 投影只含各自授权事实。
- 私人 reveal 不进入公共 archive、队伍 evidence 或其他玩家重连。
- 玩家假说不会因 AI 肯定语气变成 world truth。
- 更正追加记录并保留曾见信息；错误 reveal 标记安全事件。
- 外部 AI context 继续不含身份、令牌、安全原文和不相关秘密。

### Step 2：最小实现

- 新增 reveal 表，绑定 fact/content ID、citation、audience、source action、state version 和 event sequence。
- ResolutionPipeline 先验证 reveal proposal，再与 state delta 原子提交。
- Director context 由 ledger 和当前公共状态投影构建，不传整个 knowledge graph。
- 复用 EventLog 受众过滤，ledger 作为事实授权来源。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_reveal_ledger.py tests/server/test_director_runtime.py tests/server/test_campaign_v2.py tests/server/test_spoiler_guard.py tests/server/test_rag_security.py -q
git diff --check
git commit -m "feat: add authoritative reveal ledger"
~~~

---

## Task 8：Engine RNG、回执和两阶段幸运/推骰

**文件：**

- 新增：src/server/player/router_action_decisions.py
- 新增：tests/server/test_coc_followup_decisions.py
- 修改：tests/server/test_action_receipt_v2.py
- 修改：tests/server/test_coc7_core_rules.py
- 修改：tests/server/test_coc7_rulebook_regressions.py
- 修改：src/server/engine/roll_receipt.py
- 修改：src/server/rules/coc_handlers.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/player/action_service.py
- 修改：src/server/models.py
- 修改：实际 router 注册入口

### Step 1：写失败测试

- receipt 绑定 room、state version、action、purpose、rule version、locked inputs、raw draws 和 idempotency key；任一字段篡改验证失败。
- 初次 skill check 即使带 pushed=true 也只抽一次骰，返回 follow-up，不自动重骰。
- 幸运显示精确需要值；只有所属玩家可确认；重复确认不重复扣减。
- 推骰确认前锁定风险等级、影响范围、支撑 facts 和 warning；未确认不抽第二次骰。
- 推骰失败的 AI 具体后果必须在 envelope 内；越界一次重试后使用固定后果。
- timeout 不花幸运、不推骰。
- 隐藏检定只有编译规则声明时允许。
- 同 action/purpose 重试返回相同 draws 和 receipt。

### Step 2：最小实现

- 升级 receipt version，兼容验证旧 v1，但新 action 只生成新版本。
- 初骰写入原 action/resolution bundle；可用 follow-up 作为结构化待办。
- follow-up endpoint 只接受 spend_luck、push 或 decline，绑定原 action 和当前玩家。
- 推骰是关联原 action 的第二个 Engine 规则步骤，使用已锁定输入和独立 purpose。
- AI 只提出 pushed consequence；Engine 执行 envelope validator 和固定 fallback。
- 玩家回执隐藏未揭示来源但保留可验证 commitment。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_coc_followup_decisions.py tests/server/test_action_receipt_v2.py tests/server/test_action_lifecycle_v2.py tests/server/test_coc7_core_rules.py tests/server/test_coc7_rulebook_regressions.py tests/server/test_action_reviews_v2.py -q
git diff --check
git commit -m "feat: stage CoC luck and pushed rolls"
~~~

---

## Task 9：收口 SAN/疯狂、背景变化和替补调查员

**文件：**

- 新增：tests/server/test_coc_character_control.py
- 修改：tests/server/test_coc7_rulebook_regressions.py
- 修改：src/server/rules/coc_handlers.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/scenario/module_compiler.py
- 修改：src/server/player/router_player.py
- 修改：src/server/player/action_service.py
- 修改：src/server/models.py

### Step 1：写失败测试

- 高风险疯狂表现记录 AI 提议、Engine 拒绝、一次受限重试和固定安全替代；响应无被拒绝原文。
- 背景变化未获所属玩家确认前不写状态；拒绝后产生 Engine 安全替代且不阻塞他人。
- 临时疯狂按游戏内时间结束；不定疯狂只有已编译治疗/恢复节点可清除；伪造 recovered event 无效；永久疯狂不恢复。
- SAN=0 后原角色退出玩家控制并成为受限 NPC；仅安全场景可选择替补模板。
- 替补是当前 room-run 新实体，不复制旧角色私密记忆、状态或令牌。

### Step 2：最小实现

- 表现和背景提议写入现有 action/resolution 决定链。
- 不定疯狂恢复绑定 runtime package recovery node citation。
- 增加安全场景替补 API 与验证。
- AI 控制只发生在发作期或 SAN=0 受限 NPC 行为，不获得账号权限。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_coc_character_control.py tests/server/test_coc7_rulebook_regressions.py tests/server/test_rules.py tests/server/test_campaign_v2.py -q
git diff --check
git commit -m "feat: complete CoC character control transitions"
~~~

---

## Task 10：关键推进、唯一结局与原子归档

**文件：**

- 新增：tests/server/test_progression_recovery.py
- 修改：tests/server/test_module_compiler.py
- 修改：tests/server/test_ending_conditions.py
- 修改：tests/server/test_glass_rain_golden_flow.py
- 修改：tests/server/test_archive.py
- 修改：src/server/scenario/module_compiler.py
- 修改：src/server/ai/director.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/engine/ending_conditions.py
- 修改：src/server/campaign_archive.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：data/golden_modules/02-short-team-glass-rain/module.json

### Step 1：写失败测试

- 关键推进只有一个可被普通失败永久关闭的入口时，编译 gate 拒绝。
- recovery node 缺 citation、创造新 fact/clue 或无代价边界时拒绝。
- 当前路径耗尽只走合法 recovery node；无节点时只提示已公开未解决事实；再无信息时保持状态。
- AI 提议未编译 clue 不持久化。
- 结局 priority/exclusivity 保证唯一结果；safe_abort 最高；歧义产物在编译期拒绝。
- 结局、room completed、archive 和所有非终态 action 取消同事务；注入失败后全部回滚。
- epilogue 尝试写状态被拒绝。
- 最小 archive 不可普通 UPDATE/DELETE；受控双确认 purge 仍可执行。

### Step 2：最小实现

- 编译 critical_progression、alternative_paths、recovery_nodes、true_failure_conditions。
- Director 只看当前合法边和可用 recovery node；Engine 验证 citation 与条件。
- 结局输出 priority/exclusive group，运行时只接受唯一最高优先结果。
- 统一 end transaction，取消未提交 action 并写 archive；结语只读。
- 使用数据库保护或受控写路径保护 archive；purge 显式绕过并审计。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_progression_recovery.py tests/server/test_module_compiler.py tests/server/test_ending_conditions.py tests/server/test_glass_rain_golden_flow.py tests/server/test_archive.py -q
git diff --check
git commit -m "feat: guard progression and atomic endings"
~~~

---

## Task 11：AI 决策审计、归档分层、保留和敏感访问

**文件：**

- 新增：src/server/ai/decision_audit.py
- 新增：src/server/governance/retention.py
- 新增：tests/server/test_ai_decision_audit.py
- 新增：tests/server/test_retention_governance.py
- 新增：tests/server/test_sensitive_audit_access.py
- 修改：tests/server/test_admin_bulk_delete.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：src/server/ai/gateway.py
- 修改：src/server/ai/director.py
- 修改：src/server/engine/resolution_pipeline.py
- 修改：src/server/router_admin.py
- 修改：src/server/player/router_player_archive.py
- 修改：src/server/campaign_archive.py

### Step 1：写失败测试

- 每次权威 AI 决定审计包含 provider/model、template/rule version、最小上下文 hash、citations、结构化提议、Engine validation、final delta 和 expiry。
- 审计不含 token、账号身份、原始安全文本或无关秘密。
- 玩家只读公共解释和本角色私密 arc；其他角色 arc 拒绝；管理员默认只读运维元数据。
- 敏感读取缺事件单、理由、未过期提权或正确 scope 时拒绝；成功读取写访问 audit。
- 诊断 24 小时、AI 决定 90 天、账号/清除 audit 365 天；archive 不被常规 retention 删除。
- retention dry-run 不写数据；apply 使用同 cutoff/idempotency key，重试不重复审计。
- 删除账号继续清私密角色数据、匿名化公开 archive、墓碑化 actor。

### Step 2：最小实现

- 扩展 ai_call_logs，不另建平行 AI 日志系统。
- 对外部请求计算规范化最小上下文 hash，只保存 citation ID/版本和 Engine 结果。
- archive API 统一 public、self、admin-ops 投影。
- 敏感访问使用短时签名 grant，绑定 incident、actor、scope、expiry；每次使用写现有私密访问 audit。
- retention service 支持 dry-run/apply，由受保护管理操作或计划任务调用，不新增常驻后台线程。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_ai_decision_audit.py tests/server/test_retention_governance.py tests/server/test_sensitive_audit_access.py tests/server/test_admin_bulk_delete.py tests/server/test_archive.py tests/server/test_rag_security.py -q
git diff --check
git commit -m "feat: add decision audit and retention governance"
~~~

---

## Task 12：固定 provider 连续故障、暂停和显式切换

**文件：**

- 新增：src/server/ai/provider_health.py
- 新增：tests/server/test_room_provider_health.py
- 修改：src/server/db_adapter.py
- 修改：src/server/db_pg.py
- 修改：src/server/ai/gateway.py
- 修改：src/server/ai/ai_config.py
- 修改：src/server/router_rooms.py
- 修改：src/server/player/action_service.py
- 修改：src/server/events/events_registry.py

### Step 1：写失败测试

- 单次失败只触发受限重试或确定性 fallback，不暂停房间。
- 同一固定 binding 连续达到阈值后进入 paused_provider，新机械 action 拒绝，玩家收到脱敏通知。
- 成功调用按明确窗口重置连续失败计数。
- 恢复原 binding 需要健康检查和审计。
- 切换 provider/model 必须显式提交新版本、原因和确认；旧 binding 保留，参与者收到通知。
- 静默 PATCH 继续返回 409。

### Step 2：最小实现

- 健康计数绑定 room runtime binding version，不按全局 provider 混算。
- 只记录错误类别和时间，不保存完整 prompt 或秘密响应。
- AI-only 暂停不回退真人 Host。
- 显式切换创建新锁定 binding 版本并重置健康状态。

### Step 3：验证并提交

~~~powershell
python -m pytest tests/server/test_room_provider_health.py tests/server/test_ai_provider_config.py tests/server/test_director_runtime.py tests/server/test_action_drafts_v2.py -q
git diff --check
git commit -m "feat: pause rooms on sustained provider failure"
~~~

---

## Task 13：实现玩家端确认、回执、暂停和结局体验

**文件：**

- 新增：src/client/src/components/PlayerDecisionCard.tsx
- 新增：src/client/tests/player-decision-card.test.tsx
- 修改：src/client/src/components/CampaignHomePanel.tsx
- 修改：src/client/src/components/PlayerActionComposer.tsx
- 修改：src/client/src/pages/PlayerActionPage.tsx
- 修改：src/client/src/pages/PlayerLobby.tsx
- 修改：src/client/src/shared/player-api.ts
- 修改：src/client/src/shared/types.ts
- 修改：src/client/src/shared/player-current-priority.ts
- 修改：src/client/tests/campaign-home-panel.test.tsx
- 修改：src/client/tests/player-action-composer.test.tsx
- 修改：src/client/tests/player-action-controller.test.ts
- 修改：src/client/tests/player-current-priority.test.ts
- 修改：src/client/tests/player-api.test.ts

### Step 1：写失败测试

使用真实组件和完整 DTO fixture，mock 只停在 HTTP 边界：

- Session Zero 显示风险摘要、版本和确认状态；错误或旧版本不可标为完成。
- 澄清卡显示 2–3 个选项，未选择不能确认。
- 私密机械行动显示原因和公开重提，不显示普通确认按钮。
- PvP consent 只给被影响玩家接受/拒绝，拒绝后显示无机械效果。
- 初次失败后显示精确幸运消费和推骰风险；按钮调用 follow-up API，不重提原 action。
- 回执显示 receipt ID、规则版本、骰子、允许修正和最终 delta，不显示隐藏来源文本。
- read_only_recovery 和 paused_provider 显示只读原因并禁用机械 composer。
- completed 房间显示 archive 结局；刷新得到同一结局卡。

运行并观察 RED：

~~~powershell
Set-Location src/client
npm run test -- --run tests/player-decision-card.test.tsx tests/campaign-home-panel.test.tsx tests/player-action-composer.test.tsx tests/player-action-controller.test.ts tests/player-current-priority.test.ts tests/player-api.test.ts
~~~

### Step 2：最小实现

- 扩展 DTO，集中映射后端 reason code 到中文提示。
- PlayerDecisionCard 统一 risk、clarification、consent、luck/push，不复制确认实现。
- current priority 将安全暂停、consent、风险确认和 CoC follow-up 排在普通行动前。
- composer 只根据服务器权威状态启用。
- ending 卡只从 campaign archive 数据渲染。

### Step 3：验证并提交

~~~powershell
Set-Location src/client
npm run test -- --run tests/player-decision-card.test.tsx tests/campaign-home-panel.test.tsx tests/player-action-composer.test.tsx tests/player-action-controller.test.ts tests/player-current-priority.test.ts tests/player-api.test.ts
npm run build
Set-Location ../..
git diff --check
git commit -m "feat: surface authoritative player decisions"
~~~

---

## Task 14：扩展四人黄金样本并更新落实矩阵

**文件：**

- 修改：tests/server/test_glass_rain_golden_flow.py
- 新增：tests/server/test_glass_rain_four_player_flow.py
- 修改：data/golden_modules/02-short-team-glass-rain/module.json
- 修改：docs/10-现状盘点/2026-07-30-M0方案压力测试落实矩阵.md
- 新增：docs/10-现状盘点/2026-08-02-M0权威运行时验证记录.md

### Step 1：写四人黄金失败测试

完整使用四个预设角色，通过真实 HTTP/action/resolution 验证：

- 四人确认同一冻结风险契约。
- 一次玩家澄清、一次非冲突并发、一次 PvP 拒绝、一次安全暂停/恢复。
- 一次失败后的幸运或推骰两阶段决定。
- 合法 clue、recovery 和 progression，不产生 AI 自造线索。
- Narrator 故障时确定性继续。
- 达到 Engine 唯一结局，写 archive 并取消 pending action。
- 新房间不继承状态；当前房间 awaiting_host_exception 为零。

### Step 2：补齐黄金模块契约

- 添加 risk contract、critical progression、alternative path、recovery node、hidden-roll declaration 和 ending priority/exclusivity。
- 不添加缺少 citation 的故事事实。
- 原黄金测试不再绕过风险确认或 Host 策略。

### Step 3：更新矩阵与记录

- 决策 1–60 逐项写真实代码路径和测试名称。
- 只有行为测试通过才标记已落实。
- 浏览器、provider 或全量套件未验证时明确保留为未完成。

### Step 4：验证并提交

~~~powershell
python -m pytest tests/server/test_glass_rain_golden_flow.py tests/server/test_glass_rain_four_player_flow.py -q
git diff --check
git commit -m "test: verify four-player Glass Rain runtime"
~~~

---

## Task 15：自动化完整验证

### Step 1：顺序运行后端重点分组

~~~powershell
python -m pytest tests/server/test_rooms.py tests/server/test_room_risk_contract.py tests/server/test_room_security.py tests/server/test_reconnect.py -q
python -m pytest tests/server/test_action_policy.py tests/server/test_action_consents.py tests/server/test_action_concurrency.py tests/server/test_action_drafts_v2.py tests/server/test_action_lifecycle_v2.py -q
python -m pytest tests/server/test_runtime_integrity.py tests/server/test_event_log.py tests/server/test_state_service_consistency.py tests/server/test_archive.py -q
python -m pytest tests/server/test_reveal_ledger.py tests/server/test_director_runtime.py tests/server/test_spoiler_guard.py tests/server/test_rag_security.py -q
python -m pytest tests/server/test_coc_followup_decisions.py tests/server/test_coc_character_control.py tests/server/test_coc7_core_rules.py tests/server/test_coc7_rulebook_regressions.py -q
python -m pytest tests/server/test_progression_recovery.py tests/server/test_module_compiler.py tests/server/test_ending_conditions.py tests/server/test_glass_rain_golden_flow.py tests/server/test_glass_rain_four_player_flow.py -q
python -m pytest tests/server/test_ai_decision_audit.py tests/server/test_retention_governance.py tests/server/test_sensitive_audit_access.py tests/server/test_room_provider_health.py tests/server/test_admin_bulk_delete.py -q
~~~

不要并行运行共享数据库测试。

### Step 2：运行完整后端

~~~powershell
python -m pytest tests/server -q
~~~

若超时，保存命令、时限和最后输出，二分到明确共享状态或死锁并修复；不能用分组通过代替完整结论。

### Step 3：完整前端和构建

~~~powershell
Set-Location src/client
npm run test -- --run
npm run build
Set-Location ../..
git diff --check
git status --short
~~~

### Step 4：覆盖审计

- 对照设计完成定义和落实矩阵逐项检查。
- 搜索残留 awaiting_host_exception，逐个证明只属于非 AI-only 或不可达保护。
- 检查响应和日志不含 token、安全原文或其他玩家秘密。
- 检查 db_adapter.py 与 db_pg.py schema 一致。
- 失败修复后重跑受影响分组与完整门槛。

---

## Task 16：浏览器完成真实四人结局

**文件：**

- 修改：docs/10-现状盘点/2026-08-02-M0权威运行时验证记录.md

### Step 1：启动当前提交

~~~powershell
python dev.py --check
python dev.py
~~~

核实 5173 前端和 3001 后端进程来自当前仓库及当前提交，不使用陈旧服务。

### Step 2：建立真实会话

- 通过管理员 UI 安装或选择《玻璃雨夜》最新发布版本并创建房间。
- 创建或登录 4 个玩家账号，分别使用四个预设角色加入。
- 每个玩家通过 UI 完成当前风险契约确认。
- 保留房主和四个玩家页面；不得直接改数据库跳过产品步骤。

### Step 3：通过 UI 打到结局

至少完成：

- 公开调查和澄清。
- 非冲突并发 action 与逐次 consent。
- 安全暂停/恢复。
- 一次幸运或推骰 follow-up。
- 合法场景、线索和恢复节点推进。
- Engine 验证的最终结局。

记录关键页面状态。最终页面显示 archive 支持的结局卡，刷新后仍存在。

### Step 4：交叉验证

- 浏览器控制台无未处理异常和 Failed to fetch。
- 后端日志无 traceback、405、代理/CORS 错误或静默 Host 等待。
- 数据库中的 room completed、archive、四人 risk confirmation、roll receipt、consent、reveal 和 audit 一致。
- 当前房间不存在 awaiting_host_exception。
- 验证记录写明命令、时间、room ID、ending type、截图路径和任何限制。

### Step 5：提交验收证据

~~~powershell
git diff --check
git commit -m "docs: record M0 browser ending verification"
~~~

---

## Task 17：最终审计并推送 main

### Step 1：审计工作树和提交

~~~powershell
git status --short --branch
git log --oneline --decorate main..HEAD
git diff --stat main...HEAD
git diff --check main...HEAD
~~~

确认没有运行产物、秘密、临时数据库或无关用户修改。

### Step 2：刷新远端

~~~powershell
git fetch origin main
git log --oneline --left-right origin/main...HEAD
~~~

- origin/main 未前进时以 fast-forward 更新本地 main。
- origin/main 已前进时非破坏整合；冲突解决后重跑 Task 15 和必要浏览器回归。
- 禁止 reset --hard、checkout -- 和 force push。

### Step 3：在最终 HEAD 重验

~~~powershell
python -m pytest tests/server/test_glass_rain_golden_flow.py tests/server/test_glass_rain_four_player_flow.py -q
Set-Location src/client
npm run test -- --run
npm run build
Set-Location ../..
git diff --check origin/main...HEAD
~~~

### Step 4：更新并推送 main

仅在全部完成定义已有当前证据时：

~~~powershell
git branch -f main HEAD
git push origin main
git fetch origin main
git rev-parse HEAD
git rev-parse origin/main
git status --short --branch
~~~

本地 HEAD、本地 main 与 origin/main 必须指向同一已验证提交。推送失败或远端变化时不声称完成。

### Step 5：目标完成审计

逐条确认：

- 设计和计划已提交。
- 决策 1–60 有代码及真实行为证据。
- 自动化门槛与构建通过。
- 新鲜浏览器用 4 玩家到达并刷新验证结局。
- 远端 main 与已验证 HEAD 一致。

只有全部成立后才将持续目标标记为完成。
