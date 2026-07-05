# Transaction 事务系统 DeepSeek 计划 V2.0

## 执行目标

本计划只处理玩家行动、回合结算和 Host 演出事务的可靠性。第一轮不重写规则系统，不扩展平台外围能力，不新增复杂事务中台。所有改动必须服务核心链路：`Intent -> Transaction -> State -> Projection -> Journal`。

## 全局禁止事项

1. 禁止让 Host 前端决定规则结果、状态变更或 action result。
2. 禁止让 AI 输出直接落库，必须经过 Engine/Rule/State 校验。
3. 禁止为了修 UI 绕过 player token、owner token 或 account 权限。
4. 禁止在 duplicate、retry、重连场景重复应用同一状态 mutation。
5. 禁止把 player-only 私密 payload 放入 Host reveal transaction。
6. 禁止把 action 入队继续当作世界 `state_version` 变化。
7. 禁止大规模重命名目录或重构无关模块。

## Batch Tx-0：现状盘点与测试基线

### 目标

锁定当前事务链路真实行为，先用测试描述风险，再进入修复。

### 允许改动

- `tests/server/test_engine.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_host.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_events.py`
- 必要时新增 `tests/server/test_transaction_flow.py`
- 仅修正文档或测试触达的乱码断言文案

### 任务

1. 记录 `actions`、`room_turns`、`events`、`host_states` 当前字段和写入路径。
2. 写 active 房间 duplicate 复现测试：第二个不同 action 返回 409 后，不能多出 queued action。
3. 写 action 入队不应 bump 世界 `state_version` 的期望测试。
4. 写 `s2c_turn_resolved` 注册表缺口测试。
5. 写玩家不能查询他人 action 的隔离测试。

### 验收命令

```powershell
python -m pytest tests/server/test_engine.py tests/server/test_player_intent.py tests/server/test_resolution_pipeline.py tests/server/test_host.py tests/server/test_reconnect.py tests/server/test_events.py -q
```

### 预期结果

测试明确暴露当前问题或已覆盖的行为。若新增测试失败，必须在注释或提交说明里标明它对应哪个后续 Batch 修复。

## Batch Tx-1：玩家意图入队原子化

### 目标

修正 `/api/player/intent` active 房间流程，保证 duplicate 不产生副作用。

### 允许改动

- `src/server/player/router_player.py`
- `src/server/engine/engine.py`
- `src/server/turn_manager.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_engine.py`
- `tests/server/test_transaction_flow.py`

### 任务

1. 将 active 房间流程调整为先确认当前 collecting turn 和同玩家 duplicate。
2. 只有 duplicate 校验通过后才写 `actions`、`turn_id` 和 queued event。
3. `Engine.submit_intent` 保留 `action_id` 幂等，但不在普通 action 入队时推进世界 `state_version`。
4. 保持 ready_toggle 作为 Room/Lobby 特殊 intent，不进入回合行动。
5. 统一冲突响应：版本冲突返回 409，并带 current version 信息。

### 验收命令

```powershell
python -m pytest tests/server/test_engine.py tests/server/test_player_intent.py tests/server/test_transaction_flow.py -q
```

### 禁止事项

- 不改玩家身份来源，仍以 `X-Room-Token` 反查角色。
- 不把 duplicate 留给前端处理。
- 不删除 legacy 非 active 即时结算路径，除非对应测试和文档同步调整。

## Batch Tx-2：回合结算锁与幂等

### 目标

防止同一 turn 被多个后台任务重复结算，明确 retry/skip 的语义。

### 允许改动

- `src/server/turn_manager.py`
- `src/server/player/router_player.py`
- `src/server/router_rooms.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_transaction_flow.py`

### 任务

1. `mark_resolving` 改为条件更新：只有 collecting 或允许状态可进入 resolving。
2. `_settle_turn_background` 启动后先获取 resolving 权限，失败则直接返回已在处理。
3. `get_pending_actions` 只处理本 turn queued action，resolved/rejected 不再重算。
4. `skip-character` 生成的 system_skip 必须有明确审计字段，不污染玩家普通行动。
5. `retry` 区分“重新播放本轮摘要”和“重新计算 queued actions”，默认不重复应用 resolved mutation。

### 验收命令

```powershell
python -m pytest tests/server/test_player_intent.py tests/server/test_host_room_lifecycle.py tests/server/test_transaction_flow.py -q
```

### 禁止事项

- 不通过清空 `actions` 或 `room_turns` 来解决重复结算。
- 不在 retry 中默认重放 State mutation。

## Batch Tx-3：裁决事务提交顺序

### 目标

将单个 action 的顺序收口为：锁定 action、执行裁决、写 result、写 State、发 Projection、完成 action。

### 允许改动

- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/engine/projection.py`
- `src/server/models.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_state_service.py`
- `tests/server/test_projection.py`

### 任务

1. 保留 resolved/rejected action 的幂等返回，不重复投影。
2. 失败时只写 rejected 和 player completed，不发 Host reveal 或 public observation。
3. 成功时 StateService 先写权威状态并返回版本信息。
4. `s2c_state_patch` 和 `s2c_action_completed` 携带 actionId、baseStateVersion、stateVersion。
5. 确保 Projection 不再发送早于权威状态的 patch。
6. 对无 mutations 的 dialogue/action 明确是否推进版本，默认不推进世界版本。

### 验收命令

```powershell
python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_state_service.py tests/server/test_projection.py -q
```

### 禁止事项

- 不把 StateService 异常吞掉后继续给玩家 resolved。
- 不把 AI narrative 当作权威状态来源。
- 不在 Projection 层修改裁决结果。

## Batch Tx-4：Host reveal transaction 与私密屏障

### 目标

保证 Host 演出事务和 Player 私密结果有可审计的时序关系。

### 允许改动

- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/engine.py`
- `src/server/host/host_store.py`
- `src/server/host/router_host.py`
- `src/server/engine/projection.py`
- `src/client/src/pages/HostStage.tsx`
- `src/client/src/shared/ws.ts`
- `tests/server/test_host.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_projection.py`

### 任务

1. `s2c_reveal_transaction` payload 绑定 actionId、turnId、baseStateVersion、stateVersion。
2. Host reveal 只包含 roll、status_delta 摘要、scene_transition、narrative_text 等 Host 可见 step。
3. Player-only `s2c_state_patch`、`s2c_private_notice`、`s2c_action_completed` 进入 delayed 队列或明确的 release gate。
4. `host_step_complete` 必须校验 Host 身份和 transactionId，不能由玩家伪造。
5. Host ACK 写入事件或持久 transaction state，便于重连恢复。
6. 前端 HostStage 如需发送 ACK，只发送播放进度，不发送规则结果。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_resolution_pipeline.py tests/server/test_projection.py tests/server/test_ws_auth.py -q
```

### 禁止事项

- 不把完整 Player patch 放进 Host payload。
- 不让前端 ACK 触发新的规则裁决。
- 不依赖本地 React state 作为已播放权威记录。

## Batch Tx-5：事件注册、日志和重连一致性

### 目标

让事务相关事件在 registry、前端类型、日志和重连中保持一致。

### 允许改动

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/server/player/router_reconnect.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/client/src/shared/types.ts`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/pages/HostStage.tsx`
- `tests/server/test_events.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_archive.py`

### 任务

1. 将 `s2c_turn_resolved` 纳入事件注册表、Pydantic Literal 和前端类型。
2. 对所有事务事件定义 audience、payload 最小字段和可见性。
3. `/api/player/reconnect` 只返回该玩家可见事件和自己的 pending actions。
4. `/api/player/actions/{action_id}` 保持 character 过滤，补足 result 序列化测试。
5. Journal 查询能按 actionId、turnId、transactionId 定位相关事件。

### 验收命令

```powershell
python -m pytest tests/server/test_events.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_player_intent.py -q
```

### 禁止事项

- 不用“返回所有 events 让前端过滤”解决权限问题。
- 不增加未登记的 `s2c_*` 事件。

## Batch Tx-6：HostStore 持久化和恢复策略

### 目标

决定是否需要独立 `transactions` 表。若暂不建表，则补齐 `host_states` 对 active/queued transaction 的恢复字段。

### 允许改动

- `src/server/host/host_store.py`
- `src/server/host/router_host.py`
- `src/server/db_adapter.py`
- `src/server/db_pg.py`
- `tests/server/test_host.py`
- `tests/server/test_reconnect.py`

### 任务

1. 评估 `host_states` 是否足够保存 normal queue、urgent queue、active transaction、current_step_index、interrupted transaction。
2. 若继续使用 `host_states`，补齐序列化和 restore 字段。
3. 若新增 `transactions` 表，仅保存必要字段：transaction_id、room_id、action_id、turn_id、status、current_step_index、payload、created_at、completed_at。
4. Host 断线重连后不重复播放已完成 step，不丢失未释放 delayed event。
5. reset/pause/retry-turn 都写入可审计事件。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_reconnect.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不做大规模数据库迁移。
- 不把 HostStore 恢复设计成世界状态来源。
- 不在没有测试的情况下改变 WS 消息结构。

## Batch Tx-7：端到端回归验收

### 目标

验证完整跑团主链路，确保 Transaction 与 Room、State、Projection、Journal 的接口稳定。

### 手动验收流程

1. Host 创建房间，选择剧本，开始房间。
2. 系统创建第 1 个 collecting turn。
3. Player 加入并提交行动。
4. 重复提交同回合第二个不同 action 被拒绝，无多余 queued action。
5. 所有玩家提交后，turn 进入 resolving。
6. Rule/AI 完成裁决，StateService 写入状态。
7. Host 收到 reveal transaction。
8. Player 在安全点后收到 state patch 和 action completed。
9. turn resolved，下一 turn 创建。
10. Player 刷新或重连后，pending actions、stateVersion 和事件不乱序。

### 回归命令

```powershell
python -m pytest tests/server/test_engine.py tests/server/test_player_intent.py tests/server/test_resolution_pipeline.py tests/server/test_state_service.py tests/server/test_projection.py tests/server/test_host.py tests/server/test_reconnect.py tests/server/test_archive.py -q
```

前端涉及 HostStage、PlayerActionPage 或 shared types 时补跑：

```powershell
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | Transaction 依赖 | 对方期望 |
| --- | --- | --- |
| Room | active 房间、开局创建首 turn | Transaction 不改变房间生命周期 |
| User | token/account 权限 | Transaction 不信任前端身份字段 |
| Timeline | turn 顺序、回合状态 | Transaction 保证结算幂等和顺序 |
| Rule | `ResolutionResult` | Transaction 不修改规则数学结果 |
| AI-Keeper | 叙事和建议 | AI 输出必须先校验再进入事务 |
| State | `StateService.apply_change`、stateVersion | Transaction 不直接写世界真相 |
| Projection | audience event、Host/Player 投影 | Transaction 提供 action/turn/version 上下文 |
| Journal | action/event/turn 追溯 | Transaction 事件必须能回查 |
| Host Client | reveal transaction、ACK、pause/retry | Host 只播放和确认，不裁决 |
| Player Client | queued/completed/patch/reconnect | Player UI 以服务端状态为准 |
