# WorldBook 世界书系统 PRD V2.0

## 背景

AI-Keeper 的核心体验依赖 AI 能正确理解剧本，但玩家又不能提前看到真相。WorldBook 的职责就是把剧本变成可被 AI、RAG、地图、反剧透系统共同使用的结构化知识源，并保证这份知识源有质量、有来源、有权限边界。

当前代码已经具备 PDF 导入、AI 结构化、质量报告、NPC RAG 索引、防剧透索引和从剧本创建房间的雏形，但链路还不是闭环：导入计算了文本 chunk 却没有索引 raw scenario；NPC chunk 可能无法在房间检索命中；质量报告不参与可用剧本筛选；提示词和部分文案存在乱码。

## 产品目标

1. Admin 能导入 PDF，并得到一个可诊断的结构化世界书。
2. Host 只能选择质量达标的世界书开房。
3. AI-Keeper 能从当前房间对应世界书检索到场景、NPC、规则和已允许上下文。
4. 玩家不能通过 WorldBook、RAG、导出或投影拿到未公开真相。
5. DeepSeek 后续实现时能按导入链路逐段修复，不把 WorldBook 写成平台大杂烩。

## 非目标

- 本轮不做完整模组编辑器。
- 本轮不做社区发布和付费市场。
- 本轮不做 OCR 服务，只保留 `requires_ocr` 状态。
- 本轮不允许玩家端浏览完整世界书。
- 本轮不让 AI 直接修改 WorldBook 或房间状态。

## 用户角色

| 角色 | 可做 | 不可做 |
| --- | --- | --- |
| Admin | 导入 PDF、查看质量报告、重建索引、重建 spoiler index、调试 RAG | 把未脱敏 raw_text 发布给玩家 |
| Host | 查看可用剧本列表、从合格剧本创建房间 | 通过玩家视角读取 truth/raw_text |
| Player | 通过投影和线索系统接触已公开世界信息 | 调用 WorldBook 接口、读取未发现线索 |
| AI-Keeper | 在受控上下文内读取世界书片段 | 绕过 Safety 读取并输出完整真相 |

## 主流程

### Flow A：导入 PDF

1. Admin 上传 PDF。
2. 系统检查账号角色、文件后缀、hash 去重。
3. 系统抽取 PDF 文本。
4. 如果扫描版无法抽取文本，写入 `requires_ocr`，停止后续结构化。
5. 系统调用 AI Gateway 结构化；失败时调用本地 `structure_scenario` fallback。
6. 系统规范化 `knowledge_graph`。
7. 系统写入 `scenarios` 和原始 PDF 文件。
8. 系统生成 `quality_report`。
9. 系统索引 raw scenario chunk 和 NPC chunk。
10. 系统生成 spoiler sensitive index。
11. 返回导入状态、页数、chunk 数、质量等级、索引数量。

### Flow B：Host 选择剧本开房

1. Host/Admin 请求可用剧本列表。
2. 列表只返回 `import_status=structured` 且质量未 blocked 的剧本。
3. Host 选择剧本创建房间。
4. 房间只保存 `scenario_id` 引用，不复制完整世界书。

### Flow C：AI 使用世界书

1. 玩家提交行动。
2. AI/RAG 根据 `room_id` 找到当前 `scenario_id`。
3. RAG 只能返回当前房间、当前剧本、全局规则允许的 chunk。
4. AI 输出进入 Rule/Projection/Safety，不直接落库。

## 功能需求

### FR-1 导入状态必须可诊断

- `already_imported`：相同 PDF hash 已导入。
- `requires_ocr`：PDF 扫描版或无法抽取文本。
- `structured`：结构化、质量报告、索引、防剧透索引均完成。
- `failed`：结构化或关键写入失败。

验收：每种状态都有返回体和日志；`failed` 不进入 available 列表。

### FR-2 世界书 schema 必须稳定

必须支持字段：

- `title`
- `synopsis`
- `scenes`
- `npcs`
- `clues`
- `truth`
- `endings`
- `trigger_mechanics`
- `spoiler_boundaries`
- `key_skills`
- `recommended_tags`

验收：AI 输出 camelCase/snake_case 都能规范化到同一 schema。

### FR-3 质量报告参与业务决策

质量等级：

- `ready`：可正常开房。
- `warning`：可开房，但 Host/Admin 看到风险。
- `highRisk`：Admin 可调试，Host 开房应确认。
- `blocked`：不可进入普通可用列表，不可普通开房。

验收：`GET /api/scenarios/available` 不返回 blocked 剧本。

### FR-4 RAG 索引必须闭环

导入成功时写入：

- `source_type=scenario`：raw_text chunk。
- `source_type=npc`：NPC 图谱 chunk。
- 必要时写入 metadata：`scenario_id`、`index`、`npc_name`、`source_filename`。

验收：当前剧本房间搜索能命中 scenario 和 npc chunk；其他剧本房间不能命中。

### FR-5 防剧透索引必须闭环

- `truth.summary` 必须进入 `spoiler_sensitive_items`。
- 隐藏线索必须进入 `spoiler_sensitive_items`。
- rebuild 接口必须可重复执行且幂等。

验收：玩家 public narrative 命中未解锁真相时被拦截或替换。

### FR-6 世界书不能变成运行态

- 房间只引用 `scenario_id`。
- 玩家发现线索写入 `clues`，不回写 `knowledge_graph.clues`。
- 运行态场景、地图、角色状态归 State/Map/Clue。

验收：一次玩家行动不会修改 `scenarios.knowledge_graph`。

## 接口

| 接口 | 权限 | 说明 |
| --- | --- | --- |
| `POST /api/scenarios/import-pdf` | Admin | 导入 PDF 并结构化 |
| `GET /api/scenarios/available` | Admin/Host | 获取可用于开房的剧本 |
| `GET /api/scenarios/{scenario_id}/quality-report` | 当前需补权限 | 获取质量报告 |
| `POST /api/scenarios/{scenario_id}/create-room` | Admin/Host | 从剧本创建房间 |
| `POST /api/admin/scenarios/{scenario_id}/classify` | Admin | 结构化统计和分类 |
| `POST /api/admin/rag/reindex` | Admin | 重建 RAG |
| `POST /api/admin/scenarios/{scenario_id}/spoiler-index/rebuild` | Admin | 重建防剧透索引 |

## 数据安全

- `raw_text`、`knowledge_graph.truth`、`original_file_path` 不进入玩家 API。
- RAG 查询必须按 `room_id` 和 `scenario_id` 限定。
- quality report 可以给 Host，但不能包含完整 truth 原文。
- Admin 调试接口可看更多信息，但返回也要避免 token 和本地绝对路径扩散。

## 异常处理

- AI Gateway 失败：记录 warning，回退到 `structure_scenario`。
- DeepSeek 失败：使用 mock fallback，但质量等级通常不能为 ready。
- RAG 不可用：导入可完成，但状态应标记索引缺失，Admin 可后续 reindex。
- Spoiler index 构建失败：导入不应对 Host 标为 ready。
- PDF 无文本：写入 `requires_ocr`，不创建空世界书。

## 验收标准

1. Admin 导入普通 PDF 后，`scenarios` 有完整来源字段、`knowledge_graph` 和 `quality_report`。
2. 导入后 `document_chunks` 至少包含 scenario chunk；有 NPC 时包含 npc chunk。
3. 当前房间 RAG 搜索能命中本剧本 scenario/npc chunk，不能命中其他剧本。
4. `spoiler_sensitive_items` 包含 truth 和 hidden clue。
5. `blocked` 剧本不会出现在 Host 可用列表。
6. 玩家端没有接口能读取 `raw_text` 或完整 `truth`。
7. 相关测试命令通过：

```powershell
python -m pytest tests/server/test_ai_kp.py tests/server/test_rag*.py tests/server/test_spoiler*.py -q
```
