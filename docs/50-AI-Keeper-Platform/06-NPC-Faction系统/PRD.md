# NPC / Faction 系统 PRD 初版

## 目标

NPC / Faction v1 的目标是让剧本里的 NPC 能被稳定抽取、查询、引用和防剧透，并在必要时作为遭遇临时参与者进入战斗或追逐链路。

第一轮成功标准是：导入剧本后能形成 NPC 基础档案，AI 能在授权上下文里扮演相关 NPC，玩家只看到已公开 NPC 信息，隐藏 NPC 不被公共叙事泄露，Host 可以把临时敌人加入遭遇并完成基础回合流转。

## 产品边界

包含：

- 剧本结构化中的 NPC 列表。
- NPC 与场景、地图节点、RAG、AI 工具、防剧透索引的连接。
- 玩家已知 NPC 与隐藏 NPC 的可见边界。
- 遭遇中的临时 NPC/敌人参与者。
- NPC 公开出现、隐藏身份解锁和日志引用的事件口径。

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
| Host | 查看剧本 NPC 摘要、防剧透标记、当前场景 NPC 和遭遇临时 NPC |
| Admin/Module Author | 导入剧本、查看质量报告、重建 RAG 或防剧透索引 |
| AI-Keeper | 读取裁剪后的 NPC 上下文，生成 NPC 反应和叙事建议 |
| Engine/State/Journal | 确认 NPC 状态变化、公开出现、线索释放和事件日志 |

## 数据边界

| 数据位置 | 作用 | 当前状态 |
|---|---|---|
| `scenarios.knowledge_graph.npcs` | 剧本 NPC 基础档案 | 已存在，字段松散 |
| `scenario_assets.scenes[].npcs_present` | 场景中的 NPC 名称 | 已被 AI 工具和地图生成使用 |
| `scenario_maps.nodes[].npcs_present` | 地图节点上的 NPC 名称 | 已存在，玩家探索节点后可能展示 |
| `document_chunks(source_type='npc')` | NPC RAG chunk | 已存在，房间搜索范围需加固 |
| `spoiler_sensitive_items(category='hidden_npc')` | 隐藏 NPC 防剧透索引 | 已存在 |
| `events.payload.npcName` | NPC 公开出现解锁约定 | 已被 SpoilerGuard 读取 |
| `encounter_participants.character_id='npc:{uuid}'` | 遭遇临时 NPC/敌人 | 已存在 |

未来如果新增独立 NPC 主表，应优先承接以下字段：

| 字段 | 说明 |
|---|---|
| `npc_id` | 稳定 ID，避免只靠名字匹配 |
| `name/public_name` | 真实名与公开称呼可分离 |
| `role/type` | 剧情定位、怪物、平民、组织成员等 |
| `public_description` | 玩家可见描述 |
| `description` | Host/AI 可见详细描述 |
| `personality/motivation/goal` | AI 扮演依据 |
| `is_hidden/secrets` | 防剧透字段 |
| `scene_refs/clue_refs` | 与场景、线索的关系 |
| `faction_refs` | 所属或关联势力 |

## 核心流程

### 剧本导入

1. Admin 上传 PDF。
2. `structure_scenario` 生成 `knowledge_graph`，其中包含 `npcs`。
3. `QualityReportGenerator` 检查 NPC 数量。
4. `RAGStore.index_npc_graph` 尝试索引 NPC。
5. `SpoilerGuard.build_sensitive_index` 提取隐藏 NPC 敏感项。
6. Host 创建房间后，AI 和投影链路使用这些资产。

### AI 查询 NPC

1. 玩家提交行动，例如询问、观察、交涉。
2. AI 工具可通过 `query_npcs` 查询当前场景 NPC。
3. 工具从 `scenario_assets.scenes[].npcs_present` 找 NPC 名，再到 `knowledge_graph.npcs` 取详情。
4. 返回给 AI 的字段应是裁剪后的 role、personality、motivation、公开描述或授权描述。
5. AI 输出仍需经过 SpoilerGuard 和 Projection。

### 玩家可见 NPC

1. 玩家默认只看到公开 NPC、已出现 NPC、已发现线索关联的 NPC。
2. 隐藏 NPC 只有公开出现、Host 手动揭示或权威事件解锁后才能进入玩家侧。
3. 地图节点展示 NPC 名称前必须考虑节点探索状态和 NPC 隐藏状态。
4. 玩家 NPC 列表应来自投影或专门 DTO，不直接返回完整 `knowledge_graph.npcs`。

### 遭遇临时 NPC

1. AI 可提出 `encounterSuggestion`，Host 确认或拒绝。
2. Host 确认后创建 `encounters` 和 `encounter_participants`。
3. 快速创建 NPC 使用 `npc:{uuid}` 作为参与者 ID。
4. 临时 NPC 的 HP、DEX、MOV、武器、伤害、主技能进入遭遇结算。
5. 遭遇结束后作为日志记录保留，不自动变成长期 NPC 档案。

## 接口方向

| 接口或内部能力 | 作用 | 权限 |
|---|---|---|
| `POST /api/scenarios/import-pdf` | 导入剧本并结构化 NPC | Admin |
| `GET /api/scenarios/{scenario_id}/quality-report` | 查看剧本结构完整性 | Host/Admin 方向 |
| `POST /api/admin/scenarios/{scenario_id}/classify` | 返回场景、NPC、线索数量和类型判断 | Admin |
| `POST /api/rag/index-npc` | 重建 NPC RAG 索引 | Admin/Owner |
| `POST /api/rag/search` | 搜索当前房间可用知识 | Admin/Owner/Room Player |
| `ToolExecutor.query_npcs` | AI 内部查询当前场景 NPC | AI 内部 |
| `SpoilerController.filter_for_player` | 生成玩家可见 NPC 上下文 | AI 内部 |
| `POST /api/host/{room_id}/encounter/confirm` | Host 确认遭遇 | Host |
| `POST /api/host/{room_id}/encounter/reject` | Host 拒绝遭遇 | Host |
| `POST /api/host/{room_id}/encounter/npc` | Host 快速创建遭遇 NPC | Host |
| `POST /api/host/{room_id}/encounter/next-round` | 推进遭遇轮次 | Host |
| `POST /api/host/{room_id}/encounter/resolve` | 结束遭遇 | Host |

当前不要求新增公开 NPC REST API。后续如果新增，应优先提供：

- `GET /api/player/rooms/{room_id}/npcs`：玩家已知 NPC 列表。
- `GET /api/host/{room_id}/npcs`：Host NPC 摘要与隐藏标记。
- `POST /api/host/{room_id}/npcs/{npc_id}/reveal`：Host 显式公开 NPC。

## 权限与安全边界

- 玩家不能读取完整 `knowledge_graph.npcs`。
- `is_hidden=true` 的 NPC 默认只允许 Host/AI 内部使用，不允许直接投给 player/party。
- NPC 真实身份、秘密、动机和所属邪教或幕后势力默认属于 Host/truth 层。
- AI 生成的 NPC 反应是建议，不能直接改变 NPC 状态或势力时钟。
- 地图、RAG、日志和导出都必须沿用同一套 NPC 可见范围。
- 匿名或无 token 的地图查询不应返回包含 NPC 和线索的完整节点信息。

## 验收标准

- 导入包含 NPC 的剧本后，质量报告能反映 NPC 数量。
- 隐藏 NPC 被写入 `spoiler_sensitive_items`，公共叙事命中隐藏 NPC 名称时被拦截。
- 已公开的 NPC 能通过事件解锁，不再被同名拦截。
- AI 查询当前场景 NPC 时，不发明剧本中不存在的核心 NPC。
- RAG 搜索当前房间时能检索本剧本 NPC，且不能跨房间泄露其他房间 NPC。
- 玩家地图和 NPC 列表不展示未公开隐藏 NPC。
- Host 创建遭遇临时 NPC 后，前端能显示可读名称，后端能保存其战斗字段。
- Host confirm、reject、next-round、resolve、npc 创建均有后端测试覆盖。

## 当前风险

- 没有独立 NPC/Faction 主表，所有长期能力都不能当作已完成。
- 结构化 prompt 没有强制 `npc_id/is_hidden/personality/motivation/faction_refs`，NPC 质量不稳定。
- NPC RAG chunk 的 room/scenario scope 需要补测试，避免搜不到本剧本 NPC 或跨房泄露。
- 地图匿名查询返回完整节点，可能携带 `npcsPresent` 和 `cluesAvailable`。
- 玩家探索节点后直接看到 `npcsPresent`，如果节点内包含隐藏 NPC 名会泄露。
- 快速创建遭遇 NPC 时 `name` 没有稳定写入 participant 字段，面板可能只显示 `npc:` ID。
- 遭遇 API 缺少独立测试文件，回归风险高。
- Faction 仍是规划项，不应在第一轮被 DeepSeek 当成可直接实现的大系统。
