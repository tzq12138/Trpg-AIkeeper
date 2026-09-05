# PRD-04 - Host 事务播放器与多级队列

**版本**: 1.0  
**状态**: 待开发  
**来源**: Host 模块 3、PRD-00、PRD-02  
**适用范围**: `useTransactionPlayer`、事务队列、抢占控制

## 1. 背景

公共演出必须按顺序展示：掷骰、状态变化、场景转场、叙事字幕。旧式 boolean 锁和散落 timer 容易造成死锁、重复推进和 Urgent 插队不可恢复。本 PRD 将 Host 演出定义为可中断的线性事务播放器。

## 2. 目标

- 按 `s2c_reveal_transaction.steps[]` 顺序播放公共演出。
- 支持 normal/urgent 两级队列和抢占恢复。
- 用统一 timer 管控和 Watchdog 防止大屏永久卡死。
- 明确 Urgent 恢复点保存策略。

## 3. 范围边界

**包含**
- `popNextEvent` 调度规则。
- `roll`、`status_delta`、`scene_transition`、`narrative_text` step 执行。
- Watchdog、timer 清理、步骤完成回调。
- Urgent 中断、恢复、取消。

**不包含**
- 3D 骰子物理渲染细节。
- BGM/SFX 播放。
- Engine 事务生成算法。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-04-1 | 作为观众，我需要公共掷骰、扣血和叙事按正确顺序播放。 | P0 |
| US-04-2 | 作为 KP，我需要紧急事件可以插队，但普通事务不会因此丢失或卡死。 | P0 |
| US-04-3 | 作为开发者，我需要任何动画失败都能超时推进，避免大屏停住。 | P0 |

## 5. 功能需求

1. 当 `activeTransactionId` 为空时，播放器优先弹出 urgent 队列，再弹出 normal 队列。
2. 开始事务时保存 `transactionEvent`、`transactionId`、`stepIndex=0`。
3. 每个 step 启动 Watchdog，默认 15000ms，可由 payload 覆盖。
4. step 完成时必须清理当前 step 所有 timer，再推进 `stepIndex`。
5. `roll` step 设置 `currentRollEvent`，等待 Dice 节点回调或 Watchdog。
6. `status_delta` step 调用 `applyPublicStatusDelta`，等待动画时长后推进。
7. `scene_transition` step 调用 `setSceneImage`，等待转场时长后推进。
8. `narrative_text` step 追加完整文本；MVP 阶段始终按非阻塞处理，并依赖事务步骤顺序约定将叙事文本放在最后一步。`blocking=true` 等待打字机完成回调属于二期扩展，不作为首版实现要求。
9. Urgent 到达时必须保存 `{ transactionEvent, stepIndex }`，恢复时从当前可幂等 step 重新播放。
10. 收到 `s2c_cancel_transaction` 时丢弃被中断事务，可展示 `summaryText`。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Event | `s2c_reveal_transaction` | 事务输入 |
| Event | `s2c_resume_transaction` | 恢复被中断 normal 事务 |
| Event | `s2c_cancel_transaction` | 取消被中断事务 |
| Store | `currentRollEvent` | Dice 节点挂载条件 |
| Callback | `notifyDiceSettled` | 骰子动画完成 |
| Callback | `notifyTypewriterDone` | blocking 字幕完成（二期） |

## 7. 状态与错误处理

- 队列中出现非事务事件时 warning 跳过。
- 未知 step kind 必须安全跳过并继续后续 step。
- Watchdog 触发后不得再次响应迟到动画回调。
- 恢复事务时重复播放当前 step，不回放已经完成的 step。
- 不可幂等 step 需要 Engine 侧避免放入可恢复区间，MVP 默认所有 Host step 仅演出、可重复。

## 8. 验收标准

- `[roll, status_delta, narrative_text]` 能按顺序完整播放。
- Dice 动画不回调时 15s 后继续事务。
- Urgent 事务可插队播放，结束后根据 Engine 指令恢复或取消 normal。
- 所有 timer 在 step 完成、事务结束、组件卸载时清理。
- `narrative_text` 使用完整文本，不依赖网络流式 chunk。
- MVP 阶段不要求实现 `notifyTypewriterDone`；若需阻塞字幕，二期再启用 `blocking=true` 回调链。

## 9. 测试场景

1. 普通事务三 step 顺序播放，结束后 `activeTransactionId=null`。
2. roll step 不触发完成回调，Watchdog 推进到下一 step。
3. normal 播放到 step 2 时 urgent 到达，urgent 完成后 resume，normal 从 step 2 重新播放。
4. unknown step 被跳过，不影响后续叙事。

## 10. 风险依赖

- 依赖 Store 能保存完整 `transactionEvent`，不能只保存 txId。
- 依赖 Dice/Typewriter 组件提供幂等完成回调。
- 需要避免 React Strict Mode 导致 effect 双启动。

## 11. 已知架构 Bug：私密获取与大屏演出的时序穿透 (Spoiler Leak)

**来源**：`数据流bug+思考.md` Bug 2

**场景**：
1. 玩家 A 撬开保险箱（公开检定），保险箱内有私密手枪。
2. Engine 同时下发 Host `s2c_reveal_transaction`（6 秒骰子动画）和 Player `s2c_state_patch`（瞬间入包）。
3. 大屏骰子还在滚，手机已弹出"获得手枪"——玩家喊出声，全场剧透。

**防御方案**：含私密结果的 `s2c_state_patch` 和 `s2c_action_completed` 必须等待 Host 事务到达特定 step 后才下发。

**方案 A**：`s2c_state_patch` 携带 `executeAfterStep: number` 字段，Player 路由器收到后延迟应用，直到对应的 `s2c_reveal_transaction` 广播到达该 step 索引。

**方案 B（MVP 推荐）**：Engine 在事务的 `status_delta` step 广播后才向 Player 发送 Patch——利用广播本身就是天然的时序信号。

**实现要求**：
1. ProjectionBuilder 判断结算结果是否包含私密状态变更（如物品获取、线索发现）。
2. 若包含，将 Player Patch 标记为 `delayedDelivery: true`。
3. Host WS 广播 `status_delta` step 完成后，触发延迟的 Player Patch 下发。
4. 若 Host 事务播放超时（Watchdog 触发），仍需下发 Player Patch（避免僵尸状态）。

**新增测试场景**：
5. 公开检定获得私密物品 → Host 骰子动画播放期间 Player 未收到 Patch → 骰子播完后 Player 收到 Patch。
6. Host 事务超时 → Player Patch 仍正常下发（兜底）。
