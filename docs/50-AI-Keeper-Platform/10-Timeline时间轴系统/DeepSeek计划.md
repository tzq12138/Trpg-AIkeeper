# Timeline 时间轴系统 DeepSeek 计划 V2.1

## 执行定位

本计划服务于 `P0 主链路 + 时间线顺序与可见性风险识别版`。

目标不是一次做完完整 Timeline 平台，而是先把当前仓库里已经存在的 turn、events、archive、reconnect、checkpoint 链路加固成工程可执行版本：duplicate 不留孤儿 action、turn 结算幂等、Player 可见性统一、sequence 补发口径稳定、restore 可解释、gameTime 写入边界清楚。

## 当前仓库已确认事实

基于当前代码可确认：

- `TurnManager.ensure_current_turn()` 在无 collecting turn 时会直接创建新 turn
- `submit_intent()` 当前先 `engine.submit_intent()`，再 `tm.submit_action()`
- `mark_resolving()` 是无条件更新，`_settle_turn_background()` 会直接 `tm._create_turn()`
- `router_player_archive.py` 当前把 `party/system` 基本当成 public
- `router_reconnect.py` 的 snapshot 分支直接返回 room 全量 events
- `host/ws_manager.py` 的普通 reconnect 分支也按 room 全量 sequence 取 events
- `EventLog.get_events_for_player()` 当前允许全部 `system` 事件，并使用 `payload ->> 'character_id'`
- `s2c_turn_resolved` 仍未进入 `events_registry.py`、`models.py`、前端 TS 事件联合类型
- `restore_checkpoint()` 当前会重插 snapshot 内 events，不保留旧 sequence

## 全局禁止事项

- 禁止让 Player archive / reconnect 读取 Host 专属事件
- 禁止把全部 `system` 事件默认暴露给玩家
- 禁止 duplicate 行动场景留下无 `turn_id` 的 queued action
- 禁止在非 active 房间 GET current turn 时隐式创建 turn
- 禁止同一 turn 被并发结算多次
- 禁止只按 sequence 跨房间读取 timeline / reconnect / replay
- 禁止让 AI 直接写 sequence、turn status 或 gameTime
- 禁止把真实写入时间 `issued_at` 当成故事内时间
- 禁止前端自行决定某事件是否可见，必须以后端 DTO 为准
- 禁止顺手重构 Journal、Room、Projection 之外的大块无关代码

## Batch Timeline-0：测试基线与风险复现

### 目标

先用测试锁住 Timeline 当前真实风险，避免后续修复回退。

### 允许改动文件方向

- `tests/server/test_turn_manager.py`
- `tests/server/test_timeline_security.py`
- `tests/server/test_archive.py`
- `tests/server/test_reconnect.py`
- 必要时小范围调整 `tests/server/conftest.py`

### 任务

1. 构造 active room、两个 joined 角色、一个 collecting turn。
2. 复现同一玩家同一 turn 重复提交。
3. 验证 duplicate 后是否存在无 `turn_id` queued action。
4. 构造 `host`、`party`、`system_safe`、`player:self`、`player:other` 五类事件。
5. 验证 archive / reconnect / catch-up 的可见性一致性。
6. 增加 `player_sequences` 只能按安全返回事件更新的测试。
7. 增加 `system` 事件白名单测试。
8. 验证 `s2c_turn_resolved` 当前 registry / model / TS 缺口。

### 测试命令

```bash
python -m pytest tests/server/test_turn_manager.py tests/server/test_timeline_security.py -q
python -m pytest tests/server/test_archive.py tests/server/test_reconnect.py -q
```

### 验收

- 风险用例可稳定复现。
- 后续每修一项，都能看到对应测试转绿。

## Batch Timeline-1：回合绑定、duplicate 与结算幂等

### 目标

保证 action 生命周期和 turn 生命周期严格一致。

### 允许改动文件方向

- `src/server/player/router_player.py`
- `src/server/turn_manager.py`
- `src/server/router_rooms.py`
- `tests/server/test_turn_manager.py`
- `tests/server/test_player_intent.py`
- `tests/server/test_host_room_lifecycle.py`

### 任务

1. 调整 active 提交流程：先确认当前 turn 和 duplicate，再写 action；或在同一事务中完成 action 写入与 `turn_id` 绑定。
2. duplicate 返回 409 时不得产生新 action、event 或 version bump。
3. `GET /turns/current` 在非 active 房间返回空态或稳定错误，不再隐式创建 turn。
4. `collecting -> resolving` 通过条件更新或事务锁保证幂等。
5. `_settle_turn_background` 进入前后都检查 turn 状态。
6. 创建下一回合前检查是否已存在更新的 collecting turn。
7. 如暂不加 partial unique index，至少要用事务锁或等价策略封住 duplicate。
8. 明确 resolving 阶段当前 turn 可以处于 `resolving`，不得提前开放下一 collecting turn。
9. 明确 duplicate 阻塞的有效 action 状态集合；`rejected / cancelled` 默认不计入。

### 测试命令

```bash
python -m pytest tests/server/test_turn_manager.py tests/server/test_player_intent.py -q
python -m pytest tests/server/test_host_room_lifecycle.py -q
```

### 验收

- duplicate 没有孤儿 queued action。
- 并发 settle 只产生一个 resolved turn 和一个下一 collecting turn。
- 非 active 房间查询 current turn 不创建新 turn。

## Batch Timeline-2：玩家时间线与 reconnect 可见性统一

### 目标

统一 Player archive、WS catch-up、HTTP reconnect 的可见性规则。

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

1. 新增或复用统一 helper，例如：
   - `can_player_see_event(event, character_id)`
   - `build_event_view_for_player(event, character_id)`
2. 白名单规则：
   - `party` 可见
   - `player` 且本人可见
   - `system` 仅安全白名单可见
   - `host` 不可见
3. system 白名单至少给出最小样例：`s2c_turn_resolved`、`s2c_game_time_updated` safe payload、可选的 `s2c_checkpoint_created` 安全摘要。
4. `s2c_checkpoint_restored` 原始审计默认不得给 Player；如需通知 Player，应另发 party-safe 摘要。
5. 统一兼容 `payload.characterId` / `payload.character_id`。
6. `/api/player/archive`、`/api/player/reconnect`、WS catch-up 复用同一 helper。
7. reconnect snapshot 分支也必须过滤事件，不能返回全量 events。
8. `player_sequences` 更新为“已安全返回的最大 sequence”。
9. 如保留 `/events/public`，也必须只返回 player-visible public/system_safe 事件。

### 测试命令

```bash
python -m pytest tests/server/test_timeline_security.py tests/server/test_archive.py tests/server/test_reconnect.py -q
```

### 验收

- 玩家 A 看不到玩家 B 的 private event。
- 玩家看不到 host event。
- 只有白名单 system event 可见。
- reconnect 和 archive 对同一批事件给出一致可见结果。
- `player_sequences` 不会被 host-only/system 非白名单事件推过头。

## Batch Timeline-3：事件注册表、类型和 Timeline DTO

### 目标

让 Timeline 相关事件和 DTO 在后端、前端、筛选项里口径一致。

### 允许改动文件方向

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/client/src/shared/types.ts`
- `src/client/src/types.ts`
- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `tests/server/test_event_registry.py`

### 任务

1. 补充 `s2c_turn_resolved` 到 registry。
2. 补充 `EngineEventType` Literal。
3. 补充前端事件类型联合。
4. 定义 `TimelineEntryDTO` / `HostTimelineEntryDTO` / `PlayerTimelineEntryDTO`。
5. `visibility` 明确为派生字段，不等于原始 `audience`。
6. Host timeline 和 Player archive 尽量统一字段名。
7. 前端筛选项从明确枚举生成，避免漏掉 turn / checkpoint / map 事件。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_projection.py -q
cd src/client
npm run build
```

### 验收

- `s2c_turn_resolved` 能正常 emit、持久化、前端解析。
- HostLogsPanel / PlayerLogsPanel 不因类型收紧而构建失败。
- Timeline DTO 字段稳定。

## Batch Timeline-4：gameTime 初版

### 目标

建立最小可用的 gameTime，让故事时间与真实写入时间正式分离。

### 允许改动文件方向

- `src/server/engine/state_service.py`
- `src/server/models.py`
- `src/server/router_rooms.py` 或独立 `router_timeline.py`
- `tests/server/test_state_service.py`
- `tests/server/test_timeline_clock.py`
- 前端只在需要展示时小范围修改

### 任务

1. 定义 `gameTime` 数据结构：`label`、`sortKey`、`turnIndex`、`updatedBy`、`reason`、`safeReason`。
2. 优先通过 StateService 写入。
3. 提供 Host 设置/推进接口，玩家只读安全投影。
4. 每次推进 gameTime 写入安全事件或等价 state patch。
5. AI 只能建议推进原因，不能直接落库。
6. `sortKey` 不强制 ISO，可兼容 numeric tick / countdown。

### 测试命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_timeline_clock.py -q
```

### 验收

- Host 能设置一个 gameTime。
- Player 能读取安全展示文本。
- Timeline 中能看到 gameTime 推进记录。
- `issued_at` 与 `gameTime.label` 明确分离。

## Batch Timeline-5：checkpoint、restore 与 replay 一致性

### 目标

明确 restore 在时间线中的语义，避免恢复后历史无法解释。

### 允许改动文件方向

- `src/server/events/event_log.py`
- `src/server/router_archive.py`
- `src/server/campaign_archive.py`
- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`

### 任务

1. restore checkpoint 后必须写 `s2c_checkpoint_restored` 审计 marker。
2. 明确本轮语义：旧历史不重写产品解释，恢复后是新历史分支。
3. 如当前实现保留重插 snapshot events，则在回执和日志中说明 sequence 会重新生成。
4. Host replay 使用 `room_id + sequence` 稳定分页。
5. Player replay/export 继续走可见性过滤。
6. `s2c_checkpoint_restored` 默认走 Host 审计可见；如额外通知 Player，必须另发 party-safe 摘要而不是复用原始 payload。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py -q
```

### 验收

- checkpoint 创建、恢复、恢复 marker 都可查。
- restore 后 Host 能理解时间线断点。
- Player export 不泄露恢复前后的 host-only 数据。

## Batch Timeline-6：前端日志和时间线体验修正

### 目标

让 Host / Player 时间线 UI 对齐安全 DTO 和真实类型，不再靠前端本地硬判断可见性。

### 允许改动文件方向

- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/shared/types.ts`
- 必要 CSS

### 任务

1. 修复 HostLogsPanel 中文文案和事件标签。
2. 修复 PlayerLogsPanel 中文文案和分类值。
3. Player logs 分类和后端 `type` 参数对齐。
4. Host 单事件详情展示 `eventType`、`sequence`、`issuedAt`、`audience`、`payload`。
5. 前端以后端 `visibility` / DTO 为准，不自行决定某事件是否可看。
6. 接口报错时显示明确空态或错误态。

### 测试命令

```bash
cd src/client
npm run build
npm run test
```

### 验收

- 前端构建通过。
- Host / Player 日志没有乱码。
- 玩家切换分类不会请求后端不支持的类型。
- 前端不会因本地 visibility 推断错误而多显示事件。

## Batch Timeline-7：端到端验收

### 目标

验证完整 `开局 -> 回合 -> 行动 -> 结算 -> 时间线 -> 重连 -> checkpoint -> gameTime` 链路。

### 手动验收流程

1. Host 创建房间，玩家 A/B 加入并 ready。
2. Host 开局，进入第 1 回合。
3. 玩家 A/B 各提交一次行动。
4. 玩家 A 尝试重复提交，被拒绝且无孤儿 action。
5. 全员提交后自动结算，进入第 2 回合。
6. Host 时间线查看本轮 queued / completed / turn_resolved 事件。
7. 玩家 A 查看 archive，只能看到公开事件和自己的私密事件。
8. 玩家 A 断线后 reconnect，只补发可见事件，游标正确推进。
9. Host 创建 checkpoint 并执行一次 restore，时间线出现恢复断点。
10. Host 设置一次 gameTime，Player 只看到安全展示字段。

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
- checkpoint restore 断点可解释。
- gameTime 与真实写入时间分离。
