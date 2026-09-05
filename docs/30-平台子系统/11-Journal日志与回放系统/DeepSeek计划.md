# Journal 日志与回放系统 DeepSeek 计划 V2.1

## 当前阶段目标

本轮不是做完整的“战报平台”，而是把当前仓库中已经存在的 Journal 相关能力加固为可执行版本：

- 统一事件可见性
- 锁死 public / full export 白名单
- 明确 checkpoint / restore 语义
- 补齐 source reference chain
- 把 AI / Ops raw 审计与玩家 Journal 分层

执行阶段口径以本目录文档和 `docs/50-AI-Keeper-Platform/10-Timeline时间轴系统/` 为准，尤其是：

- `room_id + sequence`
- `system_safe`
- restore 新历史分支语义
- 玩家不可见 host-only / admin-only / raw debug 内容

## 代码现状前提

DeepSeek 执行前必须先接受这些当前事实，不能按理想架构重写：

1. `src/server/export.py` 的 public 导出仍存在 `audience != 'player'` 口径，不能继续沿用。
2. `src/server/router_archive.py` 的 `/campaign` 当前未锁死鉴权。
3. restore 入口当前只要求 `confirm: true`，尚未要求 `reason`。
4. `src/server/events/event_log.py` 的 checkpoint 快照当前未覆盖 `clue_shares`、`encounter_participants`。
5. restore 当前会重插 snapshot 内 events，旧 `sequence` 不保留。
6. `src/server/events/events_registry.py`、`src/server/models.py`、`src/client/src/shared/types.ts` 仍缺部分 Journal 事件定义。
7. `src/server/db_adapter.py` 已存在 `ai_call_logs`、`spoiler_audits`，这些必须保留在 Admin/Ops 边界内。

## 全局禁止事项

1. 不允许继续用 `audience != 'player'` 代表 public 视角。
2. 不允许仅靠前端隐藏来替代后端权限过滤。
3. 不允许让 Player 读到 host-only、他人 private、未发现 clue、raw prompt、spoiler audit。
4. 不允许把 `full export` 做成数据库原样导出。
5. 不允许在 Journal 中直接补写规则裁决或状态真相。
6. 不允许 restore 在无 `confirm=true + reason` 的情况下执行。
7. 不允许把 `s2c_checkpoint_restored` 原始审计 payload 直接下发给 Player。
8. 不允许顺手重构无关模块或批量格式化源码。

## Batch Journal-0：现状盘点与回归基线

### 目标

先用测试把当前风险钉住，再改实现。

### 允许改动

- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`
- 新增 `tests/server/test_journal_security.py`
- 新增 `tests/server/test_export.py`
- 新增或更新少量 fixture

### 任务

1. 盘点所有 Journal 写入点：`log_event()`、`ProjectionDispatcher.emit()`、直接写 `events` 的代码。
2. 增加 public events 不得泄露 host-only / admin-only 事件的测试。
3. 增加 Player archive 不得读取他人 private 事件的测试。
4. 增加 `/campaign` 未授权访问测试。
5. 增加 public/full export 脱敏测试。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_journal_security.py tests/server/test_export.py -q
```

### 完成标准

- 新增测试先能复现风险
- 修复后测试全部通过

## Batch Journal-1：统一事件可见性 helper

### 目标

建立服务端统一可见性 helper，供 public events、Player archive、replay、export 共用。

### 允许改动

- `src/server/events/event_log.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/server/export.py`
- 相关测试

### 任务

1. 定义最小可见性分类：`host`、`party`、`player:self`、`player:other`、`system_safe`、`admin_audit`。
2. 将 public events 从“反向过滤”改为“显式白名单 + safe payload”。
3. 私密事件缺少归属字段时默认拒绝向 Player 暴露。
4. 保证 `/events/public`、`/api/player/archive`、`export(scope=public)` 使用同一套判断。
5. 与 `10-Timeline时间轴系统` 的 `system_safe` 语义保持一致。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_journal_security.py tests/server/test_export.py -q
```

### 禁止事项

- 不把所有 `system` 事件默认给 Player
- 不把 helper 做成只在前端生效的“展示过滤”

## Batch Journal-2：事件定义、DTO 与写入口对齐

### 目标

让 Journal 事件的注册表、后端模型、前端类型与真实写入行为对齐。

### 允许改动

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/client/src/shared/types.ts`
- `src/server/events/event_log.py`
- `src/server/engine/engine.py`
- `src/server/engine/projection.py`
- `tests/server/test_events.py`
- 相关 engine / projection 测试

### 任务

1. 补齐 `s2c_checkpoint_created`、`s2c_checkpoint_restored`、`s2c_turn_resolved` 等缺失事件。
2. 梳理仍然直接写 `events` 的代码点，尽量收敛到统一入口。
3. 增加 registry 与 shared types 对齐测试。
4. 规范事件 DTO 最低字段：`roomId`、`sequence`、`eventType`、`audience`、`issuedAt`、`payload`。
5. 确保中英文 payload 序列化后不乱码。

### 测试命令

```bash
python -m pytest tests/server/test_events.py tests/server/test_projection.py tests/server/test_event_log.py -q
cd src/client
npm run build
```

### 禁止事项

- 不做一次性大改 schema
- 不破坏现有 WebSocket 投影链路

## Batch Journal-3：checkpoint 完整性与 restore 语义

### 目标

把 checkpoint / restore 从“能用”加固到“可审计、可解释”。

### 允许改动

- `src/server/events/event_log.py`
- `src/server/router_archive.py`
- `tests/server/test_event_log.py`
- `tests/server/test_journal_security.py`
- 新增或更新 checkpoint 相关测试

### 任务

1. 补入 `clue_shares`、`encounter_participants` 等间接依赖快照。
2. restore 接口强制要求 `confirm=true + reason`。
3. 补强 `s2c_checkpoint_restored` 审计 payload，至少带 `checkpointId`、`actorAccountId`、`reason`、`restoreMode`、`createdAt`。
4. 明确并固定当前 restore 语义：旧 `sequence` 不保留，产品解释为“从 checkpoint 恢复出的新历史分支”。
5. 如需通知 Player，另发 party-safe 摘要，不复用原始 restore 审计 payload。

### 测试命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_journal_security.py -q
```

### 禁止事项

- 不允许 Player 读取 checkpoint snapshot
- 不允许 restore 审计缺失

## Batch Journal-4：campaign summary 与 export 安全

### 目标

锁死 summary / export 的鉴权和字段边界。

### 允许改动

- `src/server/export.py`
- `src/server/router_archive.py`
- `src/server/campaign_archive.py`
- `tests/server/test_campaign.py`
- `tests/server/test_export.py`
- `tests/server/test_journal_security.py`

### 任务

1. 给 `GET /api/rooms/{room_id}/campaign` 增加明确鉴权。
2. 将 campaign summary 分为 public 与 full 两个口径。
3. public Markdown / JSON export 改为字段白名单。
4. full export 仅允许 Owner / Admin，且仍做 secret 脱敏。
5. 明确 `ai_call_logs`、`spoiler_audits` 为 `never_export`。

### 测试命令

```bash
python -m pytest tests/server/test_campaign.py tests/server/test_export.py tests/server/test_journal_security.py -q
```

### 禁止事项

- 不把 raw token、API key、raw prompt、raw response 放入任何 export
- 不把未公开 clue 原文导入 public export

## Batch Journal-5：source reference chain 与 Player archive 对齐

### 目标

让 Journal 不只是“存了一行文字”，而是能回答“这件事为什么会发生”。

### 允许改动

- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/player/router_player.py`
- `src/server/player/router_player_archive.py`
- `src/server/host/router_host.py`
- `src/server/events/event_log.py`
- 相关测试

### 任务

1. 行动类事件补 `actionId`、`characterId`、`intentType`、`turnId`。
2. 状态类事件补 `transactionId`、`stateVersion`。
3. 线索类事件补 `clueId`、`sourceEventSequence`、`sharedBy`、`sharedTo`。
4. 地图 / 场景事件补 `mapId`、`sceneId`、`transactionId`。
5. Player archive 与 Host timeline 都能追到最小来源引用，但 Player 只拿安全摘要。

### 测试命令

```bash
python -m pytest tests/server/test_player_intent.py tests/server/test_resolution_pipeline.py tests/server/test_state_service.py tests/server/test_archive.py -q
```

### 禁止事项

- 不把未发现线索塞进玩家 archive
- 不允许 AI 产出无来源引用的“已发生事实”

## Batch Journal-6：前端 Journal 面板对齐

### 目标

让 Host / Player 的日志页面与后端真实能力一致，修掉类型不一致与文案乱码风险。

### 允许改动

- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/shared/types.ts`
- 必要的前端测试

### 任务

1. 对齐 Host / Player 端事件类型枚举。
2. 修正 Player archive 不支持但前端仍暴露的筛选项。
3. 区分 public / full export 的 UI 行为与报错提示。
4. restore 确认框明确“会覆盖当前房间状态，且必须填写原因”。
5. 修复日志相关中文文案乱码。

### 测试命令

```bash
cd src/client
npm run build
npm run test
```

### 禁止事项

- 不用前端筛选代替后端权限
- 不顺手做大面积 UI 风格重构

## Batch Journal-7：端到端主链路回归

### 目标

验证完整 `开房 -> 加入 -> 行动 -> 裁决 -> 状态变更 -> 投影 -> Journal -> checkpoint -> export` 链路。

### 手动验收流程

1. Host 登录并创建房间。
2. Player 加入、绑定角色、ready。
3. Player 提交行动，系统完成 AI / 规则裁决。
4. Host timeline 中能看到行动、检定、状态 patch、地图变化、回合完成。
5. Player archive 中只能看到公开事件和自己的私密结果。
6. Host 创建 checkpoint，继续推进一次状态变化。
7. Host restore checkpoint，系统写入新的 restore 审计 marker。
8. 导出 public Markdown / JSON，确认无 token、raw prompt、未公开 clue、host-only payload。
9. 导出 full JSON，确认仅 Owner / Admin 可访问，且仍不含 raw token / API key / raw prompt。

### 回归命令

```bash
python -m pytest tests/server -q
cd src/client
npm run build
```

## 与其他模块的接口关系

| 模块 | Journal 依赖 | 执行注意点 |
| --- | --- | --- |
| Timeline | 顺序、断点、`room_id + sequence`、`system_safe` | Journal 必须复用 Timeline 的顺序和可见性语义 |
| Clue | 线索归属、分享、公共摘要 | restore 要补齐 `clue_shares` |
| Scene / Map | 地图事件、位置信息、遭遇关系 | restore 要补齐 `encounter_participants` |
| State | 权威状态版本、patch | Journal 只记录，不直接写状态 |
| Transaction | 裁决批次边界 | 关键事件必须串到 transaction |
| Projection | Host / Player 分层投影 | Journal 沉淀已安全裁剪后的结果 |
| Safety | 反剧透、脱敏、DTO 边界 | public/archive/export 全部走安全策略 |
| Admin / Ops | `ai_call_logs`、`spoiler_audits` | 属于 `never_export`，不进玩家视角 |
