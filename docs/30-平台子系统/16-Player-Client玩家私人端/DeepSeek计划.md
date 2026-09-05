# Player Client 玩家私人端 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + 玩家私人端可用性与恢复安全风险识别版`。
- 第一轮目标不是做“更酷的玩家端”，而是先把“受限、可信、可恢复”的玩家私人终端做扎实。
- 当前仓库已有真实风险点，工程执行必须以代码现状为准：`shared/api.ts` 本地自造 `player_token`、`shared/identity.ts` 长期存 token、`shared/ws.ts` query token 与内存态 `lastSequence`、`PlayerActionPage.tsx` 缺少完整版本屏障、`router_reconnect.py` recent events 收口风险、`PlayerInventory.tsx` 的 `id/clue_id` 混用。

## 执行目标

把玩家端整理成稳定、可恢复、受限的私人调查终端。第一轮优先保证主链路跑通：

`加入房间 -> 绑定角色 -> ready -> 进入行动页 -> 提交行动 -> 接收投影 -> 查看授权资源 -> 断线恢复`

本计划只处理 Player Client 及其直接依赖的必要后端接口，不重写 AI、Rule、State、Transaction、Projection 的职责边界。涉及核心链路的问题必须回看：

- `docs/30-DeepSeek任务包/Batch-1-开发态稳定性与实时闭环.md`
- `docs/30-DeepSeek任务包/Batch-2-状态版本屏障与投影时序.md`
- `docs/30-DeepSeek任务包/Batch-4-线索证据链与防剧透.md`
- `docs/50-AI-Keeper-Platform/13-State世界状态系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/14-Transaction事务系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/15-Projection投影系统/DeepSeek计划.md`

## 全局禁止事项

1. 禁止让前端直接写 HP、SAN、背包、线索、地图位置或房间状态。
2. 禁止信任请求体中的 `character_id` 作为玩家身份。
3. 禁止在玩家端展示 `owner_token`、Host-only 事件、KP note、隐藏真相、raw debug。
4. 禁止依赖前端过滤解决权限问题，最终过滤必须在服务端完成。
5. 禁止为了修 UI 绕过 `X-Room-Token`、Authorization 或 WS 鉴权。
6. 禁止把语音、动效、移动端增强排到核心链路之前。
7. 禁止顺手重构 Host/Admin/全局设计系统。
8. 禁止修改与 Player Client 无关的源码、测试产物或运行时数据。

## Batch Player-0：现状盘点与构建基线

### 目标

确认当前玩家端真实可运行状态，锁定中文乱码、构建错误、接口口径偏差和主链路断点。

### 允许改动

- `docs/50-AI-Keeper-Platform/16-Player-Client玩家私人端/`
- 必要时新增问题记录文档

### 任务

1. 运行 `git status`，确认工作区已有改动范围。
2. 检查 `PlayerJoinPage`、`PlayerLobby`、`PlayerActionPage`、`PlayerCharacter`、`PlayerInventory`、`PlayerTerminal`、`VoiceInput` 是否存在乱码或类型阻塞。
3. 检查 `shared/api.ts` 的 `getPlayerToken()` 是否仍会本地自造 token。
4. 检查 `shared/ws.ts` 的 query token、`lastSequence` 和连接状态暴露方式。
5. 检查前后端字段口径，重点是 `clue_id/id`、archive 类型、action status、`stateVersion`。
6. 记录 `npm run build` 首个失败原因即可，不在本批顺手大修。

### 验收命令

```powershell
cd src/client
npm run build
```

```powershell
python -m pytest tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_reconnect.py -q
```

### 预期结果

产出一份可执行问题清单，区分：

- 文本/构建问题
- 接口/类型问题
- 权限/恢复/状态链路问题

## Batch Player-1：中文文案与玩家触达页面可用性

### 目标

先把玩家直接触达页面修到可读、可构建、可手动操作，不改变产品结构。

### 允许改动

- `src/client/src/App.tsx`
- `src/client/src/navigation.ts`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/pages/PlayerCharacter.tsx`
- `src/client/src/pages/PlayerInventory.tsx`
- `src/client/src/components/PlayerTerminal.tsx`
- `src/client/src/components/VoiceInput.tsx`
- `src/client/src/components/TacticalButtons.tsx`

### 任务

1. 修复玩家端触达页面的历史乱码。
2. 修复明显阻塞 TSX 解析的字符串和标签问题。
3. 保留现有页面结构，不重做 Host/Admin/全局 UI 体系。
4. 统一最小错误提示文案：未登录、房间不存在、token 无效、加入失败、提交失败、网络断开。
5. 确保 VoiceInput 失败时文本输入仍可用。

### 验收命令

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不改后端业务逻辑。
- 不新增大规模 UI 框架。
- 不把中文修复和权限修复混成一个大杂烩提交。

## Batch Player-2：入房、角色绑定与身份恢复

### 目标

让玩家从登录到加入房间、绑定角色、恢复角色会话的路径闭合。

### 允许改动

- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/LoginPage.tsx`
- `src/client/src/shared/identity.ts`
- `src/client/src/shared/api.ts`
- `src/server/player/router_player.py`
- `tests/server/test_character_join_import.py`
- 必要时新增 `tests/server/test_player_session_restore.py`

### 任务

1. Join 表单明确四种角色来源互斥。
2. 入房成功后只保存服务端返回的 `player_token`。
3. 修复 `getPlayerToken()` 本地自造正式 token 的路径。
4. 增加“恢复本人角色会话”入口，串起 `/api/player/me/characters` 与 `restore-session`。
5. `restore-session` 返回新 token 后，只覆盖当前房间当前 slot，不覆盖其他 room/slot。
6. active 房间加入时，前端明确显示 `pending_approval`，不当作已可行动。
7. 文档和代码都要明确：identity slot 是开发态便利，不是生产安全会话方案。
8. 若因联调需要保留 mock token，必须限制在显式 dev/mock mode，不得进入真实 join/restore 正式路径。

### 验收命令

```powershell
python -m pytest tests/server/test_character_join_import.py tests/server/test_room_security.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不允许前端提交 `character_id` 决定身份。
- 不允许恢复他人角色。
- 不允许无登录绕过账号归属策略。

## Batch Player-3：Lobby、ready、队内消息与开局跳转

### 目标

稳定大厅实时闭环：玩家加入、ready、队内消息、Host 开局、玩家进入行动页。

### 允许改动

- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/shared/ws.ts`
- `src/server/player/router_player.py`
- `src/server/router_rooms.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_ws_auth.py`

### 任务

1. `ready_toggle` 乐观更新失败时必须回滚并提示。
2. `s2c_room_lobby_snapshot` 到达后刷新成员与 ready 状态。
3. `s2c_team_message` 保留去重，失败时撤销本地乐观消息。
4. Host start 后玩家自动跳行动页，手动按钮只作兜底。
5. 轮询兜底不能制造重复跳转。
6. active 后 ready 展示语义要与 `pending_approval` 区分清楚。

### 验收命令

```powershell
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_player_intent.py tests/server/test_ws_auth.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不为同步 ready 直接改 `characters` 表绕过 Room/Engine 口径。
- 不把队内消息发进 AI 裁决链路。

## Batch Player-4：行动终端、错误模型与 pending action 恢复

### 目标

让玩家提交行动后的等待、排队、结算、完成、失败反馈可理解，并和事务状态一致。

### 允许改动

- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/components/TacticalButtons.tsx`
- `src/client/src/components/VoiceInput.tsx`
- `src/server/player/router_player.py`
- `src/server/player/router_reconnect.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_reconnect.py`

### 任务

1. 统一 action 状态：`idle/submitting/queued/batched/resolving/resolved/rejected/timeout`。
2. 所有行动提交都带 `action_id`，重复点击不生成多条有效行动。
3. 建立统一错误模型：401/403/404/409/429/500。
4. 409 需要区分：
   - duplicate action / same turn already submitted
   - `state_version_conflict`
5. 接入 `/api/player/actions/{action_id}`，用于刷新、WS 断开和“本地 submitting 但 reconnect 找不到 action”场景。
6. reconnect 返回 `pending_actions` 后，按 queued/batched/resolving/resolved/rejected/timeout 恢复 UI。
7. 道具主张成功后只展示本人 inventory patch，失败显示服务端原因。
8. `PlayerApiErrorDTO.code` 至少固定为：`not_authenticated`、`player_token_invalid`、`room_not_found`、`action_not_found`、`duplicate_action`、`state_version_conflict`、`rate_limited`、`server_error`。

### 验收命令

```powershell
python -m pytest tests/server/test_player_intent.py tests/server/test_reconnect.py tests/server/test_retroactive_items.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不在前端判定技能成功失败。
- 不在前端伪造 action completed。
- 不把 rejected 当作 resolved 展示。

## Batch Player-5：P0 安全批次：WS、reconnect 与 `stateVersion` 屏障

### 目标

解决弱网和断线场景下的事件丢失、乱序 patch、重复应用和私密泄露风险。

### 允许改动

- `src/client/src/shared/ws.ts`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/shared/api.ts`
- `src/server/player/router_reconnect.py`
- `src/server/player/router_player.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_projection.py`
- `tests/server/test_ws_auth.py`
- 必要时新增 `src/client/src/shared/stateSync.ts`

### 任务

1. PlayerWS 暴露连接状态：`connecting/open/closed/reconnecting`。
2. 刷新或 WS 长断开后调用 `/api/player/reconnect`。
3. recent events 必须只用服务端已过滤结果恢复 UI，不允许前端自己再猜测可见性。
4. `pending_actions` 恢复到 action 状态机。
5. `s2c_state_patch` 支持 `schemaVersion/baseStateVersion/stateVersion/actionId`。
6. 建立版本屏障：
   - 当前版本 patch 才应用
   - 旧 patch 丢弃
   - 未来 patch 进 buffer 并触发 `/api/player/sync`
7. sync 覆盖 snapshot 后，只应用仍然有效的 buffered patch。
8. sequence 跳号不当作安全错误；安全仍以 Projection 过滤为准。
9. Player 消费白名单固定为：
   - `s2c_room_lobby_snapshot`
   - `s2c_team_message`
   - `s2c_action_queued`
   - `s2c_action_completed`
   - `s2c_state_patch`
   - `s2c_public_observation`
   - `s2c_turn_resolved`
   - `s2c_clue_discovered`
   - `s2c_clue_shared` 的 `publicVersion`
   - `s2c_map_updated/s2c_player_moved/s2c_map_revealed`
10. 未知 `s2c_*` 默认忽略并记录 debug，不作为安全过滤替代。
11. 回执必须说明：本轮是否只做了 WS query token 风险标注，是否做了日志脱敏，是否引入短期 WS ticket。
12. 如本轮仍保留 `localStorage` token 或 query token，只能宣称“风险已标注/部分缓解”，不能宣称“token 安全完成”。
13. 本批次至少补四类最小测试：旧 patch 丢弃、当前 patch 应用、未来 patch buffer+sync、sync 后只重放有效 patch。

### 验收命令

```powershell
python -m pytest tests/server/test_reconnect.py tests/server/test_projection.py tests/server/test_ws_auth.py tests/server/test_player_runtime_state.py -q
```

```powershell
cd src/client
npm run build
npm run test
```

### 禁止事项

- 不允许忽略版本号直接覆盖状态。
- 不允许把 Host-only 或他人私密事件发给前端后再隐藏。
- 不允许把 sequence 跳号误写成权限错误。

## Batch Player-6：角色、背包、线索、日志、地图

### 目标

把玩家私人资源面板和服务端权威读取模型对齐，避免展示过期状态或越权内容。

### 允许改动

- `src/client/src/pages/PlayerCharacter.tsx`
- `src/client/src/pages/PlayerInventory.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/server/player/router_player.py`
- `src/server/player/router_clues.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_map.py`
- `tests/server/test_player_runtime_state.py`
- `tests/server/test_clues.py`
- `tests/server/test_archive.py`
- 相关 map 测试

### 任务

1. `/api/player/character` 当前值优先 runtime；技能、背景、职业保留角色卡基线。
2. PlayerCharacter 展示与 Host HUD 一致的当前 HP/SAN/MP/Luck。
3. 前端内部统一使用 `clueId`，适配层兼容 `clue_id/id`。
4. 分享线索必须使用服务端权威 `clue_id`；分享后重新拉 `/api/player/clues`，不本地硬改 `shared=true`。
5. Player archive 查询复用 Projection 可见性口径。
6. `GET /api/map/{room_id}` 无 token 或 token 不属于房间时，默认 401/403；如未来要公开地图，只能给显式 public summary。
7. 地图移动失败显示服务端原因；成功后等待授权投影刷新。
8. archive 类型枚举与前端筛选项对齐，不保留自造 `narrative` 偏差。

### 验收命令

```powershell
python -m pytest tests/server/test_player_runtime_state.py tests/server/test_clues.py tests/server/test_archive.py tests/server/test_room_security.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不让玩家端改 runtime 当前值。
- 不把未发现地图节点、未获得线索、他人背包放进玩家响应。
- 不用前端字段隐藏替代服务端过滤。

## Batch Player-7：语音、移动端与可访问性补强

### 目标

在核心链路稳定后，补齐玩家端常用交互体验，但不改变安全边界。

### 允许改动

- `src/client/src/components/VoiceInput.tsx`
- `src/client/src/components/TacticalButtons.tsx`
- `src/client/src/components/PlayerTerminal.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/styles.css`
- `src/server/player/router_player.py`

### 任务

1. 麦克风权限拒绝、录音失败、STT 未配置时，明确提示文本输入。
2. 语音转写结果可编辑，再决定发队内消息或提交行动。
3. 战术按钮的禁用、loading、失败提示清晰。
4. 移动端底部 tab 不遮挡输入框。
5. 关键按钮支持键盘操作与基础 aria label。
6. 长文本消息和日志不挤爆容器。

### 验收命令

```powershell
cd src/client
npm run build
npm run test
```

### 禁止事项

- 不把语音当成唯一输入方式。
- 不在前端根据按钮类型直接结算战斗或追逐。
- 不引入大型移动端框架。

## Batch Player-8：端到端验收与回归

### 目标

验证玩家端与核心链路完整闭环，确保文档承诺、代码行为和测试命令一致。

### 手动验收流程

1. Host 登录并创建房间。
2. Player A 登录、加入房间并选择角色。
3. Player B 登录、加入房间并选择角色。
4. 两名玩家在 Lobby 互相可见并能发队内消息。
5. 两名玩家 ready。
6. Host 开始游戏。
7. 两名玩家进入行动终端。
8. Player A、Player B 分别提交行动。
9. 事务进入 resolving，Host 收到公共演出。
10. 每名玩家只收到自己可见的私密结果和队伍公共结果。
11. Player A 刷新页面，通过 reconnect 恢复 pending 或 completed 状态。
12. Player A 查看角色、背包、线索、地图、日志，内容均为授权视角。

### 回归命令

```powershell
python -m pytest tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_reconnect.py tests/server/test_clues.py tests/server/test_archive.py tests/server/test_ws_auth.py tests/server/test_host_room_lifecycle.py tests/server/test_player_runtime_state.py -q
```

```powershell
cd src/client
npm run build
npm run test
```

### 预期结果

- 玩家主链路完整跑通。
- 无 Host-only 或他人 `player-only` 泄露。
- 刷新和断线后状态一致。
- 前端构建通过。
- 相关后端测试通过。
