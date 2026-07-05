# Projection 投影系统 PRD V2.0

## 背景

AI-Keeper 的核心卖点不是把所有内容广播给所有人，而是让同一条权威事实在不同视角下安全呈现：Host 看到公共舞台和可控演出，玩家看到队伍公开叙事和自己的私密结果，系统日志保留可审计证据。当前代码已有 `EngineEvent`、`events` 表、`ProjectionDispatcher`、`ConnectionManager`、Host/Player WS、重连接口和 SpoilerGuard 安全网，但实时投递、重连补发、归档导出和事件注册仍有多套口径。

Projection v1 的目标是先把可见性、顺序、事件契约和防剧透补齐，不做复杂消息总线。

## 目标

1. 建立统一事件 envelope：所有实时和补发事件都使用稳定 `EngineEvent` 语义。
2. 建立统一可见性规则：live、catch-up、reconnect、archive、export 使用同一口径。
3. 保证 Host-only、Player-only、Party、System 事件不会互相泄露。
4. 保证状态 patch 有版本字段，支持客户端乱序屏障。
5. 保证 Projection 只发送已持久化事实，不改写规则和状态。
6. 保证所有 `s2c_*` 事件在 registry、后端类型、前端类型、测试中一致。
7. 保留 SpoilerGuard 作为最后安全网，命中时可审计。

## 非目标

- 不实现跨进程消息总线。
- 不实现第三方 webhook。
- 不实现观众直播延迟。
- 不创建完整频道系统，频道产品归 Channel 模块。
- 不把 Projection 改成状态写入层。
- 不让客户端本地状态决定服务端可见性。
- 不在本轮重构所有历史乱码文案，只修触达的事件契约和安全风险。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Host | 接收 host-only 与 party 事件，看到公共舞台、地图、遭遇和队伍消息 | 看到 player-only 私密 payload，或通过 UI frame 改写状态 |
| Player | 接收 party 事件和本人 player 事件，重连后补回可见内容 | 接收其他玩家私密事件、Host-only 真相或 KP-only 信息 |
| Engine/Transaction | 调用投影层发送已确认事件 | 在未持久化状态前发完成事件 |
| State | 提供带版本的 patch 和 snapshot | 让 Projection 推导世界真相 |
| Safety | 扫描 player/party payload，记录剧透拦截审计 | 代替上游权限和线索归属校验 |
| Admin/Ops | 查询投影日志、定位泄露和断线问题 | 直接编辑历史事件制造新事实 |

## 核心概念

### Event Envelope

标准事件信封包含：

- `eventId`
- `roomId`
- `type`
- `roomSequence`
- `audience`
- `visibility`
- `issuedAt`
- `payload`

所有 Player WS 帧必须使用该 envelope。Host WS 可以在内部翻译成 UI frame，但源事件仍应能在日志中追溯。

### Audience

| Audience | 含义 | 投递范围 |
| --- | --- | --- |
| `host` | Host-only 舞台、HUD、KP 可见内容 | 房主、管理员、Host WS |
| `player` | 单个玩家私密事件 | 目标 `character_id` 对应连接 |
| `party` | 队伍公开内容 | Host 与所有房间玩家 |
| `system` | 系统审计或公共系统事件 | 默认不主动给玩家，按具体事件白名单处理 |

`audience="player"` 必须有明确目标角色。缺少目标角色的 player 事件不得作为公开事件补发。

### Visibility Scope

仅有 audience 不足以表达所有规则。Projection 需要一个可复用的可见性判断：

```text
can_view_event(event, viewer_role, character_id) -> bool
```

该判断同时服务实时投递、WS catch-up、`/api/player/reconnect`、player archive、public events 和 export。

## 核心流程

### 实时投递

1. 上游模块调用 `ProjectionDispatcher.emit(room_id, event_type, audience, payload, character_id)`。
2. Projection 可选执行 SpoilerGuard 安全网。
3. 事件写入 `events` 并获得 sequence。
4. Projection 组装标准 `EngineEvent`。
5. Host-only 发给 Host，player-only 发给目标角色，party 广播给 Host 和所有玩家。
6. WS 投递失败不回滚已持久化事件。

### Player WS catch-up

1. Player 用 room、token、lastSequence 连接 WS。
2. 服务端验证 token 属于该 room 的角色。
3. 服务端查询 lastSequence 之后的事件。
4. 服务端只补发该角色可见事件。
5. 发送后客户端更新内存 `lastSequence`。

### `/api/player/reconnect`

1. Player 用 `X-Room-Token` 调接口。
2. 服务端读取 `player_sequences` 的最后确认 sequence。
3. missed events 少时返回过滤后的增量事件。
4. missed events 多或首次连接时返回 snapshot，但 `recent_events` 仍必须过滤。
5. 返回 pending actions 只包含该玩家角色的 action。
6. 返回 `stateVersion`，供客户端 patch 屏障使用。

### 状态 patch 投影

1. StateService 写入权威状态并获得 `stateVersion`。
2. Projection 只发送包含版本的 patch。
3. player-only patch 定向给目标玩家。
4. party patch 只能是公开摘要或公共状态，不得含私密数值。
5. 客户端按版本应用或重拉 snapshot。

### Host 演出投影

1. Transaction 生成 `s2c_reveal_transaction`。
2. Host WS 收到标准事件后可转成 UI frame。
3. Host 播放过程不能产生规则结果。
4. Host ACK 和 delayed private release 与 Transaction 协同，Projection 只执行安全投递。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PJ-FR-1 | 所有 `s2c_*` 事件必须登记在 registry、后端 Literal 和前端类型中。 | P0 |
| PJ-FR-2 | `ProjectionDispatcher.emit` 写入 events 后再实时投递，并返回或记录 sequence。 | P0 |
| PJ-FR-3 | Host-only 事件不得发送给 Player WS、Player reconnect、public events、public export。 | P0 |
| PJ-FR-4 | Player-only 事件必须绑定目标角色，且只对目标角色可见。 | P0 |
| PJ-FR-5 | Party 事件只允许公开 payload，发送给 Host 和所有玩家。 | P0 |
| PJ-FR-6 | `player_ws_endpoint` catch-up 必须按可见性过滤。 | P0 |
| PJ-FR-7 | `/api/player/reconnect` 普通补发和 snapshot 补发必须按可见性过滤。 | P0 |
| PJ-FR-8 | `EventLog.get_public_events`、public archive、public export 必须复用公共可见性白名单。 | P0 |
| PJ-FR-9 | `s2c_state_patch` 必须携带 `schemaVersion`、`baseStateVersion`、`stateVersion`、`actionId`。 | P0 |
| PJ-FR-10 | Projection 不得发送未持久化状态 patch。 | P0 |
| PJ-FR-11 | SpoilerGuard 安全网失败时不应中断投影，但要保留可观测日志。 | P1 |
| PJ-FR-12 | Host UI frame 与标准 EngineEvent 的边界必须稳定，避免前端分支漂移。 | P1 |
| PJ-FR-13 | 直接写 events 的路径必须标注为日志事件或收口到 Dispatcher。 | P1 |
| PJ-FR-14 | `player_sequences` 应能表达玩家已确认 sequence，避免重复补发和漏发。 | P2 |

## 接口方向

| 接口或事件 | 当前状态 | 受众 | 说明 |
| --- | --- | --- | --- |
| `ProjectionDispatcher.emit` | 已有 | 内部 | 事件落库和实时投递主入口 |
| `ConnectionManager.broadcast_to_room` | 已有 | 内部 | 按 audience 实时广播 |
| `ConnectionManager.send_event` | 已有 | 内部 | 定向到 `player:{character_id}` |
| `GET /api/player/reconnect` | 已有 | Player | 增量或 snapshot 重连 |
| Player WS `/ws?role=player` | 已有 | Player | 实时接收和 catch-up |
| Host WS `/ws?role=host` | 已有 | Host | Host 舞台实时通道 |
| `GET /api/rooms/{room_id}/events/public` | 已有 | Player | 公共事件回看，过滤需修正 |
| `GET /api/player/archive` | 已有 | Player | 玩家个人归档，私密过滤需加固 |
| `GET /api/rooms/{room_id}/export?scope=public` | 已有 | Player | 公开战报导出，过滤需修正 |
| `s2c_reveal_transaction` | 已有 | Host | Host 演出事务 |
| `s2c_state_patch` | 已有 | Player / Party | 必须明确私密和公开 patch 的差异 |
| `s2c_action_completed` | 已有 | Player | 行动完成回执 |
| `s2c_public_observation` | 已有 | Party | 公共叙事 |
| `s2c_team_message` | 已有 | Party | 队伍消息 |
| `s2c_turn_resolved` | 代码有 emit，类型缺口 | Party | 回合摘要，需统一登记 |

## 数据边界

- `events` 是投影日志，不是未落库状态的替代品。
- `roomSequence` 来自 `events.sequence`。
- `player_sequences` 是补发游标，不是权限依据。
- WS 连接表只保存在线连接，不保证持久。
- Host UI frame 不写入 events，标准 `s2c_*` 事件才是审计来源。
- Spoiler audit 记录安全网命中，不替代事件日志。

## 权限边界

- Player 请求不能声明自己是谁，只能由 token 反查角色。
- Host 请求不能伪造 owner/admin 身份。
- `audience="player"` 缺少目标角色时不能广播。
- public replay/export 不能用 `audience != 'player'` 判断公开。
- Host-only 事件可以给 Admin/Host 查询，但不能进入 Player 可见路径。
- Party 事件进入玩家可见前必须经过剧透控制。

## 验收标准

1. Player A 实时收不到 Player B 的 `s2c_state_patch`、`s2c_private_notice`、`s2c_action_completed`。
2. Player A 的 WS catch-up 不包含 Host-only 事件。
3. Player reconnect 首次 snapshot 不包含 Host-only 事件和其他玩家私密事件。
4. `GET /api/rooms/{room_id}/events/public` 不返回 Host-only reveal 或 Host snapshot。
5. public export 不含 Host-only 真相和 player token。
6. `s2c_state_patch` 带版本字段，旧 patch 可被客户端拒绝或触发重拉。
7. 所有实际 emit 的 `s2c_*` 在 registry、后端类型、前端类型和测试中一致。
8. SpoilerGuard 命中后 player/party payload 被替换为安全文本，并能查到 audit。
9. Projection 测试覆盖 live、catch-up、reconnect、archive/export 四条可见性路径。
