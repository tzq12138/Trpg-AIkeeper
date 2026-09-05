# Asset 素材库系统 PRD V2.1

## 当前阶段说明

- 本文档当前阶段为：`P0 主链路 + 素材上传安全、受控访问与防剧透风险识别版`。
- 当前代码已经具备 `router_admin.py / scenario/router_scenarios.py / db_adapter.py / ai/rag.py / engine/spoiler_guard.py / export.py / AdminDashboard.tsx / HostStage.tsx` 等真实锚点；本 PRD 必须以这些现状为基础。
- 本轮重点锁定：Admin 上传、PDF 原件导入、文件校验、Asset DTO、受控访问 URL、场景图投影、RAG metadata、隐藏素材过滤、删除审计和 public/full export 脱敏。
- 本轮不代表生产安全已经完成。受控 URL、visibility、删除引用保护、RAG 过滤等都需要后续工程与测试验收来关闭风险。

## 背景

AI-Keeper 已经有多条与素材相关的链路：

- Admin 导入 PDF 剧本并保存原件；
- Admin 上传剧本素材；
- RAG 保存规则文档、剧本文本和素材 metadata；
- Host 舞台显示场景图；
- 地图从结构化场景生成节点；
- 玩家上传 xlsx 角色卡；
- STT 处理临时音频。

这些能力目前分散在多个模块里，且边界还不稳：

- `router_admin.py` 的上传接口只做了最小文件名去路径化，仍返回 `relative_path`；
- `router_scenarios.py` 的 PDF 导入保存了 `original_file_path`，但只用扩展名限制 PDF；
- `db_adapter.py` 同时存在 `scenario_assets` 表和 `scenarios.scenario_assets` JSONB，同名易混；
- `models.py`、`state_service.py`、`HostStage.tsx` 同时存在 `assetUrl/currentAssetUrl/sceneImageUrl/image_url`；
- `rag.py` 的 `index_asset()` 还没有和上传链路形成稳定闭环；
- `spoiler_guard.py` 只覆盖 `scenarios.scenario_assets.items.*.is_secret`，还不覆盖上传素材表；
- `export.py` 的 public 过滤仍是 `audience != 'player'`，不足以支撑素材安全导出。

因此，本轮 Asset 的目标不是“多传几个文件”，而是把文件型资源定义成一套可信边界：可上传、可授权、可引用、可删除、可导出、不可剧透。

## 目标

1. 建立长期素材、临时媒体、剧本语义资产、运行时引用之间的清晰边界。
2. 让前端只拿受控 `assetUrl`，不拿本地路径、`storageKey` 或 `relative_path`。
3. 让 hidden/host-only/private 素材不进入 Player 下载、Player RAG、public export。
4. 让场景图、地图节点、线索 handout、日志导出都复用统一的素材引用口径。
5. 让素材删除具备引用预检查、强制删除语义和可审计行为。

## 非目标

- 不在本轮做对象存储、CDN、签名 URL 服务化迁移。
- 不在本轮做社区素材市场、版权交易、付费分发。
- 不让 Asset 负责 WorldBook 语义解析、线索发现、地图探索、AI 裁决。
- 不把 STT 临时音频做成长久资产。
- 不在本轮做 OCR、图片识别、转码与缩略图流水线。

## 用户角色

| 角色 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| Admin | 导入 PDF、上传/删除素材、排查引用、执行强制删除、触发重建索引 | 绕过校验直接把危险文件放入公开链路 |
| Host | 使用当前房间已授权素材驱动舞台和线索公开 | 直接枚举全局素材库、绕过 Projection 把 hidden 素材发给玩家 |
| Player | 访问已公开、已揭示或属于自己的素材 | 枚举素材库、访问 hidden/host_only、读取本地路径 |
| AI-Keeper | 使用授权 metadata 和安全摘要做检索与引用 | 直接读取未授权文件、把 hidden 素材写入玩家上下文 |
| Module Author | 在场景、地图、线索中引用 `assetId` | 直接写死服务器文件路径 |
| Admin/Ops | 配置存储根目录、清理孤儿文件、审计强制删除 | 把运行时上传目录当作无鉴权静态目录 |

## 产品范围

### 本轮进入

- PDF 原件保存、hash 去重入口与安全校验方向；
- Admin 剧本素材上传、列表、删除；
- 标准 `AssetRecordDTO` 与受控读取 URL；
- 统一 visibility 枚举与访问矩阵；
- `scenario_assets` 表与 `scenarios.scenario_assets` JSON 的边界；
- 场景图投影字段统一；
- RAG 素材 metadata 契约与 hidden asset 过滤；
- xlsx / STT 不进入长期 AssetRecord 的边界；
- public/full export 的素材脱敏口径。

### 本轮不进入

- 素材市场、跨房间共享库、对象存储迁移；
- 完整 BGM/SFX 资产库和视频播放链路；
- 版权、许可证、来源追踪后台；
- 图片/音频转码服务。

## 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `PhysicalFile` | 真实落盘文件 | `data/scenarios/` 原件、`data/scenario_assets/` 上传素材、临时文件 |
| L1 `AssetRecord` | `scenario_assets` 表 | 长期素材元数据 |
| L2 `StorageKey` | 服务端内部定位键 | 应逐步替代公开 `relative_path` |
| L3 `AssetAccessUrl` | 受控读取 URL | 前端只消费这一层 |
| L4 `AssetVisibility` | `host_only/hidden/public/revealed/private/admin_only` | 决定下发与检索边界 |
| L5 `AssetReference` | `refType/refId/field/audience` | 记录素材被场景、地图、线索、日志等引用 |
| L6 `SemanticScenarioAsset` | `scenarios.scenario_assets` JSON | 结构化剧本语义资产，不是上传文件表 |
| L7 `RuntimeAssetReference` | `assetId/assetUrl/currentAssetUrl` | 房间运行时引用 |
| L8 `RAGDocumentSource` | `document_chunks.metadata` | 索引来源与权限过滤 |
| L9 `TempMedia` | STT 临时音频 | 临时处理后删除 |
| L10 `ExportAssetView` | public/full 导出素材视图 | 输出层脱敏视图 |

## DTO 契约

### 最小 DTO 集合

- `AssetRecordDTO`
- `AssetUploadRequestDTO`
- `AssetUploadResultDTO`
- `AssetAccessUrlDTO`
- `AssetReferenceDTO`
- `AssetVisibilityDTO`
- `AssetDeletePreviewDTO`
- `AssetDeleteResultDTO`
- `AssetRagMetadataDTO`
- `AssetSceneReferenceDTO`
- `AssetExportViewDTO`
- `AssetApiErrorDTO`

### 关键 DTO 口径

#### `AssetRecordDTO`

```json
{
  "assetId": "asset_xxx",
  "scenarioId": "scenario_xxx",
  "originalName": "scene-1.png",
  "mimeType": "image/png",
  "fileSize": 123456,
  "visibility": "host_only",
  "url": "/api/assets/asset_xxx",
  "createdAt": "2026-07-08T12:00:00Z"
}
```

说明：

- `url` 是展示 URL，不是存储路径；
- `assetId` 是长期权威引用；
- 普通前端 DTO 中不得出现 `relative_path/original_file_path/storageKey`。

#### `AssetDeletePreviewDTO`

```json
{
  "assetId": "asset_xxx",
  "canDelete": false,
  "referenceCount": 2,
  "references": [
    {
      "refType": "scene",
      "refId": "scene_001",
      "field": "backgroundAssetId",
      "audience": "party"
    }
  ]
}
```

说明：

- 默认删除先返回预检查结果；
- 引用列表是强制删除前的确认依据。

#### `AssetRagMetadataDTO`

```json
{
  "sourceType": "asset",
  "assetId": "asset_xxx",
  "scenarioId": "scenario_xxx",
  "roomId": null,
  "originalName": "scene-1.png",
  "mimeType": "image/png",
  "visibility": "public",
  "refType": "scene",
  "refId": "scene_001",
  "audience": "party",
  "isRevealed": true,
  "createdAt": "2026-07-08T12:00:00Z"
}
```

说明：

- Player RAG 只能得到安全 metadata 或摘要；
- hidden asset 的 `originalName` 和描述在 Player 侧也不得提前暴露。

#### `AssetAccessUrlDTO`

```json
{
  "assetId": "asset_xxx",
  "mode": "stream|redirect|json_url",
  "url": "/api/assets/asset_xxx",
  "contentType": "image/png",
  "contentDisposition": "inline",
  "expiresAt": null
}
```

说明：

- `/api/assets/{asset_id}` 的最终行为必须在工程回执里写清楚，是返回文件流、302 临时 URL，还是 JSON + url；
- 无论采用哪种模式，都不得把高风险类型以内联可执行形式直接交给浏览器；
- `.html/.htm/.js/.svg` 默认不进入普通公开读取链路，除非后续有单独净化方案。

## 可见性枚举

| 枚举 | 含义 |
| --- | --- |
| `host_only` | 仅 Host/Admin 可见 |
| `hidden` | 未揭示；不进 Player 下载、Player RAG、public export |
| `public` | 当前房间成员与 public export 可见 |
| `revealed` | 已通过线索/投影/地图向指定范围揭示 |
| `private` | 仅特定角色或拥有者可见 |
| `admin_only` | 仅 Admin/Ops 诊断视图可见 |

权限判断必须至少结合：

- `viewer_role`
- `room_id`
- `scenario_id`
- `character_id`
- `asset.visibility`
- `reference audience`
- `reveal/unlock state`
- `revealScope`
- `ownerCharacterId/ownerAccountId`

补充约束：

- `revealed` 必须绑定揭示范围，至少区分 `party / character / public_export`；
- `private` 必须绑定归属字段，至少包含 `ownerCharacterId` 或 `ownerAccountId`，否则无法安全判断。

## 受控访问权限矩阵

| 读取方 | 允许读取 | 禁止读取 |
| --- | --- | --- |
| Admin | 当前 scenario 全量素材和诊断字段 | 无审计地批量外泄给普通前端 |
| Host | 当前房间授权素材，含 `host_only/hidden` | 其他房间或其他 scenario 的私密素材 |
| Player | `public/revealed/本人 private` | `hidden/host_only/admin_only` |
| Public export | `public` 与允许公开的 `revealed` | hidden/host_only/private、本地路径、debug 字段 |
| AI Player context | 安全 metadata / 安全摘要 | raw 文件、本地路径、hidden 原名 |
| AI Host/Admin context | 按权限的 metadata | 绕过服务端直接读磁盘 |

结论：

- 即便 `asset_id` 被猜中，也不能越权读取；
- 受控读取接口必须校验“谁在看、在哪个 room、此素材此刻是否对其可见”。

## 命名冲突策略

当前必须明确区分两套东西：

- `scenario_assets` 表：上传文件记录，文档命名为 `AssetRecord`；
- `scenarios.scenario_assets` JSON：结构化剧本语义资产，文档命名为 `SemanticScenarioAsset`。

本轮策略：

1. 暂不强制改数据库表名；
2. DTO、文档、代码注释必须使用不同命名，避免混写；
3. 如未来迁移 schema，可考虑把上传文件表改名为 `scenario_asset_files`。

## 运行时字段统一口径

### 权威字段

- `assetId`：长期引用 ID
- `assetUrl`：受控展示 URL
- `storageKey`：服务端内部字段
- `imageUrl`：前端兼容字段，不是数据库权威字段

### 约束

1. Server 内部存储定位使用 `storageKey` 或等价路径，不给 Player；
2. State / Projection / Host 运行时优先传 `assetId + assetUrl`；
3. `room_scene_state.current_asset_url` 不保存本地绝对路径；
4. `image_url / scene_image_url / sceneImageUrl` 仅作为兼容渲染层，不应继续成为权威字段源头。

## 删除策略

### 默认删除

- 无引用：删除 DB + 物理文件；
- 有引用：返回 `409 + references[]`，不执行删除。

### 强制删除

- 必须 `confirm=true + reason`；
- 必须写删除审计，至少包含 `actor/reason/assetId/referenceCount`；
- 被引用处要么清空，要么进入 `broken_reference` 可诊断状态；
- 不允许通过删除历史事件来“抹掉已发生的泄露”。

## RAG 素材契约

1. `index_asset()` 的输入必须是受控 metadata，不是任意文件原文。
2. metadata 至少包含：
   - `sourceType`
   - `assetId`
   - `scenarioId`
   - `roomId`
   - `originalName`
   - `mimeType`
   - `visibility`
   - `refType`
   - `refId`
   - `audience`
   - `isRevealed`
   - `createdAt`
3. Player RAG 只返回安全 metadata 或摘要，不返回 hidden asset 原始名称、描述、本地路径或文件正文。
4. AI 引用素材时必须带来源 metadata，不得编造文件内容。

## xlsx 与 TempMedia 边界

- `characters.xlsx_data` 属于 Character 领域数据，不属于长期素材库；
- STT 音频属于 `TempMedia`，仅为临时处理存在，处理后删除；
- 二者都不应生成可被普通 Asset 列表枚举的 `AssetRecord`。

## 运行时目录与 git 策略

当前仓库 `.gitignore` 已忽略：

- `data/scenario_assets/`
- `data/scenarios/`
- `*.db`
- `.runtime/`

本轮产品要求继续明确：

1. `ASSET_ROOT` 必须可配置；
2. 测试环境使用临时目录；
3. 运行时上传文件、STT 临时文件、导出包、本地 DB 不进入 git；
4. 生产环境不得把 `data/` 整体公开挂载成无鉴权静态目录。

## 核心流程

### 1. PDF 导入

1. Admin 调用 PDF 导入接口；
2. 后端校验 admin 身份；
3. 校验扩展名、MIME、文件头和大小上限；
4. 计算 SHA256，重复导入返回既有 scenario；
5. 保存 `original.pdf`；
6. 写入 `source_filename/source_sha256/original_file_path`；
7. 结构化剧本、建立 RAG 场景索引、建立 SpoilerGuard 基础索引。

### 2. Admin 上传素材

1. Admin 选择 scenario 并上传文件；
2. 后端校验文件类型、大小、文件头与危险扩展名；
3. 生成服务端存储文件名；
4. 写入 `AssetRecord`；
5. 返回标准 `AssetUploadResultDTO`；
6. 如果允许进入检索，则写入 `AssetRagMetadataDTO`。

### 3. 场景图投影

1. 上游模块为场景变更写入 `assetId/assetUrl`；
2. State 记录运行时素材引用；
3. Projection 按 audience 过滤并生成可见 `assetUrl`；
4. HostStage 消费受控 URL 展示公共舞台图像；
5. Player 仅在 `public/revealed/本人 private` 条件下获取 URL。

### 4. 线索 handout 公开

1. Asset 提供 `assetId` 和受控 URL；
2. Clue/Projection 决定何时公开；
3. publicVersion 与 handout URL 同步下发；
4. 未揭示前，Player 看不到 URL、原始文件名和描述。

### 5. 删除与导出

1. 删除前先返回引用预检查；
2. 有引用时默认阻止删除；
3. 强制删除必须 `confirm + reason`；
4. public/full export 按素材导出白名单输出，不透出本地路径、token、hidden 素材。

## 接口方向

| 接口或事件 | 当前现状 | 作用 | 本轮方向 |
| --- | --- | --- | --- |
| `GET /api/admin/scenarios/{scenario_id}/assets` | 已有 | Admin 素材列表 | 返回标准 `AssetRecordDTO[]` |
| `POST /api/admin/scenarios/{scenario_id}/assets` | 已有 | Admin 上传素材 | 增加校验、visibility、DTO、RAG metadata |
| `DELETE /api/admin/scenarios/{scenario_id}/assets/{asset_id}` | 已有 | 删除素材 | 增加路径校验、引用检查、force delete 语义 |
| `POST /api/scenarios/import-pdf` | 已有 | PDF 导入 | 增加 MIME/文件头/大小校验 |
| `POST /api/admin/scenarios/import-pdf` | 已有 | Admin 包装导入 | 保持 admin-only，并复用同一校验 |
| `POST /api/rag/index-rules` | 已有 | 规则文档索引 | 继续 admin-only |
| `POST /api/rag/search` | 已有 | RAG 搜索 | 素材 metadata 需按 visibility 过滤 |
| `s2c_scene_sync` | 已有 | 场景同步 | 统一携带 `assetId/assetUrl/imageUrl` 的安全口径 |
| `SceneChange.assetUrl` | 已有模型字段 | 场景变更输入 | 最终应由 Asset 提供受控展示口径 |
| `GET /api/assets/{asset_id}` | 当前未见 | 受控读取素材 | 本轮建议新增的读取入口方向 |

关于 `GET /api/assets/{asset_id}`，本轮至少要固定三件事：

1. 返回行为：文件流 / 302 到临时 URL / JSON + 受控 URL，三者选一并在回执说明；
2. 响应头：必须明确 `Content-Type` 与 `Content-Disposition`；
3. 安全边界：高风险类型默认不以内联方式交付浏览器。

## 数据边界

1. `data/scenarios/{scenario_id}/original.pdf` 是服务端原件路径，不给 Player。
2. `data/scenario_assets/{scenario_id}/` 是运行时上传目录，不等于公开静态目录。
3. `scenarios.original_file_path` 只允许服务端诊断使用。
4. `scenario_assets.relative_path` 当前只可作为临时兼容字段，且只允许 Admin 诊断视图读取，不能继续作为 Host/Player DTO 字段。
5. `document_chunks.metadata` 必须承载素材来源和 visibility。
6. `room_scene_state.current_asset_url` 是运行时显示引用，不是素材所有权记录。

## 权限边界

1. Admin 才能管理后台素材。
2. Host 只能读取其房间与其 scenario 已授权素材。
3. Player 只能读取受权素材 URL，不能枚举素材库。
4. hidden/host_only/private/admin_only 素材默认不进入 public export。
5. Player 和 public export 都不能拿到本地路径、token、debug metadata。

## Export 边界

### `public export` 禁止包含

- hidden asset URL
- host_only asset URL
- private asset URL
- `storageKey`
- `relative_path`
- `original_file_path`
- 本地绝对路径
- `owner_token`
- `player_token`
- raw prompt / raw response
- debug/admin-only metadata
- 未揭示 handout 标题与描述

### `full export` 仍禁止包含

- raw token
- API key
- 明文 secret
- raw prompt / raw response
- 账号敏感字段
- 运维原始内部日志

如未来需要 AI/Ops 原始审计导出，应另设 `admin_audit export scope`，不能复用 `full export`。

## 验收标准

1. PDF 导入同时校验扩展名、MIME、文件头和大小上限。
2. 重复 PDF 按 SHA256 返回既有 scenario，不创建重复原件。
3. 上传素材接口只允许 Admin。
4. 上传结果与列表都返回标准 DTO，不把路径给 Player。
5. 受控读取接口按 role + room + scenario + visibility 校验权限。
6. hidden/host_only 素材不进入 Player 下载、Player RAG、public export。
7. 场景图从 State 到 Projection 到 HostStage 的字段口径统一。
8. `scenario_assets` 表与 `scenarios.scenario_assets` JSON 在文档、DTO 和实现里不再混用。
9. 删除素材时，默认有引用即阻止；force delete 需要 `confirm + reason`。
10. public/full export 的素材脱敏边界符合本文档要求。
