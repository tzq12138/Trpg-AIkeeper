# State 世界状态系统 PRD V2.0

## 背景

AI-Keeper 是一个有状态跑团系统。玩家行动、规则结算、AI 建议、Host 操作最终都会改变世界：角色 HP/SAN、状态标签、线索归属、背包、场景、地图、遭遇和房间状态。State 模块负责让这些变化只有一个权威写入路径、有版本、有事件、有恢复能力。

当前代码已经有 `StateService`、`rooms.state_version`、`character_runtime_state`、`room_scene_state`、地图/遭遇 persistence、重连接口和相关测试。但写入路径仍分散，patch 缺少版本字段，部分读接口仍从 `xlsx_data` 读旧状态，必须优先收口。

## 目标

1. 建立房间级权威状态版本，支撑意图冲突检测、patch 顺序和断线重连。
2. 让角色运行时状态从角色卡基线中分离，避免改坏原始 `xlsx_data`。
3. 让 Rule/Engine/AI/Host/Admin 的状态变更都变成受控 `StateChangeSet` 或明确封装路径。
4. 让状态先持久化，再投影给 Host/Player。
5. 让 checkpoint、journal、reconnect 能恢复到一致状态。

## 非目标

1. 不在 State 内决定检定成功失败。
2. 不在 State 内决定 AI 输出是否安全。
3. 不在 State 内决定玩家可见范围。
4. 不在本轮实现分支世界线、多人离线合并、跨房间共享状态。
5. 不把 Host 本地播放状态当作世界权威状态。

## 用户角色

| 角色 | 权限目标 | 不允许 |
| --- | --- | --- |
| Player | 提交意图，读取自己的当前角色状态、背包、线索、同步版本。 | 直接写 HP/SAN、背包、线索或地图位置。 |
| Host/Owner | 通过受控操作调整场景、地图、遭遇、房间状态。 | 绕过审计直接改数据库真相。 |
| Admin | 排查、修复、审计状态异常。 | 无审计地修改玩家私密状态。 |
| AI-Keeper | 产生状态变更建议。 | 直接落库或生成 SQL/patch 后执行。 |
| Engine/Rule | 将结算结果交给 StateService。 | 在多个路径重复 bump 版本或重复投影。 |

## 核心流程

### 角色入房初始化

玩家加入或上传角色后，StateService 从 `characters.xlsx_data` 初始化 `character_runtime_state`。`xlsx_data` 作为角色卡基线，runtime state 作为当前房间即时状态。之后 HP/SAN/MP/Luck/status 变化都读写 runtime state。

### 状态变更应用

Engine/Rule 产生 `StateChangeSet`。StateService 校验房间、应用实际变更、递增版本、写事件、提交事务。只有成功持久化后的版本才能进入 Projection。

### Patch 投影

`s2c_state_patch` 必须携带 `schemaVersion`、`baseStateVersion`、`stateVersion`、`actionId`、`patches`、可见性信息。Projection 按 Host/Player 视角拆分，不应发送未持久化 patch。

### 重连同步

Player 断线后通过 `/api/player/reconnect` 或 `/api/player/sync` 获取 snapshot、recent events、pending actions 和 `stateVersion`。客户端按版本屏障应用 patch：旧 patch 丢弃，未来 patch 缓冲，缺口触发 full sync。

### Checkpoint 和恢复

Checkpoint 必须覆盖房间、角色 runtime、场景、地图、位置、背包、线索、遭遇、日志引用。恢复后写审计事件，并重新广播 snapshot 或版本更新。

## 功能需求

| 编号 | 需求 | 优先级 | 验收 |
| --- | --- | --- | --- |
| ST-FR-1 | 角色 runtime 初始化 | P0 | 玩家入房后 runtime state 存在，重复初始化幂等。 |
| ST-FR-2 | 运行时状态与角色卡分离 | P0 | HP/SAN 变化不修改 `characters.xlsx_data`。 |
| ST-FR-3 | StateChangeSet 权威写入 | P0 | 角色 mutation 经 StateService 应用、clamp、递增版本。 |
| ST-FR-4 | 持久化先于投影 | P0 | patch 投影前状态已落库并获得 `stateVersion`。 |
| ST-FR-5 | Patch 版本字段 | P0 | `s2c_state_patch` 包含 base/current/schema 版本。 |
| ST-FR-6 | Player 同步读 runtime | P0 | `/api/player/sync` 和角色面板返回最新 runtime HP/SAN。 |
| ST-FR-7 | 重连版本屏障 | P0 | snapshot 与 patch 乱序不会重复应用或回滚状态。 |
| ST-FR-8 | 直接写库路径收口 | P1 | retroactive item、admin edit、host map、clue share 有统一写入或豁免说明。 |
| ST-FR-9 | map/clue/inventory 状态事件 | P1 | 变更后有版本、事件和可追溯来源。 |
| ST-FR-10 | Checkpoint 完整性 | P1 | restore 后 runtime、scene、map、inventory、clue、encounter 一致。 |
| ST-FR-11 | 遭遇状态策略 | P1 | encounter 独立版本或纳入 StateChangeSet，行为被测试固定。 |

## 接口方向

| 接口/方法 | 当前状态 | 目标权限 | 说明 |
| --- | --- | --- | --- |
| `StateService.initialize_character_state(character_id, room_id)` | 已有 | 服务端内部 | 从角色卡创建 runtime state。 |
| `StateService.apply_change(room_id, actor, changes, reason)` | 已有 | Engine/Rule/Admin 受控调用 | 应用状态变更并返回 `state_version`、applied、events。 |
| `StateService.get_runtime_state(character_id, room_id)` | 已有 | 服务端内部 | 当前角色状态读模型来源。 |
| `StateService.get_scene_state(room_id)` | 已有 | 服务端内部 | 场景状态读模型来源。 |
| `POST /api/player/intent` | 已有 | Player token | 提交意图时携带 `base_state_version`。 |
| `GET /api/player/sync` | 已有，需增强 | Player token | 返回 runtime state、背包、线索和 stateVersion。 |
| `GET /api/player/reconnect` | 已有，需增强 | Player token | 返回 snapshot 或 missed events，支持版本屏障。 |
| Host/Admin 状态操作 | 多处已有 | Owner/Admin | 需要走 StateService 或专门 state service。 |

## 状态写入边界

| 来源 | 可提交内容 | State 处理 |
| --- | --- | --- |
| RuleExecutor | HP/SAN/MP/Luck、状态标签、背包、线索建议。 | 校验、clamp、落库、写事件。 |
| AI-Keeper | 结构化 mutation 建议。 | 只在 Engine 校验后接收。 |
| Host | 场景切换、地图显示、强制移动、遭遇管理。 | 通过受控服务写状态并审计。 |
| Player | 意图、使用道具、分享线索。 | 先进入业务模块，再由 State/Clue 写入。 |
| Admin | 修复异常状态。 | 写审计事件，避免 silent edit。 |

## 数据边界

1. `characters.xlsx_data` 是角色卡基线，不作为运行时 HP/SAN 权威。
2. `character_runtime_state` 是当前房间角色即时状态。
3. `rooms.state_version` 是房间级状态屏障，不应被纯 UI 事件滥用。
4. 地图局部版本可以存在，但必须能对应房间版本或事件 sequence。
5. checkpoint snapshot 必须包含 runtime 和间接关联表，否则恢复会丢证据链。

## 验收标准

1. 玩家加入后 runtime state 初始化，Host/Player 都显示同一 HP/SAN。
2. 玩家行动结算后，StateService 先持久化状态，再发带版本的 patch。
3. 同一状态变化不会产生重复 patch 或重复扣减。
4. 断线重连后，旧 patch 被丢弃，新 patch 按版本应用。
5. retroactive item、admin edit、host map 操作不再绕过状态版本和事件链。
6. Checkpoint restore 后，角色、场景、地图、线索、背包、遭遇状态一致。
7. AI 不能直接把 mutation 写入数据库。
