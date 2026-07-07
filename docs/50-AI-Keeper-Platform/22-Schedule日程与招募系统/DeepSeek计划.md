# Schedule 日程与招募系统 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + 房间入桌、ready、开局检查与进行中加入审批风险识别版`。
- 第一轮目标是把当前 Room / Player Join / Host Lobby 已经存在的调度链路修完整，不提前做公开招募广场、日历系统、外部提醒和社区匹配。
- 当前代码已经有：`join-info`、`join-with-character`、`ready_toggle`、普通 start、后端 `force_start` 加固、active 加入 `pending_approval`、Host approve/reject 后端。
- 当前主要缺口是：HostLobby 审批前端缺失、PlayerLobby 未区分 pending 审批态、`pending_approval` 运行态权限未完全锁死、approve/reject 缺少单独审计、DTO 白名单未固定到命名契约。

## 执行原则

Schedule 的第一轮执行只修“当前核心跑团链路已经需要的调度缺口”。所有工程批次开始前先执行 `git status --short`，确认工作区已有改动，不覆盖无关文件。

DeepSeek 必须先读当前代码和测试，再改代码。当前真实基础是 Room、Player Join、Host approve/reject、ready、Lobby WS；不存在独立 Schedule 服务。

## 现状依据

- Room 生命周期与 `force_start`：`src/server/router_rooms.py`
- 玩家加入、`join-info`、ready、intent：`src/server/player/router_player.py`
- Host 审批后端：`src/server/host/router_host.py`
- 大厅快照投影：`src/server/engine/projection.py`
- 数据表结构：`src/server/db_adapter.py`
- 玩家加入页：`src/client/src/pages/PlayerJoinPage.tsx`
- 玩家大厅页：`src/client/src/pages/PlayerLobby.tsx`
- Host 大厅页：`src/client/src/pages/HostLobby.tsx`
- 后台房间详情：`src/client/src/pages/AdminDashboard.tsx`
- 当前测试：`tests/server/test_host_room_lifecycle.py`、`tests/server/test_room_security.py`、`tests/server/test_character_join_import.py`、`tests/server/test_player_intent.py`、`tests/server/test_rooms.py`

## 全局实现规则

1. P0 只处理当前 Room 主链路，不默认进入私域招募和日程工程实现。
2. `join-info`、`GET /api/rooms/{room_id}`、大厅快照必须只返回公开字段，不得返回 token、`raw_text`、truth、ending、隐藏线索、隐藏 NPC。
3. `pending_approval` 不是普通成员：不计入 ready，不进主舞台，不提交运行态 intent，不看 player archive，不收 player-only event。
4. P0 默认不让 `pending_approval` 进入 active `party` 队伍消息流；如保留 waiting page 安全提示，必须在回执里说明。
5. `force_start` 新前端必须传 `confirm + reason`，不得继续沿用 legacy `{ force_start: true }` payload。
6. approve / reject 属于房间管理操作，必须补独立审计字段。
7. reject 后 token 是否立即失效、若不失效剩余可访问范围是什么，工程回执必须明确。
8. 未来 `RecruitApplication` 在 `submitted / under_review` 阶段不得发正式 `player_token`，不得进入 lobby / Projection / WS。
9. `SchedulePoll`、`AvailabilityVote`、`AttendanceRecord` 只产生会前协调记录，不得修改 `characters.is_ready`、`characters.status`、HP / SAN / MP / Luck 或 `room.status`。
10. `ReminderJob` 依赖 Channel / Admin-Ops，不在 Schedule 内自建通知基础设施。
11. Schedule-4 和 Schedule-5 只有在用户明确确认“从文档进入私域招募/日程工程实现”后才执行。

## Batch Schedule-0：现状复核、阶段说明与 DTO 白名单

### 目标

- 复核当前没有独立 `schedule / recruit` 表、接口和页面。
- 固定“当前阶段说明”和 P0 / P1 / P2 边界。
- 确认 `join-info`、`GET /api/rooms/{room_id}`、大厅快照不会返回 owner token、player token、剧本 `raw_text`、隐藏真相。
- 固定 `RoomJoinInfoDTO`、`RoomPublicInfoDTO`、`LobbySnapshotDTO` 最小字段契约。
- 记录当前 Host 审批后端已存在、前端缺入口的事实。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统/`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `src/server/host/router_host.py`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/pages/HostLobby.tsx`
- 相关测试文件

### 建议命令

```bash
rg -n "schedule|recruit|availability|calendar|pending_approval|join-info|force_start" src tests
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_rooms.py -q
cd src/client && npm run build
```

### 验收

- 现状报告明确“没有独立 Schedule 实现”。
- `RoomJoinInfoDTO`、`RoomPublicInfoDTO`、`LobbySnapshotDTO` 的公开字段明确。
- `join-info` 不含 `owner_token`、`player_token`、truth、ending、隐藏字段。
- 文档阶段说明与 P0 / P1 / P2 边界固定。

### 禁止事项

- 不新增 schedule / recruit 数据表。
- 不新增公开招募页面。
- 不改 AI、State、Transaction、Projection 核心裁决逻辑。
- 不把剧本 `raw_text` 或 truth 放入任何加入页响应。

## Batch Schedule-1：进行中加入审批前端闭环

### 目标

- 在 HostLobby 中区分显示 `pending_approval` 玩家和普通 `joined` 玩家。
- 为 `pending_approval` 玩家提供批准和拒绝按钮，调用现有 `POST /api/host/{room_id}/approve/{character_id}` 与 `reject`。
- 审批完成后刷新玩家列表或等待 `s2c_room_lobby_snapshot` 更新。
- PlayerLobby 对自己处于 `pending_approval` 时显示等待审批状态，不自动进入 active 主舞台。

### 允许文件方向

- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/shared/api.ts`
- 必要时增加前端轻量测试文件
- 必要时补充 `tests/server/test_host_room_lifecycle.py`

### 建议命令

```bash
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

### 验收

- Host 能看到待审批玩家的姓名、调查员名、状态。
- Host 能 approve / reject 待审批玩家。
- owner token 正确时 approve 变 `joined`，reject 变 `left`。
- 错 owner token 或非 owner 不能审批。
- pending 玩家不会因为 room active 自动进入 `/player/{roomId}` 主页面。

### 禁止事项

- 不只靠前端隐藏权限，后端鉴权必须继续有效。
- 不把 `pending_approval` 玩家算作普通 ready 玩家。
- 不在前端保存或展示 owner token 之外的敏感凭证。

## Batch Schedule-2：`join_mode`、ready 语义与 pending 权限加固

### 目标

- 固定 `join_mode` 的当前矩阵：`draft/lobby -> direct`、`active -> host_approval`、`paused/completed/archived -> closed`。
- 补测试确认不同 room status 返回稳定 `join_mode`。
- 确认 ready 只用于“当前开局准备”，不承载未来日程投票。
- 修复 HostLobby 对待审批玩家的 ready 统计，普通 start 不应被 pending 玩家干扰。
- 补齐 pending 玩家不能提交运行态 intent、不能进入 archive、不能接收 player-only 事件的后端校验和测试。

### 允许文件方向

- `src/server/player/router_player.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_rooms.py`
- `src/server/events/event_log.py`
- `src/server/engine/projection.py`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `tests/server/test_room_security.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_rooms.py`
- 可新增 `tests/server/test_schedule_permissions.py`

### 建议命令

```bash
python -m pytest tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py tests/server/test_player_intent.py -q
cd src/client && npm run build
```

### 验收

- `join-info` 对不同房间状态返回稳定 `join_mode`。
- 普通 start 只检查已加入且有效的玩家 ready。
- active 加入不直接成为 `joined`。
- pending 玩家不能提交运行态 intent。
- pending 玩家不能访问 player archive。
- pending 玩家不能进入 player-only 投影链路。
- pending 玩家默认不进入 active `party` 队伍消息流。

### 禁止事项

- 不新增报名表。
- 不把未来排期字段塞进 `characters.is_ready`。
- 不用前端判断替代后端状态校验。

## Batch Schedule-3：审计与 DTO 收口

### 目标

- 为 approve / reject 增加独立审计字段。
- 收口 `StartGateDecisionDTO`、`ForceStartRequestDTO`、`HostApprovalResultDTO`。
- 明确 `force_start` 新前端必须传 `confirm + reason`。
- 修正文案乱码，不做大范围重构。

### 允许文件方向

- `src/server/router_rooms.py`
- `src/server/host/router_host.py`
- `src/server/events/event_log.py`
- `src/server/events/events_registry.py`
- `src/client/src/pages/HostLobby.tsx`
- `tests/server/test_host_room_lifecycle.py`

### 建议命令

```bash
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

### 验收

- `force_start` UI 不再依赖 legacy payload。
- `force_start` 审计至少包含 actor、roomId、reason、notReadyCharacters 或等价字段。
- approve / reject 审计至少包含 actor、target、decision、previousStatus、newStatus。
- reject 后 token 生命周期或残余能力在回执中说明。
- 中文文案无乱码。

### 禁止事项

- 不放宽现有 `force_start` 后端校验。
- 不把审批审计做成 public event 或 public export 内容。

## Batch Schedule-4：私域招募数据设计草案

### 启动条件

- 用户明确确认要从文档进入私域招募设计。
- Room、User、Safety 的 P0 权限和脱敏口径稳定。

### 目标

- 在文档或迁移草案中设计 `recruit_posts`、`recruit_applications`、`room_invites`、`room_waitlist`。
- 明确招募申请批准前不创建正式角色运行态，不发正式 `player_token`。
- 明确公开字段白名单和禁止字段。
- 给出最小 API 契约和测试计划，但不在本批落实现代码。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Schedule-私域招募设计.md`
- 如用户明确同意，可新增 migration 草案文档，不执行迁移

### 建议命令

```bash
rg -n "raw_text|truth|owner_token|player_token" docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统
```

### 验收

- 数据模型区分 Room 成员、报名申请、候补。
- 公开招募 DTO 不包含凭证和剧本真相。
- `RecruitApplication submitted / under_review` 不发正式 `player_token`。

### 禁止事项

- 不实际创建数据库迁移。
- 不实现 `/api/recruit`。
- 不依赖 Community 还未确定的公开广场能力。

## Batch Schedule-5：日程投票和出勤初版

### 启动条件

- 用户明确确认要从文档进入日程工程实现。
- Schedule-1 到 Schedule-3 已通过回归。

### 目标

- 实现房主创建日程投票。
- 玩家提交可用时间。
- Host 查看聚合结果并确认一次 `session_slot`。
- 玩家标记本次请假、迟到、可参加。

### 允许文件方向

- `src/server/schedule/` 或 `src/server/recruit/`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- 可新增 `tests/server/test_schedule_poll.py`

### 建议命令

```bash
python -m pytest tests/server/test_schedule_poll.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

### 验收

- 日程投票不改变 `characters.is_ready`。
- 玩家只能修改自己的 availability。
- Host 只能管理自己房间的投票。
- `AttendanceRecord` 不改变 `characters.status` 或角色数值。
- 确认 session 后可在 lobby 显示计划时间。

### 禁止事项

- 不接入外部日历。
- 不做循环长团排期。
- 不把缺席直接改成角色离开或角色死亡。

## Batch Schedule-6：提醒和通知设计

### 目标

- 设计站内提醒事件和后台任务口径。
- 明确邮件、短信、Webhook、浏览器提醒的配置依赖。
- 与 Channel、Admin/Ops 对齐，不在 Schedule 内自建通知基础设施。

### 允许文件方向

- `docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Schedule-通知设计.md`

### 建议命令

```bash
rg -n "ReminderJob|Channel|Webhook|email|sms|notification" docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统
```

### 验收

- 提醒设计说明清楚依赖的模块和配置位置。
- 通知正文不含 token、私密备注、Safety feedback、剧本真相。
- 通知失败不阻断开局。

### 禁止事项

- 不新增真实第三方通知密钥配置。
- 不在 Schedule 内实现邮件或短信 provider。
- 不把通知事件写成公共剧情事件。

## Batch Schedule-7：回归验收

### 目标

- 跑后端相关测试。
- 跑前端 build。
- 手动验证一条完整会前主链路和一条 pending 越权链路。

### 建议命令

```bash
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_rooms.py -q
cd src/client && npm run build
```

### 验收

- Host 创建房间、玩家加入、ready、Host start、active 加入 pending、Host 审批前端闭环全部可用。
- pending 玩家不能提交 intent。
- pending 玩家不能进入 player archive。
- pending 玩家不能收到 player-only event。
- pending 玩家默认不进入 active `party` 队伍消息流。
- `join-info`、public room DTO、大厅快照不暴露 token 或剧本真相。

### 禁止事项

- 不因为测试失败而调低验收口径。
- 不把未完成的私域招募或日程功能伪装成“已完成”。
