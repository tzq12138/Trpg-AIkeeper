# PRD-09 - Player 活体角色卡与触控检定

**版本**: 1.0  
**状态**: 待开发  
**来源**: Player 模块 3、PRD-01、PRD-07  
**适用范围**: usePlayerStore、usePlayerAction、SkillButton、角色卡 UI

## 1. 背景

Player 手机端是玩家的“个人调查员终端”。角色卡既要展示权威状态，又要提供触控检定入口。点击技能不能直接掷骰或改状态，只能提交 `skill_check` 意图，等待 Engine 结算后同步。

## 2. 目标

- 建立 Player Store 的角色、版本、动作状态和通知基础结构。
- 实现 `IDLE -> SUBMITTING -> RESOLVING -> IDLE` 动作状态机。
- 技能按钮通过 REST 意图提交检定。
- 状态变化通过 snapshot/patch 驱动角色卡。

## 3. 范围边界

**包含**
- PlayerCharacter 基础字段。
- `usePlayerAction.submitIntent`。
- 技能按钮和角色状态展示。
- Watchdog 超时兜底同步。

**不包含**
- 角色创建器。
- 复杂成长结算。
- Host 3D 骰子动画。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-09-1 | 作为玩家，我需要看到自己的 HP、SAN、属性、技能和状态标签。 | P0 |
| US-09-2 | 作为玩家，我点击技能后需要明确知道行动已提交且正在结算。 | P0 |
| US-09-3 | 作为开发者，我需要本地状态版本参与提交，避免基于旧状态行动。 | P0 |

## 5. 功能需求

1. Player Store 包含 `character`、`stateVersion`、`lastPlayerSequence`、`actionState`、`pendingActionId`、`latestCompletedAction`。
2. `actionState` 仅允许 `IDLE | SUBMITTING | RESOLVING`。
3. `submitIntent` 在非 IDLE 或无角色时直接拒绝提交。
4. `submitIntent` 生成前端 UUID `actionId`，携带 `baseStateVersion` 和 `X-Room-Token`。
5. REST 返回 202/200 后进入 `RESOLVING`。
6. 收到匹配 `pendingActionId` 的 `s2c_action_completed` 后重置为 `IDLE`。
7. Watchdog 超时后请求 `/api/player/sync`，无论同步成功失败都解锁，并显示 toast。
8. `SkillButton` 点击提交 `intentType='skill_check'`，params 包含 `skillName`。
9. 角色状态只由 `applyFullSnapshot` 和 `applyStatePatch` 更新。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| REST | `POST /api/player/intent` | 提交技能检定 |
| REST | `GET /api/player/sync` | 超时/冲突后同步 |
| Event | `s2c_action_completed` | 解锁动作状态 |
| Event | `s2c_full_snapshot` | 初始化角色 |
| Event | `s2c_state_patch` | 更新角色状态 |

## 7. 状态与错误处理

- HTTP 409 时 toast 提示状态过期，并立即同步快照。
- HTTP 429 时 toast 提示操作过快，解锁 UI。
- 网络错误时 resetLocks，不保留僵尸 pending action。
- Watchdog 不设置 `REJECTED` 状态，失败信息由 toast 表达。
- patch 中未知路径跳过并记录 warning。

## 8. 验收标准

- 技能按钮不会直接生成骰子结果。
- 所有提交都包含 `baseStateVersion`。
- completed actionId 不匹配时不解锁当前 pending action。
- 15s 超时后 UI 可恢复操作并尝试同步。
- 本地角色卡状态变更均可追溯到 snapshot/patch。

## 9. 测试场景

1. 点击“侦查”技能，REST body 包含 `skill_check` 和 `{ skillName: '侦查' }`。
2. REST 202 后按钮禁用，收到 completed 后恢复。
3. 收到其他 actionId completed，按钮保持锁定。
4. Watchdog 触发，同步接口被调用，最终解锁。

## 10. 风险依赖

- 依赖 PRD-01 的 action completed 保证最终送达。
- JSON Patch 路径需要与 PlayerCharacter 字段保持一致。
- 如果多人共用一个设备，需要额外角色切换流程。

