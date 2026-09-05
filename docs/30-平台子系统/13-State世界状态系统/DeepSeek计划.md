# State 世界状态系统 DeepSeek 计划 V2.1

## 执行目标

把 State 模块收口成 AI-Keeper 的权威世界状态写入层和版本屏障层。第一轮优先修：

- `rooms.state_version` 语义污染
- `StateService.apply_change()` 事务契约
- `ResolutionPipeline` 先投影后落库
- runtime 读模型不统一
- reconnect 版本屏障不完整
- checkpoint / restore 不完整
- 多条直写路径缺少统一契约

本轮不扩展：

- 分支世界线
- 离线冲突合并
- 跨房间共享状态
- encounter 全量统一重构

## 交付要求

DeepSeek 每个 Batch 回执都必须说明：

1. 改了哪些文件；
2. 哪些路径仍保留专项服务，没有并入 `StateService`；
3. 是否还有已知遗留；
4. 跑了哪些测试，结果如何；
5. 是否涉及中文文案 / payload 结构变化；
6. 是否影响 Player / Host patch 契约。

## 全局禁止事项

1. 不允许为了“修版本问题”继续让 action 入队、ready、纯 UI 事件 bump `rooms.state_version`。
2. 不允许把未持久化 patch 先发给 Player，再回头写库。
3. 不允许继续把 `characters.xlsx_data` 当作当前 HP/SAN 权威来源。
4. 不允许在 `/api/player/sync`、`/api/player/reconnect` 这类读取接口里静默创建 runtime 状态并独立 commit。
5. 不允许 `encounter_changes` 接入后静默成功但没有版本、事件、restore 语义。
6. 不允许 restore 后把 Host 全量 snapshot 原样返回给 Player。

## Batch State-0：现状盘点与回归基线

### 目标

先用测试固定当前真实风险，避免后续修复过程中混淆“老行为”和“目标行为”。

### 允许改动

- `tests/server/test_state_service.py`
- `tests/server/test_state_service_consistency.py`
- `tests/server/test_player_runtime_state.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_event_log.py`
- 新增 `tests/server/test_state_security.py`

### 任务

1. 固定 action 入队不应推进世界状态版本的目标测试。
2. 固定空 `StateChangeSet` 不应 bump 版本的目标测试。
3. 固定 `ResolutionPipeline` 先写 State 再投影的目标测试。
4. 固定 reconnect snapshot 不得返回 Host / private 泄露事件的测试。
5. 固定 checkpoint 需要覆盖 runtime / scene / room `state_version` 的目标测试。

### 验收命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_player_runtime_state.py tests/server/test_reconnect.py tests/server/test_resolution_pipeline.py tests/server/test_event_log.py tests/server/test_state_security.py -q
```

## Batch State-1：`state_version` 语义收口

### 目标

把 `rooms.state_version` 固定为“权威世界状态版本”，移除 action 入队和 no-op 的污染。

### 允许改动

- `src/server/engine/engine.py`
- `src/server/engine/state_service.py`
- `tests/server/test_engine.py`
- `tests/server/test_state_service_consistency.py`
- `tests/server/test_state_security.py`

### 任务

1. `submit_intent()` 队列动作不再 bump `rooms.state_version`。
2. `ready_toggle` 保持 Room / Lobby 行为，不进入世界版本。
3. `StateService.apply_change()` 仅在存在真实已应用变化时 bump 版本。
4. no-op / heartbeat 改为不推进版本。

### 验收命令

```bash
python -m pytest tests/server/test_engine.py tests/server/test_state_service_consistency.py tests/server/test_state_security.py -q
```

### 禁止事项

- 不要用“再多加一个版本字段”规避房间世界版本语义问题。

## Batch State-2：事务契约与 patch 时序

### 目标

修正 `apply_change()` 与 `ResolutionPipeline` 的时序，让 patch 只来自已持久化状态。

### 允许改动

- `src/server/engine/state_service.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/projection.py`
- `src/server/events/events_registry.py`
- `tests/server/test_state_service.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_projection.py`

### 任务

1. `apply_change()` 返回 `baseStateVersion`、`stateVersion`、`appliedChanges`、`eventRefs` 等统一结果。
2. `s2c_state_patch` payload 补齐 `schemaVersion/baseStateVersion/stateVersion/actionId`。
3. `ResolutionPipeline` 调整为先 `apply_change()`，再 `_project()`。
4. 移除同一状态变化被 Pipeline 和 StateService 双重 patch 的情况。

### 验收命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_resolution_pipeline.py tests/server/test_projection.py -q
```

### 禁止事项

- 不允许继续向 Player 发送没有版本字段的 `s2c_state_patch`。

## Batch State-3：runtime 初始化与读模型统一

### 目标

把当前角色实时状态统一到 `character_runtime_state`，并收紧 lazy init 行为。

### 允许改动

- `src/server/engine/state_service.py`
- `src/server/player/router_player.py`
- `src/server/player/router_reconnect.py`
- `src/server/host/hud_builder.py`
- `src/server/router_admin.py`
- `tests/server/test_player_runtime_state.py`
- `tests/server/test_host.py`
- `tests/server/test_state_security.py`

### 任务

1. `/api/player/sync` 和角色当前状态接口优先返回 runtime 字段。
2. `xlsx_data` 保留为角色卡基线，不再承载当前 HP/SAN。
3. 明确 lazy init 是否保留；若保留，不得在纯读取接口中偷偷写库。
4. 后台角色状态编辑改走 runtime 状态，不再直接改 `xlsx_data` 承载当前值。

### 验收命令

```bash
python -m pytest tests/server/test_player_runtime_state.py tests/server/test_host.py tests/server/test_state_security.py -q
```

## Batch State-4：直写路径收口与专项服务对齐

### 目标

处理地图、线索、背包、retroactive item、后台状态修改这些仍然分散的写入路径。

### 允许改动

- `src/server/player/router_player.py`
- `src/server/player/router_clues.py`
- `src/server/router_admin.py`
- `src/server/map_persistence.py`
- `src/server/host/router_host.py`
- `src/server/engine/state_service.py`
- 相关测试

### 任务

1. retroactive item 改走统一状态写入或专项 `InventoryStateService`。
2. 管理员改 HP/SAN/status 改走 runtime 状态服务并记审计。
3. Map / Clue / Inventory 即便保留专项服务，也必须统一返回 `AppliedStateChange`、`stateVersion`、`eventRefs`。
4. 明确哪些路径是“Room / Lobby / UI 豁免路径”，不再误用世界版本。
5. 回执必须说明 Map 是否推进 `rooms.state_version`；若保留 map local version，如何映射到 room version 或事件序列。

### 验收命令

```bash
python -m pytest tests/server/test_player_intent.py tests/server/test_clues.py tests/server/test_state_service.py tests/server/test_state_security.py -q
```

### 禁止事项

- 不要把地图、线索、背包简单继续当成“各管各的”，却不给统一版本与事件契约。

## Batch State-5：重连版本屏障

### 目标

把 reconnect、snapshot、missed events 和客户端 patch 屏障打通。

### 允许改动

- `src/server/player/router_reconnect.py`
- `src/server/player/router_player.py`
- `src/server/events/event_log.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_state_security.py`

### 任务

1. snapshot 返回 `snapshotStateVersion`。
2. recent events / missed events 复用玩家可见性 helper。
3. 明确服务端何时要求客户端做 full sync。
4. 固定客户端版本屏障所需字段契约。

### 验收命令

```bash
python -m pytest tests/server/test_reconnect.py tests/server/test_state_security.py tests/server/test_archive.py -q
```

### 回执必须说明

1. 需要 snapshot 的场景下，是否还会返回整房间原始事件；
2. Player 是否还能看到 Host-only / 其他玩家 private 事件；
3. `snapshotStateVersion` 字段名与含义是否已固定。

## Batch State-6：checkpoint / restore 一致性

### 目标

把 checkpoint / restore 语义与 10-Timeline、11-Journal 对齐，形成新的历史分支解释。

### 允许改动

- `src/server/events/event_log.py`
- `src/server/router_archive.py`
- `src/server/engine/state_service.py`
- `tests/server/test_event_log.py`
- `tests/server/test_archive.py`

### 任务

1. snapshot 至少覆盖 `character_runtime_state`、`room_scene_state`、房间 `state_version`。
2. restore 后保留“新历史分支”解释，不把旧历史当删除。
3. restore 后继续写 `s2c_checkpoint_restored`，并限制为 Host / Admin 审计。
4. Player 如需刷新，只返回安全 snapshot 或安全摘要。
5. 若本轮仍不补 `encounter_participants` / `clue_shares`，必须在回执中明确列为遗留项。
6. 回执必须显式填写 `CheckpointStateDTO.includes[]` 与 `knownLimitations[]`。

### 验收命令

```bash
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_state_service.py -q
```

### 禁止事项

- 不允许 restore 后把旧 patch 继续当作可覆盖新状态的增量。

## Batch State-7：端到端回归

### 目标

验证 State 已经能支撑“玩家行动 -> 规则 / AI 裁决 -> 状态变更 -> 投影 -> 重连 / 恢复”主链路。

### 手动验收流程

1. 玩家入房并初始化 runtime 状态。
2. 玩家提交带 `base_state_version` 的行动。
3. Rule / Engine 产出 HP/SAN 或状态标签变化。
4. State 先落库，后发带版本 patch。
5. Player 与 Host 看到一致的当前状态。
6. 玩家断线期间发生状态变化，重连后只应用正确版本的 patch。
7. Host 创建 checkpoint，再发生新的状态变化，再 restore。
8. restore 后 runtime、scene、map、inventory、clue、日志引用重新对齐。

### 回归命令

```bash
python -m pytest tests/server/test_engine.py tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_player_runtime_state.py tests/server/test_reconnect.py tests/server/test_resolution_pipeline.py tests/server/test_event_log.py tests/server/test_archive.py -q
cd src/client
npm run build
```

## 与其他模块的接口要求

| 模块 | State 依赖 | DeepSeek 注意点 |
| --- | --- | --- |
| Room | 提供房间生命周期和成员上下文 | ready / lobby 不得继续污染世界状态版本 |
| Rule | 产出权威结算结果 | State 不负责替代 Rule 判定 |
| AI-Keeper | 只提供状态变化建议 | AI 不能直接写库 |
| Transaction | 定义一次裁决的事务边界 | `AppliedStateChange` 要能挂到事务和事件序列 |
| Projection | 下发 Player / Host patch | 只能投影已持久化状态 |
| Journal | 记录事件与导出 | State 写事实，Journal 写证据链 |
| Scene / Map | 地图探索、位置、显隐 | 允许专项服务，但必须对齐统一结果契约 |
| Clue | 线索归属和分享 | 私密 / 公共可见性由 Clue / Safety / Projection 决定 |
| Character | 角色卡基线与长期 profile | `xlsx_data` 不再承载当前房间实时状态 |
