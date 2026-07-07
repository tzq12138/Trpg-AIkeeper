# Asset 素材库系统 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + 素材上传安全、受控访问与防剧透风险识别版`。
- 第一轮目标不是扩展素材平台，而是把当前分散的上传、引用、检索、投影和导出收成一个可信的 Asset 底座。
- DeepSeek 执行前必须先复核当前代码，不得按旧 PRD 想象直接重写。

## 真实代码锚点

执行前必须至少读过：

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/db_adapter.py`
- `src/server/models.py`
- `src/server/ai/rag.py`
- `src/server/rag_router.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/engine/state_service.py`
- `src/server/host/router_host.py`
- `src/client/src/pages/AdminDashboard.tsx`
- `src/client/src/pages/HostStage.tsx`
- `src/server/player/router_player.py`
- `src/server/export.py`

## 全局禁止事项

1. 禁止把本地绝对路径、`relative_path`、`original_file_path`、`storageKey` 返回给 Player 或 public export。
2. 禁止把 `data/scenario_assets/` 或 `data/scenarios/` 直接挂成无鉴权公开目录。
3. 禁止只靠前端 `accept` 限制文件类型。
4. 禁止只靠扩展名判断文件安全。
5. 禁止把 `scenario_assets` 表和 `scenarios.scenario_assets` JSON 当成同一层数据。
6. 禁止让 AI 直接读取未授权文件或把 hidden asset 写入 Player 上下文。
7. 禁止 hidden/host_only/private 素材进入 Player Projection、Player RAG、public export。
8. 禁止为了图省事放宽 Admin / Host / Player 权限边界。
9. 禁止把 xlsx 角色导入和 STT 临时音频混入长期 `AssetRecord`。
10. 禁止通过删除历史事件来“修复”已经发生的泄露。
11. 禁止提交运行时上传文件、临时音频、导出包、本地 DB。

## Batch Asset-0：现状盘点与回归基线

### 目标

先产出现状清单和测试基线，不顺手修业务代码。

### 允许改动

- `docs/50-AI-Keeper-Platform/18-Asset素材库系统/`
- 必要的回执文档

### 任务

1. 运行 `git status --short`，确认当前工作区脏状态。
2. 搜索 `scenario_assets`、`relative_path`、`original_file_path`、`asset_url`、`current_asset_url`、`scene_image_url`、`index_asset`。
3. 记录当前：
   - 上传接口是否返回 `relative_path`
   - PDF 导入是否只按扩展名校验
   - `main.py` 是否存在公开静态挂载
   - `export.py` 是否仍用 `audience != 'player'`
   - `spoiler_guard.py` 是否只看 JSON 资产
4. 确认 `.gitignore` 是否忽略 `data/scenario_assets/`、`data/scenarios/`。
5. 跑相关测试，列出通过与阻塞项。

### 验收命令

```powershell
git status --short
```

```powershell
python -m pytest tests/server/test_pdf_parser.py tests/server/test_rag.py tests/server/test_rag_router.py tests/server/test_rag_security.py tests/server/test_character_join_import.py -q
```

### 预期结果

输出一份分层问题清单：上传校验、路径安全、DTO、访问 URL、场景图投影、RAG 过滤、删除策略、导出脱敏分别有哪些缺口。

## Batch Asset-1：上传安全与文件元数据

### 目标

把 Admin 上传和 PDF 导入的文件校验补到可执行的 P0 安全线。

### 允许改动

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/config.py`
- `tests/server/test_admin_assets.py`
- `tests/server/test_pdf_parser.py`
- `tests/server/test_room_security.py`

### 任务

1. 抽统一文件校验 helper：扩展名、MIME、文件头、大小上限。
2. 为 PDF、图片、音频、视频、规则文档拆开允许类型白名单。
3. 增加危险扩展名拒绝清单：`.html .htm .js .svg .exe .bat .cmd .ps1 .sh .php`。
4. 上传文件名继续去路径化，但服务端必须生成新的存储文件名。
5. 删除文件前必须 `resolve()` 最终路径，并确认仍在 `ASSETS_ROOT` 内。
6. 为非 Admin、路径穿越、伪装文件、超大文件补测试。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_pdf_parser.py tests/server/test_room_security.py -q
```

### 禁止事项

- 不把危险 SVG 当普通公开图片直接放行。
- 不因测试方便关闭鉴权。
- 不把 runtime 上传目录公开成静态目录。

## Batch Asset-2：标准 DTO、visibility 与受控访问 URL

### 目标

建立“Asset 记录”和“前端访问 URL”的硬边界。

### 允许改动

- `src/server/router_admin.py`
- `src/server/models.py`
- `src/server/main.py`
- `tests/server/test_admin_assets.py`
- `tests/server/test_room_security.py`

### 任务

1. 定义标准 `AssetRecordDTO` / `AssetUploadResultDTO` / `AssetAccessUrlDTO`。
2. 为上传素材增加统一 `visibility` 字段。
3. 新增受控读取入口，例如 `GET /api/assets/{asset_id}`。
4. Admin 可读全量；Host 只能读当前房间授权素材；Player 只能读 `public/revealed/本人 private`。
5. `relative_path` 降级为内部诊断字段，Player 与 public export 不得出现。
6. 明确 `admin_only` 素材只能在 Admin/Ops 诊断链路读取。
7. 明确 `revealed` 必须带 `revealScope`，`private` 必须带 `ownerCharacterId` 或等价归属字段。
8. 在工程回执中写清 `/api/assets/{asset_id}` 最终是文件流、302 临时 URL，还是 JSON + url。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_room_security.py -q
```

### 禁止事项

- 不把整个 `data/` 暴露为静态目录。
- 不让 Host 越权访问其他房间或其他 scenario 的素材。
- 不继续把 `relative_path` 当成展示 URL。
- 不把 `.html/.htm/.js/.svg` 以内联可执行形式直接交给浏览器。

## Batch Asset-3：命名统一与场景图投影闭环

### 目标

把 `assetId/assetUrl/currentAssetUrl/sceneImageUrl/image_url` 收成一套可执行口径。

### 允许改动

- `src/server/models.py`
- `src/server/engine/state_service.py`
- `src/server/engine/projection.py`
- `src/server/host/router_host.py`
- `src/server/host/host_store.py`
- `src/client/src/pages/HostStage.tsx`
- `tests/server/test_state_service.py`
- `tests/server/test_projection.py`
- `tests/server/test_host.py`

### 任务

1. 明确长期权威引用优先使用 `assetId`。
2. `assetUrl` 只作为受控展示 URL。
3. `room_scene_state.current_asset_url` 不得保存本地路径。
4. `s2c_scene_sync` 输出标准化的素材字段。
5. HostStage 不再自己拼磁盘路径，也不继续扩散兼容字段。

### 验收命令

```powershell
python -m pytest tests/server/test_state_service.py tests/server/test_projection.py tests/server/test_host.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不让前端决定素材是否可见。
- 不在 State 中保存 `C:\...` 或 `data/...` 本地路径。

## Batch Asset-4：RAG 来源治理与隐藏素材防剧透

### 目标

让 AI 只能拿到授权素材 metadata，且 hidden asset 不提前进入玩家上下文。

### 允许改动

- `src/server/ai/rag.py`
- `src/server/rag_router.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/ai/rag_context.py`
- `src/server/router_admin.py`
- `tests/server/test_rag.py`
- `tests/server/test_rag_router.py`
- `tests/server/test_rag_security.py`
- `tests/server/test_spoiler_guard.py`

### 任务

1. 上传公开素材后可写入 `source_type='asset'` 的 RAG metadata。
2. metadata 至少包含 `sourceType/assetId/scenarioId/originalName/mimeType/visibility/refType/refId/audience/isRevealed/createdAt`。
3. Player RAG 不得返回 hidden asset 的 `originalName`、描述、本地路径或原文。
4. SpoilerGuard 要把上传素材 visibility 纳入敏感索引设计，不再只看 JSON 资产。
5. AI 引用素材时必须带来源 metadata，不得编造文件内容。

### 验收命令

```powershell
python -m pytest tests/server/test_rag.py tests/server/test_rag_router.py tests/server/test_rag_security.py tests/server/test_spoiler_guard.py -q
```

### 禁止事项

- 不允许普通玩家触发 RAG 写入。
- 不允许用 RAG 搜索绕过 Projection/Visibility 规则。

## Batch Asset-5：地图、线索 handout 与 Admin UI 对齐

### 目标

让地图节点、线索 handout、后台素材 UI 都吃同一套 Asset 口径。

### 允许改动

- `src/server/router_admin.py`
- `src/server/map_persistence.py`
- `src/server/player/router_clues.py`
- `src/server/ai/map_generator.py`
- `src/client/src/pages/AdminDashboard.tsx`
- 相关 map/clue/admin 测试

### 任务

1. 地图节点与线索 handout 的文件引用统一为 `assetId` 或受控 URL。
2. handout 是否公开由 Clue / Projection 决定，不能由 Asset 直接广播。
3. Admin UI 展示类型、大小、visibility、引用数量和错误信息。
4. 前端 `accept` 与后端允许类型白名单对齐。
5. Player 视图只看到允许范围的素材 URL。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_room_security.py tests/server/test_projection_visibility.py -q
```

```powershell
cd src/client
npm run build
```

### 禁止事项

- 不在地图节点里保存本地磁盘路径。
- 不把 Host full view 的素材字段原样发给 Player。

## Batch Asset-6：删除、坏引用、导出脱敏与审计

### 目标

把删除语义、坏引用诊断、public/full export 素材边界补硬。

### 允许改动

- `src/server/router_admin.py`
- `src/server/export.py`
- `src/server/events/event_log.py`
- `tests/server/test_admin_assets.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`

### 任务

1. 删除前先查引用，默认有引用就返回 `409 + references[]`。
2. `force delete` 必须要求 `confirm=true + reason`。
3. 写删除审计，至少包含 `actor/reason/assetId/referenceCount`。
4. 被强制删除的引用进入 `broken_reference` 或等价可诊断状态。
5. `public export` 明确过滤 hidden/host_only/private URL、本地路径、token、debug metadata、未揭示 handout 标题描述。
6. `full export` 也继续脱敏 token / API key / secret / raw prompt。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_archive.py tests/server/test_event_log.py -q
```

### 禁止事项

- 不静默删掉仍被引用的素材。
- 不把 `full export` 当数据库原样导出。

## Batch Asset-7：端到端回归验收

### 目标

验证 Asset 已经能与 Room、Clue、Map、Projection、RAG、Export 主链路协同。

### 手动验收流程

1. Admin 登录并导入 PDF 剧本。
2. Admin 上传一张场景图和一个 handout。
3. Host 用该剧本开房。
4. Player 加入并 ready。
5. Host 开局。
6. 一次场景切换把场景图投到 Host 舞台。
7. 未揭示前，Player 无法读取 hidden handout。
8. handout 经 Clue/Projection 揭示后，Player 才获得 URL。
9. Player RAG 搜索不返回 hidden asset 原名和描述。
10. 删除未引用素材成功；删除被引用素材先得到引用提示。
11. public export 不包含本地路径、hidden/host_only/private URL、token。

### 回归命令

```powershell
python -m pytest tests/server/test_admin_assets.py tests/server/test_pdf_parser.py tests/server/test_rag.py tests/server/test_rag_router.py tests/server/test_rag_security.py tests/server/test_projection.py tests/server/test_room_security.py tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_character_join_import.py -q
```

```powershell
cd src/client
npm run build
```

### 预期结果

- 上传、读取、引用、投影、RAG、删除、导出都走统一权限边界；
- Host 能看到授权素材；
- Player 看不到 hidden/host_only；
- AI 不直接读文件；
- public export 可分享但不泄露路径和敏感附件信息。
