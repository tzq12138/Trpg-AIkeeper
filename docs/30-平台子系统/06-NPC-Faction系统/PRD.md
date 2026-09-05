# NPC / Faction 系统 PRD 初版

## 目标

NPC / Faction v1 的目标是让剧本里的 NPC 能被稳定抽取、查询、引用和防剧透，并在必要时作为遭遇临时参与者进入战斗或追逐链路。

第一轮成功标准是：

- 导入剧本后形成可引用的 NPC 基础档案。
- AI 在授权上下文里能扮演相关 NPC，但不会把隐藏身份、秘密目标直接投给玩家。
- 玩家只看到已公开或已解锁的 NPC 摘要。
- 隐藏 NPC 不会通过地图、RAG、公共事件或普通 DTO 提前泄露。
- Host 可以把临时敌人加入遭遇并完成基础回合流转。

当前阶段说明：

- 本 PRD 已可进入工程执行，但当前阶段仍是`P0 主链路 + NPC 可见性风险识别版`。
- 文档已识别 `npc_id` 不稳定、字段级 visibility 不足、RAG room/scenario entitlement、地图节点 DTO、隐藏 NPC 解锁、临时 NPC 与长期 NPC 混用、Faction 范围膨胀等问题。
- 文档完成不等于代码风险已关闭；只有后续工程批次与测试通过后，这些边界才算真正落地。

## 产品边界

包含：

- 剧本结构化中的 NPC 列表。
- NPC 与场景、地图节点、RAG、AI 工具、防剧透索引的连接。
- 玩家已知 NPC 与隐藏 NPC 的可见边界。
- 遭遇中的临时 NPC/敌人参与者。
- NPC 公开出现、身份揭示、秘密揭示和日志引用的事件口径。
- NPC 与 Faction 的最小引用关系口径。

不包含：

- 完整 NPC 数据库编辑器。
- 完整 Faction 组织经营、资源经济和政治模拟。
- NPC 自动行动日程。
- 怪物图鉴和完整战棋怪物系统。
- AI 生成 NPC 后直接入库成为事实。
- 玩家可自由查看全部 NPC 关系网。

## 用户角色

| 角色 | 权限 |
|---|---|
| Player | 查看已公开或已发现的 NPC 摘要，通过行动与 NPC 互动 |
| Host | 查看剧本 NPC 摘要、隐藏标记、当前场景 NPC 和遭遇临时 NPC |
| Admin / Module Author | 导入剧本、查看质量报告、重建 RAG 或防剧透索引 |
| AI-Keeper | 读取裁剪后的 NPC 上下文，生成 NPC 反应和叙事建议 |
| Engine / State / Journal | 确认 NPC 状态变化、公开出现、线索释放和事件日志 |

## 数据分层

| 层 | 来源 | 作用 | 禁止混用 |
|---|---|---|---|
| 剧本 NPC 资产 | `scenarios.knowledge_graph.npcs[]` | 长期 NPC 档案、AI/RAG/防剧透的基础源头 | 不等于房间运行态 |
| 场景 NPC 引用 | `scenario_assets.scenes[].npcs_present` | 场景中可能出现的 NPC 引用 | 不等于玩家已知 NPC |
| 地图 NPC 引用 | `scenario_maps.nodes[].npcsPresent` | 节点级 NPC 提示 | 不等于可直接展示给玩家 |
| RAG NPC chunk | `document_chunks(source_type='npc')` | AI 检索知识片段 | 不等于 player-facing 可见文本 |
| 防剧透敏感项 | `spoiler_sensitive_items(category='hidden_npc')` | 隐藏 NPC 名称、别名、身份、描述片段 | 不等于已公开 NPC |
| 玩家已知 NPC DTO | 公开事件 / 探索 / 线索派生 | 玩家可见摘要 | 不返回完整 NPC 档案 |
| Host NPC DTO | 剧本摘要 + 隐藏标记 + 授权字段 | Host 运营视角 | 不直接推进世界事实 |
| 遭遇临时 NPC | `encounter_participants.character_id='npc:{uuid}'` | 战斗/追逐临时参与者 | 不写入 Character，不升级成长期 NPC 档案 |
| Faction 草案 | WorldBook / Timeline 后续承接 | 势力关系、势力 lore、后续时钟 | 不在本轮做成完整系统 |

## NPC schema 方向

当前代码里没有独立 `npcs` 主表，v1 仍以 `knowledge_graph.npcs[]` 为主。

后续最小 schema 方向：

| 字段 | 说明 |
|---|---|
| `npc_id` | 稳定 ID，优先作为 reveal、RAG metadata、地图引用、玩家摘要的主键 |
| `public_name` | 玩家和公共投影可见称呼 |
| `name` / `true_name` | Host / truth 层真实名 |
| `role` / `type` | 剧情定位、怪物、组织成员等 |
| `public_description` | 玩家可见描述 |
| `description` | Host / AI 可见详细描述 |
| `personality` | AI 扮演依据 |
| `motivation` | AI 扮演依据 |
| `secret_goal` | truth 层字段 |
| `aliases` | 别名、化名、伪装称呼 |
| `scene_refs` | 关联场景 |
| `clue_refs` | 关联线索 |
| `faction_refs` | 关联势力 |
| `is_hidden` | 整体默认策略标记 |
| `visibility` | 字段级可见性配置或默认派生规则 |

`npc_id` 要求：

- 如果 AI 结构化结果已给 `npc_id`，优先沿用。
- 如果 AI 未给 `npc_id`，系统应生成稳定 ID。
- 建议最小生成规则：基于 `scenario_id + normalized_name + role/type` 生成稳定 hash。
- 名字只作为展示字段，不应成为唯一主键。

## 字段可见性方向

`is_hidden` 只能作为整体默认策略，不能替代字段级 visibility。

最小 visibility 口径建议：

- `public`
- `known`
- `host`
- `ai_only`
- `truth`
- `neverPlayer`

字段默认建议：

| 字段 | 默认可见性 |
|---|---|
| `public_name` | `public` |
| `public_description` | `public` |
| `name` / `true_name` | `host` 或 `truth` |
| `description` | `host` |
| `personality` | `host` / `ai_only` |
| `motivation` | `host` / `ai_only` |
| `secret_goal` | `truth` |
| `faction_refs` | `host` / `truth` |
| `aliases` | 按 alias 类型区分 |

## DTO 方向

本模块至少应明确以下 DTO 边界：

| DTO | 作用 | 可含字段 | 禁止字段 |
|---|---|---|---|
| `PlayerKnownNpcDTO` | 玩家已知 NPC 摘要 | `npcId/displayName/publicDescription/firstSeenAt/sourceEvents/visibilityLevel` | `motivation/secret_goal/true_name/faction_refs/host_notes` |
| `HostNpcDTO` | Host 摘要视图 | `npcId/publicName/name/hiddenFlags/sceneRefs/clueRefs/factionRefs` | 无关玩家凭证 |
| `NPCContextForPlayerFacingAI` | 面向玩家输出时可引用的 NPC 上下文 | 公开名、公开描述、已公开事实、已解锁事实 | truth 层字段 |
| `NPCContextForHostAI` | Host/内部 AI 使用的 NPC 上下文 | 公开字段 + personality + motivation + truth 授权字段 | 不直接输出给玩家 |
| `MapNodePublicDTO` | 匿名地图节点 | `nodeId/name/isStart/isAdjacent` | `npcsPresent/cluesAvailable/完整描述` |
| `MapNodePlayerDTO` | 玩家地图节点 | `nodeId/name/已探索描述/已公开 NPC/已发现线索摘要` | 隐藏 NPC 真名、未发现线索、Host notes |
| `MapNodeHostDTO` | Host 地图节点 | 完整节点、NPC、线索、隐藏标记 | 无关敏感字段 |
| `EncounterNpcDTO` | 遭遇临时 NPC | `participantId/displayName/source/sourceNpcId/hp/dex/mov/weapons/mainSkill` | `character` 模块身份字段 |

## 核心流程

### 剧本导入

1. Admin 上传 PDF。
2. `structure_scenario()` 生成 `knowledge_graph`，其中包含 `npcs`。
3. 质量报告检查 NPC 数量和关键字段缺口。
4. `RAGStore.index_npc_graph()` 尝试索引 NPC。
5. `SpoilerGuard.build_sensitive_index()` 提取隐藏 NPC 敏感项。
6. Host 创建房间后，AI、地图和投影链路使用这些资产。

### AI 查询 NPC

1. 玩家提交行动，例如询问、观察、交涉。
2. AI 工具可通过 `query_npcs` 查询当前场景 NPC。
3. 工具先读场景引用，再映射到剧本 NPC 档案。
4. 返回给 AI 的字段必须是裁剪后的 `NPCContextForPlayerFacingAI` 或 `NPCContextForHostAI`。
5. AI 输出仍需经过 SpoilerGuard 和 Projection。

### 玩家可见 NPC

1. 玩家默认只看到公开 NPC、已公开出现的 NPC、已发现线索关联的 NPC。
2. `已探索场景` 不等于 `场景内所有 NPC 都已公开`。
3. `已发现线索` 不等于 `该 NPC 的真相已公开`。
4. 玩家 NPC 列表必须来自投影或专门 DTO，不直接返回完整 `knowledge_graph.npcs`。

### 隐藏 NPC 公开与揭示

1. `appearance_revealed`：玩家知道这个 NPC 出现了。
2. `identity_revealed`：玩家知道公开身份或关键身份。
3. `secret_revealed`：玩家知道秘密目标、真实阵营或内幕关系。
4. 解锁事件应优先携带 `npcId`，`npcName` 仅作兼容辅助。

### 地图节点展示

1. 匿名地图视图只给基础布局，不给 NPC/线索明细。
2. 玩家已探索节点可以看到授权后的 NPC 摘要，而不是原始 `npcsPresent` 真名列表。
3. Host 视图可查看完整节点和隐藏标记。

### 遭遇临时 NPC

1. AI 可提出 `encounterSuggestion`，Host 确认或拒绝。
2. Host 确认后创建 `encounters` 和 `encounter_participants`。
3. 快速创建 NPC 使用 `npc:{uuid}` 作为参与者 ID。
4. 临时 NPC 必须有稳定 `displayName`，可选 `sourceNpcId`。
5. 遭遇结束后只保留日志和参与者记录，不自动变成长期 NPC 档案。

## 接口方向

| 接口或内部能力 | 作用 | 权限 |
|---|---|---|
| `POST /api/scenarios/import-pdf` | 导入剧本并结构化 NPC | Admin |
| `GET /api/scenarios/{scenario_id}/quality-report` | 查看剧本结构完整性 | Host / Admin 方向 |
| `POST /api/admin/scenarios/{scenario_id}/classify` | 返回场景、NPC、线索数量和类型判断 | Admin |
| `POST /api/rag/index-npc` | 重建 NPC RAG 索引 | Admin / Owner |
| `POST /api/rag/search` | 搜索当前房间可用知识 | Admin / Owner / Room Player |
| `ToolExecutor.query_npcs` | AI 内部查询当前场景 NPC | AI 内部 |
| `SpoilerController.filter_for_player` | 生成 AI 使用的玩家可见 NPC 上下文 | AI 内部 |
| `POST /api/host/{room_id}/encounter/confirm` | Host 确认遭遇 | Host |
| `POST /api/host/{room_id}/encounter/reject` | Host 拒绝遭遇 | Host |
| `POST /api/host/{room_id}/encounter/npc` | Host 快速创建遭遇 NPC | Host |
| `POST /api/host/{room_id}/encounter/next-round` | 推进遭遇轮次 | Host |
| `POST /api/host/{room_id}/encounter/resolve` | 结束遭遇 | Host |
| `GET /api/map/{room_id}` | 玩家/匿名地图视图 | Player / 匿名 |
| `GET /api/host/{room_id}/map/full` | Host 完整地图视图 | Host |

当前不要求新增公开 NPC REST API。后续如新增，应优先考虑：

- `GET /api/player/rooms/{room_id}/npcs`：玩家已知 NPC 列表。
- `GET /api/host/{room_id}/npcs`：Host NPC 摘要与隐藏标记。
- `POST /api/host/{room_id}/npcs/{npc_id}/reveal`：Host 显式公开 NPC。

当前事件方向建议：

- 兼容现状：`s2c_public_observation.payload.npcName`
- 目标方向：`s2c_npc_revealed.payload.npcId/publicName/revealLevel/source/sourceEventId`

## 权限与安全边界

- 玩家不能读取完整 `knowledge_graph.npcs`。
- Player-facing AI 不能读取或输出 truth 层 NPC 字段。
- `is_hidden=true` 的 NPC 默认只允许 Host / 内部 AI 使用，不允许直接投给 player / party。
- `room_id IS NULL` 不等于所有房间可读；NPC RAG 仍要满足 scenario entitlement。
- 地图、RAG、日志和导出必须沿用同一套 NPC 可见范围。
- 匿名或无 token 的地图查询不应返回 `npcsPresent`、`cluesAvailable`、完整节点描述。
- 遭遇临时 NPC 不能写入 `characters`，也不能被 Character 查询误当成玩家角色。
- Faction 第一阶段只定义引用关系，不推进 faction clock，不在 06 里落完整势力系统。

## 验收标准

- 导入包含 NPC 的剧本后，质量报告能反映 NPC 数量和关键字段问题。
- `knowledge_graph.npcs[]` 至少能稳定兼容 `npc_id/public_description/is_hidden/personality/motivation` 等关键字段。
- 隐藏 NPC 被写入 `spoiler_sensitive_items`，party/player 输出命中时被拦截。
- 隐藏 NPC 的解锁优先使用 `npcId`，而不是只依赖 `npcName`。
- RAG 搜索当前房间时能检索本剧本 NPC，且不会跨房间或跨剧本泄露 NPC。
- 匿名地图和玩家地图不展示未授权的 `npcsPresent/cluesAvailable`。
- 玩家 NPC 列表只展示已公开或已解锁 NPC 摘要，不直接扫 `knowledge_graph.npcs`。
- Host 创建临时 NPC 后，后续查询和事件中仍能看到稳定 `displayName`。
- 临时 NPC 不写入 `characters`，也不会自动升级成长期 NPC 档案。

## 当前风险

- 结构化 prompt 目前没有强制 `npc_id/is_hidden/personality/motivation/faction_refs`，NPC schema 质量不稳定。
- `query_npcs` 当前按 `npc name` 回查详情，同名 NPC、别名和真名/公开名容易冲突。
- `SpoilerGuard` 的 hidden NPC itemId 仍偏数组下标，解锁仍主要依赖 `payload.npcName`。
- `index_npc_graph()` 的 metadata 只有 `npc_name/index`，缺 `npc_id/scenario_id/visibility/is_hidden` 语义。
- 匿名地图接口当前直接回完整 nodes，存在 NPC/线索泄露风险。
- 玩家探索节点后当前可直接看到 `npcsPresent`；如果节点里是隐藏 NPC 真名，会直接剧透。
- 快速创建遭遇 NPC 时 `name` 未稳定持久化在 participant 结构里，容易只剩 `npc:{uuid}`。
- Faction 仍是规划项，不应在第一轮被误当成完整可实现系统。
