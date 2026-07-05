# Room 团房间系统 DeepSeek 计划

## 执行定位

Room 模块的 DeepSeek 执行目标是稳定第一条主链路：

`Host 登录 -> 创建房间 -> 玩家加入并绑定角色 -> 玩家 ready -> Host 开局 -> 房间 active -> 首回合创建 -> Host/Player 收到状态变化`

本计划只允许 DeepSeek 修补 Room 生命周期、成员、大厅同步、权限和开局入口。AI 裁决、规则执行、State 真相写入、Transaction 播放时序、Projection 私密投影分发只做接口协同，不在 Room 批次内重写。

## 全局执行规则

- 每个 Batch 开始前先运行 `git status --short`，确认工作区已有改动，禁止覆盖无关文件。
- 当前代码优先于旧 PRD；旧 PRD 只用于补产品语义。
- 每个 Batch 只能改本批允许的文件方向，发现跨模块问题先记录到对应模块文档或 DeepSeek 总任务包。
- 房间状态只能由后端校验后写入，前端本地状态不得成为权威。
- 玩家不能直接写房间状态，Host 不能通过 Room 获得完整 KP 剧透视角，AI 不能直接落库改房间。
- 新增或修改接口时必须补测试；只改文案或文档时至少运行文档检查。
- 不引入社区、付费、语音视频、动态光照、完整旁观者系统。

## Batch Room-0：现状核对与文案乱码风险

| 项 | 内容 |
|---|---|
| 目标 | 核对 Room 当前代码、测试、前端页面与文档口径，优先处理影响理解和验收的乱码文案 |
| 允许文件方向 | `src/server/router_rooms.py`、`src/server/player/router_player.py`、`src/server/host/router_host.py`、`src/client/src/pages/HostCreate.tsx`、`HostLobby.tsx`、`PlayerJoinPage.tsx`、`PlayerLobby.tsx`、Room 文档 |
| 主要任务 | 盘点接口和状态流；修正用户可见中文乱码；确认错误响应不会破坏测试断言；记录未实现能力为 P1/P2/P3 |
| 测试命令 | `pytest tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py -q` |
| 预期结果 | 测试通过；文案不再出现明显乱码；Room 文档和代码口径一致 |
| 禁止事项 | 不顺手重写 UI，不新增房间密码、白名单、旁观者等长期能力 |

## Batch Room-1：开房、查房、选剧本、权限

| 项 | 内容 |
|---|---|
| 目标 | 稳定 Host/Admin 创建房间、公开查房、房主选剧本和权限边界 |
| 允许文件方向 | `src/server/router_rooms.py`、`src/server/router_auth.py`、`src/server/scenario/router_scenarios.py`、`tests/server/test_rooms.py`、`tests/server/test_room_security.py`、`tests/server/test_host_room_lifecycle.py` |
| 主要任务 | 确认 `POST /api/rooms` 只允许 host/admin；确认 scenario 存在性校验；确认公开 DTO 脱敏；确认 owner token、owner account、admin 三类 owner/admin 鉴权一致 |
| 测试命令 | `pytest tests/server/test_rooms.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py -q` |
| 预期结果 | 未登录创建 401；player 创建 403；host/admin 创建成功；公开房间信息不返回敏感字段；active 房间不能切换剧本 |
| 禁止事项 | 不把 owner token 放进公开接口，不把 admin 能力下放给 player |

## Batch Room-2：玩家入房、角色绑定、ready、大厅同步

| 项 | 内容 |
|---|---|
| 目标 | 稳定玩家加入房间、绑定角色、ready 切换，以及 Host/Player 大厅实时同步 |
| 允许文件方向 | `src/server/player/router_player.py`、`src/server/engine/engine.py`、`src/server/engine/projection.py`、`src/client/src/pages/PlayerJoinPage.tsx`、`PlayerLobby.tsx`、`HostLobby.tsx`、`src/client/src/shared/ws.ts`、`tests/server/test_character_join_import.py`、`tests/server/test_player_intent.py`、`tests/server/test_ws_auth.py` |
| 主要任务 | 校验角色来源只能选一种；保持入房限速；加入后广播 `s2c_room_lobby_snapshot`；ready 后以后端 `is_ready` 为准；保留 WS 失败时轮询兜底 |
| 测试命令 | `pytest tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_ws_auth.py -q` |
| 前端验证 | 涉及前端页面时运行 `npm run build` |
| 预期结果 | 玩家可用预设、上传、构筑器、模板或复制方式入房；ready 能同步到 Host/Player 大厅；玩家 token 无效时不能提交 ready |
| 禁止事项 | 不让前端直接写 ready 权威状态，不把角色卡完整解析职责塞进 Room |

## Batch Room-3：开局、force_start、首回合创建、checkpoint/map 初始化

| 项 | 内容 |
|---|---|
| 目标 | 稳定 `POST /api/rooms/{room_id}/start` 的默认开局和显式急救开局 |
| 允许文件方向 | `src/server/router_rooms.py`、`src/server/turn_manager.py`、`src/server/map_persistence.py`、`src/server/events/event_log.py`、`src/client/src/pages/HostLobby.tsx`、`tests/server/test_rooms.py`、`tests/server/test_host_room_lifecycle.py` |
| 主要任务 | 默认 start 要求剧本、至少一名玩家、所有玩家 ready；`force_start: true` 仅 owner/admin 可显式使用；开局后创建首回合；尝试自动 checkpoint 和 map 初始化；广播 active 大厅快照 |
| 测试命令 | `pytest tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py -q` |
| 预期结果 | 空房普通 start 返回 409；未 ready 普通 start 返回结构化 409；force start 可成功；开局返回 `status=active`、`turn_id`、`turn_index` |
| 禁止事项 | 不把 force_start 作为 UI 默认路径，不在 Room 内实现规则结算 |

## Batch Room-4：进行中加入审批、身份恢复、权限泄露测试

| 项 | 内容 |
|---|---|
| 目标 | 补齐 active 中途加入、Host 审批、玩家身份恢复和安全测试 |
| 允许文件方向 | `src/server/player/router_player.py`、`src/server/host/router_host.py`、`src/client/src/pages/HostLobby.tsx`、`PlayerLobby.tsx`、`src/client/src/shared/identity.ts`、`tests/server/test_character_join_import.py`、`tests/server/test_room_security.py`、可新增 Room 安全测试文件 |
| 主要任务 | active 入房写入 `pending_approval`；approve/reject 后广播大厅快照；登录账号只能恢复自己名下角色 session；公开接口持续脱敏 |
| 测试命令 | `pytest tests/server/test_character_join_import.py tests/server/test_room_security.py -q` |
| 预期结果 | active join 不直接进入正式队列；非 owner/admin 不能审批；账号不能恢复他人角色；reject 后不计入玩家列表 |
| 禁止事项 | 不开放游客任意恢复他人 token，不让 pending 玩家收到不该看的 active 私密上下文 |

## Batch Room-5：回归验收与端到端主链路

| 项 | 内容 |
|---|---|
| 目标 | 对 Room 主链路做最终回归，确认与 AI-Keeper 核心链路入口兼容 |
| 允许文件方向 | 测试、少量修复文件；若发现跨模块缺陷，记录到对应模块文档或 `docs/30-DeepSeek任务包/` |
| 后端测试 | `pytest tests/server/test_rooms.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_ws_auth.py -q` |
| 前端测试 | 涉及前端时运行 `npm run build` |
| 手动验收 | Host 登录创建房间；玩家加入绑定角色；玩家 ready；Host 开局；房间 active；首回合创建；Host/Player 大厅收到变化 |
| 预期结果 | P0 主链路稳定，公开 DTO 脱敏，玩家无法越权，force_start 行为清晰 |
| 禁止事项 | 不在最终回归中新增大功能，不为了通过测试删除安全校验 |

## 工程验收命令

Room 相关后端回归：

```powershell
pytest tests/server/test_rooms.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_ws_auth.py -q
```

涉及前端 Room 页面时：

```powershell
npm run build
```

文档验收：

```powershell
$badWords = 'TO' + 'DO|TB' + 'D|待' + '补|待' + '定|<{7}|={7}|>{7}'
rg -n $badWords docs/50-AI-Keeper-Platform/01-Room团房间系统
rg -n "^#+\s*$" docs/50-AI-Keeper-Platform/01-Room团房间系统
```

## 最终交付标准

- Room 三份文档和当前代码口径一致。
- P0/P1/P2/P3 能力边界清晰。
- DeepSeek 每个 Batch 都有目标、允许文件方向、测试命令、预期结果和禁止事项。
- 第一轮执行仍聚焦核心主链路，不引入平台外围能力。
- 所有新增或修正后的接口行为都有测试或明确的手动验收路径。
