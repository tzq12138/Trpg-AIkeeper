# Host Client 公共舞台端 PRD V2.1

## 当前阶段说明

- 本文档当前阶段为：`P0 主链路 + Host 公共舞台可用性、鉴权与审计风险识别版`。
- 目标是把 Host Client 定义成一个“可信的公共舞台和房主控制台”，而不是完整的平台级导演工具。
- 当前代码已经具备 `HostCreate / HostLobby / HostStage / HostMapPanel / HostLogsPanel / EncounterPanel / host/router_host.py / router_archive.py` 等真实锚点；本 PRD 必须以这些现状为基础，不回退到旧 PRD 想象状态。

## 背景

AI-Keeper 的 Host Client 不是普通后台页面，而是跑团主链路中的公共舞台端。房主在这里完成三件事：

1. 管理房间开局前协作：创建房间、选剧本、观察成员、ready 检查、显式 `force_start`；
2. 管理开局后的公共舞台：展示 HUD、接收可公开裁决结果、控制地图可见内容、处理遭遇公开节奏；
3. 管理复盘与恢复：查看 Host timeline、创建 checkpoint、恢复、导出和留审计痕迹。

当前仓库已经有一条可运行的 Host 主链路，但还存在明显产品和工程边界问题：

- Host 前端历史上出现过中文乱码和 TSX 字符串损坏风险；
- Host WS 当前主要依赖 query `ownerToken`，前后端鉴权路径没有完全收口；
- `HostStage.tsx` 同时消费标准 `s2c_*` 事件和 Host UI frame，协议边界不清；
- `retry-turn` 当前实现只重置舞台步进，不能被误写成完整回合重算；
- `owner_token` 当前会被同步到本地身份槽位，必须明确这是开发态便利，不是生产态安全闭环；
- 地图、遭遇、恢复、导出的特权操作审计仍需统一字段口径。

## 目标

1. 让 Host 可以完成 `创建房间 -> 等待室 -> 开局 -> 进入舞台 -> 查看日志/恢复` 主链路。
2. 让 Host 端只承担“演出、监管、授权操作”职责，不承担规则裁决、AI 真相生成和世界状态权威写入。
3. 让 Host REST、Host WS、checkpoint、export 都只接受 owner/admin 授权访问。
4. 让 Host 舞台只展示 `host`/`party` 可见的安全内容，不显示 `player-only` 私密 payload。
5. 让 Host 特权操作形成统一审计链，便于长团恢复和线上排障。

## 非目标

- 不在 Host 前端计算规则结果、伤害、成功等级或判定结论。
- 不在 Host 前端直接修改角色运行时数值、物品归属、线索真相或世界状态。
- 不把 Host 舞台做成完整多屏导演软件、直播系统或音视频控制台。
- 不在本轮实现多 Host 协作权限。
- 不把 `database` tab 扩展成完整资料库编辑器。
- 不允许 Host 端绕过 Projection，把未授权内容直接投给 Player。

## 用户角色

| 角色 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| Host | 创建房间、开局、看 HUD、投影公共叙事、监管地图、处理遭遇、查看日志、恢复 checkpoint | 直接改规则结果、直接写世界真相、把 Host-only 真相公开给玩家 |
| Admin | 以管理员身份进入 Host 能力做排障、恢复、审计 | 无审计地绕过权限来源 |
| Player | 间接受益于公共舞台输出 | 访问 Host REST、Host WS、全图、Host timeline |
| AI-Keeper | 产出建议、叙事、公开 reveal 候选 | 绕过 Host/Projection 直接公开隐藏真相 |
| Future Observer | 未来可能只读观看公共舞台 | 控制房间或读取 Host-only 内容 |

## 产品范围

### 本轮进入

- Host 创建房间与 `owner_token` 会话落地；
- Host Lobby：剧本选择、成员观察、ready 检查、显式 `force_start`；
- Host Stage：HUD、公共叙事投影、地图/遭遇/日志 tab；
- Host REST/WS 鉴权；
- 暂停/恢复、reset、最小 `retry-turn`；
- Host timeline、checkpoint、restore、public/full export；
- 前端中文可读性与 Host 触达页面构建恢复。

### 本轮不做

- 多 Host 协作与精细权限矩阵；
- 观众端和直播输出；
- 完整演播台（字幕、音效、镜头、灯光）；
- 真实资料库编辑器；
- 独立的 Host 插件系统。

## 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `AccountSession` | `account_token`、账号摘要 | 账号态，用于创建房间和 owner/admin 身份校验 |
| L1 `HostRoomSession` | `room_id`、`owner_token`、owner/admin 身份 | Host 房间会话，是 Host 能力入口 |
| L2 `HostLobbyView` | 房间状态、剧本、玩家列表、ready、pending approval | 开局前协作视图 |
| L3 `HostHUDView` | 玩家公开状态、队列状态、引擎状态、场景图 | Host 舞台 HUD 视图 |
| L4 `EngineEvent` | 标准 `s2c_*` 事件 | 权威可审计事件源 |
| L5 `HostFrame` | `host_state_update`、`scene_update`、`chat_message` 等 | Host UI 展示协议 |
| L6 `RevealTransactionView` | `s2c_reveal_transaction` 的舞台展示结果 | 只读投影层 |
| L7 `HostStoreStageState` | 队列、暂停态、延迟私密事件、当前遭遇建议 | 舞台态，不是世界真相源 |
| L8 `HostMapFullView` | 全图、隐藏节点、位置、探索状态 | Host-only 读模型 |
| L9 `HostOperationAudit` | 特权操作审计记录 | 必须可追踪 |
| L10 `HostTimelineView` | Host timeline、checkpoint、恢复标记 | 复盘/恢复视图 |
| L11 `ExportView` | `public/full` 导出结果 | 导出范围视图，不等于数据库原始数据 |

## DTO 契约

### 最小 DTO 集合

- `HostCreateRequestDTO`
- `HostCreateResultDTO`
- `HostRoomSessionDTO`
- `HostLobbySnapshotDTO`
- `HostHUDDTO`
- `HostEventEnvelopeDTO`
- `HostFrameDTO`
- `HostRevealTransactionDTO`
- `HostMapFullViewDTO`
- `HostMapOperationRequestDTO`
- `HostEncounterDTO`
- `HostEncounterOperationDTO`
- `HostTimelineEventDTO`
- `HostCheckpointDTO`
- `HostExportRequestDTO`
- `HostApiErrorDTO`
- `HostOperationAuditDTO`

### 关键 DTO 口径

#### `HostRoomSessionDTO`

```json
{
  "roomId": "room_xxx",
  "authMode": "owner_token|owner_account|admin",
  "ownerAccountId": "acct_xxx",
  "hasOwnerToken": true,
  "tokenRiskLevel": "dev_storage"
}
```

说明：

- `tokenRiskLevel` 用于明确当前实现风险，不得在回执里写成“已生产安全完成”。
- `owner_token` 不进入任何 public DTO、日志导出或 URL 展示。

#### `HostLobbySnapshotDTO`

```json
{
  "roomId": "room_xxx",
  "status": "draft|lobby|active|paused|completed|archived",
  "scenarioId": "scenario_xxx",
  "scenarioTitle": "示例模组",
  "players": [],
  "pendingApprovals": [],
  "canStart": false,
  "unreadyPlayerIds": []
}
```

说明：

- `players` 与 `pendingApprovals` 需要清晰区分；
- `canStart` 只是服务端规则的 UI 显示摘要，不是前端本地决定开局权限。

#### `HostHUDDTO`

```json
{
  "roomId": "room_xxx",
  "players": [],
  "sceneImageUrl": null,
  "engineState": "idle|thinking|busy",
  "queueStatus": {
    "normal": 0,
    "urgent": 0
  }
}
```

说明：

- HUD 优先来自服务端 `build_hud`；
- HostStore 只能补充舞台态，如队列数量、暂停态、当前场景图。

#### `HostEventEnvelopeDTO`

```json
{
  "roomId": "room_xxx",
  "type": "s2c_reveal_transaction",
  "audience": "host|party",
  "roomSequence": 123,
  "payload": {},
  "issuedAt": "2026-07-07T12:00:00Z"
}
```

说明：

- 这是标准事件协议；
- 只有它和 HUD API 才能作为 Host UI 的真实来源。

#### `HostFrameDTO`

```json
{
  "frameType": "host_state_update|scene_update|chat_message|map_updated|encounter_started",
  "sourceEventType": "s2c_reveal_transaction",
  "sourceSequence": 123,
  "hud": {},
  "payload": {}
}
```

说明：

- `HostFrameDTO` 是 UI 展示协议，不回写 `events`；
- `HostFrameDTO` 不得额外承载规则结果、状态写入、玩家私密 payload；
- Host Stage 渲染的每一帧都应能追到 `sourceEventType/sourceSequence` 或 HUD API 来源。

#### `HostRevealTransactionDTO`

```json
{
  "transactionId": "tx_xxx",
  "priority": "normal|urgent",
  "steps": [],
  "summaryText": "公开摘要",
  "sourceSequence": 123
}
```

说明：

- Host 只读取并展示 reveal；
- Host 不得修改步骤内容后再写回事件表。

#### `HostOperationAuditDTO`

```json
{
  "operation": "force_start|restore|force_move|retry_turn|map_reveal|encounter_resolve",
  "roomId": "room_xxx",
  "actorAccountId": "acct_xxx",
  "actorRole": "owner|admin",
  "targetType": "room|checkpoint|map_node|character|encounter|transaction",
  "targetId": "target_xxx",
  "targetCharacterId": "char_xxx",
  "fromState": "lobby",
  "toState": "active",
  "reason": "人工恢复",
  "confirm": true,
  "transactionId": "tx_xxx",
  "stateVersion": 12,
  "eventSequence": 345,
  "createdAt": "2026-07-07T12:00:00Z"
}
```

说明：

- `force_start / restore / retry-turn / force_move` 至少要对齐这组字段；
- 当前已有 `host_force_move` 审计可作为起点，但字段还不完整。

## Token 与会话策略

### 当前实现口径

- `HostCreate.tsx` 在创建房间成功后会把 `owner_token` 写入当前身份槽位；
- `shared/identity.ts` 会把 `owner_token` 同步到 slot 和 legacy `localStorage`；
- `HostLobby.tsx` 与 `HostStage.tsx` 当前主要通过 `ownerToken` query 连接 Host WS；
- `router_host.py` 已支持 `X-Owner-Token`、owner account、admin account 作为 Host REST 和 Host WS 入口。

### 文档边界

- 开发态可以保留 identity slot/localStorage 方案，支持单机多身份测试；
- `owner_token` 不得出现在日志、导出、URL 明文展示、公共 DTO、错误文案和截图样例中；
- 生产目标是不再长期依赖 `localStorage` 中的长效 `owner_token` 和 WS query token；
- 如本轮未引入短期 WS ticket，回执必须明确写为“开发态风险已标注，未完成生产态收口”。

## 权限边界

1. 只有房主账号、管理员账号、房间 `owner_token` 可以访问 Host REST/WS。
2. 普通 `player_token` 不能访问 Host REST、Host WS、全图接口、Host timeline。
3. 跨房间 `owner_token` 必须拒绝。
4. 无 token、错 token、账号不匹配都必须失败，不允许前端静默降级成“匿名可看 Host”。
5. Host 可见“比玩家更多”的主持视角，但不等于可把 Host-only 真相投给玩家。
6. 最终可见性安全边界必须由 Projection/Archive 后端决定，而不是靠 Host 前端不渲染。

## HostEventAdapter 契约

当前代码已经存在两层协议：

- 标准事件层：`s2c_reveal_transaction`、`s2c_public_observation`、`s2c_map_revealed`、`s2c_encounter_started` 等；
- Host UI frame 层：`host_state_update`、`scene_update`、`chat_message`、`map_updated`、`encounter_started` 等。

本 PRD 要求明确：

1. 标准 `EngineEvent` 是审计、补发、重连和时间线追踪的权威来源；
2. `HostFrameDTO` 只是 Host UI 的展示协议；
3. `HostFrameDTO` 不写回 `events`，也不替代标准事件；
4. Host Stage 不得直接把 `s2c_state_patch`、`s2c_private_notice`、`s2c_action_completed` 的玩家私密 payload 显示到舞台；
5. HostStage 渲染时，如遇未知 `s2c_*`，默认不自动公开，先按未识别事件处理。

## Host ACK 与延迟私密释放契约

当前后端已有 `host_step_complete` 和 HostStore `delayed_events` 机制。本 PRD 固化以下边界：

1. Host ACK 只表示“舞台某一步已演出完成”；
2. Host ACK 必须绑定 `transactionId`、`stepId`/`stepIndex`、`actorAccountId`；
3. Host ACK 不承载规则结果、骰子结果或状态变更；
4. 玩家私密结果是否释放，由 14-Transaction 的 `ReleaseGate` 决定；
5. Host Client 不能自己决定“现在把某个私密 patch 放给玩家”。

## `retry-turn` 语义

### 当前实现

当前 `router_host.py` 的 `retry-turn` 只在 `store.active_transaction` 存在时把 `current_step_index` 重置为 `0`。它是舞台步进重试，不是完整事务重算，更不是世界状态回滚。

### 产品目标

后续可演进为三种模式，但本轮文档只定义语义，不得伪称已全部实现：

- `replay_only`：只重放已存在 reveal；
- `recompute_unresolved`：只重算未完成事务；
- `restore_from_checkpoint`：从 checkpoint 恢复出新的历史分支。

默认不允许“对已结算回合自动重算”。

## 核心流程

### 1. 创建房间

1. Host 打开 `/host/create`；
2. 未登录则跳转登录；
3. host/admin 账号选择剧本；
4. 调用 `POST /api/rooms`；
5. 后端创建房间并返回 `owner_token`；
6. 前端把 `owner_token` 写入当前身份槽位并进入 Lobby。

### 2. Lobby 与开局

1. HostLobby 获取房间摘要；
2. 通过 snapshot 观察玩家、ready、pending approval；
3. 开局前可切换剧本；
4. 普通 start 必须满足最小 ready 条件；
5. `force_start` 必须显式触发，并带 `reason + confirm`；
6. start 成功后房间进入 `active`，首回合、初始 checkpoint、地图初始化由后端执行。

### 3. Stage 舞台

1. 先通过 `/api/host/{room_id}/hud` 拿初始 HUD；
2. 再通过 Host WS 接收增量更新；
3. `s2c_reveal_transaction` 进入叙事投影；
4. `s2c_public_observation`、`s2c_team_message` 进入公共舞台消息流；
5. 地图和遭遇事件只触发对应面板更新；
6. Host 舞台暂停只暂停舞台态，不修改规则裁决真相。

### 4. 地图与遭遇

1. Host 全图读取只对 owner/admin 可见；
2. reveal/hide、force move 必须经后端校验 room 归属；
3. confirm/reject/next-round/resolve/NPC 必须经后端校验 encounter 归属；
4. 特权操作应带 reason、actor、target 和 stateVersion/eventSequence 等审计信息。

### 5. 日志、恢复与导出

1. Host timeline 只对 owner/admin 开放；
2. restore 必须 `confirm=true + reason`，并写 `s2c_checkpoint_restored`；
3. Player 不能看到 restore 原始审计 payload；
4. public export 必须复用 Projection 的 public view；
5. full export 也不是数据库原样导出，仍然禁止 token、secret、raw AI prompt/response。

## 接口方向

| 接口或事件 | 当前现状 | 作用 | 权限口径 |
| --- | --- | --- | --- |
| `POST /api/rooms` | 已有 | 创建房间 | host/admin 账号 |
| `GET /api/rooms/{room_id}` | 已有 | Host Lobby 房间摘要 | 不返回 `owner_token` |
| `GET /api/rooms/{room_id}/scenario-options` | 已有 | 开局前选剧本 | owner/admin |
| `PATCH /api/rooms/{room_id}/scenario` | 已有 | 开局前切剧本 | owner/admin |
| `POST /api/rooms/{room_id}/start` | 已有 | start / force_start | owner/admin；force 需 `reason + confirm` |
| `GET /api/host/{room_id}/hud` | 已有 | 初始 HUD | owner/admin |
| `POST /api/host/{room_id}/pause` | 已有 | 暂停/恢复舞台 | owner/admin |
| `POST /api/host/{room_id}/reset` | 已有 | 重置 HostStore | owner/admin |
| `POST /api/host/{room_id}/retry-turn` | 已有 | 舞台最小重试 | owner/admin |
| `GET /api/host/{room_id}/map/full` | 已有 | Host 全图 | owner/admin |
| `POST /api/host/{room_id}/map/reveal` | 已有 | reveal/hide 节点 | owner/admin |
| `POST /api/host/{room_id}/map/move-character` | 已有 | force move 角色 | owner/admin，必须 `reason` |
| `GET /api/host/{room_id}/encounter` | 已有 | 当前遭遇 | owner/admin |
| `POST /api/host/{room_id}/encounter/confirm` | 已有 | 确认遭遇 | owner/admin |
| `POST /api/host/{room_id}/encounter/reject` | 已有 | 拒绝遭遇建议 | owner/admin |
| `POST /api/host/{room_id}/encounter/next-round` | 已有 | 推进下一轮 | owner/admin |
| `POST /api/host/{room_id}/encounter/resolve` | 已有 | 结束遭遇 | owner/admin |
| `POST /api/host/{room_id}/encounter/npc` | 已有 | 创建临时 NPC | owner/admin |
| `GET /api/rooms/{room_id}/timeline` | 已有 | Host timeline | owner/admin |
| `POST /api/rooms/{room_id}/checkpoint` | 已有 | 创建 checkpoint | owner/admin |
| `POST /api/rooms/{room_id}/restore/{checkpoint_id}` | 已有 | 恢复 checkpoint | owner/admin；必须 `confirm + reason` |
| `GET /api/rooms/{room_id}/export` | 已有 | `public/full` 导出 | `full` 仅 owner/admin；`public` 走 player auth |
| `Host WS /ws?role=host` | 已有 | Host 实时舞台 | 当前主要靠 query `ownerToken`；后端支持 owner/admin |

## Export 边界

### `public export` 禁止包含

- `owner_token`
- `player_token`
- `account_id`、`email`
- Host-only reveal payload
- 全图节点和隐藏地图信息
- 未公开真相、隐藏 NPC、隐藏 clue、世界真相字段
- 玩家私密 patch、private notice、action completed 私密结果
- `raw AI prompt`、`raw AI response`
- debug/admin payload

### `full export` 仍禁止包含

- 原始 token
- API key
- 明文 secret
- `raw AI prompt` / `raw AI response`
- 账号敏感字段
- 运维原始内部日志

如未来需要导出 AI/Ops 原始审计，必须另设 `admin_audit export scope`，不能复用 `full export`。

## Database Tab 占位边界

当前 `navigation.ts` 中 `database` 仍是可见 tab，但本轮没有真实资料库功能。产品要求：

1. 如果本轮不接真实数据，必须标记“开发中/占位”，或直接隐藏；
2. 不允许展示看似真实的假知识条目，让主持人误以为已接入 WorldBook；
3. 真正的资料检索能力应归属于后续 WorldBook/Asset/RAG 方案。

## 验收标准

1. host/admin 可创建房间，player 创建房间返回 403。
2. Host Lobby 能看到成员、ready、pending approval 和剧本状态。
3. 普通 start 受 ready 条件限制；`force_start` 必须显式并带 `reason + confirm`。
4. Host WS 无 token、错 token、跨房间 token 均失败；owner/admin 成功。
5. Host Stage 先能用 HUD API 初始化，再接收 WS 增量。
6. Host 只展示 reveal/public 内容，不展示 `player-only` 私密 payload。
7. 全图接口只对 owner/admin 开放。
8. `force_move`、restore、force_start 等特权操作可追踪。
9. restore 必须写 `s2c_checkpoint_restored`，且 Player 看不到原始审计 payload。
10. `public export` 与 `full export` 都符合脱敏边界。
11. `database` tab 不误导用户为真实资料库。
12. Host 触达页面通过 `npm run build`，主要中文文案可读。
