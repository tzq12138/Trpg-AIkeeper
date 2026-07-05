# Player Client 玩家私人端 DeepSeek 计划 V2.0

## 执行目标

把玩家端整理成稳定、可恢复、受限的私人调查终端。第一轮优先保证主链路可跑通：加入房间、绑定角色、ready、进入行动页、提交行动、接收投影、查看本人资源、断线恢复。

本计划只处理 Player Client 与其必要后端接口，不重写 AI、Rule、State、Transaction、Projection 的职责边界。涉及核心链路的问题必须回看：

- `docs/30-DeepSeek任务包/Batch-1-开发态稳定性与实时闭环.md`
- `docs/30-DeepSeek任务包/Batch-2-状态版本屏障与投影时序.md`
- `docs/30-DeepSeek任务包/Batch-4-线索证据链与防剧透.md`
- `docs/50-AI-Keeper-Platform/13-State世界状态系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/14-Transaction事务系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/15-Projection投影系统/DeepSeek计划.md`

## 全局禁止事项

1. 禁止让前端直接写 HP、SAN、背包、线索、地图位置或房间状态。
2. 禁止信任请求体里的 `character_id` 作为玩家身份。
3. 禁止在玩家端展示 owner token、Host-only 事件、KP note、隐藏真相。
4. 禁止靠前端过滤解决权限问题，权限必须在服务端过滤。
5. 禁止为了修 UI 绕过 `X-Room-Token`、Authorization 或 WS 鉴权。
6. 禁止把语音输入、动画、移动端增强放到核心链路之前。
7. 禁止一次性重做整套前端设计系统。
8. 禁止改动与玩家端无关的源码、测试产物或运行时数据。

## Batch Player-0：现状盘点与构建基线

### 目标

确认玩家端当前真实可运行状态，锁定乱码、构建错误、主流程断点和测试基线。

### 允许改动

- `docs/50-AI-Keeper-Platform/16-Player-Client玩家私人端/`
- 必要时新增测试记录文档
- 不改源码，除非盘点过程发现明显阻断且用户批准进入修复 Batch

### 任务

1. 运行 `git status`，确认工作区已有改动范围。
2. 检查 `src/client/src/App.tsx`、`navigation.ts`、`pages/Player*.tsx`、`components/Player*.tsx` 的乱码和语法风险。
3. 检查玩家端导入路径：`../api`、`../ws`、`shared/api`、`shared/ws` 是否一致。
4. 检查后端接口是否与前端调用一致，重点是 `clue_id/id`、action status、room status、stateVersion。
5. 记录当前 `npm run build` 是否能通过，以及失败首因。

### 验收命令

```powershell
cd src/client
npm run build
```

```powershell
python -m pytest tests/server/test_character_join_import.py tests/server/test_player_intent.py tests/server/test_reconnect.py -q
```

### 预期结果

得到一份可执行问题清单：哪些是文案乱码，哪些是类型或语法阻断，哪些是服务端安全或状态链路缺口。

## Batch Player-1：中文文案与页面可用性修复

### 目标

先让玩家端主要页面可读、可构建、可手动操作，不改变产品结构。

### 允许改动

- `src/client/src/App.tsx`
- `src/client/src/navigation.ts`
- `src/client/src/pages/PlayerJoinPage.tsx`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/pages/PlayerCharacter.tsx`
- `src/client/src/pages/PlayerInventory.tsx`
- `src/client/src/components/PlayerTerminal.tsx`
- `src/client/src/components/TacticalButtons.tsx`
- `src/client/src/components/VoiceInput.tsx`

### 任务

1. 修复玩家端触达页面的历史乱码文案。
2. 修复明显破坏 TSX 解析的字符串和标签问题。
3. 保留现有 Bauhaus UI 样式，不重做布局。
4. 为主要错误提示统一可读中文：未登录、房间不存在、token 无效、加入失败、提交失败、网络断开。
5. 保留语音输入，但确保语音失败时文本输入仍可用。

### 验收命令

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不改后端业务逻辑。
- 不新增大规模 UI 框架。
- 不把文案修复和权限修复混在一个提交里。

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

1. 前端 join 表单明确四种角色来源只能选一种。
2. 入房成功后保存服务端返回的 `player_token`，不要使用前端自造 token 覆盖正式 token。
3. 增加账号角色恢复入口，调用 `/api/player/me/characters` 和 restore-session。
4. 服务端继续校验 account ownership，不能恢复他人角色。
5. 加入 active 房间时显示 `pending_approval`，不直接当作已可行动。
6. 明确 localStorage 身份槽是开发态便利，不作为长期安全方案。

### 验收命令

```powershell
python -m pytest tests/server/test_character_join_import.py tests/server/test_room_security.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不允许前端提交 `character_id` 来绑定身份。
- 不允许复制其他账号角色。
- 不允许无登录绕过账号归属策略。

## Batch Player-3：等待室 ready、队内消息与开局跳转

### 目标

稳定等待室实时闭环：玩家加入、ready、聊天、Host 开局、玩家进入行动页。

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
2. `s2c_room_lobby_snapshot` 到达后刷新成员和 ready 状态。
3. `s2c_team_message` 去重逻辑保留，失败时撤销本地消息。
4. Host start 后 Player 自动跳转行动页，手动按钮作为兜底。
5. 轮询兜底只作为 WS 异常时刷新，不制造重复跳转。
6. ready 在 active 后的展示语义与 pending approval 区分清楚。

### 验收命令

```powershell
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_player_intent.py tests/server/test_ws_auth.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不为了 ready 同步直接修改 characters 表绕过 Engine/Room 口径。
- 不把队内消息发进 AI 裁决链路。

## Batch Player-4：行动终端与事务反馈

### 目标

让玩家提交行动后的等待、排队、结算、完成、失败反馈可理解，并和 Transaction 状态一致。

### 允许改动

- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/components/TacticalButtons.tsx`
- `src/client/src/components/VoiceInput.tsx`
- `src/server/player/router_player.py`
- `src/server/player/router_reconnect.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_reconnect.py`
- 必要时新增前端状态单测

### 任务

1. 统一 action 状态：idle、submitting、queued、batched、resolving、resolved、rejected、timeout。
2. 所有行动提交带 `action_id`，重复点击不生成多条有效行动。
3. 对 202、409、401、403、429、500 做不同 UI 文案。
4. `s2c_action_queued`、`s2c_action_completed`、`s2c_public_observation` 驱动 UI 状态。
5. 接入 `/api/player/actions/{action_id}`，用于刷新或 WS 断开后的状态查询。
6. 道具主张成功后只展示本人 inventory patch，失败显示服务端原因。

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

## Batch Player-5：WS、重连与 stateVersion barrier

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

1. PlayerWS 暴露连接状态：connecting、open、closed、reconnecting。
2. 页面在刷新或 WS 失败后调用 `/api/player/reconnect`。
3. recent_events 只按服务端已过滤结果恢复 UI。
4. pending_actions 恢复到 action 状态机。
5. `s2c_state_patch` 支持 `schemaVersion`、`baseStateVersion`、`stateVersion`、`actionId`。
6. 当前版本相同则应用 patch，旧版本丢弃，未来版本缓冲并调用 `/api/player/sync`。
7. `/api/player/sync` 结果覆盖 snapshot 后，再按版本应用仍有效的缓冲 patch。
8. lastSequence 可以跳号，跳号不代表要显示不可见事件。

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

- 不让 Player 忽略版本号直接覆盖状态。
- 不把 Host-only 或他人 player-only 事件发到前端后再隐藏。
- 不把 sequence 跳号当成安全错误。

## Batch Player-6：角色、背包、线索、日志、地图

### 目标

把玩家私人资源面板和服务端权威读模型对齐，避免展示过期状态或越权内容。

### 允许改动

- `src/client/src/pages/PlayerCharacter.tsx`
- `src/client/src/pages/PlayerInventory.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/server/player/router_player.py`
- `src/server/player/router_clues.py`
- `src/server/player/router_objectives.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_map.py`
- `tests/server/test_player_runtime_state.py`
- `tests/server/test_clues.py`
- `tests/server/test_archive.py`
- 相关 map 测试

### 任务

1. `/api/player/character` 当前数值优先 runtime state，角色技能和背景保留角色卡基线。
2. PlayerCharacter 展示 Host HUD 一致的 HP/SAN/MP/Luck。
3. PlayerInventory 统一线索字段，使用 `clue_id` 作为分享接口 id。
4. 线索分享成功后重新拉取 `/api/player/clues`，不只做本地改值。
5. Player archive 过滤复用 Projection 可见性口径。
6. 地图无 token 或 token 不属于房间时不返回敏感地图内容。
7. 地图移动失败展示非法原因，成功等待投影刷新。

### 验收命令

```powershell
python -m pytest tests/server/test_player_runtime_state.py tests/server/test_clues.py tests/server/test_archive.py tests/server/test_room_security.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不让玩家端修改自己的 runtime 数值。
- 不把未发现地图节点、未获得线索或他人背包放进响应。
- 不用前端字段隐藏替代服务端过滤。

## Batch Player-7：语音、战术、移动端体验

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

1. 语音录制失败、权限拒绝、STT 未配置时提示文本输入。
2. 语音转写结果可编辑，再选择发队内消息或提交行动。
3. 战术按钮禁用状态、loading 状态和失败提示清晰。
4. 玩家端底部 tab 在移动端不遮挡输入框。
5. 关键按钮支持键盘操作和基础 aria label。
6. 长文本消息和日志不撑破容器。

### 验收命令

```powershell
cd src/client
npm run build
npm run test
```

### 禁止事项

- 不把语音作为唯一行动输入方式。
- 不在前端根据按钮类型直接结算战斗或追逐。
- 不引入大型移动端框架。

## Batch Player-8：端到端验收与回归

### 目标

验证玩家端与核心链路完整闭环，确保文档承诺、代码行为和测试命令一致。

### 手动验收流程

1. Host 登录并创建房间。
2. Player A 登录，加入房间并选择角色。
3. Player B 登录，加入房间并选择角色。
4. 两名玩家在等待室互相可见，并发送队内消息。
5. 两名玩家 ready。
6. Host 开始游戏。
7. 两名玩家进入行动终端。
8. Player A 提交自由行动，Player B 提交另一个行动。
9. Transaction 进入 resolving，Host 收到公共演出。
10. Player A 只收到自己可见的私密结果和 party 公共叙事。
11. Player B 不收到 Player A 的私密 patch。
12. Player A 刷新页面，通过 reconnect 恢复 pending 或 completed 状态。
13. Player A 查看角色、背包、线索、地图、日志，内容均为授权视角。

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

- 玩家主链路可完整走通。
- 无 Host-only 或他人 player-only 泄露。
- 玩家端刷新和断线后状态一致。
- 前端构建通过。
- 相关后端测试通过。

## 与其他模块接口

| 模块 | Player Client 依赖 | 对方期望 |
| --- | --- | --- |
| Room | 房间状态、等待室、开局跳转 | 玩家端不承载房间生命周期裁决 |
| User | account token、player token、身份槽 | 玩家端不信任本地身份声明 |
| Channel | 队内消息、事件流 | 队内消息不进入 AI 裁决 |
| Rule | 技能检定、战术动作 | 玩家端只提交 intent |
| Character | 角色卡基线、builder、上传解析 | 当前状态由 State 覆盖 |
| Clue | 线索归属和分享 | 前端不自行公开线索 |
| Scene/Map | 地图可见范围和移动 | 地图移动走 intent |
| Journal | 玩家日志和回放 | 查询必须复用可见性过滤 |
| AI-Keeper | 行动建议和叙事结果 | 玩家端不接收隐藏真相 |
| State | runtime state、stateVersion、sync | 玩家端实现版本屏障 |
| Transaction | action 状态和幂等 | 玩家端展示事务状态，不决定事务 |
| Projection | WS、reconnect、archive 可见事件 | 玩家端不承担最终安全过滤 |
| Host Client | 开局和公共舞台 | 玩家端不读取 Host-only 视角 |
| Voice/Media | STT 能力 | 语音为增强，文本为主路径 |
| Safety | 防剧透、安全边界 | 玩家端不能展示未授权内容 |
