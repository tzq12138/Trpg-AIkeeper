# Room 团房间系统 PRD v1

## 目标

Room 模块为 AI-Keeper 提供一层稳定、可鉴权、可恢复、可追踪的房间上下文，用来承接：

`开房 -> 玩家入房 -> 绑定角色 -> Lobby ready -> Host 开局 -> 进入首回合`

Room 的产品目标不是替代 KP，不是承接规则引擎，也不是写世界真相，而是为 AI-Keeper 核心链路提供“谁在这个团里、这个团现在处于哪个阶段、谁可以触发下一步”的调度壳。

当前阶段说明：

- 本 PRD 已可进入工程执行，但当前阶段仍是“P0 主链路 + 生产风险识别版”。
- 文档里已经明确识别 `force_start`、`owner_token`、`active join`、DTO/WS 脱敏等风险点，但不代表这些风险已在代码里全部关闭。
- 本文优先锁定 Room 的边界、接口方向和验收口径，不把生产硬化写成既成事实。

## 范围

包含：

- Host 或 Admin 创建房间
- 房间绑定一个剧本，并在安全状态下切换剧本
- 玩家通过当前公开 `room_id` 入房，并在入房时绑定角色
- Lobby 展示成员、角色摘要、ready 状态和房间状态
- Host 默认按规则检查开局，必要时显式 `force_start`
- 开局后创建首回合，触发基础 checkpoint、地图初始化和大厅状态广播
- `active` 房间中途入房进入审批流程
- 账号态下恢复自己的玩家身份
- 公开房间信息、房主信息、玩家信息按 audience 分层脱敏

不包含：

- AI 裁决、规则结算、战斗执行、世界真相写入
- 私密线索发放、反剧透上下文裁剪、Projection 私密投影细节
- 完整社区招募、付费房间、房间评分
- 语音视频房间、动态光照、观众系统
- 长期跨实例迁移、平台级备份恢复

## 角色与权限

| 角色 | 权限 | 禁止事项 |
|---|---|---|
| Host 房主 | 创建自己的房间、选剧本、查看大厅、开局、有限急救、进入 Host 舞台 | 不能通过 Room 直接读取完整 KP 真相，不能绕过 Engine 写世界状态 |
| Admin 管理员 | 在管理范围内代建、查房、协助房间管理 | 不能把管理接口暴露成玩家入口 |
| Player 玩家 | 入房、绑定角色、ready、进入玩家端、提交行动 intent | 不能创建房间、开局、审批、直接改房间状态 |
| Observer 旁观者 | 未来只读公共投影 | 第一轮不实现，不得读取私密信息 |
| Engine / State | 校验 intent、维护权威状态、推进版本 | 不是房间 UI 层，不直接暴露成用户角色 |

## Room 与 Session

当前代码里，`room.status` 同时承担“房间整体生命周期”和“当前这场是否进行中”的职责，因此 `lobby/active/paused/completed/archived` 先沿用现状。

但产品上必须明确：

- `Room` 是长期团房间容器，承载成员归属、权限和公开入口
- `Session` 是 Room 下面的一场具体跑团，会有 `started_at/ended_at/summary`

本 PRD 第一轮不要求立刻新增 `sessions` 表，但要求后续所有文档和实现都不要把 Room 永久写死成“只允许一生只有一场”的结构。

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| ROOM-1 | 作为 Host，我可以登录后选择剧本并创建房间。 | P0 |
| ROOM-2 | 作为 Host，我可以拿到房间入口和房主控制凭证，并进入 Host Lobby。 | P0 |
| ROOM-3 | 作为 Player，我可以输入房间入口、昵称和角色来源加入房间。 | P0 |
| ROOM-4 | 作为 Player，我可以在 Lobby 看到公开成员和自己的 ready 状态。 | P0 |
| ROOM-5 | 作为 Host，我可以看到所有玩家的 ready 进度，并在满足条件后开局。 | P0 |
| ROOM-6 | 作为 Host，我可以在特殊情况下显式强制开局，但这属于急救能力。 | P0 |
| ROOM-7 | 作为迟到玩家，我在房间 `active` 后加入时会先等待审批，而不是直接进场。 | P0 |
| ROOM-8 | 作为系统维护者，我需要保证公开房间接口和 WS 广播都不会泄露 token 或剧透字段。 | P0 |
| ROOM-9 | 作为长期团用户，我希望未来能按 Session 归档每一场记录。 | P1 |

## 状态机

### 房间状态

| 状态 | 含义 | 进入方式 | 离开方式 |
|---|---|---|---|
| `draft` | 预留草稿态 | 未来房间模板或草稿流 | 进入 `lobby` |
| `lobby` | 开局前大厅等待态 | 创建房间成功 | `start` 成功进入 `active` |
| `active` | 游戏进行中 | 开局成功 | `pause`、`complete`、`archive` |
| `paused` | 暂停或急救态 | Host 急救操作 | `resume` 或结束 |
| `completed` | 本轮流程已结束 | 结团或结束 | `archive` |
| `archived` | 只读归档态 | 管理归档 | 只读查看 |

第一轮真正要打稳的是 `lobby -> active`。其余状态允许先保持接口或后端占位，但口径必须清楚。

### 玩家成员状态

| 状态 | 含义 | 进入方式 | 处理口径 |
|---|---|---|---|
| `joined` | 已加入大厅或已成为正式成员 | lobby 入房成功 | 可切换 ready，可参与开局 |
| `pending_approval` | 进行中加人，等待房主审批 | active 入房成功 | 批准后转正式成员，拒绝后退出 |
| `left` | 已离开或被拒绝 | reject / leave | 不计入正式成员与开局检查 |

`ready` 继续使用 `is_ready` 字段表达，不额外再发明一个成员状态枚举。

## 功能需求

| 编号 | 功能 | 需求 |
|---|---|---|
| FR-ROOM-01 | 创建房间 | `host/admin` 登录后才能创建房间，且必须提供存在的 `scenario_id` |
| FR-ROOM-02 | 创建返回值 | 创建成功返回 `room_id`、`owner_token`、`status=lobby`、`scenario_id`、`scenario_title` |
| FR-ROOM-03 | 公开查询 | `GET /api/rooms/{room_id}` 可公开查询，但不得返回 `owner_token`、`owner_account_id`、`player_token` |
| FR-ROOM-04 | 剧本选项 | owner/admin 可查询可用剧本选项 |
| FR-ROOM-05 | 切换剧本 | owner/admin 仅可在非 `active/completed/archived` 状态切换剧本 |
| FR-ROOM-06 | 玩家入房 | 玩家通过当前公开入口 `room_id`、昵称和唯一角色来源入房 |
| FR-ROOM-07 | 角色来源唯一 | 入房角色来源只能在 preset、xlsx、builder、template、copy 中选一种 |
| FR-ROOM-08 | 入房限速 | 按 IP 做基础限速，超限返回 429 |
| FR-ROOM-09 | Lobby 快照 | 入房、ready、审批、开局后都要能同步 `s2c_room_lobby_snapshot` |
| FR-ROOM-10 | ready | 玩家通过 `ready_toggle` intent 切换 `is_ready`，后端为权威来源 |
| FR-ROOM-11 | 默认开局检查 | 普通 `start` 要求有剧本、至少一名正式玩家、且正式成员全部 ready |
| FR-ROOM-12 | 强制开局 | `force_start: true` 仅 owner/admin 可显式使用，并视为急救能力；新前端和后续实现应优先补 `reason + confirm + event/audit`，兼容旧 payload 只作为过渡 |
| FR-ROOM-13 | 开局副作用 | 开局后房间转 `active`，创建首回合，尝试初始化 checkpoint 与地图 |
| FR-ROOM-14 | 进行中加入 | `active` 房间新加入者状态为 `pending_approval`，不得直接进入正式成员列表 |
| FR-ROOM-15 | 审批流程 | Host 可 approve/reject，审批结果至少要回到大厅同步；工程落地时应明确触发“玩家结果通知、Projection 重算、Journal 成员变更记录、玩家重同步”四类后续动作 |
| FR-ROOM-16 | 身份恢复 | 登录账号只能恢复自己名下角色的玩家身份 |
| FR-ROOM-17 | 急救能力 | pause/reset/retry/skip 等高危能力必须走 owner/admin 鉴权 |
| FR-ROOM-18 | 对外入口演进 | 当前对外继续使用 `room_id`；后续拆 `room_code` 与 `invite_token` 时不破坏房间主键 |
| FR-ROOM-19 | DTO 分层 | 至少要定义 `PublicRoomDTO / HostRoomDTO / PlayerRoomDTO / AdminRoomDTO` 的字段边界 |
| FR-ROOM-20 | token 硬化方向 | `owner_token` 第一轮保留兼容，但未来需要过期、撤销、哈希存储与高危操作复核；在此之前不得继续扩大其适用范围 |

## 数据边界

Room 当前直接拥有或引用：

- `room_id`
- `scenario_id`
- `owner_token`
- `owner_account_id`
- `status`
- `spoiler_level`
- `state_version`
- `created_at`
- `started_at`
- 房间成员摘要，当前来自 `characters`
- 当前回合摘要，当前来自 `room_turns`

Room 不直接拥有：

- 剧本完整真相和未发现线索
- 玩家私密投影
- AI 推理上下文
- 规则结算结果
- 世界状态权威变更
- 长期日志全文

这些内容只能通过对应模块以 `room_id` 做归属隔离，不能被 Room 文档重新吞并。

## DTO 分层方向

当前代码已经实现了“公开 DTO 不返回敏感字段”的底线，但还没有把各 audience 彻底结构化。后续应统一为：

- `PublicRoomDTO`：房间标题/剧本标题/状态/玩家数量/公开 Lobby 摘要
- `HostRoomDTO`：公开信息 + 成员 ready 摘要 + pending approvals + Host 可见入口状态
- `PlayerRoomDTO`：公开信息 + 自己的角色/ready + 可见公告/队伍摘要
- `AdminRoomDTO`：管理视角需要的归属、创建时间、风险标记、审计摘要

注意：WS payload 要和 DTO 使用同一套 audience 口径，而不是 REST 脱敏、WS 放飞。

## 数据模型演进方向

当前事实：

- `rooms` 已存在
- `characters` 当前兼任角色与成员表
- 尚无 `room_code`、`room_invites`、`sessions`、`room_members`

后续建议：

- `rooms` 增加 `room_code`、`join_policy`、`max_players`、`allow_late_join`、`allow_observer`、`requires_approval`、`current_session_id`
- 引入 `room_invites` 管理邀请链接与过期策略
- 在需要时从 `characters` 中拆出 `room_members`
- 引入 `sessions` 管理每一场开团记录

这部分是演进设计，不是当前实现状态。

## 接口与事件

### 当前 REST 方向

| 接口 | 权限 | 用途 |
|---|---|---|
| `POST /api/rooms` | host/admin | 创建房间 |
| `GET /api/rooms/mine` | host/admin | 查看自己或管理范围内房间 |
| `GET /api/rooms/{room_id}` | public DTO | 查询脱敏房间信息 |
| `GET /api/rooms/{room_id}/scenario-options` | owner/admin | 查询可选剧本 |
| `PATCH /api/rooms/{room_id}/scenario` | owner/admin | 切换房间剧本 |
| `POST /api/rooms/{room_id}/start` | owner/admin | 正常开局或显式强制开局 |
| `GET /api/rooms/{room_id}/turns/current` | owner/admin | 查询当前回合收集状态 |
| `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character` | owner/admin | 急救跳过玩家行动 |
| `POST /api/rooms/{room_id}/turns/{turn_id}/retry` | owner/admin | 重试当前回合裁决 |
| `GET /api/player/rooms/{room_id}/join-info` | player/public join page | 获取加入页公开信息 |
| `POST /api/player/rooms/{room_id}/join-with-character` | player | 入房并绑定角色 |
| `POST /api/player/intent` | player token | 提交 `ready_toggle` 或后续行动 intent |

### 当前 Host 急救接口位置

| 接口 | 权限 | 用途 |
|---|---|---|
| `POST /api/host/{room_id}/pause` | owner/admin | 暂停/恢复 Host 状态 |
| `POST /api/host/{room_id}/reset` | owner/admin | Host 急救重置 |
| `POST /api/host/{room_id}/retry-turn` | owner/admin | Host 侧重试当前回合 |
| `POST /api/host/{room_id}/approve/{character_id}` | owner/admin | 批准进行中加入 |
| `POST /api/host/{room_id}/reject/{character_id}` | owner/admin | 拒绝进行中加入 |

如果后续想把这些接口统一整理回 Room 路由，应该作为重构议题，不应在 Room 文档里误写成当前现状。

### 当前事件

| 事件 | 受众 | 用途 |
|---|---|---|
| `s2c_room_lobby_snapshot` | party / host relay | 大厅成员、ready、房间状态同步 |
| `s2c_ready_toggled` | player/event log | ready 变更基础事件 |
| `s2c_action_queued` | player/event log | 行动进入队列 |
| `s2c_turn_resolved` | party | 回合结算完成 |
| `s2c_public_observation` | party | 公开叙事输出 |
| `s2c_host_snapshot` | host | Host 舞台状态同步 |

Room 文档只固化这些事件在房间链路里的用途；投影时序和私密事件分发仍以 Projection 模块为准。

## 安全与反剧透规则

- `owner_token` 目前是兼容路径，不应被包装成长期正式的唯一房主身份模型，也不应继续扩张到更多新接口、分享链路或公开导出。
- 第一轮允许创建结果返回 `owner_token`，但公开接口和广播永远不返回它。
- 高危操作至少包括 `force_start`、`pause`、`reset`、`retry-turn`、`skip-character`、`archive`、`scenario change`。
- `force_start` 当前只支持 `force_start: true`；后续建议兼容扩展 `reason`、`confirm` 和审计记录，不把它写成已上线事实，也不把它默认为正常开局路径。
- Player 不能通过本地状态把自己直接推进到 `active`，后端 DB 与事件才是权威。
- `active` 中途入房玩家在审批前不得收到不属于自己的私密上下文；审批后至少要有玩家结果通知、Projection 重算、Journal 成员变更记录和玩家重同步的触发点。

## 验收标准

- Host 登录后可以创建绑定剧本的房间。
- Player 可以用当前公开入口 `room_id`、昵称、角色来源加入房间，并获得 `player_token`。
- Host/Player Lobby 都能看到成员列表和 ready 状态变化。
- `ready_toggle` 由后端切换 `is_ready`，并通过 `s2c_room_lobby_snapshot` 同步给大厅。
- 普通开局在空房或存在未 ready 正式成员时被拒绝。
- `force_start: true` 只能由 owner/admin 显式使用。
- 开局成功后房间变为 `active`，并返回首回合信息。
- `GET /api/rooms/{room_id}` 不包含 `owner_token`、`owner_account_id`、`player_token`。
- `active` 房间新玩家加入后状态为 `pending_approval`。
- approve/reject 至少要触发大厅成员变化同步。
- Room 相关 WS payload 与公开 REST DTO 都不泄露敏感字段。
- 后续工程修改不把 AI/State/Projection 的内部规则重新写进 Room 模块。
