# Schedule 日程与招募系统 DeepSeek 计划 V2.0

## 执行原则

Schedule 的第一轮执行只修“当前核心跑团链路已经需要的调度缺口”，不提前实现公开招募广场、日历系统、外部提醒和社区匹配。所有工程批次开始前先执行 `git status --short`，确认工作区已有改动，不覆盖无关文件。

DeepSeek 必须先读当前代码和测试，再改代码。当前真实基础是 Room、Player Join、Host approve/reject、ready、Lobby WS；不存在独立 Schedule 服务。

## 现状依据

- Room 生命周期：`src/server/router_rooms.py`
- 玩家加入和 ready：`src/server/player/router_player.py`
- Host 审批后端：`src/server/host/router_host.py`
- 大厅快照投影：`src/server/engine/projection.py`
- 数据表结构：`src/server/db_adapter.py`
- 玩家加入页：`src/client/src/pages/PlayerJoinPage.tsx`
- 玩家大厅页：`src/client/src/pages/PlayerLobby.tsx`
- Host 大厅页：`src/client/src/pages/HostLobby.tsx`
- 后台房间详情：`src/client/src/pages/AdminDashboard.tsx`
- 当前测试：`tests/server/test_host_room_lifecycle.py`、`tests/server/test_room_security.py`、`tests/server/test_character_join_import.py`、`tests/server/test_player_intent.py`

## Batch Schedule-0：现状复核与字段安全

目标：

- 复核当前没有独立 schedule/recruit 表、接口和页面。
- 确认 `join-info`、`GET /api/rooms/{room_id}`、大厅快照不会返回 owner token、player token、剧本 raw_text、隐藏真相。
- 记录当前 Host 审批后端已存在、前端缺入口的事实。
- 修正加入、审批、ready、开局相关中文文案乱码，不做大范围重构。

允许文件方向：

- `docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统/`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `src/server/host/router_host.py`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/pages/HostLobby.tsx`
- 相关测试文件

建议命令：

```bash
rg -n "schedule|recruit|availability|calendar|pending_approval|join-info|force_start" src tests
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py tests/server/test_character_join_import.py tests/server/test_player_intent.py -q
cd src/client && npm run build
```

验收：

- DeepSeek 的现状报告明确“没有独立 Schedule 实现”。
- 公开 DTO 安全字段有测试或现有测试引用。
- 文案修复不改变 API 状态码和核心数据结构。

禁止事项：

- 不新增 schedule/recruit 数据表。
- 不新增公开招募页面。
- 不改 AI、State、Transaction、Projection 核心裁决逻辑。
- 不把剧本 raw_text 或 truth 放入任何加入页响应。

## Batch Schedule-1：进行中加入审批前端闭环

目标：

- 在 HostLobby 中展示 `pending_approval` 玩家和普通 `joined` 玩家。
- 为 `pending_approval` 玩家提供批准和拒绝按钮，调用现有 `POST /api/host/{room_id}/approve/{character_id}` 与 `reject`。
- 审批完成后刷新玩家列表或等待 `s2c_room_lobby_snapshot` 更新。
- PlayerLobby 对自己处于 `pending_approval` 时显示等待审批状态，不自动进入 active 主舞台。

允许文件方向：

- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/shared/api.ts`
- 必要时增加前端轻量测试文件
- 必要时补充 `tests/server/test_host_room_lifecycle.py`

建议命令：

```bash
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

验收：

- Host 能看到待审批玩家的姓名、调查员名、状态。
- owner token 正确时 approve 变 `joined`，reject 变 `left`。
- 错 owner token 或非 owner 不能审批。
- pending 玩家不会因为 room active 自动进入 `/player/{roomId}` 主页面。

禁止事项：

- 不只靠前端隐藏权限，后端鉴权必须继续有效。
- 不把 `pending_approval` 玩家算作普通 ready 玩家。
- 不在前端保存或展示 owner token 之外的敏感凭证。

## Batch Schedule-2：加入信息和 ready 语义加固

目标：

- 明确 `join_mode` 的三种现状：`direct`、`host_approval`、`closed`。
- 补测试确认 lobby/draft 可直接加入，active 进入审批，completed/archived/paused 不允许普通加入或按现有策略关闭。
- 确认 ready 只用于“当前开局准备”，不承载未来日程投票。
- 修复 HostLobby 对待审批玩家的 ready 统计，普通 start 不应被 pending 玩家干扰。

允许文件方向：

- `src/server/player/router_player.py`
- `src/server/router_rooms.py`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `tests/server/test_room_security.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_rooms.py`

建议命令：

```bash
python -m pytest tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py -q
cd src/client && npm run build
```

验收：

- `join-info` 对不同房间状态返回稳定 join mode。
- 普通 start 只检查已加入且有效的玩家 ready。
- active 加入不直接成为 `joined`。
- closed 状态不能产生有效 player token 或进入主链路。

禁止事项：

- 不新增报名表。
- 不把未来排期字段塞进 `characters.is_ready`。
- 不用前端判断替代后端状态校验。

## Batch Schedule-3：私域招募数据设计草案

目标：

- 在文档或迁移草案中设计 `recruit_posts`、`recruit_applications`、`room_invites`、`room_waitlist`。
- 明确招募申请批准前不创建正式角色运行态，不发正式 `player_token`。
- 明确公开字段白名单和禁止字段。
- 给出最小 API 契约和测试计划，但不在本批落实现代码。

允许文件方向：

- `docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统/`
- 可新增 `docs/30-DeepSeek任务包/Batch-Schedule-私域招募设计.md`
- 如用户明确同意，可新增 migration 草案文档，不执行迁移

建议命令：

```bash
rg -n "raw_text|truth|owner_token|player_token" docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统
```

验收：

- 数据模型区分 Room 成员、报名申请、候补。
- 招募公开 DTO 不包含凭证和剧本真相。
- 接口方向有权限、限速和状态机说明。

禁止事项：

- 不实际创建数据库迁移。
- 不实现 `/api/recruit`。
- 不依赖 Community 还未确定的公开广场能力。

## Batch Schedule-4：私域招募最小实现

启动条件：

- Room、User、Safety 的 P0 权限和脱敏测试稳定。
- 用户确认要从文档进入工程实现。
- 工作区无未理解的源码改动。

目标：

- 实现房主私域招募帖草稿、打开、关闭。
- 实现登录玩家提交申请。
- 实现 Host 审批申请，批准后引导玩家绑定角色入房。
- 实现容量和候补的最小逻辑。

允许文件方向：

- 可新增 `src/server/schedule/` 或 `src/server/recruit/`
- `src/server/main.py`
- `src/server/db_adapter.py` 或项目实际迁移位置
- `src/client/src/pages/HostLobby.tsx`
- 可新增 `src/client/src/pages/RecruitPostPage.tsx`
- 可新增 `tests/server/test_recruit.py`

建议命令：

```bash
python -m pytest tests/server/test_recruit.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py -q
cd src/client && npm run build
```

验收：

- Host 可创建、打开、关闭自己的私域招募。
- Player 可提交申请但未批准前不进入 room members。
- Host 批准后玩家才能继续角色绑定。
- 满员后申请进入候补或返回明确状态。
- 公开招募详情不含剧本真相和任何 token。

禁止事项：

- 不做公开招募列表和搜索。
- 不做 AI 自动筛选玩家。
- 不把申请私信写入 public event 或 public export。

## Batch Schedule-5：日程投票和出勤初版

目标：

- 实现房主创建日程投票。
- 玩家提交可用时间。
- Host 查看聚合结果并确认一次 `session_slot`。
- 玩家标记本次请假、迟到、可参加。

允许文件方向：

- `src/server/schedule/` 或 `src/server/recruit/`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- 可新增 `tests/server/test_schedule_poll.py`

建议命令：

```bash
python -m pytest tests/server/test_schedule_poll.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

验收：

- 日程投票不改变 `characters.is_ready`。
- 玩家只能修改自己的 availability。
- Host 只能管理自己房间的投票。
- 确认 session 后可在 lobby 显示计划时间。

禁止事项：

- 不接入外部日历。
- 不做循环长团排期。
- 不把缺席直接改成角色离开或角色死亡。

## Batch Schedule-6：提醒和通知设计

目标：

- 设计站内提醒事件和后台任务口径。
- 明确邮件、短信、Webhook、浏览器提醒的配置依赖。
- 与 Channel、Admin/Ops 对齐，不在 Schedule 内自建通知基础设施。

允许文件方向：

- `docs/50-AI-Keeper-Platform/22-Schedule日程与招募系统/`
- `docs/50-AI-Keeper-Platform/03-Channel聊天与信息流系统/`
- `docs/50-AI-Keeper-Platform/24-Plugin-Admin-Ops开放API与后台运维/`
- 若进入工程，可新增提醒任务测试和后台 job 草案

建议命令：

```bash
rg -n "reminder|notification|schedule|attendance" docs src tests
```

验收：

- 提醒事件有明确 owner、recipient、visibility。
- 任务失败可重试并记录审计。
- 不向未授权渠道发送房间隐私信息。

禁止事项：

- 不硬编码第三方通知服务密钥。
- 不把提醒失败作为开局失败条件。
- 不把玩家私密备注放进通知正文。

## Batch Schedule-7：回归验收

目标：

- 回归当前核心主链路。
- 回归 Schedule 新增能力与 Room/User/Safety 的边界。
- 确保没有把平台长期能力混进 AI 核心链路。

建议命令：

```bash
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_room_security.py tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_rooms.py -q
cd src/client && npm run build
cd src/client && npm run test
```

手动验收：

1. Host 登录并创建房间。
2. 玩家登录并通过房间码加入。
3. 玩家绑定角色并进入大厅。
4. 玩家 ready。
5. Host 普通开局成功。
6. active 后新玩家加入进入待审批。
7. Host 在前端批准或拒绝。
8. 被批准玩家可进入对应玩家端，被拒绝玩家不能进入主舞台。
9. 公开加入页、公开房间 DTO、招募相关页面不显示 token 和剧本真相。

禁止事项：

- 不跳过权限测试。
- 不只跑前端 build 就声明后端完成。
- 不在未通过 Safety 检查前开放公开招募。
