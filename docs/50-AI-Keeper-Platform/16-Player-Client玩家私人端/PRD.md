# Player Client 玩家私人端 PRD V2.1

## 当前阶段说明

- 本文档当前阶段为：`P0 主链路 + 玩家私人端可用性与恢复安全风险识别版`。
- 目标是把玩家端定义成一个可恢复、受限、只显示授权视角的私人调查终端。
- 本轮只固化主链路、数据边界、DTO 契约、错误模型、恢复语义与安全口径，不把 Player Client 扩展成完整平台版超级前端。
- 当前仓库代码已暴露若干真实风险：中文乱码、`shared/api.ts` 本地自造 `player_token`、`shared/identity.ts` 长期本地存 token、`shared/ws.ts` query token 与内存态 `lastSequence`、`router_reconnect.py` 补发收口风险。本文档以这些真实问题为锚点。

## 背景

AI-Keeper 的玩家端不是普通聊天窗，而是玩家在网团中的私人调查界面。它要把以下行为组织在同一个受限界面里：

- 加入房间、绑定角色、恢复本人房间会话。
- 在 Lobby 查看成员、切换 ready、发送队内消息。
- 在行动页提交文本行动、快捷动作、技能检定、道具主张、地图移动等 `intent`。
- 查看角色当前状态、背包、线索、日志和地图。
- 在刷新、断线、弱网后恢复到服务端认可的状态。

当前代码已经具备主链路雏形，但还没有把“身份可信、状态可信、可见性可信、恢复可信”这四件事关牢。

## 目标

1. 让玩家可以独立完成 `登录 -> 加入房间 -> 绑定角色 -> ready -> 开局 -> 提交行动 -> 接收授权结果`。
2. 让玩家端始终以服务端返回的 `player_token` 与服务端反查身份为准，不信任前端声称的 `character_id`。
3. 让玩家端只消费 `party` 公共内容和“本人 `player-only` 内容”，不接触 Host-only 或未公开真相。
4. 让行动状态、断线恢复、`stateVersion` 屏障和错误恢复都可理解、可验证。
5. 让角色、背包、线索、日志、地图全部以服务端过滤结果为权威。

## 非目标

- 不在玩家端实现规则裁决。
- 不在玩家端直接修改 HP、SAN、背包、地图位置或线索归属。
- 不在玩家端暴露 Host 舞台、KP 全图、隐藏真相或运维审计。
- 不在本轮实现原生移动端 App、直播观众端、完整语音房间、社区或付费能力。
- 不把前端本地过滤当成安全方案。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Player | 加入房间、恢复身份、提交行动、查看授权资源 | 直接写状态、伪造角色、查看他人私密结果 |
| Host | 看到玩家是否加入、是否 ready、公共结果是否投影 | 通过玩家端处理规则或读玩家本地 token |
| AI-Keeper | 接收玩家意图并生成建议/叙事 | 直接信任玩家端状态或向玩家发未授权真相 |
| Admin/Ops | 排查链路问题 | 无审计地读取玩家私密会话 |
| Future Observer | 只读观看公开内容 | 参与行动、读取玩家私密资源 |

## 产品范围

### 本轮进入

- 玩家登录后加入房间。
- 预设卡、xlsx、builder、scenario template 入房。
- 恢复本人角色会话。
- Lobby 成员、ready、队内消息、开局跳转。
- 自由行动、快捷动作、技能检定、道具主张、地图移动。
- 角色、背包、线索、日志、地图五类玩家资源视图。
- Player WS、`/api/player/reconnect`、`/api/player/sync`。
- 中文可读性、最小错误恢复模型、`stateVersion` 屏障。

### 本轮不做

- 原生移动端 App。
- 直播观众端。
- 完整语音视频房间。
- 玩家社区、招募、匹配、付费。
- 复杂离线同步和跨设备一致性。

## 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `AccountSession` | `account_token`、账号摘要 | 账号登录态，只用于登录和恢复本人角色 |
| L1 `PlayerRoomSession` | `player_token`、`room_id`、`character_id` | 房间内玩家会话，是玩家端权威身份 |
| L2 `IdentitySlot` | 本地 identity slot | 仅为开发态多号测试提供便利 |
| L3 `PlayerIntentDraft` | 文本草稿、语音转写、快捷动作草稿 | 待提交意图，不等于服务器已受理 action |
| L4 `ActionViewState` | 行动 UI 状态机 | 展示事务反馈，不决定事务真实状态 |
| L5 `PlayerEventStream` | Player WS 和 reconnect recent events | 只允许消费玩家授权事件 |
| L6 `StateSyncModel` | `stateVersion`、patch buffer、snapshot | 负责版本屏障与状态恢复 |
| L7 `PlayerResourceView` | character/inventory/clues/archive/map | 统一表示玩家可见资源 |
| L8 `LocalDisplayCache` | 本地消息和列表缓存 | 只用于显示优化，不是事实来源 |
| L9 `ErrorRecoveryState` | 标准错误码恢复动作 | 把错误从“失败了”变成“怎么恢复” |
| L10 `EnhancementInput` | VoiceInput、战术按钮 | 增强输入，不能阻断文本主路径 |

## DTO 契约

### 最小 DTO 集合

- `PlayerJoinRequestDTO`
- `PlayerJoinResultDTO`
- `PlayerSessionDTO`
- `PlayerIdentitySlotDTO`
- `PlayerLobbySnapshotDTO`
- `PlayerActionSubmitDTO`
- `PlayerActionStatusDTO`
- `PlayerReconnectDTO`
- `PlayerSyncSnapshotDTO`
- `PlayerStatePatchDTO`
- `PlayerCharacterViewDTO`
- `PlayerInventoryViewDTO`
- `PlayerClueViewDTO`
- `PlayerArchiveEventDTO`
- `PlayerMapViewDTO`
- `PlayerApiErrorDTO`

### 契约要点

#### `PlayerSessionDTO`

```json
{
  "roomId": "room_xxx",
  "characterId": "char_xxx",
  "playerToken": "server_returned_token",
  "displayName": "调查员A",
  "roomStatus": "lobby|active|paused|completed|archived",
  "joinStatus": "joined|pending_approval|removed"
}
```

#### `PlayerStatePatchDTO`

```json
{
  "schemaVersion": 1,
  "actionId": "act_xxx",
  "baseStateVersion": 12,
  "stateVersion": 13,
  "patches": []
}
```

#### `PlayerApiErrorDTO`

```json
{
  "status": 409,
  "code": "state_version_conflict",
  "message": "当前状态已变化，请同步后重试。",
  "recoveryAction": "sync"
}
```

`PlayerApiErrorDTO.code` 本轮至少固定以下最小枚举：

- `not_authenticated`
- `player_token_invalid`
- `room_not_found`
- `action_not_found`
- `duplicate_action`
- `state_version_conflict`
- `rate_limited`
- `server_error`

### DTO 边界要求

- Player/Public DTO 不得携带 `owner_token`、原始账号敏感字段、Host-only payload、raw AI prompt、raw AI response。
- `PlayerClueViewDTO` 前端内部统一使用 `clueId`，适配层兼容 `clue_id/id`。
- `PlayerArchiveEventDTO` 只允许 `safeText/safePayload`，不允许用“后端全量事件减去几个字段”的方式偷懒。

## 核心流程

### 1. 加入房间与角色绑定

1. 玩家打开 `/player/join`。
2. 如果没有 `account_token`，跳转 `/login`，保留 return path。
3. 玩家输入 room code 和玩家昵称。
4. 玩家从 preset/xlsx/builder/template 四种角色来源中选择一种。
5. 前端调用 `POST /api/player/rooms/{room_id}/join-with-character`。
6. 服务端创建/绑定角色并返回权威 `player_token`。
7. 前端只覆盖“当前房间当前 slot”会话，进入 Lobby。

### 2. Lobby

1. 玩家进入 `/player/{room_id}/lobby`。
2. 拉取 `join-info`、`character`，并订阅 `s2c_room_lobby_snapshot`、`s2c_team_message`。
3. 玩家点击 ready，前端发 `ready_toggle` intent。
4. 若失败，回滚乐观 UI；若成功，等待新 snapshot 落地。
5. 房间变为 `active` 后，前端自动跳转行动页，轮询只作兜底，不重复跳转。

### 3. 行动终端

1. 玩家在 `action` tab 输入自由行动，或点击战术按钮。
2. 前端生成 `action_id`，调用 `POST /api/player/intent`。
3. UI 状态流转：`submitting -> queued/batched -> resolving -> resolved/rejected/timeout`。
4. Projection 只向玩家发送其可见结果与队伍公共结果。
5. 玩家资源页通过授权接口更新，不通过本地猜测补齐状态。

### 4. 断线与恢复

1. WS 断开后进入 `offline/reconnecting`。
2. 刷新或长断线时调用 `/api/player/reconnect`。
3. 服务端返回 session、`recent_events`、`pending_actions`、`last_sequence`、`stateVersion`。
4. 前端根据 `pending_actions` 恢复 action UI，根据 `stateVersion` 恢复版本位置。
5. 发现 patch 版本缺口时，调用 `/api/player/sync` 拉授权快照，再应用仍有效的 patch。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PC-FR-1 | 未登录进入 join 时必须跳登录并保留 return path | P0 |
| PC-FR-2 | 入房时四种角色来源必须互斥，只能选一种 | P0 |
| PC-FR-3 | `player_token` 必须以服务端返回为准，前端不得自造正式会话 token | P0 |
| PC-FR-4 | 玩家 API 必须携带 `X-Room-Token`；账号级接口额外带 Authorization | P0 |
| PC-FR-5 | Lobby 必须展示房间状态、剧本标题、成员、角色名、ready 状态 | P0 |
| PC-FR-6 | ready 必须走 intent 或 Room 认可入口，失败要回滚 | P0 |
| PC-FR-7 | 房间 active 后玩家必须自动进入行动终端；非 active 打开行动页需回 Lobby | P0 |
| PC-FR-8 | 文本行动、快捷动作、技能检定、地图移动、道具主张都必须走服务端 intent | P0 |
| PC-FR-9 | 玩家端必须以 `action_id` 做幂等显示，避免弱网重复提交 | P0 |
| PC-FR-10 | 行动 UI 必须覆盖 `submitting/queued/batched/resolving/resolved/rejected/timeout` | P0 |
| PC-FR-11 | Player WS 只消费玩家授权事件，不消费 Host-only 内容 | P0 |
| PC-FR-12 | 玩家端必须实现 `stateVersion` 屏障 | P0 |
| PC-FR-13 | reconnect 返回内容必须可恢复当前 UI | P0 |
| PC-FR-14 | 角色当前 HP/SAN/MP/Luck 必须优先读 runtime state | P0 |
| PC-FR-15 | 背包、线索、日志、地图只显示服务端授权结果 | P0 |
| PC-FR-16 | 线索分享必须调用服务端 share 接口，分享后重新拉取 `/api/player/clues` | P0 |
| PC-FR-17 | 地图移动必须提交 move intent，不能直接改位置 | P0 |
| PC-FR-18 | Join/Lobby/Action/Character/Inventory/Logs/Map 主要中文文案必须可读 | P0 |
| PC-FR-19 | 401/403/404/409/429/500 必须有统一错误模型与恢复动作 | P0 |
| PC-FR-20 | VoiceInput 必须提供文本降级，不得阻断核心行动提交 | P1 |
| PC-FR-21 | 玩家端应支持移动端基础布局和键盘可访问性 | P1 |
| PC-FR-22 | 私人笔记、离线草稿、多设备同步放入长期增强 | P2 |

## 权限边界

1. 玩家不能通过请求体声明 `character_id` 作为身份，服务端必须由 `player_token` 反查。
2. 玩家不能读取、缓存、展示 `owner_token`。
3. 玩家不能调用 Host API、Admin API 或 Host WS。
4. 玩家不能看到其他玩家 `player-only` patch、private notice、action result。
5. 玩家不能看到 Host-only reveal、KP note、隐藏真相、未发现线索、内部调试事件。
6. 玩家不能在前端直接把线索、地图节点、道具标成“已发现/已公开”。
7. 前端本地过滤只提升体验，不承担最终安全责任。

## Token 与会话策略

### 开发态允许

- `IdentitySlot` 使用 `localStorage`/`sessionStorage` 支持单机多账号测试。
- 当前房间 `player_token` 允许保存在本地身份槽中。
- 但日志、控制台、错误提示、URL 可见位置不得直接暴露 token。
- `shared/api.ts` 中任何“缺 token 就本地生成正式 `player_token`”的路径都不属于可接受的开发态便利；如确有 mock 需求，也必须处于显式 dev/mock mode，且不能进入真实 join/restore 生产路径。

### 生产态目标

- 不将长期有效 `player_token` 裸存于 `localStorage`。
- WS 不长期依赖 query token。
- 目标演进到短期 WS 握手票据、HttpOnly cookie 或 session-bound token。
- 前端日志、Sentry、network error、console 输出都要脱敏。

### 本轮回执必须说明

1. 本轮是否仅完成风险标注，尚未切换生产态方案。
2. 是否已补 query token 相关日志脱敏。
3. 是否已引入短期 WS ticket；若未引入，是否把它列为明确遗留项。
4. 是否已移除 `shared/api.ts:getPlayerToken()` 在正式路径中的本地自造 token 逻辑；若未移除，是否明确限制在 dev/mock mode。
5. 若本轮仍保留 `localStorage` token，回执不得写成“token 安全已完成”，只能写成“开发态风险已标注/部分缓解”。

## WS 消费白名单

Player 端允许消费但不能“信任为安全边界”的事件：

- `s2c_room_lobby_snapshot`
- `s2c_team_message`
- `s2c_action_queued`
- `s2c_action_completed`
- `s2c_state_patch`
- `s2c_public_observation`
- `s2c_turn_resolved`
- `s2c_clue_discovered`
- `s2c_clue_shared` 的 `publicVersion`
- `s2c_map_updated`
- `s2c_player_moved`
- `s2c_map_revealed`

规则：

- 未知 `s2c_*` 默认忽略并记录 debug，不自动渲染。
- “忽略未知事件”是消费层稳定性策略，不是权限策略。
- 最终安全过滤仍由 Projection 决定。

## `stateVersion` 屏障语义

### 基本规则

1. 若 `patch.baseStateVersion == currentStateVersion`，应用 patch。
2. 若 `patch.stateVersion <= currentStateVersion`，视为旧 patch，直接丢弃。
3. 若 `patch.baseStateVersion > currentStateVersion`，说明前端缺口，先缓冲 patch，再调用 `/api/player/sync`。
4. sync snapshot 落地后，只重放“仍然满足版本条件”的 buffered patch。
5. `lastSequence` 跳号不等于安全错误；安全仍以服务端过滤为准。

### 这是 P0，不是 P1

没有这层屏障，刷新、乱序 WS、长断线后都可能把旧状态覆盖到新状态，因此它属于主链路必做项。

工程验收至少要覆盖四类最小测试：

1. 旧 patch 不应用。
2. 当前版本 patch 正常应用。
3. 未来版本 patch 进入 buffer 并触发 `/api/player/sync`。
4. sync snapshot 落地后，只应用仍然有效的 buffered patch。

## pending action 恢复规则

reconnect 返回 `pending_actions` 后：

- `queued`：显示“已排队”，禁止重复提交同一 action。
- `batched`：显示“本轮已入队，等待结算”。
- `resolving`：显示“正在结算”。
- `resolved`/`completed`：拉 action result，解除输入锁。
- `rejected`：显示失败原因，允许重新提交新 action。
- `timeout`：提示超时，允许重新提交新 action。

若本地有 `submitting` action，但 reconnect 找不到它：

1. 先请求 `GET /api/player/actions/{action_id}`。
2. 若返回 404，则提示“上一条行动未提交成功，可重新提交”。
3. 前端不得本地伪造 `queued` 或 `completed`。

## 角色页字段来源边界

| UI 字段 | 来源 |
| --- | --- |
| `currentHP/currentSAN/currentMP/currentLuck/status` | runtime |
| `maxHP/maxSAN/maxMP` | runtime 初始化后的权威值，或由服务端映射出的当前上限 |
| `skills` | `xlsx_data` 或 character profile |
| `background/bio/occupation` | `xlsx_data` 或 character profile |
| `temporaryModifiers` | runtime |
| `longTermProfile` | character profile |

## 错误模型

| 状态码 | 场景 | UI 恢复动作 |
| --- | --- | --- |
| 401 | 未登录、账号态过期 | 跳登录并保留 return path |
| 403 | `player_token` 无效、角色不属于本人 | 清当前房间会话，提示恢复角色 |
| 404 | 房间或角色不存在、action 不存在 | 返回 join 或允许重新提交 |
| 409 | duplicate action / `state_version_conflict` | duplicate 查 action status；版本冲突先 sync |
| 429 | 队内消息或动作限流 | 禁用按钮并显示倒计时/稍后重试 |
| 500 | 服务端异常 | 保留草稿，允许重试 |

## 接口方向

| 接口或事件 | 当前状态 | 用途 | 备注 |
| --- | --- | --- | --- |
| `POST /api/player/rooms/{room_id}/join-with-character` | 已有 | 加入房间并绑定角色 | 支持 preset/xlsx/builder/template |
| `GET /api/player/rooms/{room_id}/join-info` | 已有 | Lobby 加入信息与快照 | 用于大厅和角色来源补充 |
| `GET /api/player/me/characters` | 已有 | 查询本人角色 | 提供恢复入口 |
| `POST /api/player/characters/{character_id}/restore-session` | 已有 | 恢复 `player_token` | 必须校验 account ownership |
| `GET /api/player/character` | 已有 | 当前角色视图 | runtime 当前值优先 |
| `POST /api/player/intent` | 已有 | 所有玩家行动入口 | 统一进事务链路 |
| `POST /api/player/team-message` | 已有 | 队内消息 | 不进入 AI 裁决 |
| `GET /api/player/sync` | 已有 | 状态快照同步 | 为版本缺口兜底 |
| `GET /api/player/reconnect` | 已有 | 断线恢复 | recent events 必须走授权过滤 |
| `GET /api/player/actions/{action_id}` | 已有 | 查询本人 action 状态 | 不泄露他人 action |
| `GET /api/player/inventory` | 已有 | 背包 | 只返回本人视图 |
| `GET /api/player/clues` | 已有 | 线索 | 返回本人私密线索和共享安全版 |
| `POST /api/player/clues/{clue_id}/share` | 已有 | 分享线索 | 只允许线索 owner |
| `GET /api/player/archive` | 已有 | 玩家日志 | 统一复用 Projection 可见性 |
| `GET /api/map/{room_id}` | 已有 | 玩家地图视图 | 无 token 默认 401/403 |
| `POST /api/map/{room_id}/move` | 已有 | 地图移动 intent | 校验邻接、隐藏节点和可见性 |

## 验收标准

1. 玩家能完成 `登录 -> 加入房间 -> 绑定角色 -> ready -> 开局 -> 提交行动 -> 接收结果`。
2. 两名玩家同时在线时，Lobby 成员、ready、队内消息和开局跳转同步一致。
3. Player A 不能在 WS、reconnect、archive、clues、map、sync 中看到 Player B 私密内容。
4. 玩家端不能看到 Host-only reveal、KP note、未发现线索或 raw debug 内容。
5. 刷新后能恢复当前角色、`pending_actions`、`stateVersion` 和玩家资源视图。
6. 旧 `s2c_state_patch` 不会覆盖当前状态；未来 patch 会触发 sync。
7. 角色页当前 HP/SAN/MP/Luck 与 Host HUD 一致。
8. 地图移动只能经 intent 完成；非法移动会被拒绝并有明确反馈。
9. 主要中文文案无乱码。
10. 前端改动通过 `npm run build`，后端相关改动通过对应 pytest。

## 工程执行补充提醒

1. `shared/api.ts:getPlayerToken()` 的正式路径本地自造 token 属于硬 P0，不得以“先让页面能跑”为理由保留到生产路径。
2. 若本轮 token 侧只完成风险标注、日志脱敏或文档说明，不得在回执中写成“安全完成”。
3. `archive` 类型枚举必须与服务端保持一致，不得继续保留前端自造 `narrative` 偏差。
