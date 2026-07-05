# Module 模组编辑器 PRD V2.0

## 背景

AI-Keeper 当前已经具备“从 PDF 剧本到可开房 scenario”的雏形：Admin 导入 PDF，后端抽取文本并调用 AI 结构化，保存 `knowledge_graph` 和原始文件信息，生成质量报告，后台可上传素材并生成地图草稿，Host 可以从 `/api/scenarios/available` 选择结构化剧本创建房间。

但这还不是完整模组编辑器。缺口包括：没有独立 Module DTO，没有导入状态和发布状态分离，没有结构编辑 API，没有角色模板管理闭环，没有模板版本，没有发布准入，也没有玩家视角预览。Module V1 的目标是先把“导入草稿 -> 校验 -> 发布 -> 开房实例化”整理成稳定链路，再逐步建设可视化编辑器。

## 目标

1. 把 scenario 从普通数据库记录提升为可治理的 Module 模板。
2. 明确模组草稿、质量报告、发布状态、地图、素材、角色模板和规则触发器的关系。
3. 保证 Host 只能选择可运行的模组，Player 不会看到模组真相和完整后台结构。
4. 保证 Room 运行态与 Module 模板隔离，跑团过程不污染原始模组。
5. 为 DeepSeek 后续实现后端编辑 API 和 Admin 编辑界面提供边界。

## 非目标

- 不在本轮一次性实现完整可视化剧情树编辑器。
- 不实现社区发布、评分、付费和授权市场。
- 不让 Module 直接处理文件上传安全，文件治理归 Asset。
- 不让 Module 执行规则裁决、骰子结算或状态写入。
- 不把房间运行态事件反写回模组模板。
- 不开放 Player 读取完整 `knowledge_graph`、`truth`、隐藏素材和 Host-only 配置。
- 不在第一轮迁移历史 scenario 数据到复杂版本表。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Admin | 导入、查看、校验、修正、发布和归档模组 | 绕过安全校验发布 blocked 模组给普通 Host |
| Host | 浏览可用模组，创建房间，使用已发布版本开团 | 编辑模组真相、删除素材、读取其他作者草稿 |
| Author | 后续创建和编辑自己的模组 | 管理全局系统配置或绕过审核发布 |
| Player | 加入房间并读取公开简介和预设角色 | 访问模组编辑器、完整 KG、真相、隐藏线索 |
| AI-Keeper | 按权限读取模组片段，用于结构化、建议和裁决上下文 | 直接改写已发布模组或把真相泄露给玩家 |
| DeepSeek | 执行具体工程任务 | 一次性重写所有导入、地图、规则和前端架构 |

## 产品范围

### 本轮进入

- PDF 导入为 Module 草稿。
- `scenarios` 聚合为 Module DTO。
- 质量报告和发布准入口径。
- 可用模组列表与 Host 开房权限。
- 地图草稿生成、编辑、确认与开房初始化。
- 角色模板读取接口闭环。
- Admin 模组详情初版：KG 摘要、质量、素材、地图、模板、发布状态。
- 基础结构编辑 API 设计：场景、NPC、线索、结局、触发器。
- 模组模板与房间运行态隔离。

### 本轮不进入

- 完整拖拽式剧情树。
- 多作者协同编辑。
- 社区发布和付费授权。
- AI 自动重写整部模组。
- 模组版本合并和复杂差异视图。
- 多规则系统转换器。
- 大型前端编辑器重构。

## 领域模型

| 模型 | 字段方向 | 说明 |
| --- | --- | --- |
| `Module` | `moduleId/title/status/importStatus/qualityLevel/sourceFilename/createdAt/updatedAt` | 对现有 scenario 的产品化包装 |
| `ModuleDraft` | `scenarioId/rawText/knowledgeGraph/scenarioAssets/qualityReport` | 导入或编辑中的草稿 |
| `ModuleReadiness` | `level/blockers/warnings/completeness/checkedAt` | 从质量报告和发布规则生成 |
| `ModuleMap` | `mapId/status/nodes/edges/generatedBy/confirmedAt` | scenario map 草稿和确认状态 |
| `ModuleAssetBinding` | `assetId/refType/refId/visibility` | 素材绑定到场景、线索、NPC、地图节点 |
| `ModuleCharacterTemplate` | `templateId/name/occupation/attributes/skills/backstory` | 预设调查员模板 |
| `ModuleTrigger` | `condition/mechanics/scope/validationStatus` | 场景或全局触发器 |
| `ModuleVersion` | `versionId/moduleId/snapshot/publishedAt/publishedBy` | 后续版本化，第一轮可先定义接口方向 |
| `RoomInstantiation` | `roomId/moduleId/moduleVersionId/scenarioId` | 开房时从模板实例化运行态 |

## 核心流程

### 导入草稿

1. Admin 上传 PDF。
2. Asset 层完成文件安全和原件保存。
3. WorldBook/AI 提取 `knowledge_graph`。
4. Module 保存草稿、导入状态、来源文件和质量报告。
5. RAG、SpoilerGuard 和地图生成可使用该结构，但不能对 Player 暴露完整内容。

### 校验与修正

1. Admin 打开 Module 详情。
2. 系统展示场景、NPC、线索、真相、结局、触发器、素材、地图和角色模板摘要。
3. 系统展示 readiness：blocked、highRisk、warning、ready。
4. Admin 修正结构字段、补素材、生成地图、补角色模板。
5. 每次保存重新计算质量报告或标记需要复核。

### 发布

1. Admin 点击发布。
2. 后端校验结构必需项、隐藏真相边界、地图状态、触发器 schema、素材引用和角色模板。
3. `blocked` 不允许发布；`highRisk` 需要 Admin 显式 override 并记录原因。
4. 发布成功后，模组进入 Host 可用列表。
5. 后续引入 version 后，发布生成不可变快照。

### 开房实例化

1. Host 从可用模组列表选择模组。
2. Room 创建时绑定 scenario 或 module version。
3. Room start 时读取 confirmed map 初始化 `room_map_state`。
4. 首回合和 checkpoint 创建。
5. 房间中的运行态变化只写 Room/State/Event，不反写 Module 模板。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| MO-FR-1 | Admin 能将 PDF 导入为 Module 草稿 | P0 |
| MO-FR-2 | 导入必须保存来源文件名、hash、原文和结构化 KG | P0 |
| MO-FR-3 | Module 必须有导入状态和发布状态，二者不能混用 | P0 |
| MO-FR-4 | Module 详情必须聚合质量报告、地图、素材和角色模板摘要 | P0 |
| MO-FR-5 | 质量报告必须给出 ready、warning、highRisk、blocked | P0 |
| MO-FR-6 | blocked 模组不能进入普通 Host 可用列表 | P0 |
| MO-FR-7 | Host/Admin 可查看可用模组，Player 不可查看后台模组列表 | P0 |
| MO-FR-8 | 模组地图可生成、编辑和确认 | P0 |
| MO-FR-9 | confirmed 地图在房间开局时初始化运行态地图 | P0 |
| MO-FR-10 | 前后端必须闭合 `GET /api/scenarios/{scenario_id}/templates` 或采用统一替代接口 | P0 |
| MO-FR-11 | Admin 能管理 scenario 角色模板 | P1 |
| MO-FR-12 | Module 可编辑场景、NPC、线索、真相、结局和公开简介 | P1 |
| MO-FR-13 | Module 可编辑触发器，保存前验证 condition 和 mechanics | P1 |
| MO-FR-14 | Module 可把素材绑定到场景、线索、NPC 或地图节点 | P1 |
| MO-FR-15 | Player 端不得读取 truth、完整 KG、隐藏素材和 Host-only 字段 | P0 |
| MO-FR-16 | Room 运行态不得反写 Module 模板 | P0 |
| MO-FR-17 | 发布、撤回、强制发布必须记录 actor 和 reason | P1 |
| MO-FR-18 | Admin UI 的导入、质量、地图、素材和模板状态必须中文可读 | P0 |
| MO-FR-19 | 后续 ModuleVersion 必须支持开房绑定不可变快照 | P2 |
| MO-FR-20 | 模组导入导出包必须脱敏并使用 Asset manifest | P2 |

## 接口方向

| 接口 | 当前状态 | 用途 | 调整方向 |
| --- | --- | --- | --- |
| `POST /api/scenarios/import-pdf` | 已有 | Admin PDF 导入 | 保持 admin-only，归入 Module 导入链路 |
| `GET /api/scenarios/available` | 已有 | Host/Admin 可用模组列表 | 只返回 published/ready，blocked 不返回 |
| `GET /api/scenarios/{scenario_id}/quality-report` | 已有 | 查看质量报告 | 增加鉴权，返回 readiness DTO |
| `POST /api/scenarios/{scenario_id}/create-room` | 已有 | 从模组开房 | 与 `/api/rooms` 口径统一 |
| `GET /api/admin/scenarios` | 已有 | Admin 列表 | 改为 Module 列表 DTO，避免无意暴露大字段 |
| `GET /api/admin/modules/{module_id}` | 待新增 | Admin 模组详情 | 聚合 KG 摘要、质量、素材、地图、模板 |
| `PATCH /api/admin/modules/{module_id}` | 待新增 | 编辑标题、简介、状态 | 不直接修改运行态房间 |
| `PATCH /api/admin/modules/{module_id}/knowledge` | 待新增 | 编辑 KG 结构 | 保存后重新计算质量报告 |
| `POST /api/admin/modules/{module_id}/publish` | 待新增 | 发布模组 | 校验 readiness，支持 override reason |
| `POST /api/admin/scenarios/{scenario_id}/map/generate` | 已有 | 地图草稿生成 | 读取统一 scenes 数据源 |
| `PATCH /api/admin/scenarios/{scenario_id}/map` | 已有 | 地图草稿编辑 | confirmed 后不可编辑 |
| `POST /api/admin/scenarios/{scenario_id}/map/confirm` | 已有 | 地图确认 | 确认后用于 Room start |
| `GET /api/scenarios/{scenario_id}/templates` | 前端期待，后端缺口 | 玩家/角色构建器读取模板 | 补只读接口或调整前端 |
| `POST/PATCH/DELETE /api/admin/modules/{module_id}/templates` | 待新增 | Admin 管理预设角色 | 写入 `character_templates` |

## 数据边界

- Module 模板存储在 scenario 相关表中，运行态存储在 room、state、event、map state 表中。
- `raw_text`、`knowledge_graph.truth`、隐藏线索和 Host-only 触发器默认仅 Admin/Author/授权 Host 可见。
- `scenario_assets` JSON 是结构化语义，不等于上传文件表。
- `scenario_assets` 表是文件资源记录，文件安全归 Asset。
- `scenario_maps` 是模板地图，`room_map_state` 是运行态地图。
- `character_templates` 是模组预设角色，玩家实际加入后复制到 `characters.xlsx_data`。
- 发布后的 Module 后续应以不可变快照开房，避免编辑影响进行中的房间。

## 权限边界

1. 未登录不能导入、编辑、发布或查看后台模组。
2. Player 不能访问 `/api/scenarios/available`、Admin 模组列表或 Module 编辑接口。
3. Host 可以查看可用模组并开房，但不能编辑模组模板。
4. Admin 可以编辑和发布模组，并可强制处理 highRisk 模组。
5. Author 后续只能编辑自己拥有或协作授权的模组。
6. AI 只能按调用任务读取必要片段，不能直接发布或删除模组。
7. Player 角色模板接口只返回可公开的角色模板字段，不返回真相或隐藏线索。

## 验收标准

1. Admin 能导入 PDF，并得到 scenario id、结构化状态和质量报告。
2. Player 导入 PDF、查看可用模组、创建模组房间均被拒绝。
3. Host 只能看到可运行模组，并可用其创建房间。
4. blocked 模组不出现在普通 Host 可用列表。
5. 地图草稿可生成、编辑、确认；confirmed 后开房初始化地图。
6. 前端请求的 scenario templates 接口后端存在，字段与 PlayerJoin/CharacterBuilder 匹配。
7. Module 详情不把本地文件路径、owner token、player token 暴露给非 Admin。
8. Player 只能看到公开简介、预设角色和运行态投影，不能看到 truth 或完整 KG。
9. 房间运行后修改角色、地图、线索、状态不会反写 Module 模板。
10. Admin UI 中文可读，相关页面 `npm run build` 通过。
