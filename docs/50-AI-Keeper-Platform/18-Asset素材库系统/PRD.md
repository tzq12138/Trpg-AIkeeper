# Asset 素材库系统 PRD V2.0

## 背景

AI-Keeper 已经有多条素材相关链路：管理员导入 PDF 剧本、上传剧本素材，玩家上传 xlsx 角色卡，RAG 存储规则和剧本文档切片，Host 舞台显示场景图片，地图从结构化场景生成节点，STT 处理临时音频。这些能力分散在 Admin、Scenario、RAG、Host、Player、Map 和 State 中，缺少统一的 Asset 边界。

本模块的目标不是一次做完整素材市场，而是先把核心跑团链路中的文件安全、引用一致性和防剧透治理收口。

## 目标

1. 建立剧本原件、上传素材、规则文档、RAG 切片、投影图片、地图素材、角色卡输入和临时媒体的统一分类。
2. 确保所有长期素材都有归属、元数据、访问边界和删除策略。
3. 确保前端只拿到可访问、可授权的 URL，不暴露服务端本地绝对路径。
4. 确保隐藏素材在未揭示前不进入 Player 投影、Player RAG 上下文、public export 和玩家可枚举接口。
5. 为 Host 舞台、地图节点、线索手out、WorldBook 和 Module 编辑器提供稳定的素材引用口径。

## 非目标

- 不在本轮实现社区素材市场、版权交易或付费下载。
- 不在本轮迁移到对象存储或 CDN。
- 不在本轮实现完整音频库、视频库、直播投屏和动态背景。
- 不让 Asset 解析剧本文义、决定线索发现或改写世界状态。
- 不让 AI 直接读取任意文件内容或绕过权限生成素材公开结果。
- 不把 STT 临时音频保存为长期素材。
- 不在 Asset 模块内实现地图探索、角色状态或规则结算。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Admin | 导入 PDF、上传和删除剧本素材、检查素材引用、排查文件问题 | 无审计地删除被引用素材或绕过安全校验上传危险文件 |
| Host | 使用房间和剧本已授权素材，驱动公共舞台展示 | 直接访问其他剧本素材，或把 Host-only 素材推给玩家 |
| Player | 看到已公开、已揭示或与自己相关的素材 | 枚举素材库、访问隐藏文件、本地路径或其他房间素材 |
| AI-Keeper | 使用经过过滤的素材 metadata、规则文档和已授权文本上下文 | 直接落库文件、读取未授权文件、把隐藏素材编进玩家响应 |
| Module Author | 后续把素材绑定到场景、NPC、线索和地图节点 | 绕过 Asset 引用规范写任意文件路径 |
| Admin/Ops | 配置存储根目录、清理孤儿文件、审计访问 | 把生产私有素材目录直接公开为静态目录 |

## 产品范围

### 本轮进入

- PDF 剧本原件保存、来源 hash 和重复导入判断。
- Admin 剧本素材上传、列表、删除。
- 上传文件类型、大小、文件名、路径和内容头校验。
- 素材元数据 DTO 和受控访问 URL 策略。
- `scenario_assets` 表与 `scenarios.scenario_assets` JSON 的语义区分。
- `SceneChange.assetUrl`、`s2c_scene_sync`、HostStage 图片展示的链路闭合。
- RAG 素材 metadata 索引和隐藏素材过滤口径。
- public export 中素材引用脱敏。
- xlsx 上传和 STT 临时音频不进入长期素材库的边界说明。

### 本轮不进入

- 资产市场、跨房间素材共享、素材售卖。
- 对象存储、CDN、转码服务和缩略图服务。
- 完整音频控制台、BGM 编排器和视频播放系统。
- 自动 OCR 和图片内容识别。
- 完整版权管理后台。
- 模组编辑器里的高级素材编排界面。

## 领域模型

| 模型 | 字段方向 | 说明 |
| --- | --- | --- |
| `AssetRecord` | `assetId/scenarioId/originalName/storedName/mimeType/fileSize/storageKey/visibility/sha256/createdAt` | 长期上传文件记录，替代直接向前端暴露 `relative_path` |
| `AssetAccessUrl` | `assetId/url/expiresAt/public/reason` | 前端展示用 URL，可为授权下载路由或短期签名 URL |
| `AssetReference` | `assetId/refType/refId/field/audience` | 某素材被场景、地图节点、线索、事件或导出引用 |
| `SemanticScenarioAsset` | `scenes/items/triggers/mechanics` | 结构化剧本语义，仍保存在 `scenarios.scenario_assets` 或后续 WorldBook 表 |
| `DocumentSource` | `sourceType/sourceId/roomId/metadata` | RAG 切片来源，服务于权限过滤和引用追踪 |
| `TempMedia` | `requestId/mime/size/duration/provider` | STT 会话数据，只保留日志级元数据，不保存音频文件 |

## 生命周期

| 状态 | 含义 | 进入条件 | 退出条件 |
| --- | --- | --- | --- |
| `uploaded` | 文件已通过校验并落盘 | Admin 上传成功 | 被索引、被引用、删除或隔离 |
| `indexed` | 元数据或文本切片进入 RAG | 公开或授权素材触发索引 | 重新索引或删除 |
| `referenced` | 被场景、地图、线索、事件或模组引用 | 写入引用关系 | 解除引用或删除 |
| `revealed` | 已通过 Projection 对玩家公开 | 线索发现、场景投影或 Host 公布 | 战役结束或引用失效 |
| `quarantined` | 文件未通过安全校验或需要人工处理 | MIME、大小、文件头、扫描结果异常 | 删除或管理员确认处理 |
| `deleted` | DB 记录和物理文件已删除 | Admin 删除成功 | 不可恢复，除非从备份恢复 |
| `orphaned` | 文件或记录失去另一侧对应项 | 异常中断、手工改文件、旧版本遗留 | 管理员清理或修复引用 |

## 核心流程

### PDF 导入

1. Admin 调用 `POST /api/admin/scenarios/import-pdf` 或 `POST /api/scenarios/import-pdf`。
2. 后端校验登录角色为 admin。
3. 后端校验 PDF 扩展名、MIME、文件头和大小。
4. 后端计算 SHA256，若已导入则返回既有 scenario。
5. 后端抽取文本，扫描件进入 `requires_ocr`。
6. 可解析 PDF 保存原件到 `data/scenarios/{scenario_id}/original.pdf`。
7. 后端写入 `source_filename/source_sha256/original_file_path/raw_text/knowledge_graph/import_status`。
8. RAG 和 SpoilerGuard 使用结构化结果建立索引，但不把原件本地路径发给前端。

### Admin 上传素材

1. Admin 在后台选择剧本并上传文件。
2. 后端校验 scenario 存在、角色为 admin、文件大小和类型合法。
3. 后端生成 `asset_id` 和安全文件名，写入受控存储目录。
4. 后端写入 `AssetRecord`，返回标准 DTO。
5. 若素材可进入检索，调用 RAG metadata 索引。
6. 前端展示名称、类型、大小、可见性和引用状态。

### 场景投影素材

1. AI/规则裁决输出建议，Engine/State 生成 `SceneChange.assetUrl` 或 `assetId`。
2. StateService 写入 `room_scene_state.current_asset_url`。
3. Projection 依据房间、角色、素材可见性生成 `s2c_scene_sync`。
4. Host 收到 `image_url` 或标准 `assetUrl` 后更新 `current_scene_image_url`。
5. Player 仅在素材被公开或与自己相关时获得可访问 URL。

### RAG 素材检索

1. 规则文档、剧本文本、角色摘要和素材 metadata 可进入 `document_chunks`。
2. RAG 搜索必须带房间上下文，按 room、scenario、rule 和 visibility 过滤。
3. `hidden_asset`、Host-only 素材和未揭示手out不能进入玩家上下文。
4. AI 输出引用素材时必须带来源 metadata，不直接编造文件内容。

### 删除与清理

1. Admin 请求删除素材。
2. 后端查询引用关系。
3. 无引用时删除物理文件和 DB 记录。
4. 有引用时返回引用列表；强制删除必须记录审计事件。
5. 清理任务定期盘点孤儿文件和孤儿记录。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| AS-FR-1 | Admin 能导入 PDF 剧本并保存原件、hash 和来源文件名 | P0 |
| AS-FR-2 | PDF 导入必须限制文件类型、大小和扫描件状态 | P0 |
| AS-FR-3 | Admin 能为指定 scenario 上传素材文件 | P0 |
| AS-FR-4 | 非 Admin 不能上传、删除或枚举后台素材 | P0 |
| AS-FR-5 | 上传文件名必须去路径化并生成服务端存储名 | P0 |
| AS-FR-6 | 上传和删除都必须防目录穿越 | P0 |
| AS-FR-7 | 后端必须校验 MIME、扩展名、文件头和大小上限 | P0 |
| AS-FR-8 | 素材接口返回标准 DTO，不向普通前端返回本地绝对路径 | P0 |
| AS-FR-9 | 素材访问必须走受控读取路由或签名 URL | P0 |
| AS-FR-10 | `scenario_assets` 表和 `scenarios.scenario_assets` JSON 的职责必须明确 | P0 |
| AS-FR-11 | 上传素材可被标记为 `host_only/public/revealed/hidden` | P0 |
| AS-FR-12 | 隐藏素材必须进入 SpoilerGuard 或同等敏感索引 | P0 |
| AS-FR-13 | 玩家不能搜索、下载或枚举未揭示隐藏素材 | P0 |
| AS-FR-14 | `SceneChange.assetUrl` 必须能驱动 Host 场景图更新 | P0 |
| AS-FR-15 | Projection 必须按 audience 过滤素材 URL | P0 |
| AS-FR-16 | 地图节点引用素材时保存 asset id 或受控 URL，不保存本地路径 | P0 |
| AS-FR-17 | RAG 的 `asset` 切片只能包含允许进入上下文的 metadata | P0 |
| AS-FR-18 | 规则文档索引只允许 admin 写入 | P0 |
| AS-FR-19 | xlsx 上传只作为角色数据输入，不进入公共素材列表 | P0 |
| AS-FR-20 | STT 音频只作为临时媒体处理，处理后删除 | P0 |
| AS-FR-21 | 删除素材必须同步 DB 记录和物理文件 | P0 |
| AS-FR-22 | 删除被引用素材时必须返回引用信息或记录强制删除审计 | P1 |
| AS-FR-23 | public export 不得包含隐藏素材 URL、本地路径或敏感 token | P0 |
| AS-FR-24 | Admin UI 的上传限制、错误提示和后端规则一致 | P0 |
| AS-FR-25 | 存储根目录必须可配置，测试和生产路径分离 | P1 |

## 接口方向

| 接口或事件 | 当前状态 | 用途 | 调整方向 |
| --- | --- | --- | --- |
| `GET /api/admin/scenarios/{scenario_id}/assets` | 已有 | Admin 素材列表 | 返回标准 Asset DTO 和引用状态 |
| `POST /api/admin/scenarios/{scenario_id}/assets` | 已有 | Admin 上传素材 | 增加安全校验、hash、visibility、RAG metadata |
| `DELETE /api/admin/scenarios/{scenario_id}/assets/{asset_id}` | 已有 | Admin 删除素材 | 增加路径根校验、引用检查、审计 |
| `POST /api/admin/scenarios/import-pdf` | 已有 | Admin PDF 导入 | 与 `/api/scenarios/import-pdf` 共用安全校验 |
| `POST /api/scenarios/import-pdf` | 已有 | PDF 导入 | 保持 admin-only，补文件头和大小限制 |
| `POST /api/rag/index-rules` | 已有 | 规则文档索引 | 保持 admin-only，补文档来源 metadata |
| `GET /api/rag/rule-docs` | 已有 | 登录用户查看规则文档列表 | 不返回全文给无权限用户 |
| `POST /api/rag/search` | 已有 | RAG 搜索 | 过滤隐藏素材和跨房间素材 |
| `s2c_scene_sync` | 已有 | 场景同步 | 标准化 `currentScene/assetUrl/imageUrl` |
| `SceneChange.assetUrl` | 已有模型字段 | 状态变更输入 | 接入受控 Asset URL 或 asset id |
| `HostHUD.sceneImageUrl` | 已有模型字段 | Host 舞台展示 | 不保存本地路径，只保存安全 URL 或引用 |

## 数据边界

- `data/scenarios/{scenario_id}/original.pdf` 是剧本原件存储，不直接公开给 Player。
- `data/scenario_assets/{scenario_id}/` 是运行时上传素材目录，不等于公开静态目录。
- `scenarios.original_file_path` 只能服务端使用，不能返回给玩家端。
- `scenario_assets.relative_path` 当前可用于 Admin 诊断，后续应被 `storageKey` 或受控 URL 替代。
- `document_chunks.metadata` 必须包含来源类型、来源 id、可见性和引用信息。
- `room_scene_state.current_asset_url` 是运行时场景引用，不是素材所有权记录。
- `characters.xlsx_data` 是角色数据，不应保存上传 xlsx 的本地路径。
- STT 临时文件只存在于处理过程，不写入 AssetRecord。

## 权限边界

1. Admin 可管理全部剧本素材。
2. Host 可使用自己房间 scenario 授权的素材，但不直接管理全局素材库。
3. Player 只可访问服务端判定对其可见的素材 URL。
4. RAG 写入操作只允许 admin 或房主，规则文档写入只允许 admin。
5. RAG 搜索必须按房间成员、房主或 admin 身份校验。
6. Hidden/host-only 素材默认不能进入 Player 事件、Player 搜索和 public export。
7. 素材读取路由必须校验 room、scenario、audience 和素材 visibility。
8. 任何接口不得把 `owner_token`、`player_token`、本地绝对路径或未授权 `relative_path` 返回给 Player。

## 验收标准

1. Admin 导入 PDF 后，scenario 记录包含来源、hash、原文和结构化状态。
2. 重复导入同一 PDF 返回既有 scenario，不创建重复原件。
3. 非 PDF、超大 PDF 或伪装 PDF 被拒绝。
4. Admin 上传合法图片后，文件落盘、DB 有记录、列表可见。
5. 非 Admin 上传、删除、列表请求被拒绝。
6. 文件名包含 `../`、绝对路径或危险扩展名时无法逃逸资产目录。
7. 前端展示素材时使用受控 URL，不使用服务端本地路径。
8. `SceneChange.assetUrl` 能驱动 HostStage 显示场景图。
9. Player 未获得授权时不能读取隐藏素材 URL。
10. RAG 搜索不会把未揭示隐藏素材返回给玩家。
11. 删除素材时，DB 和文件状态一致；被引用素材返回引用信息。
12. public export 不含隐藏素材、绝对路径和敏感 token。
