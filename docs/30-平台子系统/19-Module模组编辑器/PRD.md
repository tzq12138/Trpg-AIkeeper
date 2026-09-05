# Module 模组编辑器 PRD V2.1

## 当前阶段说明

- 本 PRD 当前阶段为：`P0 主链路 + 模组导入、发布准入与开房实例化风险识别版`。
- 当前代码已经具备导入、质量报告、素材管理、地图生成/确认、Host 可用列表和开房链路，但还没有完整 Module 服务层与可视化编辑器。
- 本轮以仓库真实代码为基础，只收口产品边界、数据边界、权限边界、接口方向和验收标准。
- 本轮不是生产安全完成版；文档中的状态机、DTO、受控 patch、版本快照和防剧透边界，仍需要后续工程回执与测试验收。

## 背景

AI-Keeper 当前已经有“从 PDF 剧本到可开房 scenario”的雏形：

- Admin 导入 PDF；
- 后端抽取文本并调用 AI 结构化，保存 `knowledge_graph`；
- 生成 `quality_report`；
- Admin 可上传素材并生成地图草稿；
- Host 可从 `/api/scenarios/available` 选择可用 scenario 开房；
- Room start 可从 confirmed map 初始化 `room_map_state`。

但当前还不是完整的 Module 体系，主要缺口包括：

- 没有独立 Module DTO；
- 没有把 `importStatus` 和 `publishStatus` 分离；
- 没有统一的 Module 详情聚合接口；
- 没有受控的结构编辑 patch 口径；
- 没有角色模板 CRUD 闭环；
- 没有公开模板只读接口闭环；
- 没有版本快照边界；
- 没有把 Admin / Host / Player 三套视图分开。

本 PRD 的目标，是先把“导入草稿 -> 校验 -> 发布 -> 开房实例化”的主链路产品化，再为后续可视化编辑器和版本治理铺路。

## 目标

1. 把 scenario 从普通数据库记录提升为可治理的 Module 模板。
2. 明确导入状态、发布状态、质量准入、地图、素材、模板、触发器和开房实例化之间的关系。
3. 保证 Host 只能选择可运行模组，Player 不会看到 truth、完整 KG 或 Host-only 配置。
4. 保证 Room 运行态与 Module 模板隔离，跑团过程不污染原始模组。
5. 为 DeepSeek 后续实现后端编辑 API、Admin UI 和回归测试提供统一边界。

## 非目标

- 不在本轮一次性实现完整可视化剧情树编辑器。
- 不实现社区发布、评分、付费和授权市场。
- 不让 Module 直接处理文件上传安全，文件治理归 Asset。
- 不让 Module 执行规则裁决、骰子结算或状态写入。
- 不把房间运行态事件反写回模组模板。
- 不开放 Player 读取完整 `knowledge_graph`、`truth`、隐藏素材和 Host-only 配置。
- 不在第一轮强制迁移全部历史房间到 `module_versions`。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Admin | 导入、查看、校验、修正、发布、撤回和归档模组 | 绕过后端准入把 blocked 模组开放给普通 Host |
| Host | 浏览可用模组、创建房间、使用已发布模组开团 | 编辑模组真相、读取完整后台草稿 |
| Author | 后续创建和编辑自己有权限的模组 | 管理全局系统配置或越权发布 |
| Player | 加入房间并读取公开简介、公开模板和运行态投影 | 访问模组编辑器、完整 KG、truth、隐藏线索 |
| AI-Keeper | 按权限读取模组片段，用于结构化、建议和裁决上下文 | 直接发布模组或把真相泄露给玩家 |
| DeepSeek | 执行工程批次 | 一次性重写导入、地图、规则和前端全部架构 |

## 产品范围

### 本轮进入

- PDF 导入为 Module 草稿；
- `scenarios` 聚合为 Module DTO；
- `importStatus` / `publishStatus` 分离；
- `ModuleReadiness` 发布准入口径；
- 可用模组列表与 Host 开房权限；
- 地图草稿生成、编辑、确认与开房初始化；
- 角色模板公开读取接口闭环；
- Admin 模组详情初版；
- 基础结构编辑 API 方向；
- 模组模板与房间运行态隔离。

### 本轮不进入

- 完整拖拽式剧情树；
- 多作者协同编辑；
- 社区发布和付费授权；
- AI 自动重写整部模组；
- 复杂版本合并和差异视图；
- 多规则系统转换器；
- 大型前端编辑器重构。

## 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `SourceDocument` | PDF 原件、`source_filename`、`source_sha256` | 导入来源追踪 |
| L1 `ImportJob / ImportStatus` | `pending/importing/requires_ocr/structured/failed` | 导入与结构化过程状态 |
| L2 `ModuleDraft` | `raw_text`、`knowledge_graph`、`quality_report` | 可编辑草稿 |
| L3 `KnowledgeGraph` | `scenes/npcs/clues/truth/endings` | 故事结构语义 |
| L4 `SemanticScenarioAsset` | `scenarios.scenario_assets` JSON | 触发器、机制、结构化语义资产 |
| L5 `AssetBinding` | `assetId/refType/refId/visibility` | 文件资源绑定 |
| L6 `ModuleMapDraft` | `scenario_maps` draft/confirmed | 模组地图模板 |
| L7 `ModuleCharacterTemplate` | `character_templates` | 预设调查员模板 |
| L8 `ModuleTrigger` | `triggerId/scope/condition/mechanics/visibility/validationStatus` | 触发器定义 |
| L9 `ModuleReadiness` | `ready/warning/highRisk/blocked` | 发布准入结果 |
| L10 `PublishState` | `draft/review/ready/published/archived` | 模组生命周期 |
| L11 `ModuleVersion` | 发布快照 | 新房间应优先绑定此层 |
| L12 `RoomInstantiation` | `roomId/moduleVersionId/scenarioId` | 房间运行态实例 |

关键边界：

- `KnowledgeGraph` 是故事结构，不直接给 Player；
- `SemanticScenarioAsset` 是规则/地图/触发器消费的结构化语义，不等于上传文件表；
- `AssetBinding` 只保存 `assetId` 或受控 URL，不保存本地路径；
- `RoomInstantiation` 是运行态，不反写 `ModuleDraft`。

## DTO 契约

### 最小 DTO 集合

- `ModuleListItemDTO`
- `AdminModuleDetailDTO`
- `ModuleReadinessDTO`
- `ModuleImportStatusDTO`
- `ModulePublishRequestDTO`
- `ModulePublishResultDTO`
- `ModuleKnowledgeSummaryDTO`
- `ModuleMapSummaryDTO`
- `ModuleAssetBindingDTO`
- `ModuleCharacterTemplateDTO`
- `ModuleTriggerDTO`
- `PlayerModulePreviewDTO`
- `ModuleHostOptionDTO`
- `ModuleCreateRoomRequestDTO`
- `ModuleCreateRoomResultDTO`
- `ModuleEditPatchDTO`
- `ModuleApiErrorDTO`

### 关键 DTO 口径

#### `ModuleListItemDTO`

```json
{
  "moduleId": "mod_xxx",
  "scenarioId": "scenario_xxx",
  "title": "无名剧本",
  "importStatus": "structured",
  "publishStatus": "draft",
  "qualityLevel": "warning",
  "mapStatus": "draft",
  "assetCount": 3,
  "templateCount": 2,
  "updatedAt": "2026-07-08T12:00:00Z"
}
```

#### `ModuleHostOptionDTO`

```json
{
  "moduleId": "mod_xxx",
  "scenarioId": "scenario_xxx",
  "title": "公开标题",
  "publicSummary": "公开简介",
  "playerCountRange": "2-4",
  "tags": ["investigation"],
  "qualityLevel": "ready",
  "mapStatus": "confirmed",
  "templateCount": 2
}
```

#### `PlayerModulePreviewDTO`

```json
{
  "scenarioId": "scenario_xxx",
  "title": "公开标题",
  "publicSummary": "公开简介",
  "templates": [
    {
      "templateId": "tpl_xxx",
      "displayName": "预设角色",
      "occupation": "记者",
      "publicSummary": "公开背景",
      "suggestedSkills": ["图书馆使用"],
      "avatarAssetUrl": null,
      "selectable": true
    }
  ]
}
```

#### `ModuleReadinessDTO`

```json
{
  "level": "highRisk",
  "blockers": [],
  "warnings": ["缺少公开角色模板"],
  "checkedAt": "2026-07-08T12:00:00Z"
}
```

DTO 总约束：

- Host/Player 只拿瘦 DTO；
- 不允许把 `scenarios` 原始记录直接回给前端；
- 不允许对 Host/Player 返回 `raw_text`、完整 `knowledge_graph`、truth、本地路径、token。
- `AdminModuleDetailDTO` 也不是数据库 raw dump；即便 Admin 可看后台详情，也不默认返回 `raw_text` 全文、本地路径、token、无关 debug secret。

## 状态机

### 导入状态

`importStatus` 只描述导入和结构化过程：

- `pending`
- `importing`
- `requires_ocr`
- `structured`
- `failed`

### 发布状态

`publishStatus` 只描述模组生命周期：

- `draft`
- `review`
- `ready`
- `published`
- `archived`

额外约束：

- `qualityLevel.ready` 表示“质量检查结果通过”；
- `publishStatus.ready` 表示“生命周期上已进入可发布或待发布阶段”；
- 两者字段名相近，但语义不同，工程实现、DTO、回执和测试里都不得混用。

### 发布准入矩阵

| qualityLevel | 默认能否发布 | 默认能否出现在 Host 可用列表 | 要求 |
| --- | --- | --- | --- |
| `ready` | 可以 | 可以 | 正常发布 |
| `warning` | 可以 | 可以 | 给出 warning |
| `highRisk` | 默认不普通发布 | 默认不普通可见 | Admin override + reason + qualitySnapshot |
| `blocked` | 不可发布 | 不可见 | 后端硬拒绝 |

补充约束：

- `structured` 不等于 `published`；
- `highRisk` override 必须可审计；
- `blocked` 模组不得通过普通 `/available` 和普通 `create-room` 链路下发给 Host。
- 当前代码里 `/api/scenarios/{scenario_id}/create-room` 已有 `confirm_quality_risk` 兼容路径；后续工程必须把“发布准入”和“高风险开房确认”两条链路对齐，避免一条严格、一条绕过。

## 核心流程

### 1. 导入草稿

1. Admin 上传 PDF。
2. Asset 层完成文件安全与原件保存。
3. WorldBook / AI 提取 `knowledge_graph`。
4. Module 保存草稿、导入状态、来源文件和质量报告。
5. RAG、SpoilerGuard、地图生成可消费该结构，但 Player 不可读取完整内容。

### 2. 校验与修正

1. Admin 打开 Module 详情。
2. 系统展示场景、NPC、线索、真相、结局、触发器、素材、地图、模板摘要。
3. 系统展示 `ModuleReadiness`。
4. Admin 修正结构字段、补素材、补模板、生成地图并确认。
5. 每次保存重新计算质量报告或标记需复核。

### 3. 发布

1. Admin 发起发布。
2. 后端校验结构必需项、truth 边界、地图状态、触发器 schema、素材引用和模板。
3. `blocked` 直接拒绝；`highRisk` 仅允许 Admin override，且必须填写 `reason`。
4. 发布成功后，模组进入 Host 可用列表。
5. 后续引入 version 后，发布生成不可变快照。

### 4. 开房实例化

1. Host 从可用模组列表选择模组。
2. Room 创建时绑定 `scenarioId` 或未来的 `moduleVersionId`。
3. Room start 时读取 confirmed map 初始化 `room_map_state`。
4. 创建首回合和 checkpoint。
5. 房间中的运行态变化只写 Room / State / Event，不反写 Module 模板。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| MO-FR-1 | Admin 能将 PDF 导入为 Module 草稿 | P0 |
| MO-FR-2 | 导入必须保存来源文件名、hash、原文和结构化 KG | P0 |
| MO-FR-3 | Module 必须有 `importStatus` 和 `publishStatus`，二者不能混用 | P0 |
| MO-FR-4 | Module 详情必须聚合质量报告、地图、素材和模板摘要 | P0 |
| MO-FR-5 | 质量报告必须给出 `ready/warning/highRisk/blocked` | P0 |
| MO-FR-6 | blocked 模组不能进入普通 Host 可用列表 | P0 |
| MO-FR-7 | Host/Admin 可查看可用模组，Player 不可查看后台模组列表 | P0 |
| MO-FR-8 | 模组地图可生成、编辑和确认 | P0 |
| MO-FR-9 | confirmed 地图在房间开局时初始化运行态地图 | P0 |
| MO-FR-10 | 前后端必须闭合 `GET /api/scenarios/{scenario_id}/templates` | P0 |
| MO-FR-11 | Admin 能管理 scenario 角色模板 | P1 |
| MO-FR-12 | Module 可编辑场景、NPC、线索、真相、结局和公开简介 | P1 |
| MO-FR-13 | Module 可编辑触发器，保存前验证 condition 和 mechanics | P1 |
| MO-FR-14 | Module 可把素材绑定到场景、线索、NPC 或地图节点 | P1 |
| MO-FR-15 | Player 端不得读取 truth、完整 KG、隐藏素材和 Host-only 字段 | P0 |
| MO-FR-16 | Room 运行态不得反写 Module 模板 | P0 |
| MO-FR-17 | 发布、撤回、强制发布必须记录 actor、reason、qualitySnapshot | P1 |
| MO-FR-18 | Admin UI 的导入、质量、地图、素材和模板状态必须中文可读 | P0 |
| MO-FR-19 | 后续 ModuleVersion 必须支持开房绑定不可变快照 | P2 |
| MO-FR-20 | 模组导入导出包必须脱敏并使用 Asset manifest | P2 |

## 接口方向

| 接口 | 当前状态 | 用途 | 本轮方向 |
| --- | --- | --- | --- |
| `POST /api/scenarios/import-pdf` | 已有 | 底层导入入口 | 保持可复用，但由 Admin 入口驱动 |
| `POST /api/admin/scenarios/import-pdf` | 已有 | Admin UI 导入入口 | 保持 admin-only，回到同一导入链路 |
| `GET /api/scenarios/available` | 已有 | Host/Admin 可用模组列表 | 返回 `ModuleHostOptionDTO[]`，只给可开房模组 |
| `GET /api/scenarios/{scenario_id}/quality-report` | 已有 | 查看质量报告 | 返回 `ModuleReadinessDTO` 口径 |
| `POST /api/scenarios/{scenario_id}/create-room` | 已有 | 从模组开房 | 与 `/api/rooms` 的校验口径统一 |
| `GET /api/admin/scenarios` | 已有 | Admin 列表 | 改为 `ModuleListItemDTO[]`，不默认返回大字段 |
| `GET /api/admin/modules/{module_id}` | 待新增 | Admin 模组详情 | 聚合 KG 摘要、质量、地图、素材、模板、发布状态 |
| `PATCH /api/admin/modules/{module_id}` | 待新增 | 编辑标题、公开简介、标签 | 仅受控 patch，不允许整包覆盖 |
| `PATCH /api/admin/modules/{module_id}/knowledge` | 待新增 | 编辑 KG 结构 | 保存后重算质量或标记 stale |
| `POST /api/admin/modules/{module_id}/publish` | 待新增 | 发布模组 | 校验 readiness，支持 override reason |
| `POST /api/admin/scenarios/{scenario_id}/map/generate` | 已有 | 地图草稿生成 | 固定 `knowledge_graph.scenes` 优先，兼容旧 `scenario_assets.scenes` |
| `PATCH /api/admin/scenarios/{scenario_id}/map` | 已有 | 地图草稿编辑 | confirmed 后拒绝普通编辑 |
| `POST /api/admin/scenarios/{scenario_id}/map/confirm` | 已有 | 地图确认 | 确认后供 Room start 使用 |
| `GET /api/scenarios/{scenario_id}/templates` | 前端期待、后端缺口 | 玩家/角色构建读取模板 | 返回公开模板 DTO |
| `POST/PATCH/DELETE /api/admin/modules/{module_id}/templates` | 待新增 | Admin 管理预设角色 | 写入 `character_templates` |

## 关键接口契约

### `GET /api/scenarios/{scenario_id}/templates`

最小返回字段：

- `templateId`
- `displayName`
- `occupation`
- `publicSummary`
- `suggestedSkills`
- `avatarAssetUrl`
- `selectable`

禁止返回：

- `secretBackstory`
- `truthLink`
- `hiddenClueIds`
- `adminNotes`
- `raw xlsx_data` 私密字段

补充说明：

- 当前 `join-info` 已能从 `character_templates` 取到模板；
- 但因为前端页面已显式请求该接口，本轮必须补齐统一只读入口，不能继续靠隐式旁路。

### 地图生成数据源

本轮固定策略：

1. 优先使用 `knowledge_graph.scenes`
2. 兼容旧 `scenario_assets.scenes`

工程回执必须说明：

- 旧数据是否仍被支持；
- 新生成或新编辑的模组是否还允许只写旧 `scenario_assets.scenes`。

### 结构编辑 patch 约束

- 不允许整个 scenario 的任意 JSON 覆盖；
- 标题、公开简介、标签走轻量 patch；
- `scenes/npcs/clues/endings` 走受控 section patch；
- `truth` / `spoiler_boundary` / `trigger` / `template` 分开接口；
- 保存后重算质量或标记 stale；
- 记录 actor、字段摘要、变更时间。

## 数据边界

- Module 模板存储在 scenario 相关表中；
- 运行态存储在 room、state、event、map state 表中；
- `raw_text`、`knowledge_graph.truth`、隐藏线索和 Host-only 触发器默认仅 Admin / Author / 授权 Host 可见；
- `scenarios.scenario_assets` JSON 是结构化语义资产，不等于上传文件表；
- `scenario_assets` 表是文件资源记录，文件安全归 Asset；
- `scenario_maps` 是模板地图，`room_map_state` 是运行态地图；
- `character_templates` 是模组预设角色，玩家加入后复制为角色实例，不反写模板；
- 进行中的房间不应被后续模板编辑污染。

## 权限边界

1. 未登录用户不能导入、编辑、发布或查看后台模组。
2. Player 不能访问 `/api/scenarios/available`、`/api/admin/scenarios` 或 Module 编辑接口。
3. Host 可以查看可用模组并开房，但不能编辑模组模板。
4. Admin 可以编辑和发布模组，并可处理 `highRisk` override。
5. Author 未来只能编辑自己有权限的模组。
6. AI 只能按调用任务读取必要片段，不能直接发布或删除模组。
7. Player 模板接口只返回公开模板字段，不返回 truth 或隐藏线索。

## 版本边界

- 本轮允许暂不完整实现 `module_versions`；
- 但必须明确：active room 不应受后续模板编辑影响；
- 如果当前仍按 `scenarioId` 绑定开房，工程回执必须把“房间绑定 mutable scenario”列为遗留风险；
- 这个遗留风险不只影响地图和模板，也可能影响运行中房间后续的 AI / RAG 读取口径，回执必须明确说明；
- 后续方向是：发布生成 `moduleVersionId`，新房间优先绑定版本快照。

## 导出边界

后续工程里至少要区分三种导出 scope，不得混成一包：

1. `admin_debug_export`
   - 仅供后台诊断，不可分享，不可当模组包发出。
2. `module_manifest_export`
   - 供模组迁移或导入导出使用；
   - 不包含 token、本地路径、hidden assets、debug secret。
3. `public_share_package`
   - 仅包含允许公开的模组资料；
   - 不得复用 debug export 或 full raw export。

## 验收标准

1. Admin 能导入 PDF，并得到 scenario id、结构化状态和质量报告。
2. Player 导入 PDF、查看可用模组、创建模组房间均被拒绝。
3. Host 只能看到可运行模组，并可用其创建房间。
4. blocked 模组不出现在普通 Host 可用列表，且不能普通 create-room。
5. highRisk 发布需要 override reason，并留下 qualitySnapshot。
6. 地图草稿可生成、编辑、确认；confirmed 后开房初始化地图。
7. 前端请求的 `GET /api/scenarios/{scenario_id}/templates` 后端存在，字段与 PlayerJoin / CharacterBuilder 匹配。
8. Module 详情不把本地文件路径、owner token、player token 暴露给 Host 或 Player。
9. Player 只能看到公开简介、公开模板和运行态投影，不能看到 truth 或完整 KG。
10. 房间运行后修改角色、地图、线索、状态不会反写 Module 模板。
11. 结构编辑接口不接受整包任意 JSON 覆盖，保存后会重算质量或标记 stale。
12. Admin UI 中文可读，相关页面 `npm run build` 通过。
