# Channel 聊天与信息流系统 PRD

## 目标

建立一个以事件流为底座、以频道体验为上层表现的信息系统，让玩家、Host、AI-Keeper 和日志归档都围绕同一批可追溯事件工作。Channel v1 的重点是保证队伍消息、公共叙事、系统事件和归档查询可用，并先修正受众过滤风险。

当前阶段说明：

- 本 PRD 已可进入工程执行，但当前阶段仍是“P0 主链路 + 受众过滤风险识别版”。
- 文档已经识别玩家 WS 补发、`/api/player/reconnect`、`/events/public`、team-message、OOC/IC 分层和 Host timeline 边界等问题，但不代表这些风险已在代码里全部关闭。
- 本文优先锁定 Channel 的边界、接口方向和验收口径，不把生产硬化写成既成事实。

## 产品定位

Channel 不是规则引擎，也不是世界状态存储。它负责“谁能看到什么信息、如何实时送达、如何回查、如何被 AI 安全消费”。状态真相由 State/Transaction 写入，Channel 只展示和记录投影后的信息。

补充边界：

- Channel 不写 State，不做 Rule 结算，不做 AI 裁决。
- Channel 不把聊天自动升级为世界事实。
- Channel 只能消费投影后的事件，不能成为绕过 Projection/Engine 的第二套事实入口。

## 角色与权限

| 角色 | 可做 | 不可做 |
|---|---|---|
| Player | 发送队伍消息，查看自己可见的公共叙事、战术提示、系统提示和归档 | 直接写世界状态，读取其他玩家私密事件，读取 Host-only 事件 |
| Host | 查看公共信息流、队伍消息、Host 时间线，做运行审计 | 通过聊天绕过 Engine 改状态，获取未授权剧透内容 |
| AI-Keeper | 输出公开叙事、战术提示、私密反馈建议 | 直接落库写状态，把 OOC 或玩家猜测当成事实 |
| Engine | 写行动生命周期、系统事件、状态投影事件 | 接收任意聊天作为权威事实 |
| Admin | 排查事故和安全问题 | 在普通房间视角中暴露后台数据给玩家 |

## v1 范围

| 范围 | 说明 |
|---|---|
| 队伍频道 | 基于 `POST /api/player/team-message` 和 `s2c_team_message`，支持大厅和游戏内全队消息。 |
| 公共叙事流 | 基于 `s2c_public_observation`、`s2c_chat_stream`、`s2c_reveal_transaction` 展示 KP/AI 输出。 |
| 系统事件流 | 基于 `s2c_action_*`、`s2c_state_patch`、`s2c_private_notice` 等事件展示状态与回执。 |
| WS 实时送达 | Host 和 Player 都通过 `/ws` 接收事件。 |
| 事件归档 | Host 通过 timeline 查全量运行事件；Player 通过 archive 查授权内容。 |
| 服务端受众过滤 | 修正玩家重连补发、查询、归档中的越权风险。 |

## v1 不做

- 不做跨房间私信、社区聊天、好友系统。
- 不做复杂 Thread、Reaction、表情经济。
- 不做完整富媒体频道，语音先作为 `source=voice` 的文本消息进入。
- 不做把聊天直接喂给 AI 当世界事实的自动机制。
- 不新建大型社交平台能力，先稳住房间内主链路。

## 关键概念

| 概念 | 定义 |
|---|---|
| Event | 服务端权威事件，写入 `events` 表，有 `sequence` 和 `audience`。 |
| Channel Message | 面向用户阅读的消息，可由事件派生，也可后续独立建模。 |
| Audience | `host/player/party/system`，决定服务端投递和查询范围。 |
| Visibility | 信息语义层级，当前字段存在但使用较弱，后续应明确 public/private/ooc/system/dice。 |
| Source Event | 消息关联的原始事件 sequence 或 actionId，用于追溯。 |
| Viewer Filter | 统一决定“这个 viewer 是否能看到这个 event”的服务端过滤层。 |

## 公共接口方向

### 发送队伍消息

`POST /api/player/team-message`

请求头：

```http
X-Room-Token: <player_token>
Content-Type: application/json
```

请求体：

```json
{
  "text": "我去看左侧的门。",
  "source": "text"
}
```

当前代码事实：

- 服务端会自行生成 `messageId`、`createdAt`、`characterId`、`playerName`、`investigatorName`。
- 当前 player 接口白名单允许 `text/voice/system_import`，但长期口径应把 `system_import` 收回到服务端或 admin/import 工具，不继续暴露给普通玩家入口。

响应：

```json
{
  "status": "sent",
  "messageId": "<uuid>"
}
```

服务端生成 `s2c_team_message`：

```json
{
  "messageId": "<uuid>",
  "characterId": "<character_id>",
  "playerName": "Alice",
  "investigatorName": "调查员名",
  "text": "我去看左侧的门。",
  "source": "text",
  "createdAt": "2026-07-04T00:00:00+00:00"
}
```

### 实时事件

`GET /ws?room=<room_id>&role=player&token=<player_token>&lastSequence=<n>`

`GET /ws?room=<room_id>&role=host&ownerToken=<owner_token>&lastSequence=<n>`

WS 帧统一为 `EngineEvent`：

```json
{
  "eventId": "<uuid>",
  "roomId": "<room_id>",
  "type": "s2c_team_message",
  "roomSequence": 42,
  "audience": "party",
  "visibility": "public",
  "issuedAt": "2026-07-04T00:00:00+00:00",
  "payload": {}
}
```

### 查询与归档

| 接口 | 调用方 | 说明 |
|---|---|---|
| `GET /api/rooms/{room_id}/events` | Owner/Admin | 查询房间事件。 |
| `GET /api/rooms/{room_id}/events/public` | Player | 当前代码存在，且要求 `X-Room-Token`；但命名容易误解为匿名公开接口，实现上也必须收紧到“只返回玩家可见事件”，不能把 `host` audience 当成 public。 |
| `GET /api/rooms/{room_id}/timeline` | Owner/Admin | Host 时间线，支持类型和关键词过滤。 |
| `GET /api/player/archive` | Player | 查询授权归档，当前已覆盖线索、行动、检定、状态变更和 `messages`。 |

## 主要流程

1. 玩家在大厅或游戏内输入队伍消息。
2. 前端携带 `X-Room-Token` 调用 `POST /api/player/team-message`。
3. 后端校验 token，绑定发送者角色，生成服务端 `messageId` 和 `createdAt`。
4. `ProjectionDispatcher.emit` 写入 `events`，产生递增 `roomSequence`。
5. WS 将 `s2c_team_message` 投递给 Host 与 Player。
6. 大厅 UI 做乐观发送与回声去重，游戏内终端追加本地消息。
7. Host timeline 可以按 sequence 回看；Player archive 当前已支持 `messages`，但大厅刷新后的历史恢复和统一过滤口径仍需继续补齐。

## 数据边界

- v1 不引入 `messages` 表，先以 `events` 表作为权威日志。
- `payload.text` 是用户表达，不是世界状态。
- `s2c_public_observation` 是公开叙事，属于可展示事实，但仍应由 AI/Engine 流程产生。
- `s2c_private_notice`、`s2c_tactical_prompt`、`s2c_action_completed` 等 player audience 事件必须绑定角色范围。
- 队伍消息可以被日志记录，但不自动进入 AI 事实层；需要 AI 消费时必须标注 `source=player_chat`。

## 统一可见性过滤

Channel 不应让每个入口自己判断“这条事件给不给这个人看”。后续应统一为一套服务端可复用 helper，例如：

- `can_view_event(viewer, event)`
- `build_event_view_for_viewer(viewer, event)`

至少统一覆盖：

- WS catch-up
- `/api/player/reconnect`
- `/api/rooms/{room_id}/events/public`
- `/api/player/archive`
- replay / 导出 / 搜索

统一过滤时至少要检查：

- `viewer.role`
- `viewer.room_id`
- `viewer.character_id`
- `event.audience`
- `event.visibility`
- `payload.characterId / payload.character_id`

当前代码里，WS catch-up 已有第一层 `get_events_for_player`，但 `reconnect`、archive、`events/public` 仍未统一收敛到同一口径。

## 事件分类与 AI 事实层

| 分类 | 典型事件/字段 | 是否默认进入 AI 事实层 | 说明 |
|---|---|---|---|
| 玩家聊天 | `s2c_team_message` | 否 | 默认只是玩家表达，应标记为 `player_chat`。 |
| OOC | `mode=ooc` | 否 | 不得自动升级为角色事实。 |
| 公开叙事 | `s2c_public_observation` | 是 | 属于已投影给全体玩家的公开事实。 |
| 事务演出 | `s2c_reveal_transaction` | 有条件 | 应按 step/semanticType 解读，不直接把整段原样吞进事实层。 |
| 私密通知 | `s2c_private_notice` | 否 | 只对目标角色可见。 |
| 状态补丁 | `s2c_state_patch` | 是 | 代表权威状态事实。 |
| 骰子/规则结果 | `s2c_action_completed` 等 | 是 | 只能由 Rule/Engine 产生。 |
| 系统提示 | `system` audience 或系统类事件 | 视类型而定 | 不能默认全部当世界事实。 |

## 权限边界

- 玩家发送消息时，发送者只能由 `player_token` 解析，不能信任前端传入的角色名或角色 ID。
- 玩家查询历史时，只能得到 `party/system` 公开内容，以及 payload 中属于自己的 `player` 内容。
- 玩家 WS 重连补发必须使用与查询一致的服务端过滤。
- Host timeline 只能通过房主 token、房主账号或 Admin 账号访问。
- Host timeline 可查看房间运行事件和审计信息，但不得借 Channel 获取 `scenario_truth`、未发现线索、其他玩家未投影私密内容。
- 前端隐藏不是安全边界，所有隐私过滤都必须在服务端完成。

## 验收标准

| 场景 | 验收 |
|---|---|
| 队伍消息 | 玩家发送一条消息，Host、大厅玩家、游戏内玩家收到同一条 `s2c_team_message`，且无重复。 |
| 发送者绑定 | 前端不能伪造其他 `characterId/playerName`。 |
| 重连补发 | 玩家断线后按 `lastSequence` 补发，只收到公开和自己可见的事件。 |
| reconnect 快照 | 玩家通过 `/api/player/reconnect` 恢复时，不会拿到其他玩家私密事件或 Host-only 事件。 |
| 公共事件查询 | `GET /api/rooms/{room_id}/events/public` 不会向玩家返回 `host` audience 事件。 |
| 私密隔离 | 玩家 A 的 `s2c_private_notice` 不会出现在玩家 B 的 WS、archive、public events。 |
| Host 时间线 | 房主能按关键词查到队伍消息和公开叙事，普通玩家不能访问 Host timeline。 |
| AI 安全 | OOC/队伍聊天不会未经标注进入 AI 事实上下文。 |

## 当前风险

| 风险 | 影响 | 优先级 |
|---|---|---:|
| `/api/player/reconnect` 的 snapshot 路径当前直接回传房间 `all_events` | 可能把其他玩家私密事件或 Host-only 事件带给玩家 | P0 |
| `GET /api/rooms/{room_id}/events/public` 当前按 `audience != 'player'` 取数 | 若不收紧会把 `host` audience 事件误当 public 发给玩家 | P0 |
| `POST /api/player/team-message` 当前 player 白名单仍包含 `system_import` | 玩家可伪装成系统导入语义，污染展示与审计口径 | P0 |
| 队伍消息没有自动历史恢复 | 刷新大厅后聊天断层，长团复盘缺失 | P1 |
| WS catch-up、reconnect、archive、public events 各自写过滤 | 可见性逻辑分叉，后续一定会有入口漏掉 | P1 |
| `characterId/character_id` 键名并存 | 过滤 helper 和测试容易只覆盖一半 payload 形态 | P1 |
| `events` 直接写入和 `ProjectionDispatcher.emit` 并存 | sequence、WS 推送、审计口径容易分叉 | P1 |
| `s2c_team_message` 测试覆盖不足 | 事件注册和类型漂移不容易被发现 | P1 |
| OOC/IC 未分层 | AI 消费上下文时可能混淆玩家闲聊和事实 | P1 |

