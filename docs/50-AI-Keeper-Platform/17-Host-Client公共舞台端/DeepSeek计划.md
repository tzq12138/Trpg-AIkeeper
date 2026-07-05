# Host Client 公共舞台端 DeepSeek 计划 V2.0

## 执行目标

把 Host Client 整理成可构建、可鉴权、可审计、可恢复的公共舞台端。第一轮优先保证 Host 主链路：创建房间、等待室 ready、开局、进入 Stage、显示 HUD、接收 reveal、监管地图、处理遭遇、查看日志。

本计划只处理 Host 前端和必要后端接口，不让 Host 前端承担规则裁决、AI 生成或权威状态写入。涉及核心链路的问题必须回看：

- `docs/30-DeepSeek任务包/Batch-1-开发态稳定性与实时闭环.md`
- `docs/30-DeepSeek任务包/Batch-2-状态版本屏障与投影时序.md`
- `docs/50-AI-Keeper-Platform/01-Room团房间系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/13-State世界状态系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/14-Transaction事务系统/DeepSeek计划.md`
- `docs/50-AI-Keeper-Platform/15-Projection投影系统/DeepSeek计划.md`

## 全局禁止事项

1. 禁止在 Host 前端计算规则成功失败、伤害或状态变更结果。
2. 禁止让 Host 前端直接写角色 HP、SAN、背包、线索或世界真相。
3. 禁止把 Player-only payload、player token、owner token 写入 public export 或 Player 可见事件。
4. 禁止靠前端隐藏字段保护 Host-only 内容。
5. 禁止为了修舞台展示放宽 Host REST 或 Host WS 鉴权。
6. 禁止一次性重做整套视觉设计。
7. 禁止把 database 占位面板包装成已完成资料库。
8. 禁止删除历史事件或检查点来规避恢复问题。

## Batch Host-0：现状盘点与构建基线

### 目标

确认 Host 前端和后端当前真实状态，先锁定乱码、TSX 构建阻断、鉴权缺口和主流程断点。

### 允许改动

- `docs/50-AI-Keeper-Platform/17-Host-Client公共舞台端/`
- 不改源码，除非用户确认进入修复 Batch

### 任务

1. 运行 `git status`，确认工作区已有改动。
2. 检查 `HostCreate.tsx`、`HostLobby.tsx`、`HostStage.tsx`、Host components 的乱码和语法风险。
3. 检查 Host REST 调用是否都带 `X-Owner-Token` 或 Authorization。
4. 检查 Host WS 的 owner token、account token、lastSequence 现状。
5. 检查 HostStage 消费的事件名与后端发送的 frame 是否一致。
6. 跑前端 build，记录首个阻断点。
7. 跑 Host 相关后端测试，记录失败来源。

### 验收命令

```powershell
cd src/client
npm run build
```

```powershell
python -m pytest tests/server/test_host.py tests/server/test_ws_auth.py tests/server/test_host_room_lifecycle.py -q
```

### 预期结果

得到一份分层问题清单：文案乱码、TSX 语法、Host 鉴权、事件协议、Room start、地图/遭遇审计分别归类。

## Batch Host-1：中文文案与前端构建恢复

### 目标

先让 Host 端主要页面可读、可构建、可进入主流程，不改变业务边界。

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

### 任务

1. 修复 Host 触达页面和组件的历史乱码。
2. 修复损坏的字符串、标签、confirm 文案、placeholder。
3. 保留现有布局和 Bauhaus 风格。
4. 把 database tab 明确为占位或临时隐藏。
5. 为 HostCreate、HostLobby、HostStage、Map、Logs、Encounter 增加可读错误提示。
6. 保证 `npm run build` 通过。

### 验收命令

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不改后端逻辑。
- 不新增大型 UI 依赖。
- 不在文案修复中顺手重构事件协议。

## Batch Host-2：Host 鉴权与入口闭环

### 目标

让 HostCreate、HostLobby、HostStage 的 REST/WS 鉴权口径一致，owner token、owner account、admin 都有明确路径。

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

### 任务

1. HostCreate 要求 host/admin 登录，player 显示无权限。
2. owner token 保存到当前身份槽，切换身份后不串房间。
3. Host REST 支持 `X-Owner-Token` 和 Authorization owner/admin。
4. Host WS 设计安全账号鉴权路径，不只依赖 query owner token。
5. 错 token、无 token、普通 player 访问 Host REST/WS 均失败。
6. HostLobby 缺 owner token 时提供回到创建/登录路径。

### 验收命令

```powershell
python -m pytest tests/server/test_ws_auth.py tests/server/test_room_security.py tests/server/test_host_room_lifecycle.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不把 owner token 暴露给 Player API。
- 不把 account role 只放在前端判断。
- 不为了方便把 Host WS 改成无鉴权。

## Batch Host-3：等待室与开局同步

### 目标

修复 HostLobby、Room start 和 PlayerLobby 之间的开局同步，确保 Host 开局后双方状态一致。

### 允许改动

- `src/client/src/pages/HostLobby.tsx`
- `src/server/router_rooms.py`
- `src/server/player/router_player.py`
- `tests/server/test_host_room_lifecycle.py`
- `tests/server/test_rooms.py`
- `tests/server/test_player_intent.py`

### 任务

1. HostLobby 使用 room snapshot 展示玩家、调查员、ready、pending approval。
2. 普通 start 保持至少一名玩家和 ready 检查。
3. force_start 只通过显式按钮触发，UI 展示未 ready 玩家名单。
4. 修复 start active snapshot 中剧本标题来源，避免变量异常被吞掉。
5. 开局后 Host 进入 Stage，PlayerLobby 收到 active snapshot 并进入 PlayerActionPage。
6. HostLobby 轮询和 WS 不重复制造状态闪烁。

### 验收命令

```powershell
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_rooms.py tests/server/test_player_intent.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不取消 ready 检查。
- 不把 force_start 设为默认路径。
- 不在 Host 前端直接修改玩家 ready。

## Batch Host-4：Stage 事件 adapter 与 HUD 稳定

### 目标

收口 HostStage 的事件消费，让标准 `EngineEvent` 和 Host UI frame 有清楚边界，并稳定 HUD 初始化和刷新。

### 允许改动

- `src/client/src/pages/HostStage.tsx`
- `src/client/src/shared/types.ts`
- `src/server/host/router_host.py`
- `src/server/host/host_store.py`
- `src/server/host/hud_builder.py`
- `tests/server/test_host.py`
- `tests/server/test_events.py`
- `tests/server/test_projection.py`

### 任务

1. 建立 Host event adapter：标准 `s2c_*` 事件先规范化，再进入 UI 状态。
2. 保留 `host_state_update` 等 UI frame，但说明它们只服务 Host UI，不是权威事件。
3. HUD 初始加载优先走 `/api/host/{room_id}/hud`，WS 首帧作为实时更新。
4. `s2c_reveal_transaction` 解析 roll、narrative_text、summaryText。
5. `s2c_public_observation`、`s2c_team_message` 进入公共叙事流。
6. `s2c_map_*` 和 `s2c_encounter_*` 只触发对应面板刷新。
7. HostStore 继续丢弃 `PRIVATE_EVENTS`。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_events.py tests/server/test_projection.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不把 `s2c_state_patch` 直接显示在 Host 公共舞台。
- 不让 Host 前端修改 reveal transaction payload。
- 不新增未注册的 `s2c_*` 事件。

## Batch Host-5：地图与遭遇操作审计

### 目标

让 Host map 和 encounter 操作从“可用接口”升级为“有鉴权、有状态、有事件、有审计”的主持操作。

### 允许改动

- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/components/EncounterPanel.tsx`
- `src/server/host/router_host.py`
- `src/server/map_persistence.py`
- `src/server/encounter_persistence.py`
- `src/server/events/event_log.py`
- `tests/server/test_host.py`
- 相关 map/encounter 测试，必要时新增

### 任务

1. Host map full 保持 Host-only。
2. reveal/hide 节点写入 actor、reason、visible、nodeId。
3. force move 校验 character 属于 room，target node 属于 room map。
4. map 操作发事件并写可查日志。
5. encounter confirm/reject/next/resolve/npc 全部校验 room 归属。
6. NPC 创建后发 encounter updated 或返回前端刷新所需状态。
7. Host 前端展示操作 pending、成功和失败原因。

### 验收命令

```powershell
python -m pytest tests/server/test_host.py tests/server/test_event_log.py tests/server/test_room_security.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不把 Host full map payload 广播给 Player。
- 不允许移动其他房间角色。
- 不让 encounter 操作绕过日志和鉴权。

## Batch Host-6：日志、检查点与导出安全

### 目标

稳定 Host 日志面板，保证完整主持视角和 Player/public 视角隔离。

### 允许改动

- `src/client/src/components/HostLogsPanel.tsx`
- `src/server/router_archive.py`
- `src/server/events/event_log.py`
- `src/server/export.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`
- `tests/server/test_projection_visibility.py`

### 任务

1. Host timeline 只允许 owner/admin。
2. timeline 支持 event_type、keyword、limit。
3. 单条事件详情能打开和关闭，payload 可读。
4. checkpoint create/list/restore 全部鉴权。
5. restore 前端二次确认，后端记录 `s2c_checkpoint_restored`。
6. public export 复用 Projection 可见性口径，不含 Host-only 和 player-only 私密。
7. full export 脱敏 owner token、player token。

### 验收命令

```powershell
python -m pytest tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_projection_visibility.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不把 Host timeline 接口开放给 Player。
- 不把 full export 当 public 战报下载。
- 不通过删除 events 实现恢复。

## Batch Host-7：端到端验收

### 目标

验证 Host 公共舞台端与核心跑团链路协同正确。

### 手动验收流程

1. Host/admin 登录。
2. Host 创建房间并选择剧本。
3. Player A 和 Player B 加入等待室。
4. Host 看到玩家列表和 ready 状态。
5. 两名玩家 ready。
6. Host 正常开局。
7. Host 进入 Stage，看到 HUD 和队列状态。
8. Player 提交行动。
9. Host 收到 reveal transaction 和公共叙事。
10. Host 不显示玩家私密 patch。
11. Host 查看地图全图，揭示一个节点，Player 只看到授权结果。
12. Host 确认一个遭遇，推进下一轮，再结束。
13. Host 创建检查点，导出 public markdown 和 full json。

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

- Host 主流程可走通。
- Host REST/WS 权限清晰。
- Host Stage 可展示公共演出和 HUD。
- Host 不泄露 player-only 私密内容。
- 地图、遭遇、日志、检查点操作有审计路径。
- 前端构建通过。

## 与其他模块接口

| 模块 | Host Client 依赖 | 对方期望 |
| --- | --- | --- |
| Room | 创建房间、等待室、开局、force_start | Host 不绕过生命周期状态机 |
| User | owner token、account token、host/admin role | Host 前后端都必须鉴权 |
| Channel | 队内消息和公共事件展示 | Host 不把队内消息当规则行动 |
| Rule | reveal steps、遭遇动作结果 | Host 不计算规则结果 |
| Character | 玩家姓名、调查员名、runtime 状态 | HUD 只读展示 |
| Scene/Map | Host full map、揭示、移动 | full map 不给 Player |
| Timeline | 当前回合、跳过、重试 | Host 只触发授权操作 |
| Journal | timeline、checkpoint、export | Host 查询完整视角，public 严格脱敏 |
| AI-Keeper | 公共叙事、遭遇建议、氛围建议 | Host 可确认建议，不让 AI 直接公开真相 |
| State | runtime state、map/encounter state | Host 操作需经服务端写入和审计 |
| Transaction | reveal transaction、延迟私密释放 | Host 播放和 ACK，不改结果 |
| Projection | Host WS、party/host 事件 | Host 不接收 player-only 内容 |
| Player Client | ready、玩家行动、私密结果 | Host 只看授权摘要和公共舞台 |
| Safety | 防剧透、可见性边界 | Host-only 内容不能进入 Player 视角 |
