# Journal 日志与回放系统 DeepSeek 计划 V2.0

## 执行目标

把 Journal 从“能查一些 events”提升为核心链路的审计与回放层。第一轮重点修权限、可见性、导出脱敏、checkpoint 完整性和事件来源引用，不扩展社区战报、多媒体回放、复杂搜索平台。

## 全局禁止事项

1. 不允许让 Player 读取 Host-only、其他玩家私密事件、未发现线索、世界书真相。
2. 不允许把 AI 原始 prompt、API key、owner_token、player_token 写入 public 日志或导出。
3. 不允许在 Journal 中直接裁决规则或写世界状态。
4. 不允许为了修导出而删除现有 full 审计能力，full 仍需 Owner/Admin 可用。
5. 不允许重构无关模块或批量格式化源码。

## Batch Journal-0：现状盘点与回归基线

### 目标

确认所有事件写入、读取、导出、checkpoint、campaign 入口，先补安全回归测试，再改实现。

### 允许改动

- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`
- 新增 `tests/server/test_journal_security.py`
- 新增 `tests/server/test_export.py`
- 新增或更新少量测试 fixture

### 任务

1. 盘点所有 `INSERT INTO events`、`EventLog.log_event`、`ProjectionDispatcher.emit` 调用点。
2. 增加 public event 不得泄露 Host-only 事件的测试。
3. 增加 Player archive 不得读取他人 private/player 事件的测试。
4. 增加 `/campaign` 未授权不得访问的测试。
5. 增加 public/full export 脱敏测试。

### 验收命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_journal_security.py tests/server/test_export.py -q
```

### 预期结果

新增安全测试先能稳定复现当前风险，修复后全部通过。

## Batch Journal-1：统一事件可见性规则

### 目标

建立一个服务端统一 helper，供 public events、Player archive、replay、export 复用，消除各接口自行判断造成的泄露风险。

### 允许改动

- `src/server/events/event_log.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/server/export.py`
- 相关测试

### 任务

1. 新增事件可见性判断：Host full、Player private、public export 三种视角。
2. 替换 `audience != 'player'` 这类反向过滤。
3. 对 `audience='player'` 或私密事件要求明确 `characterId`/recipient 字段。
4. 让缺少归属的私密事件默认不可见。
5. 保证 system 事件不是天然 public，只有显式允许的 system 事件可公开。

### 验收命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_journal_security.py tests/server/test_export.py -q
```

### 禁止事项

- 不把所有 `system` 事件默认展示给 Player。
- 不在前端隐藏来替代后端权限过滤。

## Batch Journal-2：事件注册与写入入口收敛

### 目标

让实际写入的 Journal 事件与事件 registry、模型定义保持一致，并减少绕过 `EventLog` 或 `ProjectionDispatcher` 的散落写法。

### 允许改动

- `src/server/events/events_registry.py`
- `src/server/models.py`
- `src/server/engine/engine.py`
- `src/server/engine/projection.py`
- `src/server/events/event_log.py`
- `tests/server/test_events.py`
- 相关 engine/projection 测试

### 任务

1. 补齐 `s2c_checkpoint_created`、`s2c_checkpoint_restored`、`s2c_turn_resolved` 等实际事件定义。
2. 为 registry 增加测试，确保常用事件都能被识别。
3. 逐步把直接 SQL 写 `events` 的代码改成统一记录函数，或在代码旁明确兼容原因。
4. 确保事件 payload 保持 JSON 可序列化，中文不乱码。

### 验收命令

```bash
python -m pytest tests/server/test_events.py tests/server/test_projection.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不一次性大改事件 schema。
- 不破坏现有 WebSocket 投影行为。

## Batch Journal-3：Checkpoint 完整性与恢复审计

### 目标

修正 checkpoint 只覆盖直接 `room_id` 表导致的证据链缺口，并明确 restore 后日志语义。

### 允许改动

- `src/server/events/event_log.py`
- `src/server/router_archive.py`
- `tests/server/test_event_log.py`
- 新增或更新 checkpoint 相关测试

### 任务

1. 通过 `clues.clue_id` 纳入 `clue_shares` 快照。
2. 通过 `encounters.encounter_id` 纳入 `encounter_participants` 快照。
3. 恢复后验证角色、行动、线索、分享关系、遭遇参与者、地图位置、回合状态一致。
4. 保留或追加 `s2c_checkpoint_restored` 审计事件，避免恢复行为无迹可查。
5. 文档化当前 sequence 策略，并用测试固定行为。

### 验收命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_journal_security.py -q
```

### 禁止事项

- 不允许 Player 读取 checkpoint snapshot。
- 不允许恢复接口跳过 `confirm: true`。

## Batch Journal-4：导出与战役归档安全

### 目标

让 public/full export、campaign summary、campaign ending 的权限和脱敏策略稳定可测。

### 允许改动

- `src/server/export.py`
- `src/server/router_archive.py`
- `src/server/campaign_archive.py`
- `tests/server/test_campaign.py`
- `tests/server/test_export.py`
- `tests/server/test_journal_security.py`

### 任务

1. 为 `/api/rooms/{room_id}/campaign` 增加权限校验。
2. public campaign summary 只使用玩家可见事件生成。
3. public Markdown/JSON export 改为字段白名单。
4. full export 只允许 Owner/Admin，并仍脱敏 token 和 secret。
5. 修复导出与归档中的中文乱码文案。

### 验收命令

```bash
python -m pytest tests/server/test_campaign.py tests/server/test_export.py tests/server/test_journal_security.py -q
```

### 禁止事项

- 不把 full export 开给 room token。
- 不让 public export 包含 `xlsx_data` 原始私密内容、账号 ID、内部 prompt。

## Batch Journal-5：来源引用与证据链

### 目标

让 Journal 能支持“为什么会发生这件事”的追溯，而不是只保存一段孤立文本。

### 允许改动

- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/player/router_player.py`
- `src/server/host/router_host.py`
- `src/server/events/event_log.py`
- 相关测试

### 任务

1. 行动结果事件包含 `actionId`、`characterId`、`intentType`。
2. 状态 patch 事件包含 `stateVersion` 或等价版本字段。
3. 线索获得/分享事件包含 `clueId`、`sourceEventSequence`、分享人和接收人。
4. 投影事件保留 `transactionId` 或 `batchId`，方便串起一次裁决。
5. Host timeline 能按 action/character/clue 做基础过滤。

### 验收命令

```bash
python -m pytest tests/server/test_player_intent.py tests/server/test_resolution_pipeline.py tests/server/test_state_service.py tests/server/test_archive.py -q
```

### 禁止事项

- 不把未发现线索塞进玩家事件 payload。
- 不让 AI 生成没有来源引用的“已发现事实”。

## Batch Journal-6：前端日志体验与文案一致

### 目标

让 Host/Player 日志界面与后端能力一致，修正乱码、筛选不一致和错误提示。

### 允许改动

- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/shared/types.ts`
- 相关前端测试或类型修正

### 任务

1. 修复 HostLogsPanel 中用户可见乱码。
2. 修复 Player archive type：后端没有 `narrative` 时前端不展示该筛选，或后端补实现。
3. Host 导出按钮明确 public/full 区别和失败提示。
4. Checkpoint 恢复确认文案明确会覆盖当前房间状态。
5. Player 日志空态、错误态、加载态可读。

### 验收命令

```bash
cd src/client
npm run build
npm run test
```

### 禁止事项

- 不用前端过滤替代后端权限。
- 不新增大面积 UI 风格重构。

## Batch Journal-7：端到端主链路验收

### 目标

验证 Journal 对完整跑团链路可追溯，并且权限边界不破。

### 手动验收流程

1. Host 登录并创建房间。
2. Player 加入、绑定角色、ready。
3. Player 提交行动，系统完成 AI/规则裁决。
4. Host 查看 timeline，确认行动、裁决、状态 patch、投影事件存在。
5. Player 查看 archive，只看到公开事件和自己的私密结果。
6. Host 创建 checkpoint，再触发一次状态变化。
7. Host 恢复 checkpoint，确认恢复审计事件存在。
8. 导出 public Markdown/JSON，确认无 token、私密线索、Host-only、AI prompt。
9. 导出 full JSON，确认只有 Owner/Admin 可访问且 token 已脱敏。

### 回归命令

```bash
python -m pytest tests/server -q
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | Journal 依赖 | DeepSeek 注意点 |
| --- | --- | --- |
| Timeline | 提供游戏内时间和事件顺序语义。 | Journal 使用 sequence 和 timeline 字段，不负责推进时钟。 |
| Clue | 提供线索归属和分享关系。 | 私密线索必须按 character scope 过滤。 |
| State | 提供权威状态版本和 patch。 | Journal 记录状态变化引用，不直接写状态。 |
| Transaction | 提供一次裁决的事务边界。 | 日志事件应能串到 transaction 或 batch。 |
| Projection | 提供 Host/Player 分层投影。 | Journal 记录投影结果，并继承可见性边界。 |
| Safety | 提供防剧透和脱敏策略。 | public API、export、AI context 都必须调用安全边界。 |
| Admin/Ops | 提供 AI 调用日志和 spoiler audit。 | 运维日志不进入玩家 Journal。 |
