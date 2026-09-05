# State 世界状态系统 PRD V2.1

## 当前阶段

本 PRD 对应的是：

- `P0 主链路 + 权威状态写入与版本屏障风险识别版`
- 不是 State 模块的最终生产完成版
- 重点修正版本语义、写入时序、重连屏障、checkpoint/restore 和直写路径收口

## 背景

AI-Keeper 不是无状态聊天产品，而是一个持续演进的跑团世界。玩家行动、规则结算、Host 操作、地图探索、线索分享、背包变化都会改写房间当前事实。State 模块的目标不是“保存一些字段”，而是把这些变化收敛为：

- 一条可信的权威写入路径
- 一套明确的版本屏障
- 一组能投影、能重连、能审计、能恢复的状态契约

当前仓库已经具备以下基础：

- `StateService.apply_change()` 与 `StateChangeSet`
- `rooms.state_version`
- `character_runtime_state`
- `room_scene_state`
- 地图、线索、encounter 的独立 persistence
- `/api/player/sync`、`/api/player/reconnect`
- checkpoint 创建与 restore 接口

但当前仍存在明显缺口：

- action 入队和空变更也会推进 `rooms.state_version`
- 裁决链路仍可能先投影后落库
- patch 未固化 `schemaVersion/baseStateVersion/stateVersion`
- 重连 snapshot 缺少 `snapshotStateVersion` 契约
- checkpoint 未完整覆盖 runtime / scene / 房间版本
- 后台、地图、retroactive item 仍有多条直写路径

## 产品目标

1. 建立房间级权威状态版本，作为意图冲突、patch 顺序和重连屏障的唯一基线。
2. 把角色当前状态从 `characters.xlsx_data` 中分离，固定 `character_runtime_state` 为房间内实时状态真相。
3. 让 Rule / Engine / Host / Admin 的状态变化都经过统一写入服务或明确受控的专项状态服务。
4. 保证“先持久化，后投影”，不向 Player / Host 投递未落库 patch。
5. 让 reconnect、checkpoint、restore、Journal 引用围绕同一套状态版本语义工作。

## 非目标

1. 不在 State 内决定检定成功失败。
2. 不在 State 内判断 AI 输出是否可信。
3. 不在 State 内决定玩家可见性和防剧透裁剪。
4. 不在本轮完成多分支世界线、离线冲突合并、跨房间共享世界状态。
5. 不把 Host 舞台播放态、Lobby ready、action 队列态直接当成世界真相版本。

## 用户角色

| 角色 | 权限目标 | 不允许 |
| --- | --- | --- |
| Player | 提交意图，读取自己可见的当前状态、背包、线索、同步版本 | 直接改 HP/SAN、库存、线索、地图位置 |
| Host / Owner | 通过受控操作调整场景、地图、encounter、房间内事实 | 绕过审计和服务层直写真相 |
| Admin | 排障、修复异常状态、查看审计 | 无审计地静默修改玩家当前状态 |
| AI-Keeper | 生成状态变化建议 | 直接落库或发 SQL / JSON Patch |
| Engine / Rule | 把权威结算结果交给 State | 在多处重复 bump 版本或重复投影 |

## 状态数据分层

| 层级 | 数据对象 | 含义 | 关键边界 |
| --- | --- | --- | --- |
| L0 | `rooms.state_version` | 房间权威状态版本 | 只由世界真相变化推进 |
| L1 | `character_runtime_state` | 房间内角色实时状态 | `xlsx_data` 不再是当前 HP/SAN 权威来源 |
| L2 | `room_scene_state` | 场景推进事实 | 不承载隐藏真相全文 |
| L3 | `room_map_state` / `character_map_positions` | 地图探索与位置 | 需与房间状态版本或事件序列可对齐 |
| L4 | `clues` / `clue_shares` / `inventory` | 线索与物品事实 | 可见性由其他模块决定 |
| L5 | `AppliedStateChange` / `s2c_state_patch` | 对外状态变化契约 | 必须来自已落库状态 |
| L6 | `StateSnapshot` | 重连或恢复快照 | 需要携带快照版本 |
| L7 | `CheckpointState` | checkpoint 归档与 restore 基线 | restore 形成新历史分支 |
| L8 | Journal / Audit 引用 | 事件序列、事务引用、恢复审计 | 记录证据，不替代写入 |

## DTO 契约

### 1. `StateChangeSetDTO`

用于提交一次逻辑状态变化请求。最低字段：

- `characterMutations[]`
- `sceneChanges?`
- `mapChanges?`
- `clueChanges?`
- `inventoryChanges?`
- `encounterChanges?`
- `roomChanges?`
- `reason?`
- `sourceRefs?`

边界：

- 可以承载“建议的状态变化”
- 不能直接等价于已应用事实
- `encounterChanges` 在第一轮若未接入，必须继续明确拒绝

### 2. `StateChangeItemDTO`

用于表示单条状态变化单元。最低字段：

- `domain`
- `targetId`
- `op`
- `path`
- `value`
- `visibilityHint?`
- `sourceRefs?`

用途：

- 统一 Character / Scene / Map / Clue / Inventory 的内部变化描述
- 便于专项服务返回统一结果

### 3. `AppliedStateChangeDTO`

用于描述一次已经落库成功的状态变化结果。最低字段：

- `roomId`
- `baseStateVersion`
- `stateVersion`
- `appliedChanges[]`
- `eventRefs[]`
- `transactionId?`
- `noOp`
- `projectionReady`

边界：

- 只有真正写入成功后才能产生
- `noOp=true` 时默认不推进 `stateVersion`
- Projection 与 Journal 只消费它，不反推数据库写入
- `eventRefs[]` 作为统一命名，第一轮最小可只包含 `sequence`，后续可扩展 `eventType`、`sourceRefs`

### 4. `StatePatchDTO`

用于 Player / Host 的状态补丁投影。最低字段：

- `schemaVersion`
- `roomId`
- `actionId?`
- `transactionId?`
- `baseStateVersion`
- `stateVersion`
- `patches[]`
- `sourceRefs?`

边界：

- 不得缺少版本字段
- 不得代表未持久化的“临时结果”
- 私密 patch 必须依赖 Projection / Safety 分层后再下发

### 5. `StateSnapshotDTO`

用于 `/api/player/sync`、`/api/player/reconnect` 等全量同步。最低字段：

- `roomId`
- `snapshotStateVersion`
- `runtimeCharacters[]`
- `sceneState?`
- `mapState?`
- `positions?`
- `inventory[]`
- `ownedClues[]`
- `sharedClues[]`
- `pendingActions[]`

边界：

- `snapshotStateVersion` 是客户端丢弃旧 patch 的基线
- 玩家 snapshot 只包含玩家可见事实，不得携带 Host 全量状态
- `ownedClues[]` 可包含本人私密线索的安全 DTO
- `sharedClues[]` 只允许包含共享后的 `publicVersion` 或等价安全字段，不得把他人 `clues.text` 原文直接带给队友

### 6. `RuntimeCharacterStateDTO`

最低字段：

- `characterId`
- `roomId`
- `hp`
- `hpMax`
- `san`
- `sanMax`
- `mp`
- `mpMax`
- `luck`
- `statusTags[]`
- `tempModifiers`
- `version`

边界：

- 是房间内实时状态真相
- 不得把长期角色卡字段、token、账号敏感信息混入其中

### 7. `StateConflictDTO`

最低字段：

- `roomId`
- `providedBaseStateVersion`
- `currentStateVersion`
- `conflictType`
- `retryHint`

用途：

- 用于意图提交冲突、补丁乱序、客户端 full sync 触发说明

### 8. `CheckpointStateDTO`

最低字段：

- `checkpointId`
- `roomId`
- `snapshotStateVersion`
- `scope`
- `createdAt`
- `includes[]`
- `knownLimitations[]`

边界：

- restore 后不解释为“删掉旧历史”
- restore 的产品语义是“从某个 checkpoint 开出新历史分支”
- 工程回执必须显式填写 `includes[]` 与 `knownLimitations[]`

## `rooms.state_version` 语义

第一轮 PRD 固定如下：

1. `rooms.state_version` 是房间世界真相版本，不是房间所有事件计数器。
2. 只有权威世界状态变化才会推进它，包括：
   - runtime 数值 / 状态标签变化
   - 场景状态变化
   - 地图探索 / 显隐 / 位置变化
   - 线索归属 / 分享事实变化
   - 背包事实变化
   - 明确纳入 State 的房间内真相状态变化
3. 以下内容不应推进它：
   - action 入队
   - ready / lobby / join / typing / chat
   - heartbeat / no-op
   - 纯日志、纯投影、纯 UI 状态

## `StateService.apply_change()` 事务契约

目标契约如下：

1. 读取并锁定当前 `rooms.state_version`。
2. 校验 room 是否存在、调用方是否合法、`expectedStateVersion?` 是否冲突。
3. 计算实际会落库的变化集。
4. 若没有实际变化，返回 `AppliedStateChangeDTO(noOp=true)`，默认不 bump 版本。
5. 若有实际变化：
   - 在同一事务内写 runtime / scene / map / clue / inventory 等状态
   - 成功后推进 `rooms.state_version`
   - 记录所需事件序列或返回供 Projection 写事件的 payload
6. 提交事务。
7. 事务成功后，Projection 才能按 `AppliedStateChangeDTO` 对外投影。

当前代码现状要点：

- 现在是进入 `apply_change()` 就先 bump 版本
- `_get_or_create_runtime()` 会调用 `initialize_character_state()`，而后者当前独立 commit
- 这意味着当前还不满足“同一事务内完整应用”的目标契约

阶段边界补充：

- Player intent 的 `base_state_version` 校验属于 P0，必须保留
- `expectedStateVersion?` 的服务层乐观锁在第一轮可暂不强制用于所有 Host / Admin 写入
- 但如果 Host / Admin 当前暂不校验 `expectedStateVersion?`，也必须：
  - 写审计
  - 返回最新 `stateVersion`
  - 在工程回执中明确说明哪些路径尚未接入乐观锁

## 空变更 / no-op 策略

第一轮固定如下：

- `StateChangeSet` 为空，或所有变化都因幂等 / clamp / 重复写入而未产生实际变化时：
  - 返回 `noOp=true`
  - 默认不推进 `rooms.state_version`
  - 默认不生成 `s2c_state_patch`
- 如未来需要 heartbeat / keepalive，应使用专门事件类型，而不是世界状态 patch

## runtime 初始化策略

第一轮固定如下：

1. 推荐初始化入口：
   - 玩家 join 房间后
   - 角色绑定房间后
   - 开局前预热阶段
2. `GET /api/player/sync`、`GET /api/player/reconnect`、普通读取接口不应因为“读不到 runtime”而静默写库。
3. 若保留 lazy init，必须满足：
   - 同一事务内完成
   - 明确说明是否推进房间版本
   - 不允许在纯读取接口里偷偷创建新状态

## 直写路径收口与豁免

### 必须收口

- `src/server/engine/engine.py` action 入队 bump 房间版本
- `src/server/player/router_player.py` retroactive item 直接改 luck / inventory / room version
- `src/server/router_admin.py` 直接改 `characters.xlsx_data`
- `src/server/host/router_host.py` 主持人地图强制移动 / reveal 的版本与事件链

### 可暂时保留专项服务，但必须统一结果契约

- Map
- Clue
- Inventory

即便不全部改成 `StateService` 一处处理，也必须统一返回：

- `AppliedStateChangeDTO`
- `stateVersion` 或明确的 room version 映射
- `eventRefs` / `sourceRefs`

其中 Map 路径必须额外说明：

- 地图探索 / 显隐 / 位置变化是否推进 `rooms.state_version`
- 如果保留 map local version，如何映射到 room `stateVersion` 或事件序列
- Player / Host 如何用该映射完成 patch 乱序屏障

### 明确豁免

- `ready_toggle`
- lobby 成员变化
- 纯聊天和纯舞台态

这些属于 Room / Channel / Host Client 范畴，不进入世界状态版本。

## Encounter 状态策略

第一轮明确如下：

1. 当前 `encounter_changes` 继续保持显式拒绝。
2. `StateService.apply_change()` 不允许对 `encounter_changes` 静默成功。
3. Encounter 若暂不接入统一状态写入，也必须在文档和测试中固定为：
   - 独立 persistence
   - 独立状态语义
   - restore 是否覆盖，必须在回执中明确说明

## 重连与版本屏障

### 服务端职责

1. `/api/player/reconnect` 返回的 snapshot 必须带 `snapshotStateVersion`。
2. missed events / recent events 必须复用玩家可见性 helper，不得返回整房间 Host / private 事件。
3. 如果发现版本缺口无法可靠补齐，应明确返回需要 full sync。
4. `/api/player/sync` 返回的当前状态必须来自 runtime / read model，而不是旧 `xlsx_data`。

### 客户端职责

1. 收到 `StatePatchDTO` 时：
   - 若 `baseStateVersion == currentVersion`，正常应用
   - 若 `baseStateVersion < currentVersion`，丢弃旧 patch
   - 若 `baseStateVersion > currentVersion`，先缓冲并请求 full sync
2. 收到 snapshot 后：
   - 把本地版本设置为 `snapshotStateVersion`
   - 丢弃 `baseStateVersion <= snapshotStateVersion` 的旧 patch
   - 按顺序应用剩余 patch

## Checkpoint / Restore 语义

第一轮固定如下：

1. restore 必须要求 `confirm=true + reason`。
2. restore 完成后必须写 `s2c_checkpoint_restored` 审计事件。
3. restore 的产品语义不是“删掉旧历史”，而是“从某个 checkpoint 恢复出新的历史分支”。
4. Player 不应收到 Host 全量 snapshot；如需通知玩家，应发送安全摘要或全量安全 snapshot。
5. checkpoint 最小覆盖范围至少应包含：
   - `rooms` 中与当前房间事实相关的字段，包括 `state_version`
   - `character_runtime_state`
   - `room_scene_state`
   - `room_map_state`
   - `character_map_positions`
   - `inventory`
   - `clues`
   - `clue_shares`
   - `room_turns`
   - 需要时的 `encounters` / `encounter_participants`

## 接口方向

| 接口 / 方法 | 当前现状 | 目标权限 | 说明 |
| --- | --- | --- | --- |
| `StateService.initialize_character_state(character_id, room_id)` | 已有 | 服务端内部 | 角色 runtime 初始化入口 |
| `StateService.apply_change(room_id, actor, changes, reason)` | 已有 | Engine / Rule / Admin 受控调用 | 应返回 `AppliedStateChangeDTO` |
| `StateService.get_runtime_state(character_id, room_id)` | 已有 | 服务端内部 | 当前角色状态读模型 |
| `StateService.get_scene_state(room_id)` | 已有 | 服务端内部 | 场景状态读模型 |
| `POST /api/player/intent` | 已有 | Player token | 携带 `base_state_version` |
| `GET /api/player/sync` | 已有，需增强 | Player token | 返回 `StateSnapshotDTO` |
| `GET /api/player/reconnect` | 已有，需增强 | Player token | 返回可见事件和 `snapshotStateVersion` |
| `POST /api/archive/{room_id}/restore/{checkpoint_id}` | 已有，需增强 | Owner / Admin | 维持 `confirm + reason`，收紧 restore 输出 |

## 权限边界

1. Player 只能提交意图，不能直接提交权威状态 patch。
2. Host 可以触发受控状态操作，但必须写审计。
3. Admin 可以修复异常状态，但不得无审计静默改真相。
4. AI 只能给出建议，不能直接调用状态落库路径。
5. Projection 只能投影已确认状态，不能反过来当写入入口。

## 验收标准

1. action 入队、ready_toggle、聊天事件不再推进 `rooms.state_version`。
2. 真实状态变化只推进一次 `rooms.state_version`。
3. 空 `StateChangeSet` 默认不 bump 版本。
4. runtime HP/SAN/MP/Luck 的当前值读取自 `character_runtime_state`。
5. `s2c_state_patch` 至少带 `schemaVersion/baseStateVersion/stateVersion/actionId`。
6. 裁决链路先写 State，再对 Host / Player 投影。
7. reconnect 的 snapshot / patch 具备明确版本屏障。
8. `/api/player/reconnect` 不返回 Host-only 或其他玩家 private 事件。
9. checkpoint restore 后 runtime、scene、map、inventory、clue 与版本基线保持一致。
10. restore 审计事件只给 Host / Admin，不把原始 restore payload 下发给 Player。
11. `encounter_changes` 若仍未接入，必须继续显式报错而不是静默成功。
12. AI / Player / Host 都不能绕过 State 把建议直接写成权威状态。
