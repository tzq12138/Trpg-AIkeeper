# Projection 投影系统 DeepSeek 计划 V2.0

## 执行目标

把 Projection 收口为 AI-Keeper 的分层可见性和事件投递层。第一轮优先修安全过滤、事件注册、状态 patch 版本、重连补发和公共导出，不做跨服务消息总线和复杂订阅 DSL。

## 全局禁止事项

1. 禁止把 Host-only 事件作为 public 事件返回给玩家。
2. 禁止把 player-only 事件广播给所有玩家。
3. 禁止依赖前端本地过滤来保护私密信息。
4. 禁止在 Projection 层修改规则结果或世界状态。
5. 禁止发送未经过 State 持久化的状态 patch。
6. 禁止新增未登记的 `s2c_*` 事件。
7. 禁止通过删除历史 events 解决重连泄露问题。
8. 禁止一次性重写全部 WS 架构。

## Batch Projection-0：现状盘点与测试基线

### 目标

固定当前 Projection、WS、reconnect、archive、export 的行为，先补能暴露泄露风险的测试。

### 允许改动

- `tests/server/test_projection.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_ws_auth.py`
- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`
- `tests/server/test_events.py`
- 必要时新增 `tests/server/test_projection_visibility.py`

### 任务

1. 写 Player WS catch-up 不应收到 host-only 事件的测试。
2. 写 `/api/player/reconnect` 普通补发不应返回 host-only 或他人 player 事件的测试。
3. 写 snapshot 路径不应返回全量 events 的测试。
4. 写 `get_public_events` 不应返回 host-only 的测试。
5. 写 public export 不应返回 host-only 的测试。
6. 写所有 emit 事件必须登记在 registry 和 `EngineEventType` 的测试。

### 验收命令

```powershell
python -m pytest tests/server/test_projection.py tests/server/test_reconnect.py tests/server/test_ws_auth.py tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_events.py -q
```

### 预期结果

测试能明确暴露当前缺口，或锁定已存在的安全行为。新增失败测试必须和后续 Batch 对应。

## Batch Projection-1：统一事件注册与 envelope

### 目标

让实际 `s2c_*` 事件、后端类型、前端类型和 registry 保持一致。

### 允许改动

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/client/src/shared/types.ts`
- `tests/server/test_events.py`
- `tests/server/test_events_bus.py`
- `tests/server/test_projection.py`

### 任务

1. 盘点代码中所有实际 emit 或写入的 `s2c_*` 事件。
2. 补齐 `s2c_turn_resolved`、checkpoint 相关事件等缺口。
3. 修正 registry 中文描述乱码，只修触达事件。
4. 为每个事件标注 domain、默认 audience、最小 payload 字段。
5. 后端 `EngineEventType` 与前端 `EngineEventType` 同步。
6. 测试保证 registry、后端 Literal、前端类型清单一致。

### 验收命令

```powershell
python -m pytest tests/server/test_events.py tests/server/test_events_bus.py tests/server/test_projection.py -q
```

前端类型变更后补跑：

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不改事件业务语义。
- 不删已有事件来让测试通过。

## Batch Projection-2：统一可见性过滤

### 目标

建立复用的服务端过滤函数，让 live、catch-up、reconnect、archive、export 使用同一套权限口径。

### 允许改动

- `src/server/engine/projection.py`
- `src/server/events/event_log.py`
- `src/server/host/ws_manager.py`
- `src/server/player/router_reconnect.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/server/export.py`
- `tests/server/test_projection_visibility.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`

### 任务

1. 增加 `can_view_event(event, viewer_role, character_id)` 或等价 helper。
2. 定义 host/player/party/system 的可见性白名单。
3. `audience="player"` 必须匹配 payload `characterId`、`character_id` 或持久目标字段；无法确认归属时默认不对普通玩家可见。
4. public events 只返回 party 和安全 system 事件，不返回 host-only。
5. public export 使用同一过滤，不再用 `audience != 'player'`。
6. player archive 使用同一过滤，不依赖散落的 payload 判断。

### 验收命令

```powershell
python -m pytest tests/server/test_projection_visibility.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不把所有 `system` 事件默认视为玩家可见。
- 不让前端做最终安全过滤。
- 不把 owner/admin 的完整 timeline 改成 player 口径。

## Batch Projection-3：Player WS catch-up 与 reconnect 修复

### 目标

修正断线补发路径，确保 Player 不因 WS 重连或 API reconnect 获得额外视角。

### 允许改动

- `src/server/main.py`
- `src/server/host/ws_manager.py`
- `src/server/player/router_reconnect.py`
- `src/client/src/shared/ws.ts`
- `tests/server/test_ws_auth.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_projection_visibility.py`

### 任务

1. `player_ws_endpoint` catch-up 查询后按可见性过滤。
2. `ConnectionManager.reconnect` 返回过滤后的 missed events。
3. `/api/player/reconnect` snapshot 路径过滤 `recent_events`。
4. `last_sequence` 仍返回房间最大 sequence，但客户端只收到可见事件；文档明确中间不可见事件会造成 sequence 跳号。
5. 评估 `player_sequences` 更新时机，至少保证 reconnect 后写入当前 max sequence。
6. PlayerWS 对乱序或跳号不崩溃，后续交给 stateVersion 屏障处理。

### 验收命令

```powershell
python -m pytest tests/server/test_ws_auth.py tests/server/test_reconnect.py tests/server/test_projection_visibility.py -q
```

前端改动后补跑：

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不把 Host-only 事件转成空 payload 后发给玩家。
- 不因为 sequence 跳号而补发不可见事件。

## Batch Projection-4：状态 patch 版本与投影时序

### 目标

与 State/Transaction 模块对齐，确保 patch 有版本且只在状态持久化后发送。

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

1. `StateService.apply_change` 返回 base/current state version。
2. `s2c_state_patch` payload 加 `schemaVersion`、`baseStateVersion`、`stateVersion`、`actionId`、`patches`。
3. 私密 patch 用 `audience="player"` 且带目标角色。
4. 公开 patch 只能包含 party 可见摘要或公共状态。
5. ResolutionPipeline 改为 State 持久化成功后再投影 patch 和 action completed。
6. PlayerWS 或 PlayerActionPage 实现基本版本屏障：旧 patch 丢弃，新 patch 可触发 `/api/player/sync`。

### 验收命令

```powershell
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_resolution_pipeline.py tests/server/test_projection.py -q
```

前端涉及 WS 或页面时补跑：

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不在 Projection 层伪造 state version。
- 不把私密角色数值作为 party patch 广播。

## Batch Projection-5：实时投递入口收口

### 目标

区分“只写日志”和“写日志并实时投递”，减少直接写 `events` 导致的实时缺口和口径分叉。

### 允许改动

- `src/server/engine/engine.py`
- `src/server/events/event_log.py`
- `src/server/engine/projection.py`
- `src/server/player/router_player.py`
- `src/server/router_rooms.py`
- `src/server/router_admin.py`
- `tests/server/test_engine.py`
- `tests/server/test_projection.py`
- `tests/server/test_player_intent.py`

### 任务

1. 盘点所有 `INSERT INTO events` 直接写入路径。
2. 对需要实时送达的事件改走 `ProjectionDispatcher.emit`。
3. 对只做审计的事件保留 `EventLog.log_event`，但标注 audience 和可见性。
4. `s2c_action_queued`、`s2c_ready_toggled`、room lobby snapshot 等实时事件口径统一。
5. `ProjectionBuilder` 决定保留还是并入 Dispatcher；保留时必须被测试覆盖。

### 验收命令

```powershell
python -m pytest tests/server/test_engine.py tests/server/test_projection.py tests/server/test_player_intent.py tests/server/test_events.py -q
```

### 禁止事项

- 不为追求统一而让审计事件全部实时广播。
- 不在没有调用方测试的情况下改变事件 payload 字段名。

## Batch Projection-6：SpoilerGuard 安全网回归

### 目标

让 Projection 的最后安全网有测试、有审计、有失败观测，不替代上游防剧透。

### 允许改动

- `src/server/engine/projection.py`
- `src/server/engine/spoiler_guard.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_projection.py`
- 必要时新增 `tests/server/test_projection_spoiler.py`

### 任务

1. 测试 player/party payload 中命中敏感 label 会被替换。
2. 测试 host payload 不被 player 规则误拦截。
3. 测试 SpoilerGuard 异常不会中断投影，但会记录日志。
4. 补充 audit 中 actionId、eventType、audience、characterId 等字段方向。
5. 明确结构化 ID 和名称泄露仍由上游 AI/Clue/State 控制。

### 验收命令

```powershell
python -m pytest tests/server/test_spoiler_guard.py tests/server/test_projection.py tests/server/test_projection_spoiler.py -q
```

### 禁止事项

- 不把安全网作为唯一防剧透机制。
- 不在扫描失败时静默输出未审计的敏感 payload。

## Batch Projection-7：端到端验收

### 目标

验证主链路投影安全：Host、Player、重连、日志和导出都只看到自己应见内容。

### 手动验收流程

1. Host 创建房间并启动。
2. Player A 和 Player B 加入。
3. Player A 提交行动并获得私密 patch。
4. Host 收到 reveal transaction。
5. Player B 不收到 Player A 的私密 patch。
6. Player A 断线重连，只补回 party 事件和自己的 player 事件。
7. Player B 断线重连，不补回 Player A 私密事件。
8. `events/public` 和 public export 不包含 host-only reveal payload。
9. SpoilerGuard 命中时，player/party 文本被安全替换并可查 audit。

### 回归命令

```powershell
python -m pytest tests/server/test_projection.py tests/server/test_projection_visibility.py tests/server/test_reconnect.py tests/server/test_ws_auth.py tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_events.py tests/server/test_spoiler_guard.py -q
```

前端涉及 WS 或事件类型时补跑：

```powershell
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | Projection 依赖 | 对方期望 |
| --- | --- | --- |
| User | token/account 权限、character_id | Projection 不信任前端声明身份 |
| Transaction | actionId、turnId、transactionId、安全释放点 | Projection 不决定事务状态 |
| State | stateVersion、patch、snapshot | Projection 只发送已持久化状态 |
| AI-Keeper | 安全叙事、公开摘要 | Projection 不生成新叙事 |
| Safety | SpoilerGuard 和 audit | Projection 做最后安全网，不替代上游 |
| Channel | 事件流和消息展示 | Projection 提供事件，不建频道模型 |
| Journal | events sequence 和查询 | Journal 查询必须复用 Projection 可见性口径 |
| Host Client | Host-only 事件和 UI frame | Host 不接收 player-only payload |
| Player Client | party/player 事件和版本屏障 | Player 不承担最终权限过滤 |
