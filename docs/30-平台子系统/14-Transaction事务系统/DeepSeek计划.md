# Transaction 事务系统 DeepSeek 计划 V2.1

## 当前阶段

本计划对应的是：

- `P0 主链路 + 行动/回合/演出事务可靠性风险识别版`
- 以当前仓库真实代码为准，不按旧 PRD 想象现状
- 第一轮只处理 `Intent -> Transaction -> State -> Projection -> Journal` 主链路，不扩平台外围功能

## 执行目标

把 Transaction 主链路收口成“可执行、可测试、可审计、可恢复”的工程任务包，重点解决：

- 玩家 action 幂等与 duplicate 原子化
- turn settle 并发屏障
- State 先于 Projection 的提交顺序
- Host reveal transaction 的最小契约
- release gate 与 Host ACK
- reconnect / retry / trace 的统一语义

## 全局禁止事项

1. 禁止让 Host 前端决定规则结果、状态变更或私密释放时机。
2. 禁止让 AI 输出直接落库，必须先经 Engine / Rule / State 校验。
3. 禁止把普通 action 入队继续当成世界 `state_version` 变化。
4. 禁止在 duplicate、retry、重连场景重复应用同一组 State mutation。
5. 禁止把 player-only payload 放进 `s2c_reveal_transaction`。
6. 禁止为了赶进度跳过 `registry / model / TS` 的事件契约同步。
7. 禁止大范围重命名或重构与本模块无关的目录、路由和前端页面。

## Batch Tx-0：现状盘点与回归基线

### 目标

先用测试把当前真实行为钉住，避免后续“修复一个问题，顺手打坏另一条事务链”。

### 允许改动

- `tests/server/test_player_intent.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_host.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_events.py`
- 必要时新增 `tests/server/test_transaction_flow.py`
- 仅限事务相关文档和测试断言文案

### 任务

1. 记录当前 `actions / room_turns / events / host_states` 的关键写入路径。
2. 补 duplicate 回归测试：
   - 同一 `action_id` 重试不重复 queued
   - 同一角色同一 turn 第二个不同 action 返回 409
3. 补“普通 action 入队不 bump `rooms.state_version`”测试。
4. 补“resolved/rejected action 再 resolve 不重复投影”测试。
5. 补 `s2c_turn_resolved` registry / model / TS 的缺口测试。

### 验收命令

```powershell
python -m pytest tests/server/test_player_intent.py tests/server/test_resolution_pipeline.py tests/server/test_host.py tests/server/test_reconnect.py tests/server/test_events.py -q
```

## Batch Tx-1：玩家意图入队原子化

### 目标

把 duplicate 保护从“普通先查再写”提升为可抵抗并发竞态的事务语义。

### 允许改动

- `src/server/player/router_player.py`
- `src/server/turn_manager.py`
- `src/server/engine/engine.py`
- `src/server/db_adapter.py`
- `src/server/db_pg.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_transaction_flow.py`

### 任务

1. 把 active 房间 duplicate 保护固化为数据库唯一约束或同事务锁。
2. 明确允许存在的有效 action 状态集合，第一轮默认：
   - 占位：`queued/batched/resolving/resolved/timeout`
   - 不占位：`rejected/cancelled/system_skip`
3. 保留 `action_id` 幂等，但不能让 duplicate 失败后留下孤儿 queued action。
4. 保持 `ready_toggle` 作为 Room / Lobby 特殊 intent，不进入 turn action。
5. 统一 version conflict 响应，继续返回 `currentVersion`。

### 验收命令

```powershell
python -m pytest tests/server/test_player_intent.py tests/server/test_transaction_flow.py -q
```

### 禁止事项

- 不把 duplicate 判断下放给前端。
- 不用“发现重复后再清理脏 action”代替原子保护。
- 不回退已修正的“普通 action 不 bump `rooms.state_version`”行为。

## Batch Tx-2：回合结算锁与 retry 语义

### 目标

确保同一 turn 只被结算一次，并把 retry 行为从“模糊重试”改成受控模式。

### 允许改动

- `src/server/turn_manager.py`
- `src/server/player/router_player.py`
- `src/server/router_rooms.py`
- `src/server/host/router_host.py`
- `tests/server/test_transaction_flow.py`
- `tests/server/test_host_room_lifecycle.py`

### 任务

1. 固化 `mark_resolving()` 的 true/false 语义，失败的 worker 直接退出。
2. 确保未抢到 resolving 权限的 worker 不写事件、不建 next turn。
3. 补 `RetryTurnRequestDTO` 对应的模式：
   - `replay_only`
   - `recompute_unresolved`
   - `restore_from_checkpoint`
4. 默认禁止对已完成 State 提交的 resolved turn 重新应用 mutation。
5. `skip-character` 的 `system_skip` 必须带 actor / target / reason 审计字段或等价信息。
6. 如果本轮继续保留 `GET /turns/current` 隐式创建 collecting turn，回执必须解释其调用范围、风险和后续迁移计划。

### 验收命令

```powershell
python -m pytest tests/server/test_transaction_flow.py tests/server/test_host_room_lifecycle.py -q
```

### 禁止事项

- 不用清空 `actions` 或回退 turn 状态来掩盖并发问题。
- 不把 retry 做成“默认重算一切”。

## Batch Tx-3：裁决提交顺序与失败分级

### 目标

把单 action 事务顺序收口成“先 State，后 Projection”，并区分失败类型。

### 允许改动

- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/engine/projection.py`
- `src/server/models.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_state_service.py`
- `tests/server/test_projection.py`

### 任务

1. 把链路改成：
   `mark_resolving -> compute -> write result -> apply State -> emit Projection -> complete`
2. `StateService` 失败时，action 不得以正常 `resolved` 语义结束。
3. 明确失败分级：
   - `precondition_failed`
   - `rule_failed`
   - `ai_schema_failed`
   - `state_apply_failed`
   - `projection_failed`
4. `s2c_state_patch`、`s2c_action_completed` 至少携带 `actionId/baseStateVersion/stateVersion`。
5. 对无 mutation 的 action，明确是否推进世界版本；默认不推进。
6. 如果 State 已成功而 Projection 失败，只允许 replay Projection / redelivery event，不允许重跑 Rule 或重写 State。

### 验收命令

```powershell
python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_state_service.py tests/server/test_projection.py -q
```

### 禁止事项

- 不吞掉 State 异常后继续给玩家返回正常 resolved。
- 不在 Projection 层偷偷补写权威状态。

## Batch Tx-4：Host reveal transaction、release gate 与 ACK

### 目标

让 Host 演出和 Player 私密结果释放之间有明确、可恢复、可审计的契约。

### 允许改动

- `src/server/engine/resolution_pipeline.py`
- `src/server/host/host_store.py`
- `src/server/host/router_host.py`
- `src/server/models.py`
- `src/client/src/pages/HostStage.tsx`
- `src/client/src/shared/types.ts`
- `src/client/src/shared/ws.ts`
- `tests/server/test_host.py`
- `tests/server/test_resolution_pipeline.py`

### 任务

1. 补齐 `RevealTransactionDTO`：
   - `transactionId`
   - `actionId`
   - `turnId`
   - `baseStateVersion`
   - `stateVersion`
   - `releaseGates[]`
2. 引入 `ReleaseGateDTO`，把 player-only patch / completed 的释放条件固定到服务端。
3. 引入 `HostStepAckDTO` 或等价 ACK 事件。
4. `host_step_complete` 必须校验 Host 身份、`transactionId`、`stepId`。
5. Host ACK 只能确认进度，不能上送规则结果或状态变更。
6. 固化 Host-safe step 白名单，只允许 roll 摘要、status delta 安全摘要、scene transition、narrative text、public clue summary、map safe summary 进入 Host reveal。
7. `ReleaseGateDTO` 必须进入 `host_states`、最小 `transactions` 表或等价持久化链路，不能只存在于内存。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_resolution_pipeline.py tests/server/test_ws_auth.py -q
```

前端如触及 HostStage / shared types，再补跑：

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不把完整 player patch 塞进 Host payload。
- 不依赖 React 本地 state 作为唯一 ACK / gate 依据。

## Batch Tx-5：事件契约、Trace 与重连一致性

### 目标

让 Transaction 相关事件在 registry、Pydantic、TS、Journal、Reconnect 中保持统一。

### 允许改动

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/server/player/router_reconnect.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/client/src/shared/types.ts`
- `tests/server/test_events.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_archive.py`

### 任务

1. 所有事务相关事件至少带 `actionId/turnId/transactionId` 之一。
2. 为关键事件补 trace 字段：
   - `s2c_action_queued`
   - `s2c_state_patch`
   - `s2c_action_completed`
   - `s2c_reveal_transaction`
   - `s2c_turn_resolved`
3. `/api/player/reconnect` 继续只返回玩家可见事件和自己的 pending action。
4. Journal / archive 查询支持按 `actionId/turnId/transactionId` 定位事务链。

### 验收命令

```powershell
python -m pytest tests/server/test_events.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_player_intent.py -q
```

### 禁止事项

- 不用“返回所有 events 给前端自己过滤”解决权限和 trace 问题。
- 不新增未登记的 `s2c_*` 事件名。

## Batch Tx-6：HostStore 持久化与恢复决策

### 目标

决定继续用 `host_states` 还是引入最小 `transactions` 表，并把恢复语义写硬。

### 允许改动

- `src/server/host/host_store.py`
- `src/server/host/router_host.py`
- `src/server/db_adapter.py`
- `src/server/db_pg.py`
- `tests/server/test_host.py`
- `tests/server/test_reconnect.py`

### 任务

1. 盘点 `host_states` 当前已存和未存字段。
2. 如果继续使用 `host_states`，至少补：
   - queue
   - active transaction
   - current step
   - acknowledged steps
   - interrupted transaction
   - delayed events
3. 如果做不到，新增最小 `transactions` 表，而不是设计大而全的新中台。
4. 回执里必须明确：
   - 本轮是否新建 `transactions` 表
   - 如果没建，`host_states` 新增了哪些恢复字段
   - Host 重连后如何避免重复播放已 ACK step
   - `ReleaseGateDTO` 最终持久化在哪里

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_reconnect.py -q
```

### 禁止事项

- 不做与事务主链路无关的大迁移。
- 不把 HostStore 恢复态当成世界真相来源。

## Batch Tx-7：端到端主链路回归

### 目标

验证 Transaction 与 Room、State、Projection、Journal 的主链路能完整跑通。

### 手动验收流程

1. Host 创建房间并开局。
2. 系统创建 collecting turn。
3. Player 提交 action。
4. duplicate 提交被挡住，不产生额外 queued action。
5. 所有玩家提交后，turn 进入 resolving。
6. Rule / AI 完成裁决。
7. State 写入成功后，Host 收到 reveal transaction。
8. Host 演出到安全点后，Player 才收到私密 patch / completed。
9. turn 标记 resolved，并创建下一 turn。
10. Player / Host 重连后，事务不重复结算、不重复播放、不提前泄露。

### 回归命令

```powershell
python -m pytest tests/server/test_player_intent.py tests/server/test_resolution_pipeline.py tests/server/test_state_service.py tests/server/test_projection.py tests/server/test_host.py tests/server/test_reconnect.py tests/server/test_events.py tests/server/test_archive.py -q
```

如前端类型有变动，再补跑：

```powershell
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | Transaction 依赖 | 对方期望 |
| --- | --- | --- |
| Room | active room、开局、首 turn 创建 | Transaction 不改房间生命周期 |
| User | token / account / owner 权限 | Transaction 不信任前端身份字段 |
| Timeline | turn 顺序、回合快照 | Transaction 负责结算幂等和状态推进 |
| Rule | `ResolutionResult` | Transaction 不改规则数学结果 |
| AI-Keeper | 裁决建议 / 叙事 | AI 输出必须先校验再进入事务 |
| State | `apply_change()`、`stateVersion` | Transaction 不直接写真相 |
| Projection | Host / Player / Party 投影 | Transaction 只提供 trace 和 release 契约 |
| Journal | action / turn / event 追溯 | Journal 需要完整 trace 字段 |
| Host Client | reveal / ack / retry | Host 只负责演出与确认，不负责裁决 |
