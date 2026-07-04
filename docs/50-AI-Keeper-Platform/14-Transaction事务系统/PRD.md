# Transaction 事务系统 PRD 初版

## 目标

让一次 AI/规则裁决以事务形式安全落地，保证状态、公共演出、私密反馈和日志按可恢复顺序执行。

## 范围

包含事务队列、步骤、状态节点、投影节点、完成信号、幂等、锁、Watchdog 和恢复。不包含复杂工作流编辑器和跨房间事务。

## 角色

| 角色 | 权限 |
|---|---|
| Engine | 创建和推进事务。 |
| Host Client | 播放公共步骤并回报完成。 |
| Player Client | 接收授权反馈和 UI 解锁。 |
| Journal | 记录事务全过程。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| TX-1 | 作为系统，我能按顺序执行一次裁决。 | P0 |
| TX-2 | 作为玩家，我不会在公共演出前收到剧透反馈。 | P0 |
| TX-3 | 作为系统，我能在刷新后恢复未完成事务。 | P1 |
| TX-4 | 作为开发者，我能追踪事务卡在哪一步。 | P1 |

## 数据边界

事务属于房间，包含 txId、sourceActionId、status、priority、steps、currentStep、stateVersionBefore、stateVersionAfter、createdAt、completedAt。事务日志不可被前端直接修改。

## 接口 / 事件方向

- 内部服务：创建事务、推进步骤、完成步骤、取消事务、恢复事务。
- WS：`transaction_started`、`transaction_step`、`transaction_completed`、`transaction_failed`。
- Event：每个 step 的开始、完成和失败都写入 Journal。

## 验收标准

- 重复 action 不创建重复事务。
- Host 演出和 Player 私密反馈顺序符合配置。
- 事务卡住后 Watchdog 可解锁。
- 未完成事务可从日志恢复。

