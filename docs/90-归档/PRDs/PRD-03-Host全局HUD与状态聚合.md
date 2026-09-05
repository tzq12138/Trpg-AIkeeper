# PRD-03 - Host 全局 HUD 与状态聚合

**版本**: 1.0  
**状态**: 待开发  
**来源**: Host 模块 2、PRD-02  
**适用范围**: `useHostStore`、GlobalHUD、PlayerCard

## 1. 背景

Host 大屏需要稳定展示玩家公共状态、当前场景、字幕、队列和氛围。最终版设计要求 Host Store 成为单一真相源，后续模块不得各自维护局部状态，否则事务播放器、HUD 动画和舞台字幕会互相抢控制权。

## 2. 目标

- 建立 Host 端完整 Zustand Store。
- 用公共快照、公共状态 delta 和 Host 事务驱动 HUD。
- 支持角色卡状态、场景、字幕、队列、音效和 Engine 状态统一管理。
- 为模块 4/5 提供稳定只读状态。

## 3. 范围边界

**包含**
- Host Store 字段和原子 action。
- `GlobalHUD` 与 `PlayerCard` 的公共状态展示。
- `applyPublicStatusDelta`、`applyFullSnapshot`、`resetRoomStore`。

**不包含**
- Player 私密角色卡完整字段。
- 复杂动画 CSS 细节。
- 服务端状态计算。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-03-1 | 作为观众，我需要在大屏上看到每个调查员的公开 HP、SAN 和状态标签。 | P0 |
| US-03-2 | 作为开发者，我需要所有 Host UI 从同一个 Store 取数，避免演出状态分叉。 | P0 |
| US-03-3 | 作为 KP，我需要房间切换时大屏不会残留上个房间角色。 | P0 |

## 5. 功能需求

1. Store 必须包含 `roomId`、`players`、`currentSceneImageUrl`、`chatMessages`、`engineState`。
2. Store 必须包含事务队列状态：`normalQueue`、`urgentQueue`、`interruptedTransaction`、`activeTransactionId`、`currentRollEvent`。
3. Store 必须包含 `lastHostSequence` 和完整 `atmosphere` 状态。
4. `applyFullSnapshot` 从 `s2c_host_snapshot` 覆写公共玩家、场景和必要演出状态。
5. `applyPublicStatusDelta` 只能应用 public delta，不显示 Player 私密数值。
6. `appendChatMessage` 保留最近 200 条字幕/聊天，防止长团内存膨胀。
7. `resetRoomStore` 清空除当前连接配置外的所有房间数据。
8. `PlayerCard` 只展示公共字段：头像、姓名、HP/SAN 条、公共状态标签。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Event | `s2c_host_snapshot` | 初始化/恢复公共 Store |
| Step | `status_delta` | 更新公共 HP/SAN/MP/Luck 和标签 |
| Event | `s2c_engine_state` | 更新守秘人思考/忙碌状态 |
| Store Action | `resetRoomStore` | 房间切换和紧急恢复 |

## 7. 状态与错误处理

- 角色不存在时收到 status delta，记录 warning 并跳过。
- `displayMode=vague` 时 HUD 仅展示模糊状态变化，不展示精确 before/after。
- 百分比计算必须处理 max 为 0 或缺失的异常数据。
- 快照缺字段时使用安全默认值，不让大屏白屏。
- `resetRoomStore` 必须同时清空音效队列、事务队列和当前骰子。

## 8. 验收标准

- Store 是 Host 端唯一状态定义文件，模块 3/4/5 不重复定义核心字段。
- HUD 数值只由 `s2c_host_snapshot` 或事务 `status_delta` 更新。
- 房间切换后旧玩家卡不再显示。
- 长文本运行后 `chatMessages` 不超过 200 条。
- `displayMode=vague` 不泄漏精确私密变化。

## 9. 测试场景

1. 下发包含 4 名玩家的 Host 快照，HUD 展示 4 张角色卡。
2. 下发 HP 扣减 delta，角色卡血条变化并触发公共动画。
3. 下发未知角色 delta，Store 不崩溃。
4. 连续追加 220 条字幕，Store 只保留最近 200 条。

## 10. 风险依赖

- 依赖服务端明确 Host 可见的公共角色字段。
- 模糊显示规则需要和剧情/规则层统一，否则 UI 难以判断何时隐藏精确值。
- 后续若引入旁观者视角，需要重新审查公共字段边界。

