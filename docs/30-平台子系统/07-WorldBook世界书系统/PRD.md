# WorldBook 世界书系统 PRD V2.1

## 背景

AI-Keeper 的核心体验依赖 AI 能正确理解剧本，但玩家又不能提前看到真相。WorldBook 的职责就是把剧本变成可被 AI、RAG、地图、反剧透系统共同使用的结构化知识源，并保证这份知识源有质量、有来源、有权限边界。

当前代码已经具备 PDF 导入、AI 结构化、质量报告、NPC RAG 索引、防剧透索引和从剧本创建房间的雏形，但链路还不是闭环：导入计算了文本 chunk 却没有索引 raw scenario；quality_report 不参与可用剧本筛选；`structured` 和索引完整性口径未收敛；Admin 地图生成与导入结构字段存在断点。

当前阶段说明：

- 本 PRD 已可进入工程执行，但当前阶段仍是`P0 主链路 + 世界书安全索引风险识别版`。
- 文档已识别 PDF 导入半成品状态、schema normalization、`raw_text/truth` 泄露、RAG scenario entitlement、quality gate 缺失、地图字段对齐、Admin override 审计、重建幂等与版本追踪等问题。
- 文档完成不等于代码风险已关闭；只有后续工程批次与测试通过后，这些边界才算真正落地。

## 产品目标

1. Admin 能导入 PDF，并得到一个可诊断的结构化世界书。
2. Host 只能选择质量达标、索引完整度达标的世界书开房。
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
|---|---|---|
| Admin | 导入 PDF、查看质量报告、重建索引、重建 spoiler index、调试 RAG、执行质量 override | 把未脱敏 `raw_text` / `truth` / 本地绝对路径发布给玩家 |
| Host | 查看可用剧本列表、从合格剧本创建房间 | 通过玩家视角读取 `truth/raw_text` |
| Player | 通过投影和线索系统接触已公开世界信息 | 调用 WorldBook 管理接口、读取未发现线索、查看原始世界书 |
| AI-Keeper | 在受控上下文内读取世界书片段 | 绕过 Safety 读取并输出完整真相 |

## 数据分层

| 层 | 来源 | 用途 | 禁止混用 |
|---|---|---|---|
| 导入源文件 | PDF / `source_filename` / `source_sha256` / `original_file_path` | 去重、审计、排错 | 不进入玩家 API |
| 原始文本 | `scenarios.raw_text` | 结构化、内部索引、Admin 调试 | 不等于玩家可见知识 |
| 结构化世界书 | `scenarios.knowledge_graph` | 场景、NPC、线索、真相、结局、触发器 | 不等于房间运行态 |
| 质量报告 | `scenarios.quality_report` | 可用性判定、风险提醒、调试入口 | 不应只是展示字段 |
| RAG chunk | `document_chunks` | AI 检索世界知识 | 不等于可直接输出给玩家 |
| 防剧透索引 | `spoiler_sensitive_items` | truth / hidden clue / hidden NPC 输出拦截 | 不等于玩家已解锁事实 |
| 可用剧本 DTO | available scenarios list | Host 选剧本 | 不含 `raw_text/truth/original_file_path` |
| 地图输入 DTO | `knowledge_graph.scenes` / `scenario_assets.scenes` | 地图生成与场景派生 | 不等于玩家地图节点 |
| Admin 调试 DTO | classify / reindex / rebuild / quality override | 排错、重建、审计 | 不得向普通 Host/Player 扩散绝对路径、本地文件、敏感真相 |

## 状态模型

当前库表里主要有 `import_status`。文档层建议收敛为三层语义：

### 1. 导入状态 `import_status`

- `already_imported`
- `requires_ocr`
- `structured`
- `failed`

### 2. 就绪状态 `readiness_status`

- `ready`
- `partial`
- `blocked`

### 3. 索引状态 `index_status`

- `ready`
- `rag_missing`
- `spoiler_missing`
- `partial`
- `failed`

说明：

- `structured` 仅代表 `knowledge_graph + quality_report` 成功形成。
- RAG 或 spoiler index 缺失时，`import_status` 可以仍为 `structured`，但 `readiness_status` 不应为 `ready`。
- `blocked` 世界书不得进入 Host 普通可用列表，不得普通开房。

如果工程阶段暂不新增字段，也必须在返回体、日志和可用剧本筛选逻辑中显式实现这三层语义。

## Schema 与 Normalization

### 最小 schema

```json
{
  "title": "string",
  "synopsis": "string",
  "scenes": [],
  "npcs": [],
  "clues": [],
  "truth": {},
  "endings": [],
  "trigger_mechanics": [],
  "spoiler_boundaries": [],
  "key_skills": [],
  "recommended_tags": []
}
```

### normalization 规则方向

至少统一以下键名：

- `triggerMechanics -> trigger_mechanics`
- `spoilerBoundaries -> spoiler_boundaries`
- `keySkills -> key_skills`
- `recommendedTags -> recommended_tags`
- `npcsPresent -> npcs_present`
- `cluesAvailable -> clues_available`
- `imageUrl -> image_url`
- `npcName -> npc_name / name`

验收口径：

- camelCase / snake_case 输入最终能收敛到同一 schema。
- mock fallback 结构化结果也能被相同 normalize 逻辑消费。

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
11. 返回导入状态、页数、chunk 数、质量等级、索引完整度诊断。

### Flow B：Host 选择剧本开房

1. Host/Admin 请求可用剧本列表。
2. 列表只返回 `import_status=structured` 且 `readiness_status!=blocked` 的剧本。
3. `highRisk/partial` 剧本对 Host 显示风险提示。
4. Host 选择剧本创建房间。
5. 房间只保存 `scenario_id` 引用，不复制完整世界书。

### Flow C：AI 使用世界书

1. 玩家提交行动。
2. AI/RAG 根据 `room_id` 找到当前 `scenario_id`。
3. RAG 按 scenario-scoped、room-scoped、global rule 三类范围返回 chunk。
4. player-facing AI / RAG 不能直接把 `raw_text` / `truth` 原文吐给玩家。
5. AI 输出进入 Rule / Projection / Safety，不直接落库。

## 功能需求

### FR-1 导入状态必须可诊断

- `already_imported`：相同 PDF hash 已导入。
- `requires_ocr`：PDF 扫描版或无法抽取文本。
- `structured`：`knowledge_graph + quality_report` 已完成。
- `failed`：结构化或关键写入失败。

验收：

- 每种状态都有返回体和日志。
- `failed` 不进入 available 列表。
- `requires_ocr` 不创建可用世界书。

### FR-2 质量报告必须参与业务决策

质量等级：

- `ready`：可正常开房。
- `warning`：可开房，但 Host/Admin 看到风险。
- `highRisk`：Host 开房必须显式确认；Admin 可调试。
- `blocked`：不可进入普通可用列表，不可普通开房。

最小规则建议：

| 情况 | 建议等级 |
|---|---|
| 没有 scenes | `blocked` |
| 没有 truth / endings | `highRisk` 或更高 |
| 没有 clues | `highRisk` |
| 没有 NPC | `warning` |
| mock fallback 结构化 | 不得 `ready` |
| spoiler index 失败 | 不得 `ready` |

验收：

- `GET /api/scenarios/available` 不返回 blocked 世界书。
- `highRisk` 世界书开房需要显式确认或 Admin override。

### FR-3 RAG 索引必须闭环

导入成功时应写入：

- `source_type=scenario`：`raw_text` chunk
- `source_type=npc`：NPC 图谱 chunk
- metadata 至少包含 `scenario_id/source_type/index/visibility`

RAG scope 方向：

- scenario-scoped chunk：同一 scenario 的房间可复用基础剧本知识
- room-scoped chunk：事件、线索发现、玩家行为、临时事实只允许当前房间可读
- global rule chunk：规则书可跨房间读

验收：

- 当前剧本房间能命中 scenario chunk 和 npc chunk。
- 不同 scenario 房间不能命中彼此世界书 chunk。
- 同 scenario 两个房间不能共享 room-scoped 已发现事实。

### FR-4 raw_text / truth 必须受控

- `raw_text` 可以进入内部 RAG 索引，但默认不是 player-facing 可直接引用内容。
- `truth` 只允许用于内部推理和输出拦截，不允许作为玩家直接可读文本源。
- player-facing RAG search 不得直接返回 `raw_text` / `truth` chunk 原文。
- AI 如果内部读到了 truth，输出仍必须经过 SpoilerGuard / Projection。

验收：

- 玩家端没有接口能直接读取 `raw_text` 或完整 `truth`。
- player-facing RAG / AI 输出不会直接复述 truth chunk。

### FR-5 防剧透索引必须闭环

- `truth.summary` 必须进入 `spoiler_sensitive_items`
- hidden clue 必须进入 `spoiler_sensitive_items`
- hidden NPC 如来自世界书 schema，也应进入 sensitive index
- rebuild 接口必须可重复执行且幂等

验收：

- 玩家 narrative 命中未解锁 truth / hidden clue 时被拦截。
- 玩家发现全部线索也不等于可以直接读取 `knowledge_graph.truth`。

### FR-6 地图字段必须可派生

- 地图生成优先读取 `knowledge_graph.scenes`
- 若 `scenario_assets.scenes` 存在，可作为兼容覆盖层
- scene 派生时统一 `name/description/order/npcs_present/clues_available/image_url`
- 派生给地图时必须过滤 hidden clue 正文、未公开 hidden NPC 真名

验收：

- 导入后的剧本可直接生成地图草稿
- 玩家地图节点不会暴露 hidden clue 正文

### FR-7 Admin override / 重建必须可审计

- `highRisk/blocked` override 只允许 Admin 执行
- override 必须写审计事件
- RAG reindex / spoiler rebuild 必须记录 `rebuild_by/rebuilt_at/version` 或等价审计信息

审计事件方向示例：

```json
{
  "eventType": "admin_scenario_quality_override",
  "scenarioId": "sc_xxx",
  "fromLevel": "blocked",
  "toLevel": "warning",
  "reason": "manual review passed",
  "adminAccountId": "acc_xxx"
}
```

## 接口

| 接口 | 权限 | 说明 |
|---|---|---|
| `POST /api/scenarios/import-pdf` | Admin | 导入 PDF 并结构化 |
| `GET /api/scenarios/available` | Admin / Host | 获取可用于开房的剧本 |
| `GET /api/scenarios/{scenario_id}/quality-report` | 需补权限收敛 | 获取质量报告 |
| `POST /api/scenarios/{scenario_id}/create-room` | Admin / Host | 从剧本创建房间 |
| `POST /api/admin/scenarios/{scenario_id}/classify` | Admin | 结构化统计和分类 |
| `POST /api/admin/rag/reindex` | Admin | 重建 RAG |
| `POST /api/admin/scenarios/{scenario_id}/spoiler-index/rebuild` | Admin | 重建防剧透索引 |

## 数据安全

- `raw_text`、`knowledge_graph.truth`、`original_file_path` 不进入玩家 API。
- `original_file_path` 优先只作为内部排错字段；对普通 Admin DTO 也应优先返回 `source_filename/source_sha256`，避免本地绝对路径扩散到前端。
- RAG 查询必须同时满足 room membership、scenario entitlement 和 source-type 过滤。
- quality report 可以给 Host，但不应包含完整 truth 原文。
- Admin 调试接口可看更多信息，但返回也要避免 token 和本地绝对路径扩散。

## 异常处理

- AI Gateway 失败：记录 warning，回退到 `structure_scenario`
- DeepSeek 失败：使用 mock fallback，但质量等级通常不能为 `ready`
- RAG 不可用：导入可完成，但 `readiness_status` 不得为 `ready`
- spoiler index 构建失败：导入不应对 Host 标为 `ready`
- PDF 无文本：写入 `requires_ocr`，不创建空世界书

## 版本与幂等

后续至少应支持或预留：

- `knowledge_graph_version`
- `quality_report_version`
- `rag_index_version`
- `spoiler_index_version`

重建要求：

- 先删除当前 scenario 对应旧索引
- 再重建
- 记录 `rebuilt_at/rebuilt_by`
- 重复执行不产生重复 chunk 或重复 sensitive item

## 验收标准

1. Admin 导入普通 PDF 后，`scenarios` 有完整来源字段、`knowledge_graph` 和 `quality_report`
2. 导入后 `document_chunks` 至少包含 scenario chunk；有 NPC 时包含 npc chunk
3. 当前房间 RAG 搜索能命中本剧本 scenario / npc chunk，不能命中其他剧本
4. `spoiler_sensitive_items` 包含 truth 和 hidden clue，必要时包含 hidden NPC
5. `blocked` 世界书不会出现在 Host 可用列表
6. player-facing RAG / AI 不直接返回 `raw_text` 或完整 `truth`
7. `original_file_path` 不出现在 Host / Player 响应里
8. 相关测试命令通过：

```powershell
python -m pytest tests/server/test_ai_kp.py tests/server/test_rag*.py tests/server/test_spoiler*.py tests/server/test_quality.py -q
```
