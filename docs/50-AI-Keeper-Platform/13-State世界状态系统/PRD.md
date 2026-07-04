# State 世界状态系统 PRD 初版

## 目标

建立权威世界状态和版本屏障，保证状态变更有来源、有顺序、可恢复、可投影。

## 范围

包含状态服务、版本号、快照、角色/场景/线索/道具/房间状态、审计和恢复。不包含复杂分布式一致性和跨服同步。

## 角色

| 角色 | 权限 |
|---|---|
| Engine | 唯一权威写入者。 |
| AI KP | 读取裁剪状态并提出建议。 |
| Host/Player | 读取投影后的状态视图。 |
| Admin/Ops | 执行受审计的恢复和诊断。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| STATE-1 | 作为系统，我能保证状态只由 Engine 写入。 | P0 |
| STATE-2 | 作为玩家，我刷新后能恢复正确状态。 | P0 |
| STATE-3 | 作为开发者，我能追踪状态变化来源。 | P1 |
| STATE-4 | 作为房主，我能从检查点恢复房间。 | P0 |

## 数据边界

权威状态按 roomId 隔离，带 stateVersion。状态变更以 mutation 形式记录，包含 sourceActionId、transactionId、actor、before/after 摘要和 audience 影响。

## 接口 / 事件方向

- 内部服务：读取状态、应用 mutation、生成快照、恢复快照、比较版本。
- Event：`state_mutation_applied`、`state_snapshot_created`、`state_restored`、`state_conflict_detected`。
- Projection：只消费状态变更结果，不反向写 State。

## 验收标准

- 非 Engine 写状态路径被拒绝。
- stateVersion 单调递增。
- 快照恢复可用并写审计日志。
- 重连时旧 patch 不覆盖新状态。

