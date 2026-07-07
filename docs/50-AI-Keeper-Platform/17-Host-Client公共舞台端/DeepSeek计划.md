# Host Client 公共舞台端 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + Host 公共舞台可用性、鉴权与审计风险识别版`。
- 第一轮目标是把 Host 端修到“可构建、可鉴权、可投影、可恢复、可审计”的工程执行状态。
- DeepSeek 在本模块内不得把 Host Client 扩写成规则引擎、AI 真相层或世界状态直写入口。

## 执行目标

围绕现有代码真实锚点，完成以下收口：

1. Host 主链路稳定：`创建房间 -> Lobby -> start/force_start -> Stage -> 日志/恢复`；
2. Host 鉴权清晰：owner token、owner account、admin 有明确入口；普通 player 一律拒绝；
3. Host 协议清晰：标准 `EngineEvent` 与 Host UI frame 边界固定；
4. Host 安全边界清晰：不展示 `player-only` 私密 payload，不把 Host-only 内容导出给 public；
5. Host 特权操作清晰：地图、遭遇、restore、force_start、retry-turn 具备审计口径。

## 关键代码锚点

- `src/client/src/pages/HostCreate.tsx`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/HostStage.tsx`
- `src/client/src/components/HostSkeletonPanels.tsx`
- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/components/EncounterPanel.tsx`
- `src/client/src/navigation.ts`
- `src/client/src/shared/identity.ts`
- `src/server/router_rooms.py`
- `src/server/host/router_host.py`
- `src/server/host/host_store.py`
- `src/server/router_archive.py`
- `tests/server/test_ws_auth.py`
- `tests/server/test_host.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_room_security.py`
- `tests/server/test_archive.py`

## 全局禁止事项

1. 禁止在 Host 前端计算规则成功/失败、伤害、状态写入结果。
2. 禁止让 Host 前端直接改角色 HP/SAN、物品归属、线索真相、地图真相或世界状态。
3. 禁止把 `player-only` payload、`player_token`、`owner_token` 写入 public export、Player 可见事件或日志样例。
4. 禁止只靠前端“隐藏字段”保护 Host-only 内容。
5. 禁止为了让页面先能跑，放松 Host REST 或 Host WS 鉴权。
6. 禁止把 `database` 占位面板包装成已完成资料库。
7. 禁止用删除事件或删除 checkpoint 的方式“修复恢复问题”。
8. 禁止把当前 `retry-turn` 写成“完整回合重算已完成”。

## Batch Host-0：现状盘点与构建基线

### 目标

锁定当前 Host 模块真实问题清单，先确认构建阻塞、鉴权缺口和协议混乱点，不直接在本批次修代码。

### 允许改动

- `docs/50-AI-Keeper-Platform/17-Host-Client公共舞台端/`

### 核心任务

1. 跑 `git status`，确认工作区脏状态。
2. 检查 `HostCreate.tsx`、`HostLobby.tsx`、`HostStage.tsx`、Host 相关组件是否存在乱码或损坏字符串。
3. 检查 Host REST 是否统一支持 `X-Owner-Token` 或 `Authorization`。
4. 检查 Host WS 当前 owner token、owner account、admin、`lastSequence` 的真实现状。
5. 盘点 `HostStage.tsx` 当前消费的事件类型与 `router_host.py` 当前发出的 frame 类型。
6. 记录第一个前端 build 阻塞点和第一个后端测试阻塞点。

### 验收命令

```powershell
cd src/client
npm run build
```

```powershell
python -m pytest tests/server/test_host.py tests/server/test_ws_auth.py tests/server/test_host_room_lifecycle.py -q
```

### 回执必须说明

1. 是否真的存在中文乱码或 TSX 损坏；
2. Host WS 当前是否只靠 query `ownerToken`；
3. `lastSequence` 是否被 Host WS 真正消费；
4. 当前第一个 build 阻塞点是什么；
5. 本批次未修代码，只产出现状基线。

## Batch Host-1：中文可读性与前端构建恢复

### 目标

优先恢复 Host 触达页面与组件的可读性和可构建性，不改变业务边界。

### 允许改动

- `src/client/src/pages/HostCreate.tsx`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/HostStage.tsx`
- `src/client/src/components/HostSkeletonPanels.tsx`
- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/components/EncounterPanel.tsx`
- `src/client/src/navigation.ts`
- 必要时 `src/client/src/styles.css`

### 核心任务

1. 修复 Host 页面与组件中的中文乱码。
2. 修复损坏的字符串、标签、确认文案、placeholder 和错误提示。
3. 保持现有布局与局部视觉风格，不重做全局设计系统。
4. 明确 `database` tab 为“开发中/占位”，或在本轮暂时隐藏。
5. 给 HostCreate、HostLobby、HostStage、Map、Logs、Encounter 补最小可读错误反馈。
6. 保证 `npm run build` 通过。

### 验收命令

```powershell
cd src/client
npm run build
```

### 禁止事项

1. 不改后端逻辑。
2. 不引入大型新 UI 依赖。
3. 不在“修乱码”时顺手重构全站组件体系。

## Batch Host-2：Host 鉴权与入口闭环

### 目标

收紧 Host REST/WS 的 owner token、owner account、admin 鉴权路径，明确普通 player 和跨房间 owner token 必须失败。

### 允许改动

- `src/client/src/pages/HostCreate.tsx`
- `src/client/src/pages/HostLobby.tsx`
- `src/client/src/pages/HostStage.tsx`
- `src/client/src/shared/identity.ts`
- `src/server/host/router_host.py`
- `src/server/router_rooms.py`
- `tests/server/test_ws_auth.py`
- `tests/server/test_room_security.py`
- `tests/server/test_host_room_lifecycle.py`

### 核心任务

1. HostCreate 保持 host/admin 账号门槛。
2. 统一 Host REST 使用 `X-Owner-Token` 或 `Authorization` 的口径。
3. 明确 Host WS 支持 owner token、owner account、admin 三种授权方式。
4. 普通 `player_token` 请求 Host REST/WS 必须失败。
5. 跨房间 `owner_token` 请求 Host REST/WS 必须失败。
6. 如果短期仍保留 query `ownerToken`，必须补日志脱敏说明，并在回执中列明未完成的生产态风险。

### 验收命令

```powershell
python -m pytest tests/server/test_ws_auth.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py -q
```

```powershell
cd src/client
npm run build
```

### 回执必须说明

1. 是否新增了 owner account / admin Host WS 测试；
2. 普通 player token 请求 Host REST/WS 是否被覆盖测试；
3. 跨房间 owner token 是否被覆盖测试；
4. 本轮是否仅完成风险标注，还是完成了更安全的握手收口。

## Batch Host-3：Lobby 与开局同步

### 目标

稳定 HostLobby、Room start、PlayerLobby 之间的开局同步，并把 `force_start` 产品语义写死。

### 允许改动

- `src/client/src/pages/HostLobby.tsx`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_rooms.py`
- `tests/server/test_player_intent.py`

### 核心任务

1. HostLobby 准确显示成员、ready、pending approval。
2. 普通 start 保持最少 1 名玩家且 ready 的检查。
3. `force_start` 只通过显式按钮触发，UI 显示未 ready 玩家名单。
4. `force_start` 要求 `reason + confirm`，并写审计事件。
5. 修正开局后 Lobby/Stage/PlayerActionPage 的跳转与 snapshot 同步。
6. 避免轮询与 WS 双重刷新造成状态闪烁。

### 验收命令

```powershell
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py tests/server/test_player_intent.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

1. 不取消 ready 检查。
2. 不把 `force_start` 变成默认路径。
3. 不让 Host 前端直接修改玩家 ready 真相。

## Batch Host-4：Stage 协议收口与 HUD 稳定

### 目标

建立单一 HostEventAdapter 契约，区分标准事件和 Host UI frame，确保 Host 舞台只显示授权结果。

### 允许改动

- `src/client/src/pages/HostStage.tsx`
- `src/client/src/shared/types.ts`
- `src/server/host/router_host.py`
- `src/server/host/host_store.py`
- `src/server/host/hud_builder.py`
- `tests/server/test_host.py`
- `tests/server/test_events.py`
- `tests/server/test_projection.py`

### 核心任务

1. 固化“标准 `EngineEvent` -> HostEventAdapter -> HostFrameDTO -> HostStage”单一入口。
2. `host_state_update`、`scene_update`、`chat_message` 等 frame 只作为 UI 协议，不替代 `events`。
3. Host HUD 先走 `/api/host/{room_id}/hud`，WS 作为增量更新。
4. HostStage 正确处理 `s2c_reveal_transaction`、`s2c_public_observation`、`s2c_team_message`。
5. HostStage 不显示 `s2c_state_patch`、`s2c_private_notice`、`s2c_action_completed` 私密 payload。
6. Host ACK 只表示舞台播放进度，不承载规则结果。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_events.py tests/server/test_projection.py -q
```

```powershell
cd src/client
npm run build
```

### 回执必须说明

1. 是否为 HostStage 建立了明确 adapter；
2. `HostFrameDTO` 是否可追溯到 `sourceEventType/sourceSequence` 或 HUD API；
3. 私密事件是否仍会进入 Host 舞台；
4. `lastSequence` 是否在本批次被真正接上；若未接上，必须列为遗留项。

## Batch Host-5：地图与遭遇特权操作审计

### 目标

让 Host map/encounter 从“可调用接口”升级成“有鉴权、有审计、有边界”的特权操作。

### 允许改动

- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/components/EncounterPanel.tsx`
- `src/server/host/router_host.py`
- `src/server/map_persistence.py`
- `src/server/encounter_persistence.py`
- `src/server/events/event_log.py`
- `tests/server/test_host.py`
- 相关 map/encounter 测试

### 核心任务

1. `map/full` 保持 Host-only。
2. `map/reveal`、`map/hide`、`force_move` 统一记录 actor、target、reason、visible、stateVersion 或 eventSequence。
3. `force_move` 继续验证 character 和 node 都属于当前 room。
4. encounter confirm/reject/next-round/resolve/NPC 都验证 room 归属。
5. encounter reject、NPC 创建、resolve 都要有事件或审计痕迹。
6. Host 前端对这些操作给出 pending/成功/失败反馈。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_event_log.py tests/server/test_room_security.py -q
```

```powershell
cd src/client
npm run build
```

### 回执必须说明

1. `map/reveal` 是否已补统一审计；
2. `encounter/reject` 是否有事件或审计闭环；
3. `encounter/npc` 是否能触发前端一致刷新；
4. 审计字段是否对齐 `operation/roomId/actorAccountId/targetType/targetId/reason/stateVersion|eventSequence`。

## Batch Host-6：日志、checkpoint 与导出安全

### 目标

稳定 Host 日志面板、restore 语义和 public/full export 边界，避免 Host-only 内容泄露给 public。

### 允许改动

- `src/client/src/components/HostLogsPanel.tsx`
- `src/server/router_archive.py`
- `src/server/events/event_log.py`
- `src/server/export.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`
- `tests/server/test_projection_visibility.py`

### 核心任务

1. Host timeline 只允许 owner/admin 访问。
2. restore 必须 `confirm=true + reason`，并写 `s2c_checkpoint_restored`。
3. Player 不能看到 restore 原始审计 payload，如需提示应下发 party-safe 摘要。
4. `public export` 复用 Projection public view，不使用“`audience != player`”之类反向过滤。
5. `full export` 也继续脱敏 token、API key、secret、raw AI prompt/response。
6. `database` tab 如仍存在，不得借导出内容伪装成真实资料库。

### 验收命令

```powershell
python -m pytest tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_projection_visibility.py -q
```

```powershell
cd src/client
npm run build
```

### 回执必须说明

1. `public export` 是否明确排除了 owner/player token、账号敏感字段、Host-only reveal、全图、隐藏真相；
2. `full export` 是否仍不是数据库原样导出；
3. restore 是否写入了 `s2c_checkpoint_restored`；
4. Player 是否看不到 restore 原始审计 payload。

## Batch Host-7：端到端主链路回归

### 目标

验证 Host 公共舞台端与 Room、Player、Transaction、Projection、Journal 的主链路协同正确。

### 手动验收流程

1. Host/admin 登录。
2. Host 创建房间并选择剧本。
3. 两名玩家加入 Lobby。
4. Host 看见玩家列表和 ready 状态。
5. 玩家 ready。
6. Host 正常 start。
7. Host 进入 Stage，获得 HUD。
8. 玩家提交行动。
9. Host 看到 reveal/public 结果，但看不到玩家私密 patch。
10. Host 查看全图并公开一个节点，Player 只看到授权后的地图变化。
11. Host 确认一个遭遇，推进下一轮，再结束。
12. Host 创建 checkpoint，执行带 `confirm + reason` 的 restore。
13. Host 导出 `public markdown` 与 `full json`。

### 回归命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_ws_auth.py tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_projection.py -q
```

```powershell
cd src/client
npm run build
npm run test
```

### 预期结果

- Host 主链路可走通；
- Host REST/WS 权限清晰；
- Host Stage 只展示授权舞台内容；
- 地图、遭遇、restore、force_start、retry-turn 都有明确边界；
- `database` tab 不误导；
- Host 相关前端构建通过。

## 与其他模块接口要求

| 模块 | Host Client 依赖 | 对方期望 |
| --- | --- | --- |
| Room | 创建房间、Lobby、start/force_start | Host 不绕过房间生命周期状态机 |
| User | `owner_token`、owner account、admin | Host 前后端都必须鉴权 |
| Rule | reveal、遭遇建议 | Host 读结果，不算结果 |
| Character | 玩家公开状态、角色摘要 | HUD 只读展示 |
| Scene/Map | 全图、reveal、move | 全图不下发给 Player |
| Timeline | 当前回合、最小重试语义 | Host 不把舞台重试误写成事务重算 |
| Journal | timeline、checkpoint、restore、export | Host 完整视角与 public 视角严格分离 |
| AI-Keeper | 公共叙事、遭遇建议、氛围建议 | AI 不直接公开隐藏真相 |
| State | runtime state、地图/遭遇状态 | Host 操作必须经后端写入与审计 |
| Transaction | reveal、ACK、ReleaseGate | Host 只播放和确认演出进度 |
| Projection | Host/party 可见事件 | Host 不接 player-only 内容 |
| Player Client | ready、玩家行动、私密结果 | Host 只看公共与主持视角 |
| Safety | 防剧透、导出脱敏、审计边界 | Host-only 内容不能外泄 |
