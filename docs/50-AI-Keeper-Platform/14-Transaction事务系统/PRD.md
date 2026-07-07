# Transaction 事务系统 PRD V2.1

## 当前阶段

本 PRD 对应的是：

- `P0 主链路 + 行动/回合/演出事务可靠性风险识别版`
- 不是 Transaction 模块的最终生产安全完成版
- 重点修正 duplicate 原子化、State/Projection 顺序、Host ACK、release gate、retry-turn 语义

## 背景

AI-Keeper 的核心不是“玩家发一句话，AI 回一句话”，而是把一条意图安全地推进成：

`玩家提交 -> 入账 -> 裁决 -> 权威状态写入 -> 分层投影 -> 审计沉淀`

当前仓库已经有：

- `actions` 行动账本
- `room_turns` 回合账本
- `ResolutionPipeline`
- `StateService`
- `ProjectionDispatcher`
- `HostStore`
- reconnect / archive / checkpoint 基础设施

但事务边界仍然分散，尤其有三类核心风险：

1. 同一角色同一 turn 的 second action 仍可能在并发下双写。
2. action 当前可能先被标成 `resolved`、先对外投影，再去写 State。
3. Host 演出和 Player 私密结果释放之间还没有完整可审计的 gate 契约。

## 产品目标

1. 把 `action`、`turn`、`host reveal` 三层事务统一成一条可追溯链路。
2. 保证 duplicate、retry、重连场景不重复结算、不重复投影、不提前泄露私密结果。
3. 固化“先 State，后 Projection”的提交顺序。
4. 给 Host 舞台建立最小可恢复的 ACK / gate 契约。
5. 让 Journal、Timeline、State、Projection 围绕同一套 trace 字段工作。

## 非目标

1. 不在 Transaction 内实现规则数学。
2. 不在 Transaction 内信任 AI 直接落库。
3. 不让 Host 前端承载规则结算或世界真相写入。
4. 不在第一轮强制引入完整 `transactions` 大表。
5. 不在本轮扩展观众流、直播延迟、多舞台协作。

## 用户角色

| 角色 | 需要什么 | 不允许什么 |
| --- | --- | --- |
| Player | 提交行动、看到排队状态、收到完成回执、重连恢复 pending action | 冒充他人 action、同回合刷第二个动作、直接写状态 |
| Host | 看到 Host-safe 演出事务、暂停/重播/急救、确认演出 step | 直接修改规则结果、绕过服务端释放私密结果 |
| Admin | 排障、恢复、审计、处理 stuck 事务 | 静默改事实、不留审计 |
| Engine / Rule | 校验意图、计算裁决、生成 `ResolutionResult` | 在 State 未落库前宣布 action 完成 |
| State | 持久化权威变化，返回版本化结果 | 决定规则结果是否成立 |
| Projection / Journal | 下发事件、记录序列和回放索引 | 反向当作状态写入口 |

## 事务数据分层

| 层级 | 数据对象 | 含义 | 边界 |
| --- | --- | --- | --- |
| L0 | `PlayerIntent` | 玩家请求 | 不等于已入账 action |
| L1 | `ActionLedger` (`actions`) | action 事务账本 | 不等于世界状态 |
| L2 | `TurnLedger` (`room_turns`) | turn 收集与结算账本 | 不等于日志 sequence |
| L3 | `ResolutionResult` | Rule / AI 输出 | 不等于已落库真相 |
| L4 | `AppliedStateChange` | State 已确认写入结果 | Projection 只消费它 |
| L5 | `ProjectionEnvelope` | Host / Player / Party 的投影事件包 | 不改裁决结果 |
| L6 | `RevealTransaction` | Host 演出事务 | 不得含 player-only 私密载荷 |
| L7 | `ReleaseGate` | 演出后的私密释放门 | 只能由服务端控制 |
| L8 | `EventLog` (`events.sequence`) | 审计、补发、回放顺序 | 不替代状态写入 |
| L9 | `HostStageState` (`host_states`) | Host 舞台恢复态 | 不是世界真相 |
| L10 | `TransactionTrace` | `actionId/turnId/transactionId/stateVersion/sequence` 的追溯链 | 不能断链 |

## DTO 契约

### 1. `PlayerIntentDTO`

最低字段：

- `actionId`
- `intentType`
- `declaredIntent`
- `baseStateVersion`
- `params`

用途：

- 描述玩家一次幂等提交
- 不能直接代表已入账事务

### 2. `ActionTransactionDTO`

最低字段：

- `actionId`
- `roomId`
- `characterId`
- `intentType`
- `status`
- `turnId?`
- `baseStateVersion`
- `createdAt`

用途：

- 表示 action 账本对象

### 3. `ActionReceiptDTO`

最低字段：

- `actionId`
- `roomId`
- `characterId`
- `turnId?`
- `status`
- `baseStateVersion`
- `accepted`
- `duplicate`

要求：

- 不能只返回 `actionId/status`
- 要能解释“为何 accepted 或 duplicate”

### 4. `ActionResultDTO`

最低字段：

- `actionId`
- `status`
- `reason?`
- `resolutionSummary?`
- `stateVersion?`
- `transactionId?`

用途：

- Player 查询 action 状态时使用

### 5. `TurnTransactionDTO`

最低字段：

- `turnId`
- `roomId`
- `turnIndex`
- `status`
- `submittedCharacterIds[]`
- `pendingActionIds[]`

### 6. `TurnSettlementDTO`

最低字段：

- `turnId`
- `turnIndex`
- `status`
- `resolvedActionIds[]`
- `rejectedActionIds[]`
- `summary`
- `sourceEventSequence?`

### 7. `ResolutionTransactionDTO`

最低字段：

- `transactionId`
- `actionId`
- `turnId`
- `roomId`
- `characterId`
- `baseStateVersion`
- `stateVersion?`
- `resolutionStatus`
- `failureClass?`

### 8. `RevealTransactionDTO`

最低字段：

- `transactionId`
- `actionId`
- `turnId`
- `roomId`
- `baseStateVersion`
- `stateVersion?`
- `priority`
- `steps[]`
- `releaseGates[]`
- `summaryText?`

硬约束：

- 不能缺 `actionId/turnId`
- 不能混入 player-only payload

### 9. `ReleaseGateDTO`

最低字段：

- `gateId`
- `transactionId`
- `afterStepId`
- `eventsToRelease[]`
- `targetCharacterId`
- `released`

硬约束：

- 释放条件由服务端决定
- Host 重连后仍能恢复 gate 状态

### 10. `HostStepAckDTO`

最低字段：

- `transactionId`
- `actionId`
- `turnId`
- `stepId`
- `ackBy`
- `ackAt`
- `releasedEventSequences[]`

硬约束：

- 只表示演出进度确认
- 不承载规则结果或状态 mutation

### 11. `TransactionTraceDTO`

最低字段：

- `actionId`
- `turnId`
- `turnIndex`
- `transactionId`
- `baseStateVersion`
- `stateVersion?`
- `eventSequences[]`
- `journalRefs[]`

### 12. `RetryTurnRequestDTO`

最低字段：

- `roomId`
- `turnId`
- `mode`
- `reason`
- `actorAccountId`
- `affectedActionIds[]`

## 核心状态机

### Action 状态机

```text
submitted
  -> queued
  -> batched
  -> resolving
  -> resolved

submitted
  -> rejected

queued / batched / resolving
  -> timeout
  -> cancelled

system_skip
  -> resolved
```

约束：

1. `resolved/rejected` 的 action 再次 resolve，必须直接返回已有结果。
2. 不能重复写 State mutation。
3. 不能重复发 Projection 事件。
4. `system_skip` 与玩家主动提交必须区分。

### duplicate 占位状态集

第一轮默认把以下状态视为“已占用本回合动作槽”：

- `queued`
- `batched`
- `resolving`
- `resolved`
- `timeout`

第一轮默认把以下状态视为“不占用本回合动作槽”：

- `rejected`
- `cancelled`
- `system_skip`

补充说明：

1. `timeout` 默认继续占位，避免玩家通过超时绕过“同回合单动作”约束。
2. 只有 Host / Admin 通过 `cancelled`、`retry-turn` 或 `restore_from_checkpoint` 明确处置后，动作槽才会释放。
3. 如果后续产品决定改变 `timeout` 语义，工程回执必须明确说明。

### Turn 状态机

```text
collecting
  -> resolving
  -> resolved

collecting / resolving
  -> blocked
```

约束：

1. `mark_resolving()` 必须是条件更新。
2. 只有拿到 resolving 权限的 worker 才能继续 settle。
3. `resolved` turn 默认不能直接进入“重新应用状态 mutation”的 retry。

### Host Reveal Transaction 状态机

```text
created
  -> queued
  -> active
  -> step_acknowledged
  -> completed

active
  -> interrupted
  -> resumed
  -> cancelled
```

约束：

1. Host ACK 只确认演出进度。
2. release gate 满足前，Player 私密结果不能释放。
3. Host 重连后不能重复播放已 ACK step。

## 关键编号边界

第一轮必须把以下四个概念写硬：

- `turn_index`：属于 Timeline / Transaction 共用的回合顺序
- `events.sequence`：属于 Journal / Projection 的事件顺序
- `rooms.state_version`：属于 State 的权威世界版本
- `transactionId`：属于某次裁决或演出链路的追溯标识

四者不能互相替代。

## 核心流程

### 1. 玩家提交行动

1. Player 调用 `POST /api/player/intent`，携带 `action_id`、`base_state_version`。
2. 服务端根据 token 反查角色身份，不信任前端自报 `characterId`。
3. active 房间先确认当前 collecting turn，再检查“同角色同 turn 是否已有非 rejected/cancelled/system_skip action”。
4. duplicate 校验通过后，才允许写 `actions`、绑定 `turn_id`、发 queued 回执。
5. 同一 `action_id` 重试走幂等返回，不重复写入。
6. 同一角色同一 turn 的第二个不同 action 返回 409。

### 2. 回合收集与结算

1. `room_turns` 负责 turn 收集和状态推进。
2. 所有 active 玩家提交完成后，后台任务尝试 `collecting -> resolving`。
3. 只有 `mark_resolving()` 返回成功的 worker 可以继续。
4. worker 顺序处理该 turn 的 queued actions。
5. 全部动作处理结束后，写 turn summary，标记 `resolved`，再决定是否创建下一条 collecting turn。

### 3. 单 action 裁决事务

目标顺序固定为：

```text
lock action
-> mark resolving
-> compute resolution
-> write actions.result
-> apply State
-> emit Projection
-> mark completed
```

其中：

1. `actions.result` 可以在 State 前持久化为“裁决结果”，但不能因此提前宣布 `resolved` 对外完成。
2. `StateService.apply_change()` 成功后，才能生成带 `stateVersion` 的 patch/completed/reveal。
3. 如果 State 失败，action 不能保持“看起来已完成”的 resolved 语义。

### 4. Host 演出与私密释放

1. Projection 生成 `RevealTransactionDTO`，只包含 Host-safe steps。
2. Player 私密 `state_patch`、`private_notice`、`action_completed` 不直接下发，而是进入 `ReleaseGateDTO`。
3. Host 发送 `host_step_complete` 或等价 ACK 时，服务端验证 Host 身份和 `transactionId/stepId`。
4. gate 满足后，服务端才释放对应 player 事件，并记录 `HostStepAckDTO`。

#### Host-safe step 白名单

第一轮建议固定以下允许进入 `s2c_reveal_transaction.steps[]` 的 Host-safe step：

- `roll` 摘要
- `status_delta` 安全摘要
- `scene_transition`
- `narrative_text`
- `public clue summary`
- `map safe summary`

第一轮明确禁止进入 Host reveal payload 的内容：

- `player-only state patch`
- `private_notice`
- 他人私密线索原文
- 未公开 clue 原文
- raw mutation 明细
- hidden truth / spoiler truth
- raw debug / raw AI payload

### 5. retry-turn 语义

第一轮固定为三种模式：

- `replay_only`：只重播 Host 演出，不重算规则、不重写 State
- `recompute_unresolved`：只处理 `queued/resolving` 且尚未完成 State 提交的 action
- `restore_from_checkpoint`：走 10/11/13 的 checkpoint restore 语义

默认规则：

- 已经 `resolved` 的 turn 不能默认重放 State mutation
- 所有 retry 都必须带 `reason/actorAccountId/targetTurnId/mode`

### 6. 重连与恢复

1. Player 重连只看自己可见事件和自己的 pending actions。
2. Host 重连需要恢复 queue、active transaction、current step、delayed events、ack 进度中的最小可用集。
3. 如果 `host_states` 无法稳定恢复这些状态，再引入最小 `transactions` 表。

## 失败分级与补偿语义

第一轮至少区分：

- `precondition_failed`
- `rule_failed`
- `ai_schema_failed`
- `state_apply_failed`
- `projection_failed`

规则：

1. `precondition_failed/rule_failed/ai_schema_failed` 可归入 `rejected`，但必须给玩家可解释回执。
2. `state_apply_failed` 不能把 action 当作正常 `resolved`。
3. `projection_failed` 需要明确是否可重放投影，且不能重复应用状态 mutation。
4. 如果 State 已成功而 Projection 失败，恢复策略只能是 replay Projection / redelivery event，不能重跑 Rule，也不能重写 State。
5. 所有 Host/Admin 急救操作都要写审计。

## `host_states` 与 `transactions` 表决策标准

第一轮先不强制新建 `transactions` 表，但要用下面的标准判断：

如果 `host_states` 能稳定持久化并恢复以下信息：

- `normalQueue`
- `urgentQueue`
- `activeTransaction`
- `currentStepIndex`
- `acknowledgedSteps`
- `delayedEvents`
- `interruptedTransaction`
- `completedTransactions` 摘要

则本轮可以继续不建表。

无论继续使用 `host_states` 还是新增最小 `transactions` 表，都必须满足：

- `ReleaseGateDTO` 不能只存在于内存
- Host 重连后必须能知道哪些 gate 尚未释放
- 已 ACK 的 step 不能因重连重复播放

如果做不到，就应新增最小 `transactions` 表，仅保存：

- `transaction_id`
- `room_id`
- `action_id`
- `turn_id`
- `status`
- `current_step_index`
- `payload`
- `created_at`
- `completed_at`

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| TX-FR-1 | `action_id` 是玩家动作幂等键，同一 action 不得重复写库或重复结算 | P0 |
| TX-FR-2 | 同一角色同一 turn 只能存在一个有效玩家 action | P0 |
| TX-FR-3 | duplicate 保护必须有数据库级唯一约束或同事务锁，不得只依赖普通先查再写 | P0 |
| TX-FR-4 | `base_state_version` 冲突必须拒绝提交并返回 `currentVersion` | P0 |
| TX-FR-5 | 普通 action 入队不得推进 `rooms.state_version` | P0 |
| TX-FR-6 | 同一 turn 只允许一个 worker 完成 settle | P0 |
| TX-FR-7 | `resolved/rejected` action 重复 resolve 必须直接返回已有结果 | P0 |
| TX-FR-8 | State 写入成功前不得发版本化 patch 或完成事件 | P0 |
| TX-FR-9 | Host reveal transaction 必须可追溯到 `actionId/turnId/stateVersion` | P0 |
| TX-FR-10 | Player 私密结果必须经由 release gate 释放 | P0 |
| TX-FR-11 | Host ACK 必须可审计、可恢复 | P1 |
| TX-FR-12 | `retry-turn` 必须区分 replay / recompute / restore | P1 |
| TX-FR-13 | `transactionId` 必须能绑定 `actionId/turnId/eventSequences` | P1 |
| TX-FR-14 | `s2c_turn_resolved` 等事务事件必须统一进入 registry / model / TS 类型 | P1 |
| TX-FR-15 | `state_apply_failed/projection_failed` 必须有明确恢复语义 | P1 |

## 接口方向

| 接口 / 事件 | 当前现状 | 目标受众 | 说明 |
| --- | --- | --- | --- |
| `POST /api/player/intent` | 已有 | Player | action 提交入口 |
| `GET /api/player/actions/{action_id}` | 已有 | Player | 只查询自己的 action |
| `GET /api/player/reconnect` | 已有 | Player | 恢复 pending actions 和可见事件 |
| `GET /api/rooms/{room_id}/turns/current` | 已有 | Host/Admin | 当前实现会隐式创建 collecting turn |
| `POST /api/rooms/{room_id}/turns/{turn_id}/retry` | 已有 | Host/Admin | 需要补模式化语义 |
| `POST /api/host/{room_id}/retry-turn` | 已有 | Host/Admin | 当前只重置 active transaction step |
| `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character` | 已有 | Host/Admin | 生成 `system_skip` 行为 |
| `s2c_action_queued` | 已有 | Player | action 入队回执 |
| `s2c_reveal_transaction` | 已有 | Host | Host-safe 演出载体 |
| `s2c_state_patch` | 已有 | Player | 需要补版本字段 |
| `s2c_action_completed` | 已有 | Player | 需要补 trace/version 字段 |
| `s2c_public_observation` | 已有 | Party | 公共叙事 |
| `s2c_turn_resolved` | 已 emit | Party | 需补 registry/model/TS 一致性 |

### 当前接口遗留约束

`GET /api/rooms/{room_id}/turns/current` 当前实现会通过 `ensure_current_turn()` 隐式创建 collecting turn。

第一轮允许暂时保留这一现状，但工程回执必须明确说明：

1. 当前是否继续保留隐式创建；
2. 调用方是否限制为 Host / Admin；
3. 是否会破坏 `collecting/resolving/resolved` 语义；
4. 后续是否迁移为显式 `init/ensure turn` 接口。

## 数据边界

1. `actions` 是 action 事务账本。
2. `room_turns` 是 turn 事务账本。
3. `events` 是投影 / 审计记录，不是未落库状态的唯一事实来源。
4. `host_states` 是 Host 舞台恢复缓存，不是世界真相。
5. `transactionId` 不是 `turnId`、不是 `stateVersion`、不是 `events.sequence` 的替代品。

## 权限边界

1. Player 只能提交和查询自己的 action。
2. Host 只能确认演出进度，不能上送规则结果或状态 mutation。
3. Admin 能急救，但必须写审计。
4. AI 输出只能作为裁决建议，不能直接进入状态落库。
5. Projection 负责分层可见性，不允许 Transaction 把私密内容塞进 Host payload。

## 验收标准

1. 同一 `action_id` 重试只保留一条 action，且不重复 queued。
2. 同一角色同一 turn 第二个不同 action 返回 409，数据库不留额外 queued action。
3. duplicate 保护在并发下仍成立，不靠前端兜底。
4. turn settle 并发时只有一个 worker 能进入 resolving。
5. `resolved/rejected` action 重复 resolve 不重复写 State、不重复投影。
6. `StateService` 失败时 action 不会伪装成正常 resolved。
7. `s2c_state_patch` 和 `s2c_action_completed` 带 `actionId/baseStateVersion/stateVersion` 或等价 trace。
8. `s2c_reveal_transaction` 带 `transactionId/actionId/turnId/stateVersion` 或等价引用。
9. Host payload 不包含 player-only 私密 patch。
10. Player 私密 patch / completed 不早于 Host 安全演出点。
11. retry-turn 默认不重放已落库 mutation。
12. Host / Player 重连后，不重复结算、不重复播放、不提前泄露私密结果。
