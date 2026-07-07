# Projection 投影系统 PRD V2.1

## 背景

AI-Keeper 的差异化不在于“把所有信息都广播给所有人”，而在于让同一条权威事实在不同视角下被安全地看到：

- Host 看到公共舞台、演出编排和主持控制信息。
- Player 看到队伍公开叙事和自己的私密结果。
- Journal / Export 看到可追溯、可审计、可脱敏的事件视图。
- Admin / Ops 看到调试与安全审计，但这些内容不能回流到玩家面。

当前仓库里已经有：

- `EngineEvent` 事件信封；
- `ProjectionDispatcher.emit()`；
- `events` 持久化事件表；
- Player / Host WebSocket；
- `get_events_for_player()`、`get_public_events()`；
- `/api/player/reconnect`；
- SpoilerGuard 安全网。

但现状仍然存在几类真实风险：

1. reconnect snapshot 直接返回整房间事件；
2. public export 仍把 `audience != 'player'` 近似当成“公开”；
3. `player_sequences` 语义不清，容易被误当“玩家已完整看过所有事件”；
4. `s2c_state_patch` 缺版本字段；
5. `resolution_pipeline` 仍有“先投影、后 State 落库”的顺序风险；
6. Host UI frame 与标准 `EngineEvent` 边界还不够硬。

Projection v1 的目标不是做完整消息平台，而是先把“可见性、payload 裁剪、事件时序、断线补发、公开导出、安全审计”固化到可执行、可验证的程度。

## 当前阶段

当前阶段定位为：

`P0 主链路 + 分层可见性与事件投递风险识别版`

这一版先锁定 Room 主链路、Player 实时链路、Host 演出链路、Journal 公共回放与 public export 的安全边界，不在本轮内引入跨进程消息总线、复杂订阅 DSL 或多设备可靠投递协议。

## 目标

1. 建立统一事件信封，所有实时、补发、归档、回放都可追溯到同一条 `EngineEvent` 语义。
2. 建立统一可见性契约，live / catch-up / reconnect / archive / export 使用同一套后端判断和 payload 裁剪口径。
3. 保证 Host-only、Player-only、Party、System-safe 事件不会互相泄露。
4. 保证 `s2c_state_patch` 带版本字段，并且只在权威状态落库后对外下发。
5. 固化 Host UI frame 与标准 `EngineEvent` 的边界，避免 Host 客户端协议反向污染审计事实。
6. 固化 Projection 与 Transaction 的边界：ReleaseGate 属于 Transaction，Projection 只在允许释放时做投递。
7. 固化 direct `events` write path 的分类：哪些是 `realtime`，哪些是 `audit-only`。

## 非目标

- 不在本轮实现跨服务事件总线。
- 不在本轮实现离线消息队列。
- 不在本轮实现复杂订阅表达式、事件 DSL、插件投影转换器。
- 不让 Projection 负责规则结算、状态写入、AI 叙事生成。
- 不让客户端本地状态决定服务器可见性。
- 不把 Host UI frame 当成权威事件日志。

## 角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Host | 看到 Host-only 与公共舞台事件，驱动演出与释放流程 | 不能通过 Host frame 写世界状态，不能把私密玩家 payload 当成公共事实 |
| Player | 看到队伍公开叙事和自己的私密结果 | 不能拿到其他玩家 private 事件，不能拿到 Host-only / KP-only 真相 |
| Transaction | 在合适时机创建 reveal / release gate / trace refs | 不应让 Projection 自己决定事务状态 |
| State | 提供已落库的权威状态与版本号 | 不应依赖 Projection 推导事实 |
| Journal / Export | 获取可回放、可脱敏的事件视图 | 不应绕过 Projection 视图 helper 直接裸读 `events` 做 public 输出 |
| Safety | 扫描公开文本、记录 SpoilerAudit | 不替代上游 clue / truth / hidden data 的所有权限约束 |
| Admin / Ops | 查询审计、排障、定位泄露 | 不将 raw audit、debug payload 回流到玩家界面 |

## Projection 数据分层

| 层级 | 名称 | 说明 |
| --- | --- | --- |
| L0 | 权威事实 | `actions`、`rooms.state_version`、runtime state、clue ownership、map state 等真实业务状态 |
| L1 | `ProjectionRequest` | 上游请求投递某个事件 |
| L2 | `EngineEventEnvelope` | 标准事件外壳 |
| L3 | `EventLog` | 落库后的 sequence 事件流 |
| L4 | `VisibilityDecision` | 某个 viewer 对某条事件的允许/拒绝判定 |
| L5 | `PayloadProjection` | 针对某个 viewer 的安全 payload 视图 |
| L6 | `HostFrame` | HostStage 消费的显示协议 |
| L7 | `PlayerEventStream` | Player WS 的标准事件流 |
| L8 | `ReconnectSnapshot` | missed events / snapshot 返回包 |
| L9 | `PublicEventView` | public replay / public export 的公共事件视图 |
| L10 | `SpoilerAudit` | SpoilerGuard 的命中与失败审计 |

关键约束：

- L0 不等于 L3。世界状态与事件日志不能互相替代。
- L3 不等于 L9。`events` 表中的内容不能直接裸给 public export。
- L6 不等于 L3。Host frame 是显示协议，不是审计事实。
- L10 不等于玩家日志。安全审计只属于 Admin / Ops。

## DTO 契约

### 1. `EngineEventEnvelopeDTO`

标准事件信封最低字段：

- `eventId?`
- `roomId`
- `type`
- `roomSequence`
- `audience`
- `payload`
- `issuedAt?`

要求：

- Player WS、catch-up、reconnect recent events 都以此为准。
- Host 可把它翻译为 `HostFrameDTO`，但原事件仍应可在 `events` 中追溯。

### 2. `ProjectionRequestDTO`

用于上游向 Projection 发起投递：

- `roomId`
- `eventType`
- `audience`
- `payload`
- `characterId?`
- `traceRefs?`：如 `actionId / turnId / transactionId / stateVersion`

要求：

- `audience=player` 时必须有目标角色。
- `party` 不等于“可以带完整私密 payload 广播”。

### 3. `VisibilityDecisionDTO`

最低字段：

- `allowed: bool`
- `viewerRole`
- `viewerCharacterId?`
- `reason`

推荐 `reason`：

- `host_view`
- `player_owner`
- `party_visible`
- `system_safe`
- `deny_host_only`
- `deny_other_player_private`
- `deny_missing_owner`
- `deny_not_public`

### 4. `ProjectedPayloadDTO`

针对特定 viewer 的安全事件视图：

- `type`
- `roomSequence`
- `safePayload`
- `safeText?`
- `sourceRefs?`

约束：

- public 视图只能带 public 字段。
- player archive 视图只能带玩家本人可见字段。
- full export 也不是数据库原样导出，仍然要脱敏 token、secret、raw debug。

### 5. `StatePatchEventDTO`

最低字段：

- `actionId`
- `schemaVersion`
- `baseStateVersion`
- `stateVersion`
- `patches`

可选字段：

- `transactionId`
- `turnId`
- `sourceRefs`

约束：

- 不允许再下发无版本字段的 `s2c_state_patch`。
- Player-only patch 必须绑定目标角色。
- Party patch 只能带公共摘要，不得带私密数值真相。

### 6. `HostFrameDTO`

Host 端展示协议，例如：

- `host_state_update`
- `chat_message`
- `map_updated`
- `scene_update`
- `encounter_started`

边界：

- `HostFrameDTO` 来自标准 `EngineEvent` 翻译。
- `HostFrameDTO` 不写入 `events`。
- `HostFrameDTO` 不作为 Journal replay / export 的数据源。

### 7. `SpoilerAuditDTO`

最低字段方向：

- `auditId`
- `roomId`
- `actionId?`
- `eventType`
- `audience`
- `characterId?`
- `violations`
- `finalText`
- `status`

边界：

- 仅 Admin / Ops 可读。
- 不进入 public export。
- 不进入 Player archive。

## Audience 与可见性模型

### Audience 只定义顶层受众

| Audience | 含义 | 默认去向 |
| --- | --- | --- |
| `host` | Host-only 舞台、HUD、主持控制信息 | Host / Admin |
| `player` | 单个玩家私密事件 | 目标 `character_id` |
| `party` | 队伍公开叙事 | Host + 房间全部玩家 |
| `system` | 系统事件、审计事件、公共系统摘要 | 默认不 public，按白名单单独开放 |

### `can_view_event()` 不够，必须再有 `build_event_view()`

Projection 不能只有一个“能不能看”的 bool 判断，还必须同时定义“给谁看时应该长什么样”。

建议契约：

```text
can_view_event(event, viewer_role, viewer_character_id, scope) -> VisibilityDecisionDTO
build_event_view(event, viewer_role, viewer_character_id, scope) -> ProjectedPayloadDTO | None
```

其中 `scope` 至少包括：

- `live`
- `catch_up`
- `reconnect`
- `archive`
- `public_export`
- `full_export`

核心规则：

1. `host` audience：默认只有 Host / Admin 可读。
2. `player` audience：只有目标角色本人可读；缺少 owner 标识时默认拒绝给普通玩家。
3. `party` audience：所有玩家可读，但 payload 必须已是公共版。
4. `system` audience：默认不 public，只有 `system_safe` 白名单才可进入玩家 / public 视图。
5. 同一条事件的 public / player / host / admin 视图允许字段不同。

## `system_safe` 白名单

当前代码里已有 `PLAYER_VISIBLE_SYSTEM_EVENTS`，但产品语义还要再收紧。

### 可作为 `system_safe` 的最小示例

- `s2c_turn_resolved` 的安全摘要。
- `s2c_checkpoint_created` 的安全摘要，前提是不含 raw restore reason、snapshot 路径、debug payload。

### 默认不能作为 `system_safe` 的示例

- `s2c_checkpoint_restored` 的原始审计 payload。
- `host_force_move`。
- admin override / debug / internal error。
- spoiler audit。
- raw restore reason。

要求：

- `system_safe` 不只按事件名白名单，还要按 payload 字段白名单裁剪。
- 工程回执必须明确说明：
  - `s2c_turn_resolved` 最终是否只下发安全摘要；
  - `s2c_checkpoint_created` 是否排除了 raw snapshot / path / debug payload；
  - `s2c_checkpoint_restored` 是否保持 `audit-only`，不进入 Player / public 视图。

## `player_sequences` 语义

`player_sequences.last_delivered_sequence` 在本项目中的语义必须明确为：

`该角色在该房间的投递游标（delivery cursor）`

它表示：

- 服务器已经把某个房间 sequence 之前的可见事件流交给了这个角色；
- reconnect 可以从这个游标继续计算 missed events。

它不表示：

- 玩家看到了房间里所有 sequence；
- 玩家确认读过所有事件；
- 玩家拥有某个 sequence 之后所有事件的权限。

必须接受的现实：

- 因为房间 sequence 是全局递增的，玩家视图里天然会出现“跳号”。
- 跳号不应被解释成数据丢失；它可能只是中间夹着 Host-only 或其他玩家 private 事件。
- P0 允许使用“房间全局 sequence + 玩家可见过滤”的方案；更强的 per-device ACK 留到后续阶段。

工程回执必须分别说明：

- WS catch-up 后是否更新 `player_sequences`；
- `/api/player/reconnect` 后是否更新 `player_sequences`；
- snapshot 分支是否推进到 room max sequence；
- 本轮是否仍不做 per-device ACK，以及限制是什么。

## Host UI frame 边界

Host 当前已经存在一层独立显示协议，这一层必须与 Projection 标准事件边界对齐：

1. 标准 `EngineEvent` 才是落库、回放、审计来源。
2. `HostFrameDTO` 只是 Host UI 消费协议。
3. `HostFrameDTO` 不得反向写入 `events` 作为事实。
4. Host frame 不得携带玩家私密 patch、raw mutation、hidden truth、未公开 clue 原文。

## realtime / audit-only 路径分类

当前仓库里并不是所有事件都通过 `ProjectionDispatcher.emit()` 发出，必须明确分类：

| 路径 | 当前现状 | 应有分类 |
| --- | --- | --- |
| `ProjectionDispatcher.emit()` | 落 `events` 并实时推送 | `realtime` |
| `EventLog.log_event()` 写 `s2c_checkpoint_created` | 只落库 | `audit-only` 或 `system_safe` 摘要 |
| `EventLog.log_event()` 写 `s2c_checkpoint_restored` | 审计性质 | `audit-only` |
| `EventLog.log_event()` 写 `host_force_move` | 审计性质 | `audit-only` |
| 房间大厅快照、ready、队伍消息等如果需要实时同步 | 代码中部分走 `emit()`，部分仍直接写日志 | 应统一分类并在工程回执中列清 |

要求：

- 每一条 direct `events` write path 都要在回执中说明是 `realtime` 还是 `audit-only`。
- 不能把“为了统一”误改成“所有日志都实时广播给玩家”。
- 工程回执还必须说明 `ProjectionBuilder` 的去留：
  - 如果保留，它与 `ProjectionDispatcher` 的职责边界是什么；
  - 如果不保留，统一 helper 由谁调用、如何避免双口径。

## 与 Transaction 的 ReleaseGate 边界

Projection 不拥有 ReleaseGate。

本模块定义：

1. Transaction 负责生成 release gate、延迟释放队列、Host ACK 语义。
2. Projection 负责在“允许释放”的时点投递给正确受众。
3. Projection 不决定何时播完 reveal step。
4. Projection 不决定 `action_completed` 是否应该提前给玩家。

也就是说：

- `ReleaseGateDTO` 的创建、持久化、恢复，归 14-Transaction。
- 15-Projection 只消费 gate 的结果，不再自行推断“现在能不能放私密结果”。

## 核心流程

### 1. 实时投递

1. 上游模块构造 `ProjectionRequestDTO`。
2. Projection 视情况调用 SpoilerGuard 扫描 player / party 文本。
3. Projection 先写 `events` 并拿到 `roomSequence`。
4. Projection 生成 `EngineEventEnvelopeDTO`。
5. Projection 按 audience + visibility helper 发送给 Host / Player。
6. WS 推送失败不回滚已落库事件。

### 2. Player WS catch-up

1. Player 使用 `token + room + lastSequence` 建立 WS。
2. 服务端鉴权并反查角色。
3. 服务端查询 `lastSequence` 之后的房间事件。
4. 逐条走 `can_view_event + build_event_view`。
5. 只返回玩家本人可见事件。

### 3. `/api/player/reconnect`

1. 服务端读取 `player_sequences`。
2. missed events 少时返回增量事件。
3. missed events 多或首次进入时返回 snapshot。
4. 不论增量还是 snapshot，`recent_events` 都必须是经过统一裁剪的安全视图。
5. 返回的 `last_sequence` 是 room sequence cursor，不等于“玩家已看完所有事件”。

### 4. public replay / public export

1. 只允许 `party` 与 `system_safe` 视图。
2. 不允许继续使用 `audience != 'player'` 当作公开判断。
3. public export 必须复用 public 视图 helper，而不是单独拼接 SQL 近似逻辑。

### 5. 状态 patch 投递

1. State 先写权威状态并拿到 `stateVersion`。
2. Projection 再下发 `s2c_state_patch`。
3. `s2c_state_patch` 必须携带版本字段。
4. Player 端按版本应用或触发 full sync。

### 6. Host 演出视图

1. Transaction 发出标准 reveal 事件。
2. Projection 只负责把 Host-safe 事件交给 Host。
3. Host router 可翻译为 `HostFrameDTO`。
4. Host ACK / delayed release / replay control 仍归 Transaction。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PJ-FR-1 | 所有真实发出的 `s2c_*` 事件必须在 registry、后端类型、前端类型中对齐 | P0 |
| PJ-FR-2 | Projection 必须先落 `events`，再实时下发 | P0 |
| PJ-FR-3 | Host-only 事件不得进入 Player WS、player reconnect、public replay、public export | P0 |
| PJ-FR-4 | Player-only 事件必须绑定目标角色，且只对目标角色可见 | P0 |
| PJ-FR-5 | Party 事件只能带公共 payload，不得夹带私密真相 | P0 |
| PJ-FR-6 | live / catch-up / reconnect / archive / export 必须复用同一可见性口径 | P0 |
| PJ-FR-7 | reconnect missed events 与 snapshot 都必须走统一过滤与 payload 裁剪 | P0 |
| PJ-FR-8 | public replay / public export 只能返回 `party + system_safe` 视图 | P0 |
| PJ-FR-9 | `s2c_state_patch` 必须带 `schemaVersion / baseStateVersion / stateVersion / actionId` | P0 |
| PJ-FR-10 | Projection 不得下发尚未持久化的状态 patch | P0 |
| PJ-FR-11 | `player_sequences` 语义必须被写清并在回执里说明更新时机 | P0 |
| PJ-FR-12 | Projection 只消费 ReleaseGate 结果，不拥有 gate 决策权 | P0 |
| PJ-FR-13 | Host UI frame 与标准 `EngineEvent` 边界必须稳定 | P1 |
| PJ-FR-14 | 直接写 `events` 的路径必须分类为 `realtime` 或 `audit-only` | P1 |
| PJ-FR-15 | SpoilerGuard 命中与失败必须有可查审计，但不能阻断已落库事实 | P1 |

## 接口方向

| 接口或事件 | 当前状态 | 受众 | 说明 |
| --- | --- | --- | --- |
| `ProjectionDispatcher.emit()` | 已有 | 内部 | 主实时投递入口 |
| `EventLog.get_events_for_player()` | 已有 | 内部 | Player WS catch-up 过滤入口 |
| `GET /api/player/reconnect` | 已有 | Player | missed events / snapshot 恢复 |
| Player WS `/ws?role=player` | 已有 | Player | 实时事件 + catch-up |
| Host WS `/ws?role=host` | 已有 | Host | Host 演出通道 |
| `GET /api/rooms/{room_id}/events/public` | 已有 | Player / Public | 必须只返回 public 视图 |
| `GET /api/player/archive` | 已有 | Player | 必须只返回本人可见 archive 视图 |
| `GET /api/rooms/{room_id}/export?scope=public` | 已有 | Player / Public | 必须复用 public 视图裁剪 |
| `s2c_reveal_transaction` | 已有 | Host | Reveal 事务，gate 决策归 Transaction |
| `s2c_state_patch` | 已有 | Player / Party | 需补版本字段并区分 public/private patch |
| `s2c_turn_resolved` | 部分代码已引用 | Party / system_safe | 需统一注册与类型定义 |

## 数据边界

- `events` 是事件日志，不是世界状态本体。
- `roomSequence` 来自 `events.sequence`。
- `player_sequences` 是 delivery cursor，不是权限依据。
- Host frame 不写回 `events`。
- public export / player archive 只能使用裁剪后的视图 DTO，不能裸透 `events.payload`。
- `SpoilerAuditDTO`、raw prompt、raw response、debug payload 不得进入玩家视图。

## 权限边界

- Player 身份只能通过 token 反查，不能由前端自报 `character_id` 决定可见性。
- Host 身份只能通过 owner token 或 owner/admin 账号鉴权获得。
- `audience=player` 缺少 owner 时默认拒绝给普通玩家。
- public 视图不得使用 `audience != 'player'` 的反向近似。
- Player 视图中，缺少 `characterId / recipientCharacterId` 的 private 事件默认不下发。
- Host 可查看 Host-only 事实，但不等于可以查看 Admin/Ops raw 审计。

## public / full export 字段边界

### public export 禁止包含

- `owner_token`
- `player_token`
- `account_id`
- `email`
- 原始 `xlsx_data`
- raw prompt / raw response
- host-only payload
- player-only patch
- hidden truth / 未公开 clue 原文
- hidden node / hidden NPC / admin debug payload
- spoiler audit raw text

### full export 仍禁止包含

- raw token
- API key
- secret
- raw AI prompt / raw AI response
- 运维级调试字段

如未来需要导出 raw AI/Ops 审计，应另设 `admin_audit export scope`，不复用 `full export`。

## 验收标准

1. Player A 实时收不到 Player B 的 private 事件。
2. Player WS catch-up 只返回本人可见事件。
3. `/api/player/reconnect` 普通补发与 snapshot 都不泄露 Host-only 或其他玩家 private 事件。
4. public replay 与 public export 只包含 `party + system_safe` 视图。
5. `system` 事件默认不 public，只有白名单事件能下发给玩家。
6. `s2c_state_patch` 携带完整版本字段，且在 State 落库后才下发。
7. `player_sequences` 的更新时机、语义和跳号解释在工程回执中说清。
8. Host UI frame 不写回 `events`，不被拿来做 public replay / export。
9. 直接写 `events` 的路径都在回执中被分类为 `realtime` 或 `audit-only`。
10. 所有真实发出的 `s2c_*` 事件在 registry、后端类型、前端类型、测试中一致。
11. 工程回执明确写清 `system_safe` 字段裁剪、`player_sequences` 更新时机、direct write path 分类与 `ProjectionBuilder` 去留。
