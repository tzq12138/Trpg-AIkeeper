# State 世界状态系统 DeepSeek 计划 V2.0

## 执行目标

把 State 模块收口为 AI-Keeper 的权威状态写入和版本屏障层。第一轮优先修“状态先落库再投影、patch 带版本、读 runtime、直接写库路径收口、checkpoint 完整性”，不扩展分支世界线和复杂离线合并。

## 全局禁止事项

1. 不允许 AI、Player、Host 直接写权威状态表后不经过审计。
2. 不允许 patch 在状态持久化前发送给 Player。
3. 不允许用 `xlsx_data` 覆盖 runtime state 作为当前 HP/SAN。
4. 不允许无实际状态变化时随意推进 `rooms.state_version`。
5. 不允许为了修版本问题删除现有事件日志或 checkpoint 能力。

## Batch State-0：现状盘点与测试基线

### 目标

固定当前 StateService、runtime state、重连、projection、直接写库路径的行为，先补会暴露风险的测试。

### 允许改动

- `tests/server/test_state_service.py`
- `tests/server/test_state_service_consistency.py`
- `tests/server/test_player_runtime_state.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_projection.py`
- 新增 `tests/server/test_state_security.py`

### 任务

1. 盘点所有直接写 `characters.xlsx_data`、`inventory`、`clues`、`room_map_state`、`encounters`、`rooms.state_version` 的路径。
2. 增加 pipeline 先投影后持久化的风险测试。
3. 增加 `s2c_state_patch` 缺版本字段的测试。
4. 增加 `/api/player/sync` 必须返回 runtime HP/SAN 的测试。
5. 增加空 `StateChangeSet` 不应推进 world state 的目标测试。

### 验收命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_player_runtime_state.py tests/server/test_reconnect.py tests/server/test_projection.py tests/server/test_state_security.py -q
```

### 预期结果

新增测试先能暴露当前差距，修复后全部通过。

## Batch State-1：版本化 patch 与投影时序

### 目标

保证状态先持久化并获得版本，再投影带版本的 patch，解决 Player 端乱序和重复应用问题。

### 允许改动

- `src/server/engine/state_service.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/projection.py`
- `src/server/events/events_registry.py`
- `tests/server/test_state_service.py`
- `tests/server/test_resolution_pipeline.py`
- `tests/server/test_projection.py`

### 任务

1. `StateService.apply_change` 返回 `base_state_version` 和 `state_version`。
2. `s2c_state_patch` payload 加 `schemaVersion`、`baseStateVersion`、`stateVersion`、`actionId`。
3. ResolutionPipeline 调整为先 apply_change，再投影。
4. 避免 Pipeline 和 StateService 对同一 mutation 发两条重复 patch。
5. Projection 只发送已持久化版本的 patch。

### 验收命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_resolution_pipeline.py tests/server/test_projection.py -q
```

### 禁止事项

- 不让 Player 收到没有版本的状态 patch。
- 不用延迟计时替代事务节点。

## Batch State-2：Runtime 读模型统一

### 目标

让当前角色状态读模型统一到 `character_runtime_state`，角色卡 `xlsx_data` 只作为初始化基线。

### 允许改动

- `src/server/player/router_player.py`
- `src/server/host/hud_builder.py`
- `src/server/router_admin.py`
- `src/server/engine/state_service.py`
- `tests/server/test_player_runtime_state.py`
- `tests/server/test_host.py`
- `tests/server/test_state_security.py`

### 任务

1. `/api/player/sync` 返回 runtime HP/SAN/MP/Luck/status。
2. `/api/player/character` 当前状态字段优先 runtime，角色卡背景/技能仍来自 `xlsx_data`。
3. Admin 状态编辑不要直接改 runtime 相关 `xlsx_data` 字段。
4. Host HUD 已读 runtime，补测试防止回退错误。
5. runtime 缺失时允许懒初始化，但要写清是否推进版本。

### 验收命令

```bash
python -m pytest tests/server/test_player_runtime_state.py tests/server/test_host.py tests/server/test_state_security.py -q
```

### 禁止事项

- 不把 runtime HP/SAN 回写覆盖原始角色卡。
- 不让 Player 修改自己的 runtime 数值。

## Batch State-3：直接写库路径收口

### 目标

把已知会改变世界状态的直写路径收口到 StateService 或专门状态服务，并写入事件链。

### 允许改动

- `src/server/player/router_player.py`
- `src/server/router_admin.py`
- `src/server/host/router_host.py`
- `src/server/map_persistence.py`
- `src/server/player/router_clues.py`
- `src/server/agent/tools.py`
- `src/server/engine/state_service.py`
- 相关测试

### 任务

1. retroactive item 的 luck 扣减和 inventory 增加走 StateService。
2. Admin 修改 HP/SAN/status 走 runtime state，并写审计事件。
3. Host 强制移动、节点显示/隐藏走统一 MapState 写入，并同步房间版本。
4. Agent `engine_save_clue` 不再直接插入 clue 后无事件。
5. ready/lobby 类非世界状态变更不滥用 `state_version`。

### 验收命令

```bash
python -m pytest tests/server/test_player_intent.py tests/server/test_retroactive_items.py tests/server/test_state_service.py tests/server/test_state_security.py tests/server/test_clues.py -q
```

### 禁止事项

- 不一次性重构所有路由。
- 不删除现有业务行为，只替换写入路径和事件链。

## Batch State-4：线索、背包、地图状态一致性

### 目标

完善 StateService 的 clue/inventory/map pass-through，让这些变更也有版本、事件、来源引用。

### 允许改动

- `src/server/engine/state_service.py`
- `src/server/player/router_clues.py`
- `src/server/map_persistence.py`
- `src/server/host/router_host.py`
- `tests/server/test_state_service.py`
- `tests/server/test_clues.py`
- `tests/server/test_map.py` 或相关 map 测试

### 任务

1. 修复 `clue_shares` 写入缺 `public_version` 的问题。
2. 线索分享、背包增删、地图探索/显隐/移动都写来源 action 或 actor。
3. map local version 和 room state_version 建立明确映射。
4. `applied` 返回实际变更数量，不把无变化当变更。
5. 每类变更都有 Journal 事件引用。

### 验收命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_clues.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不把私密线索作为 public patch 发送。
- 不让地图隐藏节点信息进入 Player patch。

## Batch State-5：遭遇状态策略

### 目标

明确遭遇状态是否纳入 StateService；若暂不纳入，也要让独立 persistence 有版本和事件语义。

### 允许改动

- `src/server/encounter_persistence.py`
- `src/server/host/router_host.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `tests/server/test_state_service_consistency.py`
- 相关 encounter/combat/chase 测试

### 任务

1. 保持 `encounter_changes` raise 的测试，或实现受控接入并更新测试。
2. 遭遇开始、轮次推进、参与者状态变更、结束都写事件。
3. encounter/participant `version` 字段实际递增。
4. Player/Host 投影不早于遭遇状态落库。
5. Checkpoint 能恢复遭遇和参与者状态。

### 验收命令

```bash
python -m pytest tests/server/test_state_service_consistency.py tests/server/test_resolution_pipeline.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不让 DeepSeek 把 encounter_changes 接入后静默成功。
- 不把遭遇 UI 状态当作权威战斗状态。

## Batch State-6：重连、snapshot 与 checkpoint

### 目标

把断线重连、full snapshot、checkpoint restore 和版本屏障打通。

### 允许改动

- `src/server/player/router_reconnect.py`
- `src/server/player/router_player.py`
- `src/server/events/event_log.py`
- `src/server/engine/state_service.py`
- `tests/server/test_reconnect.py`
- `tests/server/test_event_log.py`
- `tests/server/test_player_runtime_state.py`

### 任务

1. `/api/player/reconnect` snapshot 包含 runtime state 和 stateVersion。
2. missed events 按可见性过滤，不泄露 Host/private 状态。
3. checkpoint snapshot 包含 `character_runtime_state`、`room_scene_state` 和间接关联表。
4. restore 后写审计事件并广播新 snapshot 或版本更新。
5. 客户端版本屏障所需字段在服务端契约中固定。

### 验收命令

```bash
python -m pytest tests/server/test_reconnect.py tests/server/test_event_log.py tests/server/test_player_runtime_state.py tests/server/test_archive.py -q
```

### 禁止事项

- 不把全量 Host snapshot 发给 Player。
- 不在 restore 后留下旧版本 patch 可覆盖新状态。

## Batch State-7：端到端验收

### 目标

验证状态系统支撑完整 AI-Keeper 主链路。

### 手动验收流程

1. Host 创建房间，Player 加入并初始化 runtime state。
2. Player 提交带 `base_state_version` 的行动。
3. Rule/Engine 产生 HP/SAN 或状态标签变化。
4. StateService 先落库，返回新 stateVersion。
5. Projection 发带版本 patch，Host/Player UI 显示一致。
6. Player 断线期间发生状态变化，重连后只应用正确版本。
7. Host 创建 checkpoint，继续变更状态，再 restore。
8. restore 后角色 runtime、场景、地图、背包、线索、日志一致。

### 回归命令

```bash
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_player_runtime_state.py tests/server/test_reconnect.py tests/server/test_projection.py tests/server/test_player_intent.py tests/server/test_event_log.py -q
cd src/client
npm run build
```

## 与其他模块的接口

| 模块 | State 依赖 | DeepSeek 注意点 |
| --- | --- | --- |
| AI-Keeper | AI 输出 mutation 建议。 | 只有 Engine 校验后才能变成 StateChangeSet。 |
| Rule | 提供权威结算结果。 | Rule 结果先转 StateChangeSet，再落库。 |
| Transaction | 定义一次裁决的播放和完成节点。 | State 版本必须和 transaction 绑定。 |
| Projection | 分层投影状态 patch。 | Projection 不应发送未持久化状态。 |
| Journal | 记录 state patch 和 checkpoint。 | 每次状态变更要能追 action/transaction/event。 |
| Player Client | 应用 patch、处理重连。 | 必须实现版本屏障和 patch buffer。 |
| Scene/Map | 地图探索、位置、场景变量。 | 地图局部版本需要和房间版本对齐。 |
| Clue | 线索获得和分享。 | 私密/公开范围由 Clue/Safety 决定，State 只写事实。 |
