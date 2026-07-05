# Schedule 日程与招募系统 PRD V2.0

## 背景

AI-Keeper 的核心链路需要一个稳定的会前调度层：房主能开团、玩家能加入、大家能 ready、房主能开局，进行中临时补人时不破坏桌面秩序。当前代码已经在 Room 和 Player Join 中实现了这条基础链路，但没有独立的招募帖、报名、排期、候补和提醒系统。

Schedule v1 的产品方向是先把“房间周边的组队和排期边界”定义清楚，再等 Room、User、Safety、Community 和 Ops 稳定后扩展为平台级招募系统。第一阶段不做公开招募广场，不做社区匹配，不做外部通知服务。

## 目标

1. 固化当前会前调度主链路：房间码加入、角色绑定、ready、大厅同步、开局检查。
2. 补齐进行中加入审批的前端可用性，让 `pending_approval` 不是只有后端测试存在。
3. 明确未来招募申请与当前角色入房的区别，避免玩家未获批准就拿到完整运行态权限。
4. 明确日程投票与 ready 的区别，避免把现实时间协调写进游戏状态。
5. 定义招募公开信息的反剧透边界。
6. 给 DeepSeek 后续实现留出清晰的表、接口、测试和禁止事项。

## 非目标

- 不在本轮实现公开招募广场。
- 不实现玩家信誉、匹配推荐、活动运营。
- 不实现邮件、短信、移动推送等外部通知。
- 不让 Schedule 参与 AI 裁决、规则结算或世界状态写入。
- 不让招募页暴露剧本 raw_text、隐藏真相、结局、隐藏线索、隐藏 NPC。
- 不把 `characters.is_ready` 当作日程投票。
- 不把 `characters.status = pending_approval` 当作完整报名系统。

## 用户角色

| 角色 | 诉求 | 权限边界 |
| --- | --- | --- |
| Host | 开房、邀请玩家、查看 ready、审批进行中加入、未来发布招募和排期 | 只能管理自己房间或自己招募帖，不能看玩家账号隐私 |
| Player | 通过房间码入桌、绑定角色、ready、未来报名和提交可用时间 | 只能管理自己的报名、角色和可用时间 |
| Admin | 查看违规招募、处理平台治理问题 | 可下架公开招募，但 public 页面仍必须脱敏 |
| Future Observer | 未来旁观公开活动或招募 | 不进入 v1；不能进入玩家或 Host 权限 |
| DeepSeek 执行者 | 后续按批次补代码 | 必须先读当前 Room/User/Safety 代码和测试，不抢核心链路 |

## 范围

### v1 进入

- 保持现有房间码加入和 `join-info` 可用。
- 保持玩家登录后 `join-with-character`、账号角色恢复和 ready 可用。
- 保持 Host 普通 start 的 ready 检查和 `force_start` 显式绕过。
- 保持 active 房间加入写入 `pending_approval`。
- 补齐 Host 前端对 `pending_approval` 的展示、批准和拒绝。
- 建立招募公开字段和反剧透字段白名单。
- 写清未来 `RecruitPost`、`Application`、`SchedulePoll` 的数据归属。

### v1 不进入

- 公开招募列表、搜索、筛选和推荐。
- 完整报名表、候补、房间容量、邀请码、白名单。
- 日历视图、循环排期、自动提醒。
- 出勤信誉、玩家评分、社区治理工作流。
- 外部日历、Webhook、邮件、短信、移动推送。

## 当前主链路

```mermaid
flowchart LR
  H["Host 创建房间"] --> J["玩家输入房间码"]
  J --> I["读取 join-info"]
  I --> C["选择或创建角色"]
  C --> L["进入 Player Lobby"]
  L --> R["ready toggle"]
  R --> S["Host start"]
  S --> A["Room active"]
  A --> P["进行中新玩家加入"]
  P --> Q["pending_approval"]
  Q --> D["Host approve 或 reject"]
```

当前主链路中，Schedule 只负责会前和入桌协调。开局后的行动、AI、事务、状态、投影和日志仍由对应核心模块负责。

## 数据模型方向

### 当前已存在

| 表或字段 | 用途 | Schedule 解读 |
| --- | --- | --- |
| `rooms.room_id` | 房间码和房间主键 | 当前私域加入入口 |
| `rooms.scenario_id` | 绑定剧本 | 招募页只能展示公开标题和公开摘要 |
| `rooms.owner_token` | 房主管理凭证 | 不出现在任何公开 Schedule DTO |
| `rooms.owner_account_id` | 房主账号 | 用于房主找回房间和管理权限 |
| `rooms.status` | `draft/lobby/active/paused/completed/archived` | 决定 join mode |
| `rooms.created_at` | 创建时间 | 可作为招募和后台排序基础 |
| `rooms.started_at` | 开始时间 | 不是计划开团时间，只是实际开局时间 |
| `characters.status` | `joined/pending_approval/left` 等 | 当前入房和进行中审批状态 |
| `characters.is_ready` | 玩家 ready | 只表示当前可开局，不表示未来可用时间 |
| `characters.account_id` | 角色归属账号 | 用于恢复 session 和防止冒领 |

### 未来新增

| 表 | 主要字段方向 | 说明 |
| --- | --- | --- |
| `recruit_posts` | `post_id`、`room_id`、`host_account_id`、`scenario_id`、`visibility`、`title`、`public_pitch`、`ruleset`、`max_players`、`status`、`created_at`、`closed_at` | 招募帖只引用公开信息，不复制剧本真相 |
| `recruit_applications` | `application_id`、`post_id`、`account_id`、`display_name`、`message`、`character_source_hint`、`status`、`created_at`、`reviewed_at` | 报名申请独立于角色运行态，批准后才入房 |
| `room_invites` | `invite_id`、`room_id`、`code_hash`、`expires_at`、`max_uses`、`used_count`、`created_by` | 私域邀请和可撤销链接 |
| `room_waitlist` | `waitlist_id`、`room_id`、`account_id`、`source_application_id`、`status`、`rank` | 候补不进入大厅 ready |
| `schedule_polls` | `poll_id`、`room_id`、`created_by`、`timezone`、`status`、`created_at` | 日程投票容器 |
| `availability_votes` | `vote_id`、`poll_id`、`account_id`、`slot_start`、`slot_end`、`availability`、`note` | 玩家现实时间可用性 |
| `session_slots` | `session_id`、`room_id`、`planned_start`、`planned_end`、`timezone`、`status` | 一次跑团的计划时间 |
| `attendance_records` | `record_id`、`session_id`、`account_id`、`status`、`reason_scope` | 出勤、请假、迟到、缺席记录 |
| `reminder_jobs` | `job_id`、`session_id`、`channel`、`scheduled_at`、`status` | 依赖 Ops 的后台任务 |

## 权限边界

| 行为 | Host | Player | Admin | 未登录 |
| --- | --- | --- | --- | --- |
| 查看公开 `join-info` | 可 | 可 | 可 | 可 |
| 通过房间码加入 lobby | 可作为玩家加入 | 可 | 可 | 需先登录才能绑定角色 |
| ready toggle | 不适用或仅玩家角色 | 仅自己的角色 | 不建议代操作 | 不可 |
| 普通 start | owner/admin | 不可 | 可 | 不可 |
| `force_start` | owner/admin 显式操作 | 不可 | 可 | 不可 |
| approve/reject pending | owner/admin | 不可 | 可 | 不可 |
| 发布招募帖 | 自己房间 | 不可 | 可代管或下架 | 不可 |
| 提交报名 | 可报名他人房间但不能自动入房 | 可 | 可 | 需登录 |
| 修改可用时间 | 自己的记录 | 自己的记录 | 可审计 | 不可 |
| 下架公开招募 | 自己帖子 | 不可 | 可 | 不可 |

## 公开信息白名单

招募、加入页、公开房间信息只能展示以下内容：

- 房间码或招募帖短链接。
- 房间状态：lobby、active、closed 等脱敏状态。
- 剧本公开标题和公开简介。
- 规则系统、推荐人数、预计时长、语言、时区。
- Host 显示名和非敏感公开说明。
- 内容警示标签，但不展示隐藏真相。
- 已加入人数和容量，不展示 player token、owner token。
- 玩家公开昵称和 ready 状态，必要时允许 Host 设置隐藏名单。

禁止展示：

- `owner_token`、`player_token`、账号 token。
- `scenarios.raw_text`、truth、ending、隐藏线索、隐藏 NPC、隐藏素材。
- 玩家私密备注、申请私信、Safety 会前边界反馈。
- 本地文件路径、后台日志、AI prompt、AI call details。

## 接口方向

### 当前已存在

| 接口 | 用途 | Schedule 口径 |
| --- | --- | --- |
| `POST /api/rooms` | Host 创建房间 | 会前调度入口 |
| `GET /api/rooms/mine` | Host/Admin 找回自己的房间 | 后续招募帖可引用 |
| `GET /api/rooms/{room_id}` | 公开房间 DTO | 必须保持脱敏 |
| `POST /api/rooms/{room_id}/start` | 开局或 `force_start` | Schedule 到 Room active 的边界 |
| `GET /api/player/rooms/{room_id}/join-info` | 玩家加入前信息 | 公开字段安全关键接口 |
| `POST /api/player/rooms/{room_id}/join-with-character` | 玩家绑定角色入房 | 当前直接入房流程 |
| `POST /api/player/intent` with `ready_toggle` | 切换准备状态 | 当前 ready 状态来源 |
| `POST /api/host/{room_id}/approve/{character_id}` | 批准进行中加入 | 后端已有，前端需补 |
| `POST /api/host/{room_id}/reject/{character_id}` | 拒绝进行中加入 | 后端已有，前端需补 |

### 未来接口

| 接口 | 用途 | 约束 |
| --- | --- | --- |
| `POST /api/recruit/posts` | 创建招募帖 | 仅 host/admin，字段走公开白名单 |
| `GET /api/recruit/posts` | 公开招募列表 | 只返回公开、审核通过、未关闭帖子 |
| `GET /api/recruit/posts/{post_id}` | 招募详情 | 不返回申请私信和剧本真相 |
| `PATCH /api/recruit/posts/{post_id}` | 更新招募 | 仅 owner/admin |
| `POST /api/recruit/posts/{post_id}/applications` | 提交报名 | 登录账号，限速，不生成正式 player token |
| `POST /api/recruit/applications/{application_id}/approve` | 批准报名 | owner/admin；批准后才进入 Room join/character 绑定 |
| `POST /api/recruit/applications/{application_id}/reject` | 拒绝报名 | 记录审核结果，不创建角色 |
| `POST /api/rooms/{room_id}/invites` | 创建邀请链接 | owner/admin，可设置过期和次数 |
| `POST /api/rooms/{room_id}/schedule-polls` | 创建日程投票 | owner/admin |
| `POST /api/schedule-polls/{poll_id}/votes` | 提交可用时间 | 房间成员或申请者，只改自己的 vote |
| `POST /api/session-slots/{session_id}/attendance` | 标记出勤状态 | 房间成员，只改自己的记录 |

## 状态机

### 招募帖状态

```mermaid
stateDiagram-v2
  [*] --> draft
  draft --> open
  open --> paused
  paused --> open
  open --> filled
  open --> closed
  filled --> closed
  closed --> archived
```

### 报名申请状态

```mermaid
stateDiagram-v2
  [*] --> submitted
  submitted --> under_review
  under_review --> approved
  under_review --> rejected
  approved --> joined_room
  approved --> expired
  submitted --> withdrawn
  rejected --> archived
```

### 日程投票状态

```mermaid
stateDiagram-v2
  [*] --> collecting
  collecting --> locked
  locked --> scheduled
  collecting --> cancelled
  scheduled --> completed
  scheduled --> rescheduled
  rescheduled --> collecting
```

## 与核心链路关系

- Room 决定房间生命周期；Schedule 只提供加入和排期前置条件。
- Character 决定角色卡结构；Schedule 不解析角色数值。
- User 决定账号、角色归属、Host/Admin 权限；Schedule 不单独实现身份系统。
- Safety 决定公开字段、申请私信和会前边界反馈的可见范围。
- Channel 承载通知和聊天；Schedule 只产生需要通知的业务事件。
- Journal 记录开局、审批、改期、取消等可审计事件；Schedule 不写游戏内事件真相。
- AI-Keeper 不参与报名审批的最终决策，只能在未来提供可解释的辅助整理，不能自动拒绝或通过玩家。

## 验收标准

### v1 工程验收

- `join-info`、公开 room DTO 不返回凭证和剧本真相。
- 玩家加入 lobby 后 Host 和 Player 都能看到最新大厅快照。
- ready toggle 能影响普通 start 的通过条件。
- 未 ready 玩家阻止普通 start，返回可读的未准备名单。
- `force_start` 只能由 owner/admin 显式使用。
- active 房间中新加入角色状态为 `pending_approval`。
- Host 前端能批准或拒绝 `pending_approval` 玩家。
- 被拒绝玩家不能进入 active 主舞台。
- 账号恢复不能恢复他人角色。

### v1 文档验收

- Schedule 文档不宣称已有招募帖、报名表、日程投票和提醒。
- 未来接口与当前接口分区明确。
- 公开信息白名单和禁止字段明确。
- DeepSeek 计划中每批都有测试命令和禁止事项。

### 后续平台验收

- 报名申请批准前不生成完整玩家运行态权限。
- 候补不进入 ready、lobby 成员和投影。
- 日程投票不改变世界状态。
- 改期、取消、审批都有 Journal 审计记录。
- 公开招募页经过 Safety 字段过滤和 Admin 下架机制。
