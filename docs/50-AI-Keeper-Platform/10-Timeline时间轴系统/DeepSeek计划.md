# Timeline 时间轴系统 DeepSeek 计划 V2.0

## 执行目标

先修顺序和权限，再补游戏内时间。第一轮不做复杂日历，也不重写 Journal；只围绕现有 `room_turns`、`actions`、`events`、`player_sequences`、checkpoint、archive 和前端日志面板加固。

## 全局禁止事项

- 禁止让 Player 时间线读取 Host 专属事件。
- 禁止用 `audience != 'player'` 判断玩家公开可见。
- 禁止在 duplicate 行动场景留下无 `turn_id` 的 queued action。
- 禁止同一 turn 被并发结算多次。
- 禁止让 AI 直接写事件 sequence、回合状态或游戏内时间。
- 禁止把真实写入时间 `issued_at` 当成游戏内故事时间。
- 禁止顺手重构 Journal、Room、Projection 之外的大块无关代码。

## Batch Timeline-0：测试基线与风险复现

### 目标

用测试锁住 Timeline 当前风险：重复提交、回合结算幂等、玩家时间线可见性、reconnect 补发过滤、turn 事件注册缺口。

### 允许改动文件方向

- `tests/server/test_turn_manager.py`
- `tests/server/test_timeline_security.py`
- `tests/server/test_archive.py`
- `tests/server/test_reconnect.py`
- 必要时小范围调整 `tests/server/conftest.py`

### 任务

1. 构造 active room、两个 joined/ready characters、一个 collecting turn。
2. 复现同一玩家同一 turn 重复提交。
3. 检查 duplicate 后是否存在无 `turn_id` queued action。
4. 构造 host、party、system、player:self、player:other 五类 events。
5. 验证 player archive 和 reconnect 的可见性。
6. 验证 `s2c_turn_resolved` 是否被 registry、model、前端类型识别。

### 测试命令

```bash
python -m pytest tests/server/test_turn_manager.py tests/server/test_timeline_security.py -q
python -m pytest tests/server/test_archive.py tests/server/test_reconnect.py -q
```

### 验收

- 风险用例可稳定失败或稳定暴露当前行为。
- 后续批次每修一个风险，都能看到对应测试转绿。

## Batch Timeline-1：回合绑定、duplicate 与结算幂等

### 目标

保证 active 房间里的 action 生命周期和 turn 生命周期严格一致。

### 允许改动文件方向

- `src/server/player/router_player.py`
- `src/server/turn_manager.py`
- `src/server/router_rooms.py`
- `src/server/engine/engine.py`
- `tests/server/test_turn_manager.py`
- `tests/server/test_player_intent.py`

### 任务

1. 调整 active 提交流程：先确认当前 turn 和 duplicate，再写 action，或在同一事务中写 action 与 `turn_id`。
2. duplicate 返回 409 时不能产生新 action、event 或 state_version bump。
3. `GET /turns/current` 不应在非 active 房间隐式创建 turn。
4. `mark_resolving` 需要检查 collecting -> resolving 的状态转移，避免重复 settle。
5. `_settle_turn_background` 进入前后都检查 turn 状态，保证幂等。
6. 创建下一回合前检查是否已存在更新的 collecting turn。

### 测试命令

```bash
python -m pytest tests/server/test_turn_manager.py tests/server/test_player_intent.py -q
python -m pytest tests/server/test_host_room_lifecycle.py -q
```

### 验收

- 同一玩家重复提交没有孤儿 queued action。
- 并发触发 settle 只产生一个 resolved turn 和一个下一回合。
- 非 active 房间查询当前 turn 不创建新 turn。

## Batch Timeline-2：玩家时间线与 reconnect 可见性过滤

### 目标

统一 Player archive、public events、WS catch-up、HTTP reconnect 的可见性规则。

### 允许改动文件方向

- `src/server/events/event_log.py`
- `src/server/player/router_player_archive.py`
- `src/server/player/router_reconnect.py`
- `src/server/host/ws_manager.py`
- `src/server/main.py`
- `tests/server/test_timeline_security.py`
- `tests/server/test_archive.py`
- `tests/server/test_reconnect.py`

### 任务

1. 新增或复用一个 `can_player_see_event(event, character_id)` helper。
2. player 可见规则：party 可见；player 且 payload.characterId/character_id 为本人可见；system 只允许安全白名单；host 不可见。
3. `EventLog.get_public_events` 不再使用 `audience != 'player'`。
4. `/api/player/archive`、`/api/player/reconnect`、WS catch-up 使用同一 helper。
5. reconnect 的 snapshot 分支也必须过滤事件，不能返回全量 events。
6. `player_sequences` 更新为“已安全返回的最大 sequence”。

### 测试命令

```bash
python -m pytest tests/server/test_timeline_security.py tests/server/test_archive.py tests/server/test_reconnect.py -q
```

### 验收

- 玩家 A 看不到玩家 B 的 private event。
- 玩家看不到 host event。
- system event 只有白名单类型可见。
- reconnect 和 archive 对同一批事件给出一致可见结果。

## Batch Timeline-3：事件注册表、类型和 Timeline DTO

### 目标

让 Timeline 相关事件在后端 registry、Pydantic 类型、前端 TypeScript 类型、筛选项里口径一致。

### 允许改动文件方向

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/client/src/shared/types.ts`
- `src/client/src/types.ts`
- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `tests/server/test_event_registry.py` 或现有事件测试

### 任务

1. 补充 `s2c_turn_resolved` 到事件注册表。
2. 补充 `EngineEventType` Literal。
3. 补充前端事件类型联合。
4. 定义 TimelineEntry DTO：sequence、eventType、audience、payload、issuedAt、turnId、turnIndex、visibility。
5. Host timeline 和 Player archive 尽量返回一致字段名。
6. 前端筛选项从明确枚举生成，避免漏掉 turn/map/encounter 事件。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_projection.py -q
cd src/client
npm run build
```

### 验收

- `s2c_turn_resolved` 能正常 emit、持久化、前端解析。
- HostLogsPanel 和 PlayerLogsPanel 不因类型收紧而构建失败。
- Timeline DTO 字段稳定。

## Batch Timeline-4：游戏内时间初版

### 目标

建立最小可用的 gameTime，不做复杂历法，只让故事时间与真实写入时间分离。

### 允许改动文件方向

- `src/server/engine/state_service.py`
- `src/server/models.py`
- `src/server/router_rooms.py` 或独立 `router_timeline.py`
- `tests/server/test_state_service.py`
- `tests/server/test_timeline_clock.py`
- 前端只在需要展示时小范围修改

### 任务

1. 定义 `gameTime` 数据结构：label、sortKey、turnIndex、updatedBy、reason。
2. 优先通过 StateService 写入，可放在房间状态或 `room_scene_state.scene_variables` 中。
3. 提供 Host 设置/推进接口，玩家只读安全投影。
4. 每次推进 gameTime 写入事件，例如 `s2c_game_time_updated` 或复用安全 state patch。
5. AI 只能建议推进原因，不能直接落库。
6. 不实现复杂农历、时区、自动 NPC 日程。

### 测试命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_timeline_clock.py -q
```

### 验收

- Host 能设置一个游戏内时间。
- Player 能读取安全展示文本。
- 事件 timeline 中能看到 gameTime 推进原因。
- `issued_at` 与 `gameTime.label` 明确分离。

## Batch Timeline-5：checkpoint、restore 与 replay 一致性

### 目标

明确 checkpoint/restore 在时间线中的语义，避免恢复后历史顺序不可解释。

### 允许改动文件方向

- `src/server/events/event_log.py`
- `src/server/router_archive.py`
- `src/server/campaign_archive.py`
- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`

### 任务

1. restore checkpoint 后必须写 `s2c_checkpoint_restored` 审计事件。
2. 明确恢复后的 events 是“新历史”还是“恢复 snapshot 中的历史”。
3. 如果恢复时跳过原 sequence，需要在返回值和日志里说明恢复点。
4. Host replay 使用 sequence 稳定分页。
5. Player replay/export 继续走可见性过滤。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py -q
```

### 验收

- checkpoint 创建、恢复、恢复审计事件都可查。
- 恢复后 Host 能理解时间线断点。
- Player export 不泄露恢复前后的 host-only 数据。

## Batch Timeline-6：前端日志和时间线体验修正

### 目标

修复 Host 与 Player 时间线相关 UI 的乱码、状态和字段对齐问题。

### 允许改动文件方向

- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/shared/types.ts`
- 必要 CSS

### 任务

1. 修复 HostLogsPanel 中文文案和事件类型标签。
2. 修复 PlayerLogsPanel 中文文案和分类标签。
3. Player logs 的分类值和后端 `type` 参数对齐。
4. Host 单事件详情展示 eventType、sequence、issuedAt、audience、payload。
5. 时间线接口报错时显示明确空态或错误态。

### 测试命令

```bash
cd src/client
npm run build
npm run test
```

### 验收

- 前端构建通过。
- Host 和 Player 日志没有乱码。
- 玩家切换分类不会请求后端不支持的类型。

## Batch Timeline-7：端到端验收

### 目标

验证完整“开局 -> 回合 -> 行动 -> 结算 -> 时间线 -> 重连 -> 归档”链路。

### 手动验收流程

1. Host 创建房间，玩家 A/B 加入并 ready。
2. Host 开局，进入第 1 回合。
3. 玩家 A/B 各提交一次行动。
4. 玩家 A 尝试重复提交，被拒绝且无孤儿 action。
5. Host 查看当前回合状态。
6. 全员提交后自动结算，进入第 2 回合。
7. Host 时间线查看本轮行动和结算事件。
8. 玩家 A 查看 archive，只能看到公开事件和自己的私密事件。
9. 玩家 A 断线后 reconnect，只补发可见事件。
10. Host 创建 checkpoint，再查看 checkpoint 事件。

### 回归命令

```bash
python -m pytest tests/server/test_turn_manager.py tests/server/test_timeline_security.py tests/server/test_archive.py tests/server/test_reconnect.py -q
python -m pytest tests/server/test_event_log.py tests/server/test_projection.py tests/server/test_host_room_lifecycle.py -q
python -m pytest tests/server -q
cd src/client
npm run build
```

### 最终验收

- 回合顺序稳定。
- 事件 sequence 稳定。
- 玩家可见性安全。
- reconnect 与 archive 口径一致。
- Host 能审计和回放。
- 游戏内时间有明确初版边界，不再与真实写入时间混用。
