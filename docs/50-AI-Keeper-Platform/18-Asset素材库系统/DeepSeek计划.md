# Asset 素材库系统 DeepSeek 计划 V2.0

## 执行目标

把当前分散的文件处理能力整理成安全、可引用、可审计的 Asset 底座。第一轮优先解决上传安全、URL 权限、素材引用一致性、隐藏素材防剧透和 RAG 来源治理，不迁移存储后端，不扩展社区素材市场。

执行前必须先复核当前代码，尤其是：

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/db_adapter.py`
- `src/server/ai/rag.py`
- `src/server/rag_router.py`
- `src/server/engine/state_service.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/host/router_host.py`
- `src/server/host/host_store.py`
- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/pages/HostStage.tsx`

## 全局禁止事项

1. 禁止把本地绝对路径返回给 Player 或 public export。
2. 禁止把 `data/scenario_assets` 直接作为无鉴权公开目录。
3. 禁止仅凭前端 `accept` 限制文件类型，后端必须校验。
4. 禁止仅凭扩展名判断文件安全。
5. 禁止让 AI 直接读取未授权文件或写入素材文件。
6. 禁止隐藏素材进入玩家 RAG 上下文、Player 事件或 public export。
7. 禁止为了省事放宽 Admin、Host、Player 的权限边界。
8. 禁止本批次迁移到对象存储、CDN 或重做完整素材市场。
9. 禁止提交运行时上传文件、临时音频、导出包和本地数据库。

## Batch Asset-0：现状盘点与测试基线

### 目标

确认当前素材链路真实状态，先建立问题清单和测试基线，再进入代码修改。

### 允许改动

- `docs/50-AI-Keeper-Platform/18-Asset素材库系统/`
- 必要时新增审计记录文档，不改业务代码

### 任务

1. 运行 `git status --short`，确认工作区改动。
2. 搜索 `scenario_assets`、`asset_url`、`current_asset_url`、`UploadFile`、`document_chunks`、`rule_documents`。
3. 记录 Admin 上传、PDF 导入、RAG、Host scene sync、STT、xlsx 上传的现状。
4. 确认 `main.py` 是否存在静态文件挂载或授权读取路由。
5. 确认 `data/scenario_assets/` 和 `data/scenarios/` 的 git 忽略策略。
6. 跑相关测试，记录失败项和首个阻断点。

### 验收命令

```powershell
git status --short
```

```powershell
python -m pytest tests/server/test_pdf_parser.py tests/server/test_rag.py tests/server/test_rag_router.py tests/server/test_rag_security.py tests/server/test_room_security.py tests/server/test_character_join_import.py -q
```

### 预期结果

得到一份分层问题清单：上传安全、路径安全、URL 策略、引用一致性、RAG 权限、Host 投影、导出脱敏分别归类。

## Batch Asset-1：上传安全与文件元数据

### 目标

让 Admin 素材上传和 PDF 导入具备服务端安全校验，避免危险文件、巨型文件、伪装文件和目录穿越。

### 允许改动

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/config.py`
- `tests/server/test_admin_assets.py`
- `tests/server/test_room_security.py`
- `tests/server/test_pdf_parser.py`

### 任务

1. 增加统一文件校验函数：扩展名、MIME、文件头、大小上限。
2. 分开配置 PDF、图片、音频、视频、规则文档的允许类型。
3. 上传文件名继续使用服务端生成名，保留原始名仅作 metadata。
4. 删除文件时 resolve 最终路径，确认仍在 `ASSETS_ROOT` 内。
5. PDF 导入使用同一套文件大小和文件头校验。
6. 新增恶意文件名、超大文件、伪装类型、非 Admin 上传的测试。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_room_security.py tests/server/test_pdf_parser.py -q
```

### 禁止事项

- 不把上传文件直接放入可公开访问目录。
- 不允许 `.html`、`.js`、`.svg`、`.exe`、`.bat`、`.ps1` 等可执行或脚本型文件作为公开素材。
- 不因测试方便关闭鉴权。

## Batch Asset-2：标准 Asset DTO 与受控访问 URL

### 目标

统一素材接口返回值，建立“前端展示用 URL”和“服务端存储路径”的分离。

### 允许改动

- `src/server/router_admin.py`
- `src/server/models.py`
- `src/server/main.py`
- `tests/server/test_admin_assets.py`
- `tests/server/test_room_security.py`
- `tests/server/test_projection_visibility.py`

### 任务

1. 定义标准 Asset DTO：`assetId/scenarioId/originalName/mimeType/fileSize/visibility/url/createdAt`。
2. 将 `relative_path` 降级为 Admin 诊断字段或改为 `storageKey`。
3. 新增受控读取路由，例如 `/api/assets/{asset_id}`，由服务端校验权限后返回文件。
4. Admin 可访问所管理素材，Host 只能访问其房间 scenario 授权素材。
5. Player 只能访问已公开、已揭示或与自己相关的素材。
6. 所有读取路由禁止目录穿越，禁止通过 asset id 枚举跨剧本文件。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_room_security.py tests/server/test_projection_visibility.py -q
```

### 禁止事项

- 不把 `original_file_path`、`relative_path` 或磁盘路径发给 Player。
- 不把整个 `data/` 目录挂为公开静态服务。
- 不让 Host 访问其他房间或其他 scenario 的私密素材。

## Batch Asset-3：素材引用一致性与场景投影闭环

### 目标

修正 `assetUrl/currentAssetUrl/sceneImageUrl/image_url` 多口径并存的问题，让场景图从 State 到 Projection 再到 HostStage 可稳定展示。

### 允许改动

- `src/server/engine/state_service.py`
- `src/server/engine/projection.py`
- `src/server/host/router_host.py`
- `src/server/host/host_store.py`
- `src/server/models.py`
- `src/client/src/pages/HostStage.tsx`
- `tests/server/test_state_service.py`
- `tests/server/test_projection.py`
- `tests/server/test_host.py`

### 任务

1. 明确 `SceneChange.assetUrl` 的输入格式：优先 asset id 或受控 URL。
2. `room_scene_state.current_asset_url` 保存标准引用，不保存本地路径。
3. `s2c_scene_sync` payload 同时携带 `currentScene` 和标准图片引用。
4. Host router 将标准 payload 转为 Host UI 需要的 `image_url` 或直接使用 `assetUrl`。
5. HostStage 兼容标准字段，移除多余的临时命名分支。
6. Projection 根据 audience 过滤素材 URL。

### 验收命令

```powershell
python -m pytest tests/server/test_state_service.py tests/server/test_projection.py tests/server/test_host.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不让 HostStage 自己拼接磁盘路径。
- 不通过前端判断决定素材是否可见。
- 不新增未注册的 `s2c_*` 事件名。

## Batch Asset-4：RAG 来源治理与隐藏素材防剧透

### 目标

让素材 metadata 可以被 AI 检索，但隐藏素材和未揭示手out不会进入玩家上下文。

### 允许改动

- `src/server/ai/rag.py`
- `src/server/rag_router.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/ai/rag_context.py`
- `src/server/router_admin.py`
- `tests/server/test_rag.py`
- `tests/server/test_rag_router.py`
- `tests/server/test_rag_security.py`
- `tests/server/test_spoiler*.py`

### 任务

1. 上传公开素材时可调用 `RAGStore.index_asset` 写入 metadata。
2. metadata 包含 `asset_id/scenario_id/original_name/mime_type/visibility`。
3. hidden 或 host-only 素材不进入 Player 搜索结果。
4. SpoilerGuard 覆盖结构化 JSON 中的 hidden asset，并为上传表预留同步路径。
5. RAG 搜索按 room、scenario、role、visibility 过滤。
6. AI 输出引用素材时必须带 source metadata，不能编造文件内容。

### 验收命令

```powershell
python -m pytest tests/server/test_rag.py tests/server/test_rag_router.py tests/server/test_rag_security.py tests/server/test_spoiler_guard.py -q
```

### 禁止事项

- 不把隐藏素材描述塞进 Player RAG 上下文。
- 不允许普通玩家触发 RAG 写入。
- 不用 RAG 结果绕过 Projection 可见性规则。

## Batch Asset-5：地图、线索手out与 Admin UI 接入

### 目标

让素材可以被场景、地图节点和线索手out稳定引用，同时让 Admin UI 显示可读状态。

### 允许改动

- `src/server/router_admin.py`
- `src/server/ai/map_generator.py`
- `src/server/map_persistence.py`
- `src/server/player/router_clues.py`
- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/components/HostMapPanel.tsx`
- 相关 map/clue/admin 测试

### 任务

1. 为地图节点和线索手out定义 asset 引用字段。
2. 地图生成只引用结构化场景信息，不编造素材 URL。
3. Admin UI 展示素材分类、可见性、大小、引用数量和错误信息。
4. 上传限制与后端白名单一致。
5. Host 看到全量授权素材，Player 只看到已探索或已分享素材。
6. 线索手out公开时写入 Journal 或 Projection 事件。

### 验收命令

```powershell
python -m pytest tests/server/test_room_security.py tests/server/test_projection_visibility.py tests/server/test_clue*.py tests/server/test_map*.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不在地图节点里保存本地文件路径。
- 不把 Host full map 的素材字段原样发给 Player map view。
- 不把 Admin UI 的 `accept` 当作安全边界。

## Batch Asset-6：删除、孤儿清理、导出脱敏与审计

### 目标

完善素材删除和战报导出，避免坏引用、孤儿文件和敏感路径泄露。

### 允许改动

- `src/server/router_admin.py`
- `src/server/export.py`
- `src/server/events/event_log.py`
- `src/server/campaign_archive.py`
- `tests/server/test_admin_assets.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`

### 任务

1. 删除前查询引用关系并返回引用列表。
2. 支持强制删除，但必须记录 actor、reason、asset_id、reference_count。
3. 建立孤儿文件和孤儿记录盘点函数。
4. public export 过滤隐藏素材、本地路径和未公开附件。
5. full export 继续脱敏 owner token 和 player token。
6. 素材 reveal、delete、force delete 写入审计事件。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_archive.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不通过删除历史事件来解决泄露问题。
- 不把 full export 当作 public export。
- 不静默删除被引用素材。

## Batch Asset-7：端到端回归验收

### 目标

验证 Asset 与 AI-Keeper 核心跑团链路能协同工作。

### 手动验收流程

1. Admin 登录。
2. Admin 导入 PDF 剧本。
3. Admin 上传一张场景图和一个手out。
4. Host 创建该剧本房间。
5. Player 加入并 ready。
6. Host 开局。
7. 一次行动触发场景切换和公开投影。
8. HostStage 显示场景图。
9. Player 只能访问已公开素材。
10. RAG 搜索不返回隐藏手out。
11. Admin 删除未引用素材成功，删除被引用素材得到引用提示。
12. 导出 public 战报，不含隐藏素材、本地路径和敏感 token。

### 回归命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_pdf_parser.py tests/server/test_rag.py tests/server/test_rag_router.py tests/server/test_rag_security.py tests/server/test_room_security.py tests/server/test_projection.py tests/server/test_projection_visibility.py tests/server/test_host.py tests/server/test_character_join_import.py tests/server/test_archive.py -q
```

```powershell
cd src/client
npm run build
npm run test
```

### 预期结果

- 素材上传、访问、引用、投影、RAG、删除和导出均通过权限过滤。
- Host 能展示授权素材，Player 不能读取隐藏素材。
- AI 不直接落库文件，不把未发现素材写入玩家上下文。
- public export 可分享，full export 仅用于授权调试。

## 与其他模块接口

| 模块 | Asset 提供 | 对方需要遵守 |
| --- | --- | --- |
| Room | 房间 scenario 的素材归属和访问校验 | 不直接拼接素材路径 |
| User | admin/host/player 身份和房间成员判断 | 所有素材读写都经服务端鉴权 |
| Channel | 手out 分享和素材公开消息 | 不把私密素材发到公共频道 |
| Rule | 规则文档来源和 RAG 切片 | 规则写入仅 admin |
| Character | xlsx 输入边界 | 角色卡解析后不进入公共素材库 |
| WorldBook | 结构化场景、NPC、线索与素材引用 | 语义引用使用 asset id 或标准 URL |
| Clue | 手out 与线索发现关系 | 未发现线索不公开素材 |
| Scene/Map | 地图节点和场景图引用 | Player map view 必须过滤素材字段 |
| Journal | reveal、delete、export 审计 | public 视角严格脱敏 |
| AI-Keeper | 可检索素材 metadata | 不直接读未授权文件 |
| State | `currentAssetUrl` 运行时引用 | 不保存本地绝对路径 |
| Projection | audience 过滤后的素材 URL | Player 只收可见素材 |
| Host Client | 公共舞台图片和素材管理入口 | Host 不绕过后端读取素材 |
| Player Client | 已公开素材展示 | Player 不枚举素材库 |
| Safety | hidden asset 和文件安全策略 | 安全校验失败必须阻断 |
| Voice/Media | 临时音频边界 | 实时媒体不写入 AssetRecord |
| Admin/Ops | 存储根、清理和审计 | 运行时目录不进入 git |
