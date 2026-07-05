# Transaction 事务系统 PRD V2.0

## 背景

AI-Keeper 的核心链路不是“玩家发一句话，AI 回一句话”，而是“玩家意图进入受控事务，系统裁决，权威状态变更，按可见性投影，日志沉淀”。当前代码已经有 `actions`、`room_turns`、`ResolutionPipeline`、`StateService`、`ProjectionDispatcher`、`HostStore` 和重连查询，但事务边界仍分散：入队、回合绑定、裁决、状态写入、投影、Host 播放和 Player 解锁没有统一闭环。

Transaction v1 的目标是先把这条链路锁稳，不扩展复杂平台功能。

## 目标

1. 玩家 action 具备幂等、去重、状态机和可查询回执。
2. 回合事务能从 collecting 安全推进到 resolving 和 resolved，不会并发重复结算。
3. 裁决事务保证“验证通过后写入、失败可解释、重复不重算”。
4. 权威状态先持久化，投影和完成事件后发送。
5. Host reveal transaction 和 Player 私密结果存在清晰时序屏障。
6. 所有关键事务都能从 `action_id`、`turn_id`、`transactionId`、event sequence 追溯。

## 非目标

- 不在 Transaction 内实现技能、战斗、追逐等规则。
- 不让 Host 前端承载规则逻辑或改写裁决结果。
- 不让 AI 直接生成数据库写入命令。
- 不在第一轮强制新增大型 `transactions` 表。
- 不做观众延迟流、多舞台同步、剪辑式回放。
- 不替代 State、Projection、Journal、Timeline 的职责。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Player | 提交行动、看到排队/结算/失败回执、重连后恢复 pending action | 伪造他人 action、重复刷回合行动、直接写状态 |
| Host | 看到公共演出事务、暂停/恢复/急救、处理卡住的回合 | 直接裁决规则、读取玩家私密结果、绕过 Engine 改状态 |
| Engine | 校验意图、维护 action 状态、调用 Rule/AI/State/Projection | 在状态未持久化前宣布完成 |
| State | 接收已校验 StateChangeSet 并写权威状态 | 决定 action 是否成功 |
| Projection | 按受众投递事件并维护日志 sequence | 修改规则结果或世界真相 |
| Journal/Ops | 查询事务链路、定位失败、支持恢复 | 修改历史事实 |

## 状态机

### Action 状态机

```text
submitted
  -> queued
  -> resolving
  -> resolved

submitted
  -> rejected

queued / resolving
  -> timeout
```

当前数据库以 `actions.status` 记录 `queued/resolving/resolved/rejected`，模型中已有 `batched/timeout`，但工程闭环尚不完整。

### Turn 状态机

```text
collecting
  -> resolving
  -> resolved
  -> collecting(next)

collecting / resolving
  -> blocked
```

`room_turns` 记录 `turn_id`、`turn_index`、status、summary。Transaction 只保证结算顺序，游戏内时间表达归 Timeline。

### Host Reveal Transaction 状态机

```text
created
  -> queued
  -> active
  -> step_acknowledged
  -> completed

active
  -> interrupted
  -> resumed / cancelled
```

当前 HostStore 有 normal/urgent queue、active transaction、interrupted transaction 和 delayed events，但缺少持久化 ACK 与完整 completed 事件。

## 核心流程

### 玩家提交行动

1. Player 调 `POST /api/player/intent`，带 `action_id`、`intent_type`、`declared_intent`、`base_state_version`、`params`。
2. 服务端用 `X-Room-Token` 反查角色，不信任前端传来的 characterId。
3. 系统校验 room、当前状态版本、当前 turn、同回合重复提交。
4. 校验通过后写 `actions`，绑定 `turn_id`，发 queued 回执。
5. 重复提交同一 `action_id` 返回 accepted，不重复写库。
6. 同一玩家同一 turn 第二个不同 action 返回 409，不产生新 queued action。

### 回合收集与结算

1. active 房间使用 `room_turns` 收集行动。
2. 所有 active 玩家完成提交后，turn 通过条件更新进入 resolving。
3. 后台 worker 顺序 resolve 本 turn 的 queued actions。
4. 每个 action 完成后写 result、状态变更、投影事件。
5. turn 完成后写 summary，标记 resolved，创建下一 turn。

### 单个 action 裁决事务

1. Pipeline 把 action 从 queued 改为 resolving。
2. 读取 character、room、scenario、inventory 等裁决上下文。
3. 预校验移动、遭遇等硬规则前置条件。
4. MechanicCompiler 和 RuleExecutor 产出 `ResolutionResult`。
5. 失败时写 rejected 和完成回执，不发公共剧情。
6. 成功时先持久化 `actions.result`，再由 StateService 写权威状态。
7. State 写入成功后，Projection 发 Host reveal、state patch、public observation、action completed。

### Host 演出事务

1. Projection 生成 `s2c_reveal_transaction`，payload 内含 `transactionId`、priority、steps、summaryText。
2. HostStore 将普通事务入 normal queue，urgent 事务可抢占 active transaction。
3. Host 前端播放 roll/status/narrative 等 step。
4. 关键 step 完成后发送 `host_step_complete`。
5. 服务端释放该 step 之后允许送达的 delayed player events。
6. 完成 ACK 应写入 event 或 transaction state，供重连和审计使用。

### 重连与恢复

1. Player 调 `/api/player/reconnect`，返回 recent events、pending actions、last sequence、stateVersion。
2. Player 调 `/api/player/actions/{action_id}` 查询自己的 action，不能查他人 action。
3. Host 重连时恢复 HUD、last_host_sequence、delayed events，并在 P1 增强 active transaction 恢复。
4. 重连后的 patch 应受 `stateVersion` 屏障控制，避免乱序覆盖。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| TX-FR-1 | `action_id` 是玩家行动幂等键，同一 action 不得重复写库或重复结算。 | P0 |
| TX-FR-2 | active 房间必须先通过 turn duplicate 校验，再写新 action 或发 queued 事件。 | P0 |
| TX-FR-3 | `base_state_version` 非 0 且落后当前版本时拒绝提交。 | P0 |
| TX-FR-4 | action 入队不应推进世界 `rooms.state_version`。 | P0 |
| TX-FR-5 | 同一 turn 只能有一个结算 worker 获得 resolving 权限。 | P0 |
| TX-FR-6 | resolved/rejected action 再次被 resolve 时应直接返回，不重复投影和落状态。 | P0 |
| TX-FR-7 | Rule/AI 裁决失败必须进入 rejected，并给玩家可解释回执。 | P0 |
| TX-FR-8 | StateService 写入成功后才能发版本化 state patch 和 action completed。 | P0 |
| TX-FR-9 | Host reveal transaction 不得包含 player-only 私密 payload。 | P0 |
| TX-FR-10 | Player 私密 patch 和 completed 不得早于 Host 安全演出点。 | P0 |
| TX-FR-11 | `transactionId` 应能关联 `action_id`、`turn_id`、stateVersion 和 event sequence。 | P1 |
| TX-FR-12 | Host ACK 应可持久化或写入事件，支持重连后不重复播放。 | P1 |
| TX-FR-13 | `s2c_turn_resolved` 等新增事件必须进入 registry、前端类型和测试。 | P1 |
| TX-FR-14 | retry-turn 要区分重算、重播和恢复，默认不能重复应用状态 mutation。 | P1 |
| TX-FR-15 | timeout/cancel 状态应释放玩家 UI，并保留审计信息。 | P2 |

## 接口方向

| 接口或事件 | 当前状态 | 受众 | 说明 |
| --- | --- | --- | --- |
| `POST /api/player/intent` | 已有 | Player | 提交行动或 ready_toggle |
| `GET /api/player/actions/{action_id}` | 已有 | Player | 查询自己的 action 状态 |
| `GET /api/player/reconnect` | 已有 | Player | 恢复 pending actions 和事件 |
| `GET /api/rooms/{room_id}/turns/current` | 已有 | Host/Admin | 查看当前回合收集状态 |
| `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character` | 已有 | Host/Admin | 为未行动玩家生成跳过动作 |
| `POST /api/rooms/{room_id}/turns/{turn_id}/retry` | 已有 | Host/Admin | 当前语义需收口 |
| `POST /api/host/{room_id}/pause` | 已有 | Host/Admin | 暂停或恢复 Host 舞台 |
| `POST /api/host/{room_id}/retry-turn` | 已有 | Host/Admin | 当前只重置 active Host transaction step |
| `s2c_action_queued` | 已有 | Player | 行动入队 |
| `s2c_reveal_transaction` | 已有 | Host | Host 演出事务 |
| `s2c_state_patch` | 已有 | Player | 私密状态 patch |
| `s2c_action_completed` | 已有 | Player | 行动完成或失败 |
| `s2c_public_observation` | 已有 | Party | 公共叙事 |
| `s2c_turn_resolved` | 代码有 emit，registry 缺口 | Party | 回合结算完成摘要 |

## 数据边界

- `actions` 是行动事务的权威账本。
- `room_turns` 是回合事务的权威账本。
- `events` 是投影和审计日志，不应作为未落库状态的唯一事实来源。
- `host_states` 是 Host 舞台恢复缓存，不是规则或状态真相。
- `transactions` 表第一轮不是硬要求。只有当 Host 演出恢复、ACK、重播需求无法由 `events + host_states` 满足时再新增。
- `rooms.state_version` 属于 State 屏障，Transaction 不能把“行动排队”伪装成世界状态变化。

## 权限边界

- Player token 只能提交和查询自己的 action。
- Host 只能播放、暂停、恢复、跳过、重试受控事务，不能直接改 action result。
- Admin 可做运维恢复，但必须写审计事件。
- AI 输出必须先经 Rule/Engine 校验，再进入 Transaction。
- Projection 必须按 audience 过滤，Host 不接收 player-only 结果。

## 验收标准

1. 同一 `action_id` 重复提交不会重复写 action。
2. 同一玩家同一 turn 提交两个不同 action 时，第二个返回 409，数据库无额外 queued action。
3. 版本冲突返回 409 或 conflict，并提供当前版本。
4. Rule 执行异常时 action 进入 rejected，只有玩家完成回执，没有公共叙事。
5. 成功 action 可从 `actions.result`、State patch、Host reveal、public observation、action completed 追溯。
6. 所有玩家提交后 turn 只被一个 worker 结算一次。
7. Player 重连能恢复自己的 pending action，不能读取他人 action。
8. Host reveal 不包含玩家私密状态，私密 patch 不早于 Host 安全点。
9. `s2c_turn_resolved` 等事务事件在 registry、前端类型和测试中口径一致。
