# Projection 投影系统 DeepSeek 计划 V2.1

## 执行目标

把 Projection 收口为 AI-Keeper 的“分层可见性与事件投递层”。

本轮优先修四类问题：

1. 统一可见性与 payload 裁剪；
2. 修断线补发、snapshot、public replay / export 的泄露风险；
3. 补 `s2c_state_patch` 的版本契约与投影时序；
4. 固化 Host frame、ReleaseGate、direct `events` write path 的模块边界。

当前阶段口径：

`P0 主链路 + 分层可见性与事件投递风险识别版`

## 全局禁止事项

1. 禁止把 Host-only 事件作为 public 事件返回给玩家或导出给 public。
2. 禁止把 `player` audience 事件广播给所有玩家。
3. 禁止依赖前端本地过滤来兜底私密信息安全。
4. 禁止在 Projection 层改写规则结果或世界状态。
5. 禁止在 State 落库前下发 `s2c_state_patch`。
6. 禁止继续使用 `audience != 'player'` 近似 public 视图。
7. 禁止把所有 `system` 事件默认视为玩家可见。
8. 禁止把 Host UI frame 当成 `events` 的权威来源。
9. 禁止让 Projection 自己决定 ReleaseGate 的释放时机。
10. 禁止为了“统一”把审计事件全部改成实时广播。

## Batch Projection-0：现状盘点与回归基线

### 目标

先把现状跑清楚，锁定哪些路径会泄露、哪些路径会跳过统一 helper。

### 允许改动

- `tests/server/test_projection.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_ws_auth.py`
- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`
- `tests/server/test_events.py`
- 必要时新增 `tests/server/test_projection_visibility.py`

### 任务

1. 补 Player WS catch-up 不应拿到 Host-only 事件的测试。
2. 补 `/api/player/reconnect` 普通 missed events 不应泄露 Host-only / other-player private 的测试。
3. 补 reconnect snapshot 不应返回整房间 `events` 的测试。
4. 补 `get_public_events()` 不应返回 Host-only 事件的测试。
5. 补 public export 不应返回 Host-only / private 的测试。
6. 盘点所有真实发出的 `s2c_*` 事件与 registry / 后端类型 / 前端类型的一致性测试。
7. 在回执中列出所有 direct `log_event()` / direct `events` write path，并初步标记为 `realtime` 或 `audit-only`。

### 验收命令

```powershell
python -m pytest tests/server/test_projection.py tests/server/test_reconnect.py tests/server/test_ws_auth.py tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_events.py -q
```

## Batch Projection-1：统一事件注册、Envelope 与 DTO 契约

### 目标

让真实发出的事件、标准事件信封和前后端类型口径对齐，并把 Projection DTO 契约补完整。

### 允许改动

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/client/src/shared/types.ts`
- `tests/server/test_events.py`
- `tests/server/test_projection.py`

### 任务

1. 盘点当前代码中所有实际 emit 的 `s2c_*` 事件。
2. 补齐 `s2c_turn_resolved`、checkpoint 相关事件等缺口。
3. 修正 registry 中本轮触达事件的说明、domain、默认 audience、最小 payload 字段。
4. 明确 `EngineEventEnvelopeDTO`、`ProjectionRequestDTO`、`HostFrameDTO`、`PublicEventDTO` 等最小字段契约。
5. 前后端 `EngineEventType` 对齐。

### 验收命令

```powershell
python -m pytest tests/server/test_events.py tests/server/test_projection.py -q
```

如改动前端共享类型，再补跑：

```powershell
cd src/client
npm run build
```

## Batch Projection-2：统一可见性 helper 与 payload 裁剪

### 目标

让 live / catch-up / reconnect / archive / public replay / public export 复用同一套“能不能看 + 看什么”的后端逻辑。

### 允许改动

- `src/server/engine/projection.py`
- `src/server/events/event_log.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/server/export.py`
- `src/server/player/router_reconnect.py`
- `tests/server/test_projection_visibility.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`

### 任务

1. 定义统一 helper：
   - `can_view_event(...)`
   - `build_event_view(...)` 或 `sanitize_event_payload(...)`
2. 不再只做 bool 过滤，必须支持 public / player / host / admin 的不同 payload 视图。
3. `audience=player` 时，若无法确认 owner，默认拒绝对普通玩家可见。
4. `system` 默认不 public，只有 `system_safe` 白名单可见。
5. `get_public_events()`、player archive、public export 都复用同一 public 视图裁剪逻辑。
6. 明确 public export 字段禁出名单，至少覆盖 token、host-only payload、hidden truth、raw prompt/raw response、debug payload。
7. 回执中必须明确：
   - `s2c_turn_resolved` 是否只返回安全摘要；
   - `s2c_checkpoint_created` 是否排除了 raw snapshot / path / debug payload；
   - `s2c_checkpoint_restored` 是否保持 `audit-only`。

### 验收命令

```powershell
python -m pytest tests/server/test_projection_visibility.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不把所有 `system` 事件直接开放给玩家。
- 不把 Owner/Admin 完整时间线误改成玩家可见口径。

## Batch Projection-3：Player WS catch-up、reconnect 与 `player_sequences`

### 目标

修正断线恢复主链路，写清并落实 `player_sequences` 的 delivery cursor 语义。

### 允许改动

- `src/server/main.py`
- `src/server/player/router_reconnect.py`
- `src/server/host/ws_manager.py`
- `src/client/src/shared/ws.ts`
- `tests/server/test_ws_auth.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_projection_visibility.py`

### 任务

1. Player WS catch-up 必须复用统一 helper。
2. reconnect missed events 路径必须复用统一 helper。
3. reconnect snapshot 路径的 `recent_events` 必须只返回玩家可见事件。
4. 在回执中明确：
   - `last_delivered_sequence` 代表什么；
   - 何时更新；
   - 为什么玩家视图会出现 sequence 跳号；
   - 跳号不代表数据丢失。
5. 回执中还必须明确：
   - WS catch-up 后是否更新 `player_sequences`；
   - reconnect 后是否更新 `player_sequences`；
   - snapshot 分支是否推进到 room max sequence。
6. 如本轮仍不做 per-device ACK，也必须把限制写进回执。

### 验收命令

```powershell
python -m pytest tests/server/test_ws_auth.py tests/server/test_reconnect.py tests/server/test_projection_visibility.py -q
```

如改动前端 WS 消费，再补跑：

```powershell
cd src/client
npm run build
```

## Batch Projection-4：状态 patch 版本契约与投影时序

### 目标

与 13-State、14-Transaction 对齐，确保 patch 有版本、Projection 晚于 State 落库、ReleaseGate 不再由 Projection 擅自决定。

### 允许改动

- `src/server/engine/state_service.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/projection.py`
- `src/server/models.py`
- `src/client/src/shared/ws.ts`
- `src/client/src/pages/PlayerActionPage.tsx`
- `tests/server/test_state_service.py`
- `tests/server/test_state_service_consistency.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_projection.py`

### 任务

1. `s2c_state_patch` 增加 `schemaVersion / baseStateVersion / stateVersion / actionId`。
2. 明确 player-private patch 与 party-safe patch 的边界。
3. `resolution_pipeline` 调整为先 State、后 Projection。
4. Projection 不再自己决定 release gate，等待 Transaction 给出可释放结果。
5. Player 端对旧 patch / 跳版本 patch 至少具备基础屏障和 full sync 兜底。

### 验收命令

```powershell
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_resolution_pipeline.py tests/server/test_projection.py -q
```

如改动前端页面或共享 WS 类型，再补跑：

```powershell
cd src/client
npm run build
```

## Batch Projection-5：direct `events` write path 收口与 Host frame 边界

### 目标

把所有写 `events` 的路径分类清楚，并明确 Host frame 只是显示协议。

### 允许改动

- `src/server/engine/projection.py`
- `src/server/events/event_log.py`
- `src/server/engine/engine.py`
- `src/server/player/router_player.py`
- `src/server/router_rooms.py`
- `src/server/router_admin.py`
- `src/server/host/router_host.py`
- `tests/server/test_projection.py`
- `tests/server/test_events.py`
- `tests/server/test_player_intent.py`

### 任务

1. 盘点所有 direct `log_event()` / direct `events` write path。
2. 回执中逐条标记：
   - `realtime`
   - `audit-only`
3. 对应该实时同步的事件，统一通过 `ProjectionDispatcher.emit()` 或等价统一入口。
4. 明确 Host frame 只来自标准 `EngineEvent` 翻译，不写回 `events`。
5. 避免 Host frame 漂移成另一套事实源。
6. 回执中必须逐条列出：
   - 哪些路径改走 `ProjectionDispatcher.emit()`；
   - 哪些路径保留 `EventLog.log_event()`；
   - 哪些是 `audit-only`；
   - `ProjectionBuilder` 是否保留，以及职责边界是什么。

### 验收命令

```powershell
python -m pytest tests/server/test_projection.py tests/server/test_events.py tests/server/test_player_intent.py -q
```

### 禁止事项

- 不为了“统一”把 `s2c_checkpoint_restored`、`host_force_move` 这类审计事件全部广播给玩家。

## Batch Projection-6：SpoilerGuard 安全网与审计

### 目标

让投影层最后一道安全网有测试、有审计、有失败可观测性，但不被误用成唯一防线。

### 允许改动

- `src/server/engine/projection.py`
- `src/server/engine/spoiler_guard.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_projection.py`
- 必要时新增 `tests/server/test_projection_spoiler.py`

### 任务

1. 测试 player / party payload 命中敏感内容时会被替换。
2. 测试 host-only payload 不会套用 player 规则误拦截。
3. 测试 SpoilerGuard 失败不阻断已落库事实，但会留下可查日志。
4. 审计字段至少覆盖 `actionId / eventType / audience / characterId` 方向。
5. 在回执中说明：结构化 truth、hidden clue、hidden node 的源头约束仍由上游负责。

### 验收命令

```powershell
python -m pytest tests/server/test_spoiler_guard.py tests/server/test_projection.py tests/server/test_projection_spoiler.py -q
```

## Batch Projection-7：端到端主链路回归

### 目标

验证 Host、Player、reconnect、archive、export、State patch 一起工作时，所有人都只看到自己该看的内容。

### 手动验收流程

1. Host 创建房间并开局。
2. Player A、Player B 加入。
3. Player A 提交行动并获得私密结果。
4. Host 收到 reveal transaction / Host frame。
5. Player B 收不到 Player A 的 private patch。
6. Player A 断线重连，只补回 `party` 事件和自己的 `player` 事件。
7. Player B 断线重连，不补回 Player A 的 private 事件。
8. public replay 与 public export 不包含 Host-only payload。
9. 命中 SpoilerGuard 时，玩家看到的是安全文本，审计里能查到替换记录。

### 回归命令

```powershell
python -m pytest tests/server/test_projection.py tests/server/test_projection_visibility.py tests/server/test_reconnect.py tests/server/test_ws_auth.py tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_events.py tests/server/test_spoiler_guard.py tests/server/test_state_service.py tests/server/test_resolution_pipeline.py -q
```

如动到前端共享类型、WS 消费或相关页面，再补跑：

```powershell
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | Projection 依赖 | 对方应满足 |
| --- | --- | --- |
| 02-User | token、account、character 归属 | Projection 不信任前端自报身份 |
| 13-State | `stateVersion`、patch、snapshot | Projection 只下发已落库状态 |
| 14-Transaction | `actionId / turnId / transactionId / ReleaseGate` | Projection 不决定何时释放私密结果 |
| 11-Journal | `events.sequence`、回放与导出入口 | Journal 的 public / player 视图复用 Projection helper |
| 17-Host Client | Host frame 协议 | Host frame 来源于标准事件，不反向写事实 |
| 16-Player Client | `EngineEvent` 与版本屏障 | 客户端不承担最终权限过滤职责 |
| 21-Safety | SpoilerGuard 与审计 | Projection 只做末端安全网，不替代上游边界 |
