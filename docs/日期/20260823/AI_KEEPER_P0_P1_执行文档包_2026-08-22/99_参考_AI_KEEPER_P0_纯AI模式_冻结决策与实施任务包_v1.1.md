# AI-Keeper P0 纯 AI 模式：冻结决策与实施任务包

> 文档状态：执行基线 v1.1（Decisions Frozen）  
> 更新日期：2026-08-22  
> 适用范围：CoC 7e、`runtime_version=v2`、`session_mode=ai_only`  
> 目标读者：产品、后端、前端、测试、Prompt、剧本运行时、运维与审计负责人  
> 决策状态：`P0-1-D01`～`P0-6B-D25` 已全部确认；P0 产品级待拍板问题为 **0**

---

## 0. 使用说明

本文件把纯 AI 模式已经冻结的产品决策转成可直接分工、开发、测试和验收的任务基线。

执行规则：

1. `D01`～`D25` 已全部确认，默认不得在实现阶段重新解释或降级执行。
2. 任何实现与本文件冲突时，应修改实现；如确需改变决策，必须先提交带影响分析的规范变更，不得以“现有代码就是这样”为理由保留旧逻辑。
3. 变更申请至少要包含：原决策 ID、变更原因、受影响模块、数据库/接口兼容性、测试变化、Golden Run 影响和回退方案。
4. 现有 PRD、`AI_ONLY_ACCEPTANCE_SPEC.md`、`soul.md`、`rules.md`、`contract.md` 和黄金模组仍是实现输入；与本文件冲突时，应先修订规范或记录正式例外。
5. `soul.md`、`rules.md`、`contract.md` 与 Glass Rain 实际运行包尚未完成正文级深审；后续发现的问题原则上作为缺陷和修复项处理，不重新打开已冻结的产品边界。
6. 本文件当前依据：`功能文档.md`、`CLAUDE.md`、`README.md` 及本轮 `D01`～`D25` 产品决策记录。

---

## 1. P0 总目标

纯 AI-Keeper 的验收目标是：

> 2–4 名玩家在没有人类 KP 理解意图、裁定规则、处理争议或推动剧情的情况下，从创建房间运行到 Engine 判定的 authored ending。AI 负责意图理解和叙事，确定性 Engine 仍是唯一权威状态写入者。

P0 工作链固定为：

```text
P0-1 纯 AI 边界与运行策略
→ P0-2 AI_ONLY_ACCEPTANCE_SPEC
→ P0-3 Prompt/DTO/Contract 对齐
→ P0-4 Glass Rain 剧本运行时强化
→ P0-6A Resolution Trace
→ P0-5 Golden Run
→ P0-6B Session Benchmark 与发布门禁
```

在 P0 达标前，新的规则系统、通用平台、复杂战斗、内容商城、图片/地图精修和任意时间线回滚继续暂缓。

---

# 2. 已确认决策总表

| 决策 ID | 决策主题 | 冻结结论 |
|---|---|---|
| `P0-1-D01` | 运行时角色 | 拆分 `RoomOwner`、`StageClient`、`LegacyHostAdjudicator` |
| `P0-1-D02` | 正常行动调度 | 服务器自动调度是 `ai_only` 唯一正常结算路径 |
| `P0-1-D03` | 风险与伤害确认 | 事前授权风险范围，结果产生后不得反悔 |
| `P0-1-D04` | 状态模型 | 动作状态、房间运行状态、结算结果和战役生命周期正交拆分 |
| `P0-1-D05` | Provider 全失败 | 按流水线阶段 Fail-Closed |
| `P0-1-D06` | 重试 | 技术恢复与游戏内再次尝试彻底分离 |
| `P0-1-D07` | 玩家异议 | 自动复核流水线 + 有界补偿 |
| `P0-1-D08` | 意图歧义 | 按候选是否改变权威结果路由 |
| `P0-1-D09` | 动作确认 | 按影响分级确认，不是所有动作都阻塞确认 |
| `P0-1-D10` | 玩家缺勤 | 确定性缺勤策略，AI 不代理玩家创造新行动 |
| `P0-1-D11` | 检查点恢复 | 系统生成确定性恢复方案，Owner 不选择历史结果 |
| `P0-1-D12` | Owner 手动结束 | 运营终止形成 `aborted`，不形成 authored ending |
| `P0-1-D13` | `session_mode` 冻结 | Session Zero 完成或首个权威 action 入队后永久冻结 |
| `P0-1-D14` | 运行版本束 | 规则、运行包、Prompt、场景哈希和 AI policy 在房间启动时固定 |
| `P0-1-D15` | 暂停语义 | 区分 `soft_pause` 与 `emergency_pause`，均在安全边界停止 |
| `P0-1-D16` | 规则/运行包不可用 | 开团前阻断；单动作无默认则拒绝；整体失效则系统暂停 |
| `P0-1-D17` | 移除离线玩家 | 吊销凭据、角色 inactive、不删除、不由 AI 接管 |
| `P0-1-D18` | Admin break-glass | 仅服务恢复、隔离、确定性恢复和终止；不得裁决或 patch 游戏结果 |
| `P0-2-D19` | Session Zero | 由 Engine 根据强制子项确定完成，不允许单按钮伪造 |
| `P0-4-D20` | 核心线索冗余 | 至少两个独立来源，或一个来源加已编译 recovery node |
| `P0-4-D21` | 场景/NPC 质量门禁 | 按重要性分级，必填字段或明确 exemption；缺失不得 `ready` |
| `P0-4-D22` | 多结局冲突 | 使用 `priority` + `mutual_exclusion_group`，编译期阻断冲突 |
| `P0-6A-D23` | Trace 保留与权限 | 完整 Trace 加密 30 天；脱敏 Trace 180 天；玩家档案保留可见摘要 |
| `P0-6B-D24` | Benchmark 规模 | 至少 30 场自动仿真 + 2 场真实浏览器多人 Golden Run |
| `P0-6B-D25` | 发布门槛 | 硬阻断 + 发布质量门槛两层执行，不接受口头豁免 |

---

# 3. 已确认决策详细规范

## 3.1 `P0-1-D01`：拆分 RoomOwner / StageClient / LegacyHostAdjudicator

### 结论

```text
RoomOwner ≠ StageClient ≠ LegacyHostAdjudicator
```

### RoomOwner

允许：

- 创建房间、邀请和移除玩家；
- 配置运营参数；
- 暂停、恢复、结束和归档；
- 查看脱敏系统健康状态；
- 发起受限的技术恢复。

禁止：

- 解释玩家意图；
- 选择技能、机制、难度、奖励骰或惩罚骰；
- 修改骰点、要求重投；
- 修改 HP、SAN、Luck、物品、线索和场景进度；
- 决定线索揭示和剧本结局；
- 处理普通行动争议。

### StageClient

- 只读消费公共投影；
- 不使用 `owner_token`；
- 不接收玩家私密事件、隐藏事实、管理数据；
- 无任何房间写权限。

### LegacyHostAdjudicator

- 仅为旧模式或未来 Human-KP 模式保留；
- `session_mode=ai_only` 中完全禁用；
- 服务端必须拒绝旧 Host 审查、重算、异常裁决和跳过接口，不能只隐藏前端按钮。

### 验收要求

```text
AIO-ROLE-001  ai_only 中不存在可用的人类裁决身份。
AIO-ROLE-002  StageClient 不持有 RoomOwner 权限。
AIO-ROLE-003  旧 Host 裁决接口在服务端返回稳定错误码。
AIO-ROLE-004  RoomOwner 离线不影响正常游戏链路。
```

---

## 3.2 `P0-1-D02`：服务器自动调度是唯一正常结算路径

### 标准链路

```text
玩家提交 action
→ Action 入队
→ 自动批次/回合调度器
→ 领取唯一 Resolution Job
→ ResolutionPipeline
→ completed / rejected / 等待玩家交互
```

`BatchCollector`、`TurnTimeoutWorker`、`GameLoop` 和恢复任务必须调用同一条幂等结算入口，不得各自实现不同裁决逻辑。

### ai_only 中禁用

```text
POST /api/host/{room_id}/turn/resolve
POST /api/host/{room_id}/turn/skip
```

RoomOwner 的“恢复”只能唤醒或恢复基础设施任务，不得触发、跳过、选择或重新裁定具体行动。

### 验收要求

```text
AIO-SCHED-001  普通行动不得等待 RoomOwner 点击。
AIO-SCHED-002  同一 action 只能被一个结算任务取得权威执行权。
AIO-SCHED-003  Owner 页面关闭后仍能完成整场运行。
AIO-SCHED-004  ai_only 中 turn/resolve 与 turn/skip 不可用于游戏控制。
```

---

## 3.3 `P0-1-D03`：风险采用事前授权

玩家确认的是风险类别、严重度上限和不可逆性质，不是精确骰点结果。

### 事前至少展示

```text
risk_categories
maximum_severity
possible_resource_cost
possible_position_or_status_change
irreversible_characteristics
affected_players
```

### 正常流程

```text
RiskContract
→ 玩家同意
→ Intent Contract 冻结
→ 生成规则计划
→ 生成 RollReceipt
→ Engine 计算并提交授权范围内的后果
```

结果产生后不再进行二次确认，玩家不能根据成功或失败选择是否接受。

### 必须重新取得 consent

- 后果超出原风险类别或严重度上限；
- 新增原声明中没有的不可逆后果；
- PVP 伤害、资源剥夺、行动限制或状态变化；
- 消耗不可恢复的共享资源；
- 放弃队友；
- 结局选择；
- 风险扩张；
- 系统将原动作解释成性质明显不同的动作。

### 验收要求

```text
AIO-RISK-001  Consent 必须发生在随机数生成之前。
AIO-RISK-002  授权范围内的失败结果不得事后撤销。
AIO-RISK-003  超范围后果必须重新取得 consent。
AIO-RISK-004  Consent 必须绑定 action、RiskContract 版本和状态版本。
```

---

## 3.4 `P0-1-D04`：状态模型正交拆分

### `action_status`

```text
analyzing
awaiting_confirmation
awaiting_player_choice
awaiting_player_consent
queued
batched
resolving
sync_required
completed
rejected
canceled
timeout
```

`awaiting_host_exception` 仅可读取历史记录；`ai_only` 禁止新建或迁入。`resolved` 不再作为正式动作状态，旧值映射为 `completed`。

### `room_runtime_status`

```text
lobby
running
paused_by_owner
paused_system
recovering
ended
```

### `resolution_outcome`

```text
success
failure
partial_success
no_check
blocked
not_applicable
```

### `campaign_lifecycle_status`

```text
active
finalized
archived
```

典型组合：

```json
{
  "action_status": "completed",
  "resolution_outcome": "failure",
  "room_runtime_status": "running",
  "campaign_lifecycle_status": "active"
}
```

### 禁止混用

```text
action_status = paused
action_status = safe_abort
action_status = resolved
resolution_outcome = completed
room_runtime_status = failure
```

### 验收要求

```text
AIO-STATE-001  流水线完成与游戏内失败可同时表达。
AIO-STATE-002  房间暂停不得伪装成 action 终态。
AIO-STATE-003  旧状态必须提供明确迁移映射。
AIO-STATE-004  非法状态跃迁必须被拒绝并审计。
```

---

## 3.5 `P0-1-D05`：Provider 全失败按阶段 Fail-Closed

### 权威副作用前失败

```text
全部 Provider 失败
→ 检查已登记、已测试的确定性 fallback
→ 有 fallback：继续
→ 无 fallback：action_status = rejected
→ 房间保持 running
```

不得用空字典、默认 DTO 或缺省字段继续权威结算。

### RollReceipt 已生成、状态尚未提交

- 保存并复用原 RollReceipt；
- 禁止重新生成随机数；
- 无法证明输入和状态基线有效时，`room_runtime_status=paused_system`。

### 状态已提交后失败

Narrator、SpoilerGuard 或 Projection 失败时：

- 不回滚规则结果；
- 不重新投骰；
- 不重复提交 mutations；
- 仅恢复 Reveal、Narration、SpoilerGuard 和 Projection；
- 无法保证受众安全时暂停系统。

### 验收要求

```text
AIO-PROVIDER-001  所有 Provider 失败不得返回空对象继续结算。
AIO-PROVIDER-002  Gateway 必须返回结构化 ProviderFailure。
AIO-PROVIDER-003  只有登记并测试通过的 fallback 可以产生 completed。
AIO-PROVIDER-004  权威一致性无法证明时必须 paused_system。
```

---

## 3.6 `P0-1-D06`：技术恢复与游戏内再次尝试分离

### `technical_retry`

表示继续同一个 action，必须复用：

```text
action_id
resolution_id
idempotency_key
intent_contract_version
rule_version_id
runtime_package_version_id
RollReceipt
已提交的状态事务
```

阶段恢复：

| 已完成阶段 | 技术恢复允许执行 |
|---|---|
| Director 尚未成功 | 重试同一任务或切换 Provider |
| Intent Contract 已冻结 | 从 MechanicCompiler 或后续阶段继续 |
| Mechanic Plan 已验证 | 从规则执行阶段继续 |
| RollReceipt 已生成 | 复用回执，禁止重投 |
| 状态事务已提交 | 只恢复 Reveal/Narration/SpoilerGuard/Projection |
| 最终投影已完成 | 返回已有结果，不重复广播业务事件 |

### `gameplay_reattempt`

玩家在游戏内“再试一次”必须创建新的 `action_id`，由 CoC 规则判断：

- 普通再次尝试；
- 孤注一掷；
- 更换方法或条件后再试；
- 不允许继续尝试。

### 验收要求

```text
AIO-RETRY-001  技术恢复不得产生第二份 RollReceipt。
AIO-RETRY-002  技术恢复不得重复提交状态事务。
AIO-RETRY-003  技术恢复不得重复揭示事实或线索。
AIO-RETRY-004  游戏内再次尝试必须创建新 action。
AIO-RETRY-005  断线、刷新、重复请求和 Owner 恢复不能获得额外骰点。
AIO-RETRY-006  状态提交结果未知时必须先查事务结果。
AIO-RETRY-007  技术恢复不得重新解释已确认 Intent Contract。
```

---

## 3.7 `P0-1-D07`：自动复核与有界补偿

### 可复核问题

```text
intent_misinterpreted
wrong_target
wrong_mechanic
wrong_difficulty
wrong_bonus_penalty
receipt_mismatch
state_mismatch
risk_contract_violation
reveal_error
projection_error
explanation_error
```

不构成有效复核的情况：

- 玩家看到失败后改变主意；
- 单纯不喜欢骰点；
- 事后更换原声明的方法；
- 用结算后获得的新信息重构原意图；
- 仅叙事风格不满意且无事实、规则或受众错误。

### 自动复核链路

```text
玩家提交 objection
→ 冻结原 action 证据
→ AI 重新解释原始语言
→ Engine 比较原 Intent Contract
→ RuleExecutor 复核规则与难度
→ verify_roll_receipt()
→ StateService 审计 mutations
→ RevealLedger 审计揭示
→ ProjectionDispatcher 审计受众
→ 输出复核结论
```

### 复核终态

```text
upheld
explanation_corrected
projection_repaired
compensated
review_rejected
system_paused
```

### 补偿约束

- 只追加新的 compensation transaction；
- 引用原 action、原 RollReceipt、原状态版本和错误码；
- 不删除原 action；
- 不覆盖原结果；
- 不修改原 RollReceipt；
- 默认不重新投骰；
- 不直接修改数据库；
- AI 不能自行提交补偿。

### 验收要求

```text
AIO-REVIEW-001  ai_only 申诉不得转交 RoomOwner 或 LegacyHostAdjudicator。
AIO-REVIEW-002  原始证据不可变。
AIO-REVIEW-003  确认错误时只追加补偿事务。
AIO-REVIEW-004  严重剧透即使补发纠正也仍记为安全失败。
```

---

## 3.8 `P0-1-D08`：意图歧义按结果影响差异路由

置信度仅用于候选排序、质量监控和 Benchmark，不单独决定是否询问玩家。

### 允许自动采用保守解释

候选在下列维度全部等价：

```text
target
method
mechanic
skill
difficulty
bonus_or_penalty_dice
resource_cost
risk_scope
state_effect
reveal_scope
audience
scene_progression
```

并且行动低风险、可逆、不影响其他玩家、不涉及秘密揭示差异、不消耗不可恢复资源。

### 必须进入 `awaiting_player_choice`

候选在以下任一维度不同：

- 是否检定；
- 技能、机制或难度；
- 目标对象；
- 风险或资源消耗；
- 其他玩家权益；
- 事实揭示；
- 场景推进；
- 不可逆后果。

向玩家展示 2–3 个经 Engine 过滤且不剧透的候选，以及“都不是，我补充说明”。

### 验收要求

```text
AIO-INTENT-001  confidence 不得作为唯一业务门禁。
AIO-INTENT-002  结果不同的候选必须询问玩家。
AIO-INTENT-003  自动解释必须选择最保守、最可逆候选。
AIO-INTENT-004  必须保留原输入、候选和路由原因。
```

---

## 3.9 `P0-1-D09`：普通动作按影响分级确认

### 三种交互保持独立

| 类型 | 目的 | 是否阻塞 |
|---|---|---|
| `confirmation` | 核验 AI 是否忠实理解原声明 | 仅实质改写时阻塞 |
| `choice` | 多个实质不同解释中选择 | 阻塞 |
| `consent` | 授权风险、跨玩家权益或重大不可逆后果 | 阻塞 |

### 普通动作自动入队

同时满足：

- 单一意图；
- 无实质歧义；
- 目标和方法来自原声明；
- 无新增风险；
- 无重要资源消耗；
- 不影响其他玩家；
- 无重大不可逆后果。

流程：

```text
analyzing
→ 非阻塞 interpreted_summary
→ queued
→ 自动结算
```

### 阻塞式 confirmation

适用于：

- 实质规范化；
- 推断目标或方法；
- 复合动作拆分；
- 步骤存在顺序依赖；
- 重要个人资源；
- 需玩家核验的隐含条件。

玩家可在权威 RollReceipt 生成前取消或修正；RollReceipt 生成后需走自动复核。

### 验收要求

```text
AIO-CONFIRM-001  普通低风险动作不得强制二次点击。
AIO-CONFIRM-002  实质改写必须在结算前确认。
AIO-CONFIRM-003  confirmation 不得替代 choice 或 consent。
AIO-CONFIRM-004  RollReceipt 生成后不得用普通取消撤回。
```

---

## 3.10 `P0-1-D10`：缺勤采用确定性策略

### 自由调查阶段

- 不为缺勤角色创建新行动；
- 不阻塞其他玩家；
- 不改变缺勤角色位置、立场和资源；
- AI 不代替其调查、交涉、移动或使用物品。

### 回合制阶段

`idle`：

```text
本回合无新的主动行动
```

`maintain_existing`：

仅延续玩家此前明确声明、确认且规则允许持续的行为，例如警戒、持续观察、准备动作或维持防御。

不得自动变成攻击、追击、资源消耗、谈判、路线选择或结局选择。

### 强制规则效果

Engine 可以继续执行：

- 持续伤害；
- 环境伤害；
- 状态倒计时；
- 已触发的强制检定；
- 已确认准备动作；
- 规则明确规定的被动效果。

### 可选反应

默认不执行。可允许玩家事前配置有限枚举策略，且不得使用共享资源、影响其他玩家或作出重大剧情决定。

### 验收要求

```text
AIO-ABSENT-001  玩家缺勤不得阻塞其他玩家独立行动。
AIO-ABSENT-002  AI 不得为缺勤角色创造主动行动。
AIO-ABSENT-003  Engine 可执行已成立的强制规则效果。
AIO-ABSENT-004  maintain_existing 只能延续已授权行为。
AIO-ABSENT-005  缺勤玩家在 consent 中按未同意处理。
AIO-ABSENT-006  RoomOwner 不得代理动作、确认、同意或投票。
```

---

## 3.11 `P0-1-D11`：检查点仅用于确定性技术恢复

RoomOwner 可以触发恢复检查或确认系统生成的方案，不能选择恢复到哪个历史结果。

### 标准流程

```text
room_runtime_status = paused_system
→ RuntimeIntegrity 收集状态、事件、事务和 RollReceipt
→ 识别最近可验证检查点
→ 计算检查点后的权威事务重放集合
→ 生成 recovery_proposal
→ 生成 proposal_hash
→ dry-run
→ 自动执行或由 Owner 确认同一方案
→ room_runtime_status = recovering
→ 恢复和完整性验证
→ running
```

### `recovery_proposal` 最小字段

```text
proposal_id
room_id
source_checkpoint_id
source_state_version
target_state_version
transactions_to_replay
roll_receipts_to_reuse
reveal_transactions_to_replay
projection_events_to_replay
integrity_checks
proposal_hash
expires_at
```

### 禁止

- Owner 指定任意检查点或恢复时间；
- 选择性跳过失败、伤害、SAN 或资源事务；
- 删除 RollReceipt；
- 重新投骰；
- 重新解释 Intent Contract；
- 重复 mutations 或线索揭示；
- 把玩家已经看到的秘密视为“未揭示”。

### 验收要求

```text
AIO-RECOVERY-001  ai_only 中 Owner 不得指定检查点。
AIO-RECOVERY-002  恢复方案必须由 RuntimeIntegrity 生成。
AIO-RECOVERY-003  恢复不得重新投骰、改写意图或丢弃权威事务。
AIO-RECOVERY-004  已向玩家揭示的信息不能通过回滚视为未发生。
AIO-RECOVERY-005  无法证明一致性时必须暂停。
AIO-RECOVERY-006  检查点恢复属于 technical_retry，不是游戏内时间回溯。
```

---

# 4. 统一权威链路

根据以上决策，`ai_only` 的目标链路冻结为：

```text
Player 原始输入
→ DirectorPlan（建议）
→ AiOnlyResolutionPolicy
→ Intent Contract
→ confirmation / choice / consent（按需）
→ MechanicCompiler
→ Engine 校验、规则版本绑定
→ RuleExecutor
→ RollReceipt
→ StateService 权威事务
→ RevealLedger
→ Narrator（仅引用授权 fact_ref）
→ SpoilerGuard
→ ProjectionDispatcher
→ Player / StageClient
```

基本不变量：

```text
AI 不直接写状态
RoomOwner 不裁决
StageClient 只读
LegacyHostAdjudicator 在 ai_only 中不可用
所有正常 action 自动调度
所有权威副作用幂等
所有玩家交互发生在相应权威边界之前
```

---

# 5. 可立即开工的实施任务包

以下任务不依赖第 7 节剩余问题，可立即安排开发。

## WP-A：角色与权限拆分

可能涉及：

```text
src/server/router_rooms.py
src/server/host/router_host.py
src/server/host/ws_manager.py
src/server/host/public_stage.py
src/client/src/pages/HostStage.tsx
src/client/src/pages/HostLobby.tsx
src/client/src/components/HostCampaignControls.tsx
鉴权 DTO / token scope / WebSocket role
```

任务：

1. 新增 `RoomOwner`、`StageClient`、`LegacyHostAdjudicator` 权限模型。
2. Stage 使用独立只读凭据或 public stage session。
3. `ai_only` 对 Host 审查、重算、异常裁决、turn resolve、turn skip 返回稳定错误码。
4. 前端移除或禁用对应功能，但服务端门禁是权威。
5. Owner HUD 仅显示运营和脱敏健康信息。

首批测试：

```text
test_ai_only_owner_cannot_adjudicate
test_ai_only_stage_has_no_owner_permission
test_ai_only_legacy_host_routes_rejected
test_ai_only_owner_offline_does_not_block
```

---

## WP-B：自动调度与单一结算入口

可能涉及：

```text
src/server/engine/resolution_pipeline.py
src/server/engine/batch.py
src/server/turn_manager.py
src/server/turn_timeout_worker.py
src/server/game_loop.py
player action background worker
```

任务：

1. 建立单一 `claim_and_resolve(action_id)` 幂等入口。
2. 所有调度源只负责创建/领取 job。
3. 使用条件更新或唯一 job key 防止并发重复结算。
4. `ai_only` 不再依赖 Host 手动触发。
5. 记录 `resolution_id`、job claim、attempt 和阶段游标。

测试：

```text
test_ai_only_action_auto_resolves
test_concurrent_workers_only_resolve_once
test_duplicate_submit_returns_existing_action
test_owner_offline_full_session_path
```

---

## WP-C：状态模型与迁移

任务：

1. 新增/规范化：
   - `action_status`
   - `room_runtime_status`
   - `resolution_outcome`
   - `campaign_lifecycle_status`
2. 建立旧值映射：
   - `resolved → completed`
   - 旧 `active/finalized/archived` 映射到对应生命周期字段。
3. 修改 DTO、事件和前端显示。
4. 为非法跃迁增加稳定错误码和审计。
5. 历史 `awaiting_host_exception` 只读兼容，ai_only 不得生成。

测试：

```text
test_completed_action_can_have_failure_outcome
test_room_pause_does_not_change_action_outcome
test_ai_only_cannot_enter_awaiting_host_exception
test_legacy_status_migration
```

---

## WP-D：Intent / Confirmation / Choice / Consent

可能涉及：

```text
src/server/ai/director.py
src/server/ai/contracts.py
src/server/player/action_service.py
src/server/engine/action_policy.py
src/server/engine/risk_contract.py
src/server/engine/action_consent.py
src/server/engine/action_state.py
```

任务：

1. Director 输出有限候选和候选差异维度。
2. Engine 比较候选的机制、风险、状态、揭示和场景推进差异。
3. 普通动作显示非阻塞理解摘要后自动入队。
4. 实质改写进入 `awaiting_confirmation`。
5. 实质候选差异进入 `awaiting_player_choice`。
6. 风险与跨玩家权益进入 `awaiting_player_consent`。
7. Consent 必须冻结在 RollReceipt 生成前。
8. 保存原输入、Intent Contract 版本、RiskContract 版本和路由原因。

测试：

```text
test_low_confidence_equal_outcome_does_not_force_choice
test_high_confidence_different_mechanics_requires_choice
test_simple_action_skips_blocking_confirmation
test_material_rewrite_requires_confirmation
test_consent_precedes_roll
test_authorized_failure_cannot_be_revoked_after_roll
```

---

## WP-E：ProviderFailure 与阶段恢复

可能涉及：

```text
src/server/ai/gateway.py
src/server/ai/providers.py
src/server/ai/provider_health.py
src/server/engine/resolution_pipeline.py
src/server/engine/fallback_narrative.py
```

任务：

1. 禁止 Gateway 在所有 Provider 失败时返回空 dict 继续。
2. 新增结构化 `ProviderFailure`：
   - task_type
   - attempts
   - last_error_code
   - fallback_available
   - retryable
3. 对每个 AI task 登记允许的确定性 fallback。
4. 保存流水线阶段游标和产物 ID。
5. 状态提交后只允许恢复输出侧阶段。
6. 连续核心故障达到阈值时进入 `paused_system`。

测试：

```text
test_all_provider_failure_never_returns_empty_success
test_pre_roll_provider_failure_rejects_action
test_post_roll_retry_reuses_receipt
test_post_commit_narrator_retry_does_not_reapply_state
test_projection_failure_replays_projection_only
```

---

## WP-F：幂等与技术恢复

任务：

1. 为 resolution、RollReceipt、state transaction、reveal transaction 和 projection 建立唯一键。
2. Technical retry 复用同一 action 和已完成产物。
3. Gameplay reattempt 强制创建新 action。
4. 状态提交未知时先查询事务记录。
5. 最终投影完成后重复请求返回已有结果。

测试：

```text
test_technical_retry_never_rerolls
test_technical_retry_never_reapplies_mutation
test_technical_retry_never_duplicates_reveal
test_gameplay_reattempt_requires_new_action
test_unknown_commit_state_queries_before_retry
```

---

## WP-G：自动复核与补偿

可能涉及：

```text
src/server/player/router_action_reviews.py
src/server/engine/compensation_service.py
src/server/engine/roll_receipt.py
src/server/engine/reveal_ledger.py
src/server/engine/projection.py
```

任务：

1. Host 审查入口从 ai_only 流程移除。
2. 新建自动 `ReviewCase` 和证据快照。
3. AI 只重新解释自然语言；Engine 复核规则、回执、状态和揭示。
4. 补偿使用追加事务。
5. 严重剧透生成安全事故，不能通过删除历史“修复”。
6. 输出机器可读复核终态。

测试：

```text
test_review_upheld_without_state_change
test_review_corrects_explanation_only
test_review_repairs_projection_only
test_review_compensation_is_append_only
test_review_never_rerolls_by_default
test_severe_reveal_remains_failed_metric
```

---

## WP-H：缺勤策略

任务：

1. 自由调查阶段缺勤不阻塞他人。
2. 回合阶段支持 `idle` 和严格的 `maintain_existing`。
3. 事前结构化缺勤反应使用有限枚举。
4. 缺勤玩家在 consent 中按未同意处理。
5. Owner 不能代理玩家行动和同意。

测试：

```text
test_absent_player_does_not_block_independent_actions
test_ai_never_creates_action_for_absent_player
test_maintain_existing_only_continues_authorized_action
test_forced_rule_effects_still_apply
test_absent_player_cannot_be_auto_consented
```

---

## WP-I：确定性恢复提案

可能涉及：

```text
src/server/events/event_log.py
src/server/engine/runtime_integrity.py
checkpoints / resolution_bundles / state transactions
```

任务：

1. 恢复入口不接受任意 checkpoint ID 作为 Owner 决策。
2. RuntimeIntegrity 生成 `recovery_proposal` 和 `proposal_hash`。
3. Dry-run 验证后执行。
4. 重放检查点后的原权威事务，而不是重新裁决。
5. 已公开秘密进入安全事故记录，不进行认知回滚。
6. 无可证明方案时维持 `paused_system`。

测试：

```text
test_owner_cannot_select_checkpoint
test_recovery_reuses_roll_receipts
test_recovery_replays_transactions_in_order
test_recovery_does_not_unreveal_seen_fact
test_invalid_proposal_hash_rejected
test_no_safe_recovery_keeps_room_paused
```

---

## WP-J：同步修订验收规范

将本文件的已确认决策回填到 `AI_ONLY_ACCEPTANCE_SPEC.md`：

1. 增加 Requirement ID。
2. 增加四套状态定义。
3. 增加重试阶段矩阵。
4. 增加自动复核终态。
5. 增加角色权限/API 门禁表。
6. 增加恢复提案约束。
7. 建立 Requirement → Module → Test → Metric 追踪矩阵。

---


## WP-K：房间终止、模式冻结、版本束与暂停语义

对应决策：`D12`～`D15`。

可能涉及：

```text
src/server/router_rooms.py
src/server/campaign_archive.py
src/server/runtime_lifecycle.py
src/server/models.py
src/server/engine/resolution_pipeline.py
src/server/turn_manager.py
rooms / runtime package binding / campaign finalization schema
前端 Lobby、Owner 控制与暂停状态展示
```

任务：

1. 区分 authored ending 与 Owner 运营终止；Owner 结束写入 `termination_reason=owner_terminated`、`ending_status=aborted`、`ending_id=null`。
2. 在 Session Zero 完成或首个权威 action 入队时冻结 `session_mode`。
3. 建立并持久化房间版本束：`runtime_package_version_id`、`rule_version_id`、`prompt_bundle_version`、`scenario_package_hash`、`ai_policy_version`。
4. 禁止进行中的房间静默跟随最新 Prompt、规则、场景或策略。
5. 实现 `soft_pause` 与 `emergency_pause`；记录暂停请求、阶段游标、安全边界和恢复原因。
6. 版本迁移仅允许在 `paused_system` 中，通过兼容性预检、显式确认和完整审计执行。

测试：

```text
test_owner_termination_is_aborted_not_authored_ending
test_session_mode_freezes_after_session_zero
test_session_mode_freezes_after_first_authoritative_action
test_room_version_bundle_is_immutable_during_run
test_new_release_does_not_change_running_room
test_soft_pause_stops_at_next_safe_boundary
test_emergency_pause_never_reverts_committed_effects
```

---

## WP-L：规则/运行包可用性与玩家移除

对应决策：`D16`、`D17`。

可能涉及：

```text
src/server/rule_source_lifecycle.py
src/server/scenario/content_package.py
src/server/engine/resolution_pipeline.py
src/server/router_rooms.py
src/server/host/ws_manager.py
src/server/engine/action_consent.py
characters / actions / device sessions / consent tables
```

任务：

1. 开团前验证绑定规则版本和 runtime package 均为可用、已审计、`ready`。
2. 单个 action 缺少安全规则默认时拒绝该 action，不使用模型常识补齐。
3. 已绑定规则版本或 runtime package 整体不可用、签名失败或完整性失败时进入 `paused_system`。
4. 移除玩家时立即吊销 token 和设备会话，角色标记 `inactive`，但保留状态和历史。
5. 未生成 RollReceipt 的未完成 action 取消；已生成 RollReceipt 的 action 按既定安全边界继续或恢复。
6. 旧 consent 统一过期；如仍需决策，按当前有效参与者重新生成，不能把离线或被移除视为同意。
7. 恢复角色控制必须通过显式重新邀请和身份绑定。

测试：

```text
test_room_cannot_start_with_unready_rule_or_runtime_package
test_action_without_safe_rule_default_is_rejected
test_bound_rule_integrity_failure_pauses_room
test_removed_player_token_is_revoked
test_removed_character_becomes_inactive_not_deleted
test_pre_roll_action_is_canceled_on_player_removal
test_post_roll_action_preserves_authoritative_receipt
test_pending_consents_are_expired_and_recreated
```

---

## WP-M：Admin break-glass 与验收污染标记

对应决策：`D18`。

可能涉及：

```text
src/server/router_admin.py
src/server/governance/
src/server/engine/runtime_integrity.py
src/server/ai/decision_audit.py
admin roles / audit events / room qualification fields
```

任务：

1. 建立独立的 `operations_admin` 与 `audit_admin` 权限范围。
2. 普通运维 Admin 只能查看脱敏健康信息、隔离 Provider/规则/运行包、触发确定性恢复或终止损坏房间。
3. 授权审计人员可在审计用途下读取加密完整 Trace，但不得修改权威游戏状态。
4. 所有 Admin 游戏状态 patch、改骰点、代替 consent、选择 ending 的接口在 `ai_only` 中服务端拒绝。
5. 不可避免的数据修复必须通过独立迁移任务执行，写入完整审计，并将房间标记 `acceptance_disqualified=true`。
6. 被人工数据修复的场次不得计入 Golden Run 或 Benchmark 有效样本。

测试：

```text
test_operations_admin_cannot_patch_game_state
test_admin_cannot_change_roll_or_ending
test_admin_cannot_respond_to_player_consent
test_audit_admin_full_trace_access_is_scoped_and_logged
test_manual_data_repair_disqualifies_acceptance_run
test_break_glass_can_quarantine_and_terminate_only
```

---

## WP-N：Session Zero 开团门禁

对应决策：`D19`。

可能涉及：

```text
src/server/router_rooms.py
src/server/player/router_player_settings.py
src/server/player/router_reconnect.py
src/server/engine/risk_contract.py
src/server/engine/action_consent.py
src/client/src/pages/HostLobby.tsx
src/client/src/pages/PlayerLobby.tsx
```

任务：

1. 将 Session Zero 拆成 Engine 可验证的子项，而不是单一布尔按钮。
2. 强制检查：所有角色 ready、内容警告/边界确认、风险和 consent 规则确认、私密/公共投影测试、缺勤策略、版本束锁定、设备重连验证。
3. 由 Engine 计算 `session_zero_completed`；客户端只能展示进度，不能直接写完成。
4. 未完成 Session Zero 时禁止进入 `running` 或接受首个权威 action。
5. 任何子项失效时必须重新计算门禁状态。

测试：

```text
test_session_zero_cannot_be_completed_by_single_client_flag
test_all_required_subchecks_are_enforced
test_private_and_public_projection_probe_required
test_device_recovery_probe_required
test_incomplete_session_zero_blocks_first_action
test_version_bundle_locks_when_session_zero_completes
```

---

## WP-O：Glass Rain 剧本质量门禁与确定性结局

对应决策：`D20`～`D22`。

可能涉及：

```text
data/golden_modules/02-short-team-glass-rain/module.json
src/server/scenario/module_compiler.py
src/server/scenario/quality.py
src/server/scenario/content_package.py
src/server/engine/ending_conditions.py
scenario DTO / JSON schema / quality report
```

任务：

1. 为每个 `importance=core` 的线索验证：两个独立来源，或一个来源加一个已编译 recovery node。
2. “独立来源”必须避免共享同一个单点失败前置条件；不得把 AI 临场创造视为替代来源。
3. 为主要场景补齐 purpose、entry/exit、pressure_clock、escalation_events、improv_boundaries。
4. 为主要 NPC 补齐 goals、knowledge refs、secret refs、fears、attitude、reaction_rules、improv_boundaries。
5. 不适用字段必须提供机器可读 `exemption_code` 和说明。
6. Ending 增加 `priority` 和 `mutual_exclusion_group`；编译期检测同组同优先级冲突。
7. 运行时由 Engine 确定性选择最高优先级 authored ending；无法唯一选择时不得结局提交。
8. 上述缺失或冲突均阻止 runtime package 进入 `ready`。

测试：

```text
test_core_clue_requires_two_sources_or_recovery_node
test_shared_single_failure_does_not_count_as_independent_sources
test_major_scene_quality_gate
test_major_npc_quality_gate
test_exemption_requires_code_and_reason
test_ending_conflict_blocks_package_ready
test_engine_selects_highest_priority_ending_deterministically
```

---

## WP-P：Resolution Trace 保留、脱敏与访问控制

对应决策：`D23`。

可能涉及：

```text
src/server/ai/decision_audit.py
src/server/governance/retention.py
src/server/engine/resolution_pipeline.py
src/server/engine/projection.py
trace storage / encryption / export / archive APIs
```

任务：

1. 完整 Trace 加密保存 30 天，仅授权 `audit_admin` / 开发审计身份访问，所有读取均审计。
2. 脱敏 Trace 和聚合指标保存 180 天。
3. 玩家可见的解释、RollReceipt 摘要、状态变化和投影结果随战役档案保存。
4. RoomOwner 和 StageClient 不得读取未揭示秘密、原始 Prompt 或其他玩家私密内容。
5. 完整 Trace 不进入普通应用日志；导出前执行字段白名单和秘密分级。
6. 每个 Trace 保存完整性校验值，以支持篡改检测和回放验证。
7. 到期清理由 retention job 执行，并生成清理审计记录。

测试：

```text
test_full_trace_is_encrypted_and_role_scoped
test_owner_and_stage_cannot_read_secret_trace
test_redacted_trace_contains_no_forbidden_fields
test_full_trace_retention_is_30_days
test_redacted_trace_retention_is_180_days
test_player_archive_keeps_only_player_visible_evidence
test_trace_integrity_hash_detects_tampering
```

---

## WP-Q：Session Benchmark、真实 Golden Run 与发布门禁

对应决策：`D24`、`D25`。

可能涉及：

```text
scripts/run_multiplayer_loop.py
scripts/run_golden_module_suite.py
新增 AI-Keeper Session Benchmark runner
CI / release report / metrics aggregation
真实浏览器 E2E 工装
```

任务：

1. 自动仿真总量至少 30 场：2 人不少于 15 场，4 人不少于 15 场。
2. 覆盖正常、谨慎、偏航、暴力、沉默、规则质疑和套取秘密型玩家。
3. 至少完成 2 场真实浏览器多人 Golden Run；从新房间开始，不复用旧状态。
4. 记录随机种子、版本束、玩家模型、故障注入配置和完整 Trace，使失败可复现。
5. 执行 D25 硬阻断；任一硬阻断非零即停止发布候选。
6. 执行发布质量门槛；所有目标达到后才生成 `release_candidate_passed=true`。
7. 口头豁免无效；任何阈值调整必须修订验收规范并保留变更记录。
8. 人工修复、Admin 状态 patch、Owner 终止或 Trace 不完整的场次不得计入有效样本。

测试与报告：

```text
test_benchmark_requires_minimum_30_sessions
test_benchmark_has_15_two_player_and_15_four_player_runs
test_real_browser_evidence_count_is_at_least_two
test_any_hard_blocker_fails_release_candidate
test_quality_thresholds_are_calculated_with_defined_denominators
test_disqualified_run_is_excluded_from_success_rate
test_benchmark_failure_is_reproducible_from_seed_and_version_bundle
```


# 6. 实施优先级与依赖

## 6.1 第一波：先消除人类裁决和静默错误

可并行启动：

```text
WP-A 角色与权限拆分
WP-B 自动调度与单一结算入口
WP-C 状态模型与迁移
WP-E ProviderFailure 与阶段恢复
WP-F 幂等与技术恢复
WP-K 模式/版本束/暂停/终止
WP-L 规则包可用性与玩家移除
WP-M Admin break-glass
```

第一波合并门槛：

- `ai_only` 不再进入 Host 裁决；
- 普通 action 自动结算；
- `completed` 与游戏内 `failure` 可正交表达；
- Provider 全失败不再以空对象继续；
- 技术恢复不重复投骰、状态提交或线索揭示；
- 运行中的房间版本束不可静默变化；
- Admin、Owner 均无法改变游戏内裁决结果。

## 6.2 第二波：完善玩家控制、复核和开团门禁

```text
WP-D Intent / Confirmation / Choice / Consent
WP-G 自动复核与补偿
WP-H 缺勤策略
WP-I 确定性恢复提案
WP-N Session Zero 门禁
WP-P Trace 保留与访问控制
```

依赖关系：

- WP-D 依赖 WP-C 的状态枚举；
- WP-G 依赖 WP-F 的幂等产物和 WP-P 的证据链；
- WP-I 依赖 WP-F 的阶段产物与事务唯一键；
- WP-N 依赖 WP-A、WP-K 的身份和版本束；
- WP-P 应在 Golden Run 前完成，不能事后补 Trace。

## 6.3 第三波：剧本运行时和发布验证

```text
WP-O Glass Rain 质量门禁与结局确定性
WP-Q Session Benchmark 与发布门禁
```

依赖关系：

```text
WP-O 完成
+ WP-P Trace 可用
+ 第一、第二波回归通过
→ 才允许 P0-5 Glass Rain Golden Run
→ 再进入 WP-Q 批量 Benchmark 与发布判定
```

## 6.4 持续同步

`WP-J` 在所有波次持续进行：每个 Requirement ID 必须同步到 `AI_ONLY_ACCEPTANCE_SPEC.md`、代码、测试和指标追踪矩阵。

---
# 7. 补充已确认决策详细规范（D12～D25）

## 7.1 `P0-1-D12`：Owner 手动结束只形成运营终止

Owner 可以终止房间，但不能选择胜利、混合、失败等剧本结局。

```text
room_runtime_status = ended
campaign_lifecycle_status = finalized
termination_reason = owner_terminated
ending_status = aborted
ending_id = null
```

只有 Engine 根据已冻结运行包中的 ending conditions 提交的 authored ending，才计入有效结局率。Owner 终止可以生成中止档案，但不得伪装成剧本内结局。

```text
AIO-END-001  Owner 终止不得产生 authored ending。
AIO-END-002  Owner 不得选择 victory/mixed/failure。
AIO-END-003  aborted 场次不得计入 authored-ending 到达率分子。
AIO-END-004  中止原因、操作者和时间必须审计。
```

---

## 7.2 `P0-1-D13`：`session_mode` 在进入权威运行前冻结

Lobby 阶段可以选择模式；以下任一条件先发生即永久冻结：

```text
session_zero_completed = true
或
首个权威 action 成功入队
```

运行中不能从 `ai_only` 切换到 Human-KP，也不能先切出再切回。需要其他模式时创建新房间并重新完成 Session Zero。

```text
AIO-MODE-001  冻结后任何客户端、Owner 或 Admin 均不能直接修改 session_mode。
AIO-MODE-002  模式切换不得作为故障恢复或申诉手段。
AIO-MODE-003  模式冻结事件必须进入 Trace 和审计日志。
```

---

## 7.3 `P0-1-D14`：房间运行版本束固定

房间进入运行前固定：

```text
runtime_package_version_id
rule_version_id
prompt_bundle_version
scenario_package_hash
ai_policy_version
```

管理员发布新版本不得改变进行中房间。升级仅允许在 `paused_system` 中，通过显式兼容迁移：预检、dry-run、迁移计划哈希、审计、执行后完整性验证。

```text
AIO-VERSION-001  每个 action Trace 必须记录完整版本束。
AIO-VERSION-002  运行中不得隐式使用 latest 版本。
AIO-VERSION-003  Provider 切换不得改变 Prompt/规则/策略版本。
AIO-VERSION-004  兼容迁移必须显式且可回放。
AIO-VERSION-005  未经批准的版本变化使该场验收失效。
```

---

## 7.4 `P0-1-D15`：区分软暂停与紧急暂停

### `soft_pause`

- 停止接收新的游戏 action；
- 已领取的 action 完成当前原子阶段并持久化阶段游标；
- 到达下一个安全边界后停止，不开始新的权威阶段。

### `emergency_pause`

- 立即发出停止信号；
- 在下一个副作用前检查点停止；
- 已经提交的骰点、状态事务和揭示不得撤销；
- 转入 technical recovery，而不是取消或重跑整个 action。

安全边界至少包括：随机数生成前、RollReceipt 已持久化后、状态事务提交后、最终投影后。

```text
AIO-PAUSE-001  暂停不得删除已提交权威副作用。
AIO-PAUSE-002  soft_pause 不接受新 action。
AIO-PAUSE-003  emergency_pause 在下一个可证明安全的副作用边界停止。
AIO-PAUSE-004  恢复必须从阶段游标继续。
AIO-PAUSE-005  暂停不能被用来获得重投或改写意图。
```

---

## 7.5 `P0-1-D16`：规则或运行包不可用时分级处理

- 开团前发现绑定规则版本或 runtime package 不可用：阻止开始。
- 单个 action 缺少规则且无已登记安全默认：拒绝当前 action，房间保持运行，并给出可行动替代。
- 已绑定规则版本或 runtime package 整体不可用、签名失败、完整性失败：`room_runtime_status=paused_system`。
- 不得回退到其他未绑定版本、Prompt 常识或模型自由裁决。

```text
AIO-RULESRC-001  未 ready 的规则/运行包不得开团。
AIO-RULESRC-002  单动作无安全规则时只能 rejected。
AIO-RULESRC-003  绑定版本整体失效必须 paused_system。
AIO-RULESRC-004  不允许静默回退到其他版本。
AIO-RULESRC-005  故障原因和受影响版本必须进入 Trace。
```

---

## 7.6 `P0-1-D17`：移除玩家不删除角色，也不由 AI 接管

移除离线玩家时：

- 立即吊销玩家 token、WebSocket 和设备会话；
- 角色标记 `inactive`，保留状态、历史、私密信息和归属记录；
- AI 不接管角色；
- 未生成 RollReceipt 的 action 取消；
- 已生成 RollReceipt 的 action 按安全边界完成或恢复；
- 待处理 consent 过期，必要时按当前有效参与者重新创建；
- 角色恢复控制必须通过显式重新邀请和身份绑定。

```text
AIO-REMOVE-001  移除玩家不得删除角色历史。
AIO-REMOVE-002  AI 不得自动接管 inactive 角色。
AIO-REMOVE-003  凭据和设备会话必须立即吊销。
AIO-REMOVE-004  已生成的 RollReceipt 不得因移除而作废或重投。
AIO-REMOVE-005  旧 consent 不得静默按通过处理。
AIO-REMOVE-006  恢复控制必须显式审计。
```

---

## 7.7 `P0-1-D18`：Admin break-glass 不包含游戏裁决权

Admin 可以：

- 恢复服务；
- 隔离 Provider、规则源或运行包；
- 查看权限范围内的 Trace；
- 执行系统生成的确定性恢复方案；
- 隔离、终止损坏房间。

Admin 不得：

- 修改骰点；
- 修改 HP/SAN/物品/线索或场景进度；
- 选择剧情结局；
- 代替玩家 consent；
- 直接修补数据后继续把该场计为有效 Golden Run。

普通运维 Admin 默认只读脱敏 Trace；只有专门授权并受审计的 `audit_admin` 可读取加密完整 Trace。不可避免的数据修复必须走独立迁移并标记该场不具备验收资格。

```text
AIO-ADMIN-001  break-glass 不能产生游戏内裁决。
AIO-ADMIN-002  Admin 状态 patch 在 ai_only 中服务端拒绝。
AIO-ADMIN-003  确定性恢复方案不可由 Admin 改写。
AIO-ADMIN-004  完整 Trace 访问必须最小权限并记录审计。
AIO-ADMIN-005  人工数据修复必须使 acceptance_disqualified=true。
AIO-ADMIN-006  被取消资格场次不得计入 Golden Run/Benchmark。
```

---

## 7.8 `P0-2-D19`：Session Zero 由 Engine 计算完成

多人 `ai_only` 开团前必须完成：

- 所有角色 ready；
- 内容警告和玩家边界确认；
- RiskContract 与 consent 规则确认；
- 私密投影和公共投影探测成功；
- 缺勤策略确认；
- 版本束锁定；
- 玩家设备会话与断线恢复探测成功。

`session_zero_completed` 是 Engine 根据子项计算的派生状态，任何单一按钮或客户端字段都不能直接将其置为 true。

```text
AIO-SZ-001  所有强制子项完成后才可进入 running。
AIO-SZ-002  客户端不得直接写 session_zero_completed。
AIO-SZ-003  每位玩家的边界和风险确认必须可追踪。
AIO-SZ-004  私密/公共投影必须实际探测。
AIO-SZ-005  缺勤策略必须在开团前冻结初始值。
AIO-SZ-006  版本束必须在完成时锁定。
AIO-SZ-007  设备恢复探测失败不得开团。
AIO-SZ-008  子项失效时 Engine 必须重新计算门禁。
```

---

## 7.9 `P0-4-D20`：核心线索必须具有编译期冗余

每个 `importance=core` 的线索必须满足：

```text
至少 2 个独立获取来源
或
1 个获取来源 + 1 个已编译 recovery node
```

“独立”表示获取链路不能共享同一个未替代的单点失败前置条件。AI 临场补线索、自由编造新 NPC 或直接给提示不计为替代路径。

```text
AIO-CLUE-001  core clue 必须满足冗余门禁。
AIO-CLUE-002  来源独立性必须由编译器验证。
AIO-CLUE-003  recovery node 必须有稳定 ID、触发条件和揭示范围。
AIO-CLUE-004  不合格核心线索阻止 runtime package=ready。
```

---

## 7.10 `P0-4-D21`：场景和 NPC 采用分级质量门禁

主要场景必须具备：

```text
purpose
entry_conditions
exit_conditions
pressure_clock
escalation_events
improv_boundaries
```

主要 NPC 必须具备：

```text
goals
knowledge_fact_refs
secret_fact_refs
fears
attitude
reaction_rules
improv_boundaries
```

不适用字段必须提供机器可读 `exemption_code` 和说明。缺失必填字段、仅依赖 `raw_text` 或模型常识补足时，运行包不得进入 `ready`。

```text
AIO-SCEN-001  场景/NPC 必须显式标记重要性。
AIO-SCEN-002  主要对象必须通过分级必填门禁。
AIO-SCEN-003  exemption 必须可审计、可测试。
AIO-SCEN-004  模型常识不能替代核心运行字段。
AIO-SCEN-005  质量报告必须列出阻断项和对象 ID。
```

---

## 7.11 `P0-4-D22`：结局由 Engine 确定性选择

Ending 增加：

```text
priority: integer
mutual_exclusion_group: string | null
```

编译期检测同一互斥组中同优先级且可能同时成立的结局；存在冲突则拒绝发布。运行时由 Engine 在已满足的 authored endings 中确定性选择最高优先级。无法唯一选择时不得提交结局，必须视为运行包缺陷。

```text
AIO-ENDING-001  AI 不得选择最终 ending。
AIO-ENDING-002  结局冲突必须在编译期阻断。
AIO-ENDING-003  运行时选择必须仅依赖冻结状态和版本束。
AIO-ENDING-004  tie 或不唯一结果不得按文件顺序静默选择。
AIO-ENDING-005  ending 提交必须记录条件证据和状态版本。
```

---

## 7.12 `P0-6A-D23`：Trace 分层保留和最小权限访问

- 完整 Trace：包含秘密和原始 AI 输入/输出，加密保存 30 天，仅授权 `audit_admin` / 开发审计人员访问。
- 脱敏 Trace 与聚合指标：保存 180 天。
- 玩家可见解释、RollReceipt 摘要、状态变化和投影：随战役档案保留。
- RoomOwner 与 StageClient 不得访问未揭示秘密、原始 Prompt 或其他玩家私密信息。

```text
AIO-TRACE-001  完整 Trace 必须加密、完整性校验并限制访问。
AIO-TRACE-002  完整 Trace 保留 30 天。
AIO-TRACE-003  脱敏 Trace/指标保留 180 天。
AIO-TRACE-004  玩家档案只保留该玩家合法可见证据。
AIO-TRACE-005  所有完整 Trace 读取和导出必须审计。
AIO-TRACE-006  Retention 清理必须可证明执行。
```

---

## 7.13 `P0-6B-D24`：首轮 Benchmark 至少 30 场自动仿真

最小样本：

```text
自动仿真总场次 ≥ 30
2 人配置 ≥ 15
4 人配置 ≥ 15
真实浏览器多人 Golden Run ≥ 2
```

必须覆盖正常、谨慎、偏航、暴力、沉默、规则质疑和套取秘密型玩家，并记录随机种子、版本束、玩家模型和故障注入配置。

```text
AIO-BENCH-001  样本数量不足不得形成发布结论。
AIO-BENCH-002  2 人与 4 人样本均必须达到最低数量。
AIO-BENCH-003  至少两场真实浏览器证据。
AIO-BENCH-004  每场必须可由种子和版本束复现。
AIO-BENCH-005  被人工修复或中止的场次不得作为成功样本。
```

---

## 7.14 `P0-6B-D25`：发布门槛采用硬阻断与质量门槛两层

### 硬阻断

以下任一非零或不满足即阻断发布：

```text
Host/人工裁决次数 > 0
ai_only awaiting_host_exception > 0
非法权威写入 > 0
严重剧透 > 0
重复骰点 > 0
重复状态提交 > 0
不可恢复卡死 > 0
Trace 完整率 < 100%
```

### 发布质量门槛

```text
authored ending 到达率 ≥ 80%
动作澄清率 ≤ 15%
有机械影响的静默误解 = 0
普通文本动作 P95 ≤ 15 秒
真实玩家清晰度/主动权/氛围平均 ≥ 4/5
```

测量口径必须在 Benchmark 规范中固定：Owner 中止不算 authored ending；玩家等待时间不计入服务端 P95；确认/choice/consent 响应不计入自然语言动作澄清率分母。临时放宽只能通过正式修订验收规范，不接受口头豁免。

```text
AIO-GATE-001  任一硬阻断失败即 release candidate 失败。
AIO-GATE-002  质量指标必须使用固定分母和排除规则。
AIO-GATE-003  所有指标同时达标后才可恢复 P1/P2。
AIO-GATE-004  阈值变化必须有版本化规范变更记录。
AIO-GATE-005  不合格场次不得通过人工剔除美化结果。
```

---

# 8. 团队分工与最小交付物

| 责任域 | 主要工作包 | 最小交付物 |
|---|---|---|
| 产品/架构 | WP-J、D01～D25 追踪 | 冻结规范、ADR/例外记录、Requirement Traceability Matrix |
| 后端核心引擎 | WP-B、WP-C、WP-E、WP-F、WP-I、WP-K、WP-L | 幂等主链、阶段游标、状态迁移、恢复与版本束 |
| 权限/运维/治理 | WP-A、WP-M、WP-P | 身份拆分、服务端门禁、break-glass、Trace ACL/retention |
| AI/Prompt/DTO | WP-D、WP-E、WP-G | Director 候选、结构化失败、复核、Prompt/Contract 对齐 |
| 玩家端/Owner/Stage UI | WP-A、WP-D、WP-H、WP-K、WP-N | 分级确认、只读 Stage、暂停/门禁/缺勤交互 |
| 剧本运行时 | WP-O | Glass Rain 字段补齐、质量报告、结局冲突门禁 |
| QA/自动化 | 全部，重点 WP-Q | 单元/集成/故障注入、30 场 Benchmark、2 场真实浏览器证据 |

每个工作包提交时必须附：

1. 关联 Decision ID / Requirement ID；
2. 修改文件和数据库迁移说明；
3. 新增/修改测试；
4. 可观测字段和错误码；
5. 对 Golden Run 的影响；
6. 已知未完成项，不得用“后续优化”隐藏阻断缺陷。

---

# 9. 决策—工作包—验收映射

| 决策范围 | 主要工作包 | 核心验收证据 |
|---|---|---|
| D01 | WP-A | 权限测试、Stage 只读证据、旧 Host API 拒绝 |
| D02 | WP-B | Owner 离线完整行动链、并发只结算一次 |
| D03 | WP-D | consent 在 RollReceipt 前、授权后果不可事后撤销 |
| D04 | WP-C | 状态迁移、正交状态组合、非法跃迁测试 |
| D05 | WP-E | Provider 全失败结构化错误、无空对象继续 |
| D06 | WP-F | 不重投、不重复 mutation/reveal、gameplay reattempt 新 action |
| D07 | WP-G | 自动复核、追加补偿、原证据不可变 |
| D08～D09 | WP-D | 候选差异路由、普通动作非阻塞、实质改写确认 |
| D10 | WP-H | 缺勤不阻塞、AI 不代理、强制规则效果可执行 |
| D11 | WP-I | 系统恢复提案、Owner 不选 checkpoint、事务重放 |
| D12～D15 | WP-K | 中止非结局、模式冻结、版本束固定、暂停安全边界 |
| D16～D17 | WP-L | 规则包故障路由、玩家移除与 action/consent 收敛 |
| D18 | WP-M | Admin 无裁决权、人工修复取消验收资格 |
| D19 | WP-N | Engine 计算 Session Zero、投影/设备探测证据 |
| D20～D22 | WP-O | Glass Rain quality gate、线索冗余、结局确定性 |
| D23 | WP-P | Trace 加密、ACL、30/180 天 retention、玩家档案脱敏 |
| D24～D25 | WP-Q | 30+ 自动场次、2+ 浏览器场次、发布门禁报告 |

所有映射最终应落入机器可读追踪表：

```text
Requirement ID
→ Implementation Module
→ Test Case
→ Runtime Metric
→ Evidence Artifact
→ Blocking Level
```

---
# 10. P0 完成定义

## P0-1 完成

- `D01`～`D18` 已全部冻结并落入代码、Schema、API 和测试；
- `ai_only` 不存在人类裁决路径；
- Owner 离线不影响正常行动；
- Provider、重试、复核、缺勤、暂停和恢复均有确定性闭环；
- 模式与版本束不可静默改变；
- Owner/Admin 无法通过运营接口改变游戏内结果；
- 对应回归与故障注入测试通过。

## P0-2 完成

- `AI_ONLY_ACCEPTANCE_SPEC.md` 已吸收 `D01`～`D25`；
- 所有强制条款具有 Requirement ID；
- 状态、重试、权限、异常、Session Zero、Trace 和指标无歧义；
- Requirement → Module → Test → Metric → Evidence 可追踪。

## P0-3 完成

- `soul.md`、`rules.md`、`contract.md` 和运行时 DTO 完成正文级审查；
- AI 输出权限、Schema、正反例和 fallback 可测试；
- Prompt 不承担 Engine 权威职责；
- Prompt bundle 有独立版本并进入房间版本束。

## P0-4 完成

- Glass Rain 的场景、NPC、线索、失败推进、压力、临场边界和结局字段达到 quality gate；
- 每个核心线索满足 D20；
- 场景/NPC 满足 D21；
- 结局满足 D22；
- 不依赖 `raw_text` 或模型常识补齐核心运行信息。

## P0-6A 完成

- 每个进入 ResolutionPipeline 的 action 具有完整 Resolution Trace；
- 可定位 Director、机制、骰点、状态、揭示、叙事、反剧透和投影阶段；
- 完整 Trace 加密、权限和 retention 符合 D23；
- Trace 完整率在验收样本中为 100%。

## P0-5 完成

- `02-short-team-glass-rain` 从新房间开始；
- 覆盖 2–4 名玩家；
- Owner 页面可全程离线；
- 覆盖歧义、失败推进、Provider 降级、断线恢复、玩家移除/缺勤、暂停恢复和 authored ending；
- 无人工改库、人类裁决、重复骰点或非法状态写入；
- 至少一场达到 `victory` 或 `mixed`，同时证明其他 authored ending 可确定性结束。

## P0-6B 完成

- 自动仿真和真实浏览器样本达到 D24；
- 硬阻断与质量门槛达到 D25；
- 生成整场 Trace、浏览器证据、故障注入结果和指标汇总；
- 所有成功样本均未被 Owner 中止、Admin 修补或人工裁决污染；
- 通过后才恢复 P1/P2 扩展。

---

# 11. 当前结论与下一步

`D01`～`D25` 已全部选择 A，P0 的产品边界、运行策略、剧本门禁、Trace 保留、Benchmark 规模和发布口径现已冻结。

```text
剩余产品级待拍板问题：0
```

团队可以立即按以下顺序推进：

```text
第一波：WP-A/B/C/E/F/K/L/M
→ 第二波：WP-D/G/H/I/N/P
→ 第三波：WP-O
→ P0-5 Glass Rain Golden Run
→ WP-Q Benchmark 与发布门禁
```

下一轮仍可能出现两类问题：

1. 审查 `soul.md`、`rules.md`、`contract.md`、DTO 和 Glass Rain 实际文件时发现的内容缺陷；
2. 实现中发现的技术约束、迁移风险和兼容问题。

这两类默认进入缺陷清单或变更申请，不再通过口头讨论重新打开纯 AI 产品边界。只有确实改变 D01～D25 的方案，才需要提交正式规范变更。
