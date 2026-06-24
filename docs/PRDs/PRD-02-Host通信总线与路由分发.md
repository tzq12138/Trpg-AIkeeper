# PRD-02 - Host 通信总线与路由分发

**版本**: 1.0  
**状态**: 待开发  
**来源**: Host 模块 1、PRD-00  
**适用范围**: Host WebSocket、EventRouter、Host Store 入口

## 1. 背景

Host 是公共演出终端，只消费 Engine 投影事件，不做业务判定。通信层必须解决四件事：连接房间、断线重连、序列号去重、事件分流。旧式“收到就广播到 UI”的模式会导致重复播放、跨房污染和 Player 私密事件误入大屏。

## 2. 目标

- 建立 Host 专属 WebSocket 客户端和路由器。
- 只接收并处理 Host 可见事件。
- 将事务事件送入队列，将瞬时事件直接写入 Store。
- 支持房间切换清理和指数退避重连。

## 3. 范围边界

**包含**
- `HostWSClient` 单例生命周期。
- `routeHostEvent` 信封校验、序列号校验和白名单分发。
- `s2c_reveal_transaction`、抢占控制、Host 快照和瞬时事件处理。

**不包含**
- 事务 step 的具体播放逻辑。
- HUD 和舞台组件样式。
- WebSocket 服务端实现细节。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-02-1 | 作为 KP，我需要 Host 大屏断线后自动重连，并从正确序列继续播放。 | P0 |
| US-02-2 | 作为开发者，我需要 Host 丢弃 Player 私密事件，以便防止剧透。 | P0 |
| US-02-3 | 作为观众，我不希望同一演出事件因为重连重复播放。 | P0 |

## 5. 功能需求

1. Host 连接 URL 包含 `roomId`、`role=host`、`lastSequence`。
2. 切换房间时必须断开旧连接，并调用 `resetRoomStore()`。
3. WebSocket 关闭后使用指数退避 + jitter 重连，最大间隔 30s。
4. 路由器校验 `roomId`、`hostSequence`，重复/乱序事件直接丢弃。
5. `s2c_reveal_transaction` 按 `priority` 进入 normal 或 urgent 队列。
6. `s2c_resume_transaction` 与 `s2c_cancel_transaction` 直达事务 Store。
7. 瞬时白名单包含 `s2c_atmosphere`、`s2c_engine_state`、`s2c_scene_sync`、`s2c_host_snapshot`。
8. `s2c_full_snapshot`、`s2c_state_patch`、`s2c_private_notice` 等 Player 事件进入 Host 时必须丢弃并告警。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| WebSocket | `/ws?room={roomId}&role=host&lastSequence={seq}` | Host 下行事件 |
| Event | `s2c_reveal_transaction` | 入事务队列 |
| Event | `s2c_host_snapshot` | 初始化公共状态 |
| Event | `s2c_atmosphere` | 更新氛围状态 |
| Event | `s2c_engine_state` | 显示 Engine 状态 |
| Event | `s2c_scene_sync` | 同步背景图 |

## 7. 状态与错误处理

- JSON 解析失败时记录错误，不影响连接。
- 达到最大重连次数后显示 Host 连接异常状态，不清空已有画面。
- 收到非法事件类型时 warning 丢弃。
- `hostSequence` 缺失时使用 `roomSequence` 兜底，但记录协议告警。
- `s2c_host_snapshot` 应覆盖公共 Store，并重置 `lastHostSequence` 到快照序列。

## 8. 验收标准

- Host 断线重连请求携带最后已处理序列号。
- Player 私密事件不会更新 Host Store。
- 切换房间后旧房间队列、HUD、背景、音效全部清空。
- 重复事件不会触发第二次播放。
- 白名单与 PRD-00 事件全集一致。

## 9. 测试场景

1. 模拟 Host 收到同一事件两次，第二次被丢弃。
2. 模拟收到 `s2c_private_notice`，Host Store 无变化并输出 warning。
3. 切换 roomA 到 roomB，旧连接断开，Store 清空后新连接建立。
4. WebSocket 连续断开，重连间隔按指数增长。

## 10. 风险依赖

- 依赖 Engine 为 Host 生成稳定递增 `hostSequence`。
- 依赖 `s2c_host_snapshot` 服务端实现。
- 若未来支持多 Host，需要明确同房多大屏的序列策略。

