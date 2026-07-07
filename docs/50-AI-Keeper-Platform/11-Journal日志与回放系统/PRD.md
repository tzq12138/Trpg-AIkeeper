# Journal 日志与回放系统 PRD V2.1

## 当前阶段

本 PRD 对应的不是“完整平台版 Journal”，而是：

- `P0 主链路 + Journal 可见性与导出安全风险识别版`
- 面向工程执行的第一轮边界文档
- 重点解决事件可见性不统一、导出脱敏不够、checkpoint 恢复语义不清、AI/Ops 审计边界未钉死的问题

## 背景

AI-Keeper 的核心价值不只是“AI 会讲故事”，而是让每一次玩家输入、规则裁决、状态变更、分层投影和房间演出都能留下可追溯记录。

当前仓库已经具备：

- `events` 事件流水
- Host timeline 与日志入口
- Player archive
- checkpoint 创建 / 恢复
- campaign archive
- Markdown / JSON export

但这些能力的权限与视角边界仍然分散在不同路由、查询和导出逻辑中。Journal v1 的目标不是增加更多花哨回放，而是先把“谁能看到什么、什么能导出、恢复后历史怎么解释”这三件事做扎实。

## 产品目标

1. 让每条主链路事件都能以 `room_id + sequence` 被稳定追踪。
2. 为 Host 提供完整、可审计、可回放的房间时间线。
3. 为 Player 提供只包含授权内容的私人档案与公开剧情历史。
4. 为 `public export` 与 `full export` 建立明确字段白名单。
5. 为 checkpoint / restore 建立一致、可解释、可审计的产品语义。
6. 把 raw AI 调用日志、运维审计和玩家可见 Journal 彻底分层。

## 非目标

1. 不在 Journal 中执行规则裁决。
2. 不在 Journal 中直接修改世界状态、角色数值或真相层。
3. 不把 Admin/Ops 的 raw 调试日志暴露给玩家。
4. 不在本轮实现多媒体回放、社区公开战报编辑器、复杂全文搜索。
5. 不把 Host 全知视角直接等价为 public / 玩家可见视角。

## 用户角色

| 角色 | 目标 | 不允许做什么 |
| --- | --- | --- |
| Host / Owner | 查看房间完整日志、创建与恢复 checkpoint、导出 full、结束归档 | 绕过 Engine / State 直接改真相 |
| Admin | 安全排障、权限审计、运维查看 | 把 host-only / AI debug 内容下发给玩家 |
| Player | 查看公开历史、自己的行动 / 检定 / 线索、读取 public export | 查看他人私密事件、未发现线索、host-only 审计 |
| Observer | 未来只读公开视角 | 读取 private / host-only 事件 |
| AI-Keeper | 在授权范围内读取历史摘要 | 读取未授权私密事件或把 raw prompt 暴露到 Journal |

## 模块边界

### Journal 负责

- 记录权威事件流水
- 生成 Host timeline、Player archive、public event stream
- 提供 checkpoint / restore 审计断点
- 提供 campaign summary 与 export 的分层视图
- 串起 source reference，支持“这件事为何发生”的追溯

### Journal 不负责

- 决定行动是否合法
- 生成最终规则结算
- 直接写世界状态
- 判断线索是否应当被发现
- 替代 Admin/Ops 保存 raw AI 调用日志

## 数据分层模型

| 层级 | 数据对象 | 描述 | 权限 |
| --- | --- | --- | --- |
| L0 | `events` | Journal 权威底层事件表 | 内部源，不直接裸暴露 |
| L1 | `HostTimelineView` | Host 审计视图，保留完整可追溯上下文 | Owner / Admin |
| L2 | `PlayerArchiveView` | 玩家档案视图，只含玩家可见事件 | 当前 Player |
| L3 | `PublicEventView` | 公开事件流 / 公开战报数据 | public / observer / 玩家公开视角 |
| L4 | `CheckpointSnapshot` | 可恢复状态快照 | Owner / Admin |
| L5 | `CampaignArchive` | 结团 summary / highlights / arcs | 分 public / full |
| L6 | `ExportPackage` | Markdown / JSON 导出包 | 分 `public` / `full` |
| L7 | `AI/Ops Audit` | `ai_call_logs`、`spoiler_audits` 等排障数据 | Admin / Ops only |
| L8 | `SourceReferenceChain` | action / transaction / state / clue / map / turn 引用链 | Host 全量，Player 仅安全摘要 |

## DTO 契约

### 1. `JournalEventDTO`

用于服务端标准化 Journal 事件。

必需字段：

- `roomId`
- `sequence`
- `eventType`
- `audience`
- `issuedAt`
- `payload`

禁止字段：

- `owner_token`
- `player_token`
- API key
- raw AI prompt / raw AI response

### 2. `HostJournalEventDTO`

在 `JournalEventDTO` 基础上可增加：

- `sourceRefs`
- `stateVersion`
- `transactionId`
- `debugMeta?`

但即便是 Host 视角，也不应直接透出完整 secret。

### 3. `PlayerArchiveEventDTO`

只允许包含：

- `sequence`
- `eventType`
- `issuedAt`
- `safeText`
- `safePayload`
- `sourceRefs?`

不得包含：

- 他人私密 payload
- host-only 审计 reason
- 未授权 clue 原文

### 4. `PublicExportEventDTO`

只允许包含：

- `sequence`
- `eventType`
- `publicText`
- `publicPayload`
- `issuedAt`

不得包含：

- token
- 账号 ID / 邮箱
- 原始 `xlsx_data`
- 世界真相字段
- raw prompt / raw response

### 5. 其他 DTO

| DTO | 用途 | 最低字段 |
| --- | --- | --- |
| `CheckpointDTO` | checkpoint 列表 / 恢复摘要 | `checkpointId`、`roomId`、`createdAt`、`createdBy`、`reason`、`snapshotMeta` |
| `CampaignSummaryDTO` | 战役归档摘要 | `ending`、`highlights`、`characterArcs`、`publicClues` |
| `ExportPackageDTO` | 导出包 | `scope`、`generatedAt`、`roomSummary`、`events`、`characters?`、`clues?` |

## 可见性策略

Journal 必须与 `10-Timeline时间轴系统` 共享同一套可见性语义。

### 事件视角分类

- `host`
- `party`
- `player:self`
- `player:other`
- `system_safe`
- `admin_audit`

### 规则

1. Host timeline 可以读取房间内完整 Journal 事件，但仍不直接等于 Admin/Ops raw 日志。
2. Player archive 只能读取：
   - `party`
   - 明确进入 public/system 白名单的 `system_safe`
   - 归属于当前角色自己的私密事件
3. `player:other` 永远不能出现在当前玩家 archive 中。
4. 私密事件缺少 `characterId`、`recipientCharacterId` 等归属字段时，默认不下发给玩家。
5. `public events`、`player archive`、`replay`、`export` 必须复用同一个服务端 helper。
6. 所有查询、补发、回放、导出都以 `room_id + sequence` 为边界。

## 核心用户故事

### 1. Host 审计

作为 Host，我希望在一条时间线上看到：

- 玩家何时提交了行动
- 系统如何结算
- 哪些状态发生了变化
- 地图 / 线索 / 回合何时更新
- checkpoint 在哪里创建、何时恢复

这样我才能复盘争议、回滚事故、解释现场演出。

### 2. Player 私人档案

作为玩家，我希望看到：

- 我自己的行动和结果
- 我的检定结果
- 我已发现、已分享或公开的线索
- 队伍公开发生过的关键剧情

但我不应该看到别人的私密行动、Host 审计、未发现线索或模组真相。

### 3. 安全导出

作为 Host，我希望能导出房间记录给玩家或归档，但系统必须自动帮我避免：

- token 泄露
- raw AI prompt 泄露
- 剧透字段泄露
- 角色卡原始私密数据泄露

### 4. checkpoint 恢复

作为 Host，我希望在出现错误状态时恢复到 checkpoint，并且：

- 恢复动作可审计
- 恢复理由被记录
- 时间线断点可解释
- 不会误让玩家拿到 host-only 恢复理由或 snapshot 内容

### 5. 结团归档

作为房间系统，我希望在战役结束时生成 summary / highlights / arcs，但 public 版本必须只基于玩家已知事实。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| JR-FR-1 | 所有主链路事件都必须沉淀为可查询 Journal 记录 | P0 |
| JR-FR-2 | Host 可按 `room_id + sequence` 查询完整 timeline | P0 |
| JR-FR-3 | Player archive 只返回玩家可见事件 | P0 |
| JR-FR-4 | public events、archive、export、replay 必须共用统一可见性 helper | P0 |
| JR-FR-5 | `public export` 与 `full export` 必须走字段白名单，不允许底表直出 | P0 |
| JR-FR-6 | `GET /campaign` 必须做权限分层，public 与 full 摘要分开 | P0 |
| JR-FR-7 | restore 必须要求 `confirm=true + reason`，并写新的 restore 审计 marker | P0 |
| JR-FR-8 | restore 后历史语义必须解释为“从 checkpoint 恢复出的新历史分支” | P1 |
| JR-FR-9 | checkpoint 快照必须逐步补齐 `clue_shares`、`encounter_participants` 等间接表 | P1 |
| JR-FR-10 | checkpoint / turn / map / clue / campaign 等事件定义必须在 registry 与前端类型中对齐 | P1 |
| JR-FR-11 | 关键事件必须保留 source reference chain | P1 |
| JR-FR-12 | raw AI 调用日志与 spoiler audit 必须留在 Admin/Ops 层，`never_export` | P0 |

## 导出策略

### `public export`

可包含：

- 房间公开信息
- 玩家可见事件
- 已公开线索摘要
- 脱敏后的角色摘要
- 公开结局与公开高光

禁止包含：

- `owner_token`
- `player_token`
- `account_id`
- email / 外部账号标识
- 原始 `xlsx_data`
- 未公开 clue 原文
- `raw_text`
- 世界真相字段
- `original_file_path`
- host-only payload
- admin/debug payload
- raw AI prompt / raw AI response

### `full export`

`full export` 不是“数据库原样导出”，而是“Host / Admin 可读的完整业务导出”。

它可以比 public 更完整，但仍禁止导出：

- raw token
- API key
- 明文 secret
- raw AI prompt / raw AI response
- 账号敏感字段
- 仅供运维排障的审计日志

## checkpoint / restore 语义

Journal 必须与 `10-Timeline时间轴系统` 保持一致：

1. restore 不重写旧历史的产品解释。
2. 当前实现允许 restore 重插 snapshot 内事件，因此旧 `sequence` 不保留。
3. 产品语义定义为：`从某个 checkpoint 恢复出新的历史分支`。
4. restore 后必须写新的 `s2c_checkpoint_restored` 审计 marker。
5. 若需要通知玩家，应另发 `party-safe` 摘要事件，不能复用原始 restore 审计 payload。
6. restore 接口必须要求 `confirm=true + reason`。

### restore 审计事件建议字段

- `checkpointId`
- `actorAccountId`
- `reason`
- `restoreMode`
- `restoredTables`
- `createdAt`

## 事件来源引用契约

| 事件类别 | 必须带的引用字段 |
| --- | --- |
| 行动类 | `actionId`、`characterId`、`intentType`、`turnId` |
| 检定类 | `actionId`、`ruleCheckId`、`rolls` |
| 状态类 | `transactionId`、`stateVersion`、`patchScope` |
| 线索类 | `clueId`、`sourceEventSequence`、`ownerCharacterId`、`sharedBy`、`sharedTo` |
| 地图类 | `mapId`、`sceneId`、`transactionId` |
| 回合类 | `turnId`、`transactionBatchId`、`stateVersion` |
| checkpoint 类 | `checkpointId`、`sourceSequence`、`reason` |
| campaign 类 | `archiveId`、`sourceSequences[]` |

## AI / Ops 审计边界

以下内容属于 `Admin/Ops`，不属于 Player Journal，也不属于 public export：

- `ai_call_logs` 中的 raw prompt
- `ai_call_logs` 中的 raw response
- provider trace / token 用量明细
- `spoiler_audits`
- 内部调试事件

这些字段统一标记为：

- `never_export`
- `admin_only`

如果 Journal 需要引用 AI 行为，只能引用安全摘要，例如：

- 调用了哪个能力
- 返回了什么“经安全裁剪后的结果类型”
- 引用了哪些已授权 source refs

## 接口方向

| 接口 | 当前状态 | 目标权限 | 说明 |
| --- | --- | --- | --- |
| `GET /api/rooms/{room_id}/events` | 已有 | Owner / Admin | 房间全量事件 |
| `GET /api/rooms/{room_id}/events/public` | 已有，需收紧 | Room Player / Observer | 仅返回 public / `system_safe` |
| `GET /api/rooms/{room_id}/timeline` | 已有 | Owner / Admin | Host 时间线 |
| `GET /api/rooms/{room_id}/timeline/{sequence}` | 已有 | Owner / Admin | 单事件详情 |
| `POST /api/rooms/{room_id}/checkpoint` | 已有 | Owner / Admin | 创建 checkpoint |
| `GET /api/rooms/{room_id}/checkpoints` | 已有 | Owner / Admin | checkpoint 列表 |
| `POST /api/rooms/{room_id}/restore/{checkpoint_id}` | 已有，需加 `reason` | Owner / Admin | 恢复 checkpoint |
| `GET /api/player/archive` | 已有 | Player | 玩家可见档案 |
| `GET /api/player/archive/actions` | 已有 | Player | 玩家行动档案 |
| `GET /api/player/archive/clues` | 已有 | Player | 玩家线索档案 |
| `GET /api/player/archive/skill-checks` | 已有 | Player | 玩家检定档案 |
| `GET /api/rooms/{room_id}/campaign` | 已有，需加鉴权 | Player public / Owner full | 战役摘要 |
| `POST /api/rooms/{room_id}/end` | 已有 | Owner / Admin | 结团归档 |
| `GET /api/rooms/{room_id}/export` | 已有，需脱敏 | `public: Player` / `full: Owner/Admin` | Markdown / JSON 导出 |

## 验收标准

1. Host 能按 `room_id + sequence` 查看完整 Journal 事件，并能定位行动、检定、状态 patch、地图更新、回合完成与 checkpoint。
2. Player archive 只返回公开事件与自身私密事件，无法读取他人私密事件。
3. public events、Player archive、public export 三个口径使用同一套服务端可见性规则。
4. 未授权请求无法读取 checkpoint、full export、Host timeline、full campaign summary。
5. public export 不包含 token、未公开 clue、世界真相、raw AI prompt/response、host-only payload。
6. restore 必须要求 `confirm=true + reason`，并写新的 restore 审计 marker。
7. restore 后 Journal 能解释时间线断点，不把“旧 sequence 消失”误描述成“历史被抹除”。
8. `ai_call_logs`、`spoiler_audits` 不进入 Player Journal 与 public export。
