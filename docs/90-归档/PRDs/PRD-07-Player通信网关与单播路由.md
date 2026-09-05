# PRD-07 - Player 通信网关与单播路由

**版本**: 1.0  
**状态**: 待开发  
**来源**: Player 模块 1、PRD-00、PRD-01  
**适用范围**: PlayerWSClient、PlayerRouter、Player Store 入口

## 1. 背景

Player 端 v2 从 WebSocket 双向命令改为 REST 上行意图 + WebSocket 下行事件。私密信息安全不能依赖前端 `target` 过滤，而要由服务端按角色连接物理隔离。Player 路由器只负责本地序列、状态同步和 UI 分发。

## 2. 目标

- 建立 Player 专属 WebSocket 客户端。
- 基于 `playerSequence` 做去重和乱序拦截。
- 消费快照、patch、私密通知、公共观察、战术 prompt 和动作完成事件。
- 杜绝 Player 端直接接收或渲染 Host 事务演出。

## 3. 范围边界

**包含**
- `PlayerWSClient` 连接、重连、断开。
- `routePlayerEvent` 分发。
- Player 下行事件白名单。
- room token 身份凭证使用。

**不包含**
- REST 意图提交细节。
- 角色卡、背包、聊天的具体 UI。
- 服务端单播实现。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-07-1 | 作为玩家，我只应收到属于自己角色的私密线索和状态更新。 | P0 |
| US-07-2 | 作为开发者，我需要 Player 重连后能从最后序列继续同步。 | P0 |
| US-07-3 | 作为 KP，我需要 Player 端不会渲染 Host 大屏专属事务，避免体验混乱。 | P1 |

## 5. 功能需求

1. Player 连接 URL 包含 `roomId`、`role=player`、`characterId`、`lastSequence`、`token`。其中 `characterId` 仅用于服务端日志和调试展示，不作为安全身份依据；实际路由和权限判定必须以 `X-Room-Token` 或等价 token 解密结果为准。
2. 服务端单播是信息隔离主机制，前端不实现 `target === myCharacterId` 过滤作为安全前提。
3. 路由器校验 `roomId` 和 `playerSequence`，重复/乱序事件丢弃。
4. `s2c_action_completed` 更新动作生命周期。
5. `s2c_full_snapshot` 覆写 Player 本地状态。
6. `s2c_state_patch` 按 `baseStateVersion` 应用增量。
7. `s2c_private_notice` 追加私密通知。
8. `s2c_tactical_prompt` 追加战术聊天消息。
9. `s2c_public_observation` 追加公共观察。
10. `s2c_reveal_transaction` 默认不进入 Player UI，公共演出由 Host 负责。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| WebSocket | `/ws?room={roomId}&role=player&characterId={id}&lastSequence={seq}&token={token}` | Player 下行事件 |
| Event | `s2c_full_snapshot` | 初始化/重连状态 |
| Event | `s2c_state_patch` | 增量状态同步 |
| Event | `s2c_private_notice` | 私密通知 |
| Event | `s2c_public_observation` | 公共观察 |
| Event | `s2c_tactical_prompt` | 战术行动提示 |
| Event | `s2c_action_completed` | 动作解锁 |

## 7. 状态与错误处理

- 连接失败后指数退避重连，最大间隔 30s。
- token 缺失或失效时进入重新加入房间流程。
- patch 版本不匹配时停止应用并请求全量同步。
- 未知事件 warning 丢弃，不弹窗打扰玩家。
- 重连期间 UI 保留最后状态，并显示同步中状态。

## 8. 验收标准

- Player 所有下行事件都通过 `EngineEvent` 信封。
- 重复 `playerSequence` 不导致重复通知或重复状态更新。
- `s2c_reveal_transaction` 不渲染在 Player 主界面。
- token 失效有明确恢复路径。
- Player Router 覆盖所有 PRD-00 中的 Player 相关事件。

## 9. 测试场景

1. Player A 收到私密线索，Player B 的 Store 无该线索。
2. 连续收到同一 `s2c_state_patch` 两次，只应用一次。
3. patch 版本不匹配，触发 `/api/player/sync`。
4. WebSocket 断开后重连，携带最后 `playerSequence`。

## 10. 风险依赖

- 依赖服务端真实单播隔离，前端过滤不能作为安全边界。
- 依赖 room token 映射角色身份。
- 多设备登录同一角色时需要后续定义冲突策略。
