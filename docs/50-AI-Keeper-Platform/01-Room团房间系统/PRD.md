# Room 团房间系统 PRD v1

## 目标

Room 模块提供 AI-Keeper 跑团的房间生命周期与成员协作能力，让一场团可以稳定完成：

`开房 -> 玩家入房 -> 绑定角色 -> 大厅 ready -> 房主开局 -> 进入回合链路`

Room 的产品目标不是替代 KP，也不是成为规则引擎，而是为 AI-Keeper 的核心链路提供一个清晰、可鉴权、可恢复、可追踪的房间上下文。

## 范围

包含：

- 房主或管理员创建房间。
- 房间绑定一个剧本，并允许在安全状态下切换剧本。
- 玩家通过房间码加入，并在入房时绑定角色。
- 大厅展示玩家列表、调查员摘要、ready 状态和房间状态。
- 房主从大厅开始游戏，默认要求至少一名玩家且所有玩家 ready。
- 房主可显式使用 `force_start` 作为急救能力。
- 开局后创建首回合、触发基础 checkpoint、初始化已确认地图状态并广播大厅状态。
- 进行中加入时进入房主审批流程。
- 房间公开信息脱敏，房主权限与玩家权限分离。

不包含：

- AI 裁决、规则检定、战斗结算、世界真相写入。
- 私密线索分发、反剧透上下文裁剪。
- 完整社区招募、房间评价、付费房间。
- 语音视频房间、动态光照、复杂观众系统。
- 长期备份迁移和跨实例房间导入导出。

## 角色与权限

| 角色 | 权限 | 禁止事项 |
|---|---|---|
| Host 房主 | 创建自己的房间、选择剧本、查看大厅、开始游戏、使用有限急救、进入 Host 舞台 | 不能通过 Room 直接读取完整 KP 真相，不能绕过 Engine 改世界状态 |
| Admin 管理员 | 创建或查看管理范围内房间、代建房间、辅助状态管理 | 不能把管理接口暴露为玩家入口 |
| Player 玩家 | 加入房间、绑定角色、ready、发送队内消息、提交行动 intent | 不能创建房间、开始房间、修改房间状态、读取他人私密信息 |
| Observer 旁观者 | 未来只读公共投影 | 不能提交行动、不能读取私密投影，本轮不实现 |
| Engine/State | 校验 intent、维护状态版本、写入权威状态 | AI 和前端不得绕过 Engine 写权威状态 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| ROOM-1 | 作为房主，我可以登录后选择一个剧本并创建房间。 | P0 |
| ROOM-2 | 作为房主，我可以拿到房间码和房主令牌，并进入房主大厅。 | P0 |
| ROOM-3 | 作为玩家，我可以输入房间码、昵称和角色来源加入房间。 | P0 |
| ROOM-4 | 作为玩家，我可以在大厅看到同队玩家和自己的 ready 状态。 | P0 |
| ROOM-5 | 作为房主，我可以看到所有玩家 ready 进度，并在满足条件后开局。 | P0 |
| ROOM-6 | 作为房主，我可以在特殊情况下显式强制开局，但该能力被视为急救操作。 | P0 |
| ROOM-7 | 作为迟到玩家，我在房间 active 后加入时不会直接进入场内，而是等待房主审批。 | P0 |
| ROOM-8 | 作为安全维护者，我确认公开房间信息不会泄露 owner token 或玩家 token。 | P0 |
| ROOM-9 | 作为长团用户，我希望未来按 Session 归档每场跑团记录。 | P1 |

## 状态机

### 房间状态

| 状态 | 含义 | 可进入方式 | 可离开方式 |
|---|---|---|---|
| `draft` | 草稿房间，尚未准备进入大厅 | 后续模板或草稿能力 | 选择剧本并进入 `lobby` |
| `lobby` | 大厅等待，玩家加入和 ready | 创建房间成功 | start 成功进入 `active` |
| `active` | 游戏进行中，玩家行动进入回合链路 | owner/admin 开始游戏 | pause、complete、archive |
| `paused` | 暂停或急救状态 | owner/admin 暂停 | resume 回到 active，或结束 |
| `completed` | 本房间游戏完成 | 结局或房主结束 | archive |
| `archived` | 房间归档，不再接受普通操作 | 管理或结团归档 | 只读查看 |

当前 P0 重点稳定 `lobby -> active`。`draft/paused/completed/archived` 作为接口和后台状态保留，完整产品流在后续 Journal/Timeline 批次深化。

### 玩家状态

| 状态 | 含义 | 进入方式 | 处理口径 |
|---|---|---|---|
| `joined` | 已加入大厅或正式成员 | lobby 入房成功 | 可 ready，可参与开局 |
| `pending_approval` | 进行中加入，等待房主审批 | active 入房成功 | Host approve 后变成 joined 或 active 参与 |
| `left` | 已离开或被拒绝 | reject 或离开 | 不计入大厅成员和回合参与 |

ready 独立使用 `is_ready` 字段表达，不再新增 `ready` 玩家状态作为权威来源。

## 功能需求

| 编号 | 功能 | 需求 |
|---|---|---|
| FR-ROOM-01 | 创建房间 | `host/admin` 登录后才能创建房间，必须提供存在的 `scenario_id` |
| FR-ROOM-02 | 返回创建结果 | 创建成功返回 `room_id`、`owner_token`、`status=lobby`、`scenario_id`、`scenario_title` |
| FR-ROOM-03 | 公开查询 | `GET /api/rooms/{room_id}` 可公开查询，但不得返回 `owner_token`、`owner_account_id`、玩家 token |
| FR-ROOM-04 | 剧本选项 | 房主或管理员可查询可用剧本选项 |
| FR-ROOM-05 | 切换剧本 | 仅 owner/admin 可在非 active/completed/archived 状态切换剧本 |
| FR-ROOM-06 | 玩家入房 | 玩家用房间码、昵称和唯一角色来源加入房间 |
| FR-ROOM-07 | 角色来源 | 入房角色来源只能在预设、上传 xlsx、构筑器数据、剧本模板、复制角色中选择一种 |
| FR-ROOM-08 | 入房限速 | 同 IP 默认每分钟最多 5 次入房尝试 |
| FR-ROOM-09 | 大厅快照 | 入房、ready 变化、开局后广播 `s2c_room_lobby_snapshot` |
| FR-ROOM-10 | ready | 玩家通过 `ready_toggle` intent 切换 `is_ready`，后端为权威来源 |
| FR-ROOM-11 | 默认开局校验 | 普通 start 要求有剧本、至少一名玩家、所有正式玩家 ready |
| FR-ROOM-12 | 强制开局 | `force_start: true` 只允许 owner/admin 显式使用，并视为急救能力 |
| FR-ROOM-13 | 开局副作用 | 开局后房间进入 active，创建首回合，尝试地图初始化和 checkpoint |
| FR-ROOM-14 | 进行中入房 | active 房间新加入角色状态为 `pending_approval`，不得直接进入正式玩家队列 |
| FR-ROOM-15 | 审批迟到玩家 | Host 可 approve/reject pending 角色，审批结果需要进入大厅同步 |
| FR-ROOM-16 | 断线恢复 | 已登录账号可恢复自己名下角色的 player token，游客恢复能力不作为 P0 扩展 |
| FR-ROOM-17 | 房主急救 | pause/reset/retry/skip 等急救能力必须走 owner/admin 鉴权，并留下可追踪结果 |

## 数据边界

Room 直接拥有或引用：

- `room_id`
- `scenario_id`
- `owner_token`
- `owner_account_id`
- `status`
- `spoiler_level`
- `state_version`
- `created_at`
- `started_at`
- 房间成员摘要，来源是 `characters`
- 当前回合摘要，来源是 `room_turns`

Room 不直接拥有：

- 剧本完整真相和未发现线索。
- 玩家私密投影。
- AI 推理上下文。
- 规则结算结果。
- 世界状态权威变更。
- 长期归档全文。

这些内容必须由对应模块通过 `room_id` 做归属隔离。

## 接口与事件

### REST

| 接口 | 权限 | 用途 |
|---|---|---|
| `POST /api/rooms` | host/admin | 创建房间 |
| `GET /api/rooms/mine` | host/admin | 查看自己或管理范围内房间 |
| `GET /api/rooms/{room_id}` | public DTO | 查询脱敏房间信息 |
| `GET /api/rooms/{room_id}/scenario-options` | owner/admin | 查询可选剧本 |
| `PATCH /api/rooms/{room_id}/scenario` | owner/admin | 切换房间剧本 |
| `POST /api/rooms/{room_id}/start` | owner/admin | 开始游戏或显式强制开局 |
| `GET /api/rooms/{room_id}/turns/current` | owner/admin | 查询当前回合收集状态 |
| `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character` | owner/admin | 急救跳过玩家行动 |
| `POST /api/rooms/{room_id}/turns/{turn_id}/retry` | owner/admin | 重试当前回合裁决 |
| `GET /api/player/rooms/{room_id}/join-info` | player token 可用，当前也可作为入房页信息 | 获取大厅加入信息 |
| `POST /api/player/rooms/{room_id}/join-with-character` | 可带 account token | 入房并创建角色身份 |
| `POST /api/player/intent` | player token | 提交 `ready_toggle` 或行动 intent |

### 事件

| 事件 | 受众 | 用途 |
|---|---|---|
| `s2c_room_lobby_snapshot` | party | 大厅成员、ready、房间状态同步 |
| `s2c_ready_toggled` | player/event log | ready 变化基础事件 |
| `s2c_action_queued` | player/event log | 行动进入队列 |
| `s2c_turn_resolved` | party | 回合结算完成 |
| `s2c_public_observation` | party | 公开叙事输出 |
| `s2c_host_snapshot` | host | Host 舞台状态同步 |

Room 文档只固化事件用途。投影时序和私密分发以 Projection 模块为准。

## 安全与反剧透规则

- `owner_token` 只允许创建结果和房主本地上下文使用，公开查询永不返回。
- 玩家 token 只返回给对应玩家，不进入公共大厅快照。
- Host 不是全知 KP，Room 不提供“查看完整剧本真相”的能力。
- 玩家不能通过前端本地状态使自己 ready、开局或进入 active；后端 DB 和事件才是权威。
- AI 输出不能直接开始房间或修改房间状态。
- 强制开局、retry、skip、reset 属于高风险操作，需要被视为急救能力并纳入日志或审计。
- active 中途入房必须先审批，避免新玩家直接获得场内上下文。

## 验收标准

- Host 登录后可以创建绑定剧本的房间。
- Player 可以用房间码、昵称、角色来源加入房间并获得 `player_token`。
- Host/Player 大厅都能看到玩家列表和 ready 状态。
- 玩家点击 ready 后，后端切换 `is_ready`，并通过 `s2c_room_lobby_snapshot` 同步给大厅。
- 普通开局在无玩家或有未 ready 玩家时拒绝。
- `force_start: true` 可以显式绕过默认开局检查，但只允许 owner/admin。
- 开局成功后房间状态为 `active`，返回首回合信息。
- `GET /api/rooms/{room_id}` 不包含 `owner_token`、`owner_account_id`、`player_token`。
- active 房间新玩家加入后状态为 `pending_approval`。
- Room 相关后续修改通过现有测试集验证，不把 AI/State/Projection 的内部规则写进 Room 模块。
