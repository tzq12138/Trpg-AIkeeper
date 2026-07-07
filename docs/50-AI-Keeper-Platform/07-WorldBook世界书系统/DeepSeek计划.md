# WorldBook 世界书系统 DeepSeek 计划 V2.1

## 执行目标

把 WorldBook 从“能导入 PDF 的雏形”修成“导入后可被 AI / RAG / Safety / Map 稳定使用的世界书链路”。本计划只覆盖 `07-WorldBook世界书系统`，不做完整模组编辑器，不改玩家运行态状态系统。

当前阶段说明：

- 本计划对应的是`P0 主链路 + 世界书安全索引风险识别版`的执行包，不是 WorldBook 的最终生产安全完成版。
- 当前文档已识别 `raw_text/truth` 泄露、quality gate 缺失、RAG scenario entitlement、状态口径不清、地图字段断点、Admin 调试脱敏和重建幂等等关键问题。
- 文档完成不等于风险关闭；只有相关批次实现并通过测试后，这些风险才算真正关闭。

## 总体禁止事项

- 不让玩家接口返回 `raw_text`、`knowledge_graph.truth`、未发现线索或本地文件绝对路径。
- 不让 player-facing RAG 直接返回 `raw_text` / `truth` chunk 原文。
- 不让 AI 直接写 `scenarios` 或房间状态。
- 不把 WorldBook 修成 Module 编辑器大重构。
- 不绕过 Admin / Host 权限。
- 不用前端隐藏作为安全边界。
- 不让 `structured` 被错误当成“所有索引和防剧透都已完整就绪”。

## Batch WB-0：现状基线、乱码修正与 normalization 锁定

### 为什么做

当前结构化 prompt、fallback 文案、部分错误文案存在乱码。除此之外，schema 的 camelCase / snake_case 混用也会直接影响后续 06-NPC、09-Map、04-Rule 的对接。

### 允许修改

- `src/server/ai/ai_kp.py`
- `src/server/ai/gateway.py`
- `src/server/scenario/quality.py`
- 必要的测试断言

### 具体任务

1. 修复 `STRUCTURE_SYSTEM_PROMPT`，明确输出 JSON schema。
2. 修复 `structure_scenario` 的 user prompt。
3. 修复 `_structure_mock` 的默认中文字段，保证 fallback 可读。
4. 修复 `QualityReportGenerator` 的中文 message。
5. 锁定 normalization 规则：`triggerMechanics/spoilerBoundaries/keySkills/recommendedTags/npcsPresent/cluesAvailable/imageUrl`。

### 验收命令

```powershell
python -m pytest tests/server/test_ai_kp.py tests/server/test_quality.py -q
```

### 验收结果

- mock 结构化返回可读中文。
- AI 结构化 prompt 不再乱码。
- camelCase / snake_case 能稳定落到统一 schema。

## Batch WB-1：导入链路状态收口

### 为什么做

当前导入失败时多处 fallback 会让半成品看起来像成功；`requires_ocr` 有状态，但 `structured`、索引缺失、spoiler index 缺失、可用性状态之间没有明确分层。

### 允许修改

- `src/server/scenario/router_scenarios.py`
- `src/server/scenario/quality.py`
- 相关测试

### 具体任务

1. 明确 `import_status`：`already_imported / requires_ocr / structured / failed`。
2. 明确 `structured` 只代表 `knowledge_graph + quality_report` 成功。
3. RAG 或 spoiler index 失败时，不要静默吞掉；返回体或日志要包含诊断字段。
4. 通过派生状态或明确规则体现 `readiness_status / index_status` 语义。
5. `quality_report.level=blocked` 时，导入可以保存，但不能进入 Host 普通可用列表。

### 验收命令

```powershell
python -m pytest tests/server/test_pdf_parser.py tests/server/test_ai_kp.py tests/server/test_quality.py -q
```

### 验收结果

- 扫描 PDF 进入 `requires_ocr`
- 结构化失败进入 `failed`
- 重复导入返回 `already_imported`
- 索引失败不会被误报为 fully ready

## Batch WB-2：RAG 索引闭环与 visibility

### 为什么做

导入时计算了 chunk 数，但没有调用 `RAGStore.index_scenario`；只调用了 `index_npc_graph`。同时 RAG scope 现在没有把“scenario-scoped 基础知识”和“player-facing 可直接引用内容”分开。

### 允许修改

- `src/server/scenario/router_scenarios.py`
- `src/server/ai/rag.py`
- `src/server/rag_router.py`
- `src/server/router_admin.py`
- RAG 测试

### 具体任务

1. 导入成功后调用 `rag.index_scenario(scenario_id, raw_text)`。
2. 保留并修正 `rag.index_npc_graph(scenario_id, knowledge_graph)`。
3. 给 scenario / npc chunk metadata 预留 `scenario_id/source_type/visibility` 方向。
4. 明确 RAG scope：scenario-scoped、room-scoped、global rule。
5. player-facing RAG 不能直接返回 `raw_text` / `truth` 原文。
6. Admin `rag_reindex` 与导入链路保持一致，并要求幂等。

### 验收命令

```powershell
python -m pytest tests/server/test_rag*.py tests/server/test_rag_security.py -q
```

### 验收结果

- 当前剧本房间能搜到本剧本 scenario chunk
- 当前剧本房间能搜到本剧本 NPC chunk
- 不同剧本房间不能搜到彼此世界书 chunk
- 同剧本不同房间不共享 room-scoped 已发现事实
- player-facing RAG 不直接返回 `raw_text/truth`

## Batch WB-3：质量报告进入可用剧本筛选

### 为什么做

`QualityReportGenerator` 能输出 `blocked/highRisk/warning/ready`，但 `GET /api/scenarios/available` 当前只按 `import_status='structured'` 过滤，无法阻止 blocked 剧本被 Host 使用。

### 允许修改

- `src/server/scenario/router_scenarios.py`
- `src/server/router_rooms.py`
- `src/server/router_admin.py`
- 相关测试

### 具体任务

1. `available` 默认排除 `quality_report.level=blocked`。
2. 返回列表增加 `qualityLevel`、`completeness` 和必要风险提示字段。
3. `create-room` 对 blocked 剧本拒绝普通创建。
4. `highRisk` 剧本要求 Host 显式确认或 Admin override。
5. Admin override 必须 Admin-only，并写审计事件。

### 验收命令

```powershell
python -m pytest tests/server/test_rooms.py tests/server/test_room_security.py tests/server/test_admin_auth.py -q
```

### 验收结果

- blocked 剧本不出现在 Host 可用列表
- Host 不能普通开 blocked 剧本
- highRisk 剧本有显式确认或 override 流程
- override 有审计记录

## Batch WB-4：防剧透索引和 unlock 逻辑回归

### 为什么做

WorldBook 是真相源。`SpoilerGuard.build_sensitive_index` 已能提取 truth 和 hidden clue，但世界书层还需要把“玩家发现线索”和“玩家能直接读 truth”严格分开。

### 允许修改

- `src/server/engine/spoiler_guard.py`
- `src/server/player/router_clues.py`
- `src/server/engine/state_service.py`
- 相关 spoiler / clue 测试

### 具体任务

1. truth 永远不因普通玩家发现线索而完整解锁。
2. hidden clue 未发现时不进玩家输出。
3. 分享线索后只允许 `public_version` 进入玩家视图。
4. rebuild spoiler index 保持幂等：先删当前 scenario，再重建。
5. 必要时补 hidden NPC worldbook-sensitive 口径测试。

### 验收命令

```powershell
python -m pytest tests/server/test_spoiler*.py tests/server/test_clues.py tests/server/test_state_service*.py -q
```

### 验收结果

- truth 命中时被拦截
- hidden clue 未解锁时被拦截
- 玩家发现全部线索不等于能直接读 `knowledge_graph.truth`

## Batch WB-5：地图生成字段对齐

### 为什么做

Admin 地图生成读取 `scenarios.scenario_assets.scenes`，但导入结构化主要写 `knowledge_graph.scenes`。这会导致“导入成功但无法生成地图”的断点。

### 允许修改

- `src/server/router_admin.py`
- `src/server/ai/map_generator.py`
- `src/server/scenario/router_scenarios.py`
- 地图相关测试

### 具体任务

1. 地图生成优先读取 `knowledge_graph.scenes`。
2. 如果 `scenario_assets.scenes` 存在，可作为覆盖或兼容输入。
3. 统一 scene 字段：`name/description/order/npcs_present/clues_available/image_url`。
4. 派生给地图时过滤 hidden clue 正文和 hidden NPC 真名。
5. 生成失败返回可读错误。

### 验收命令

```powershell
python -m pytest tests/server/test_rooms.py tests/server/test_room_security.py -q
```

前端涉及 Admin 地图页面时补跑：

```powershell
cd src/client
npm run build
```

### 验收结果

- 导入后的剧本可直接生成地图草稿
- 地图节点不暴露 hidden clue 正文
- 地图字段和世界书 schema 对齐

## Batch WB-6：Admin 调试接口脱敏与版本追踪

### 为什么做

WorldBook 当前已有 classify / reindex / rebuild 入口，但文档阶段还没把绝对路径、版本、重建人、重建时间和普通可见字段边界写实到执行包里。

### 允许修改

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/db_adapter.py`
- 必要测试

### 具体任务

1. `original_file_path` 不进入 Host / Player 响应。
2. 普通 Admin DTO 优先返回 `source_filename/source_sha256`，绝对路径只在内部调试必要时出现。
3. reindex / rebuild 记录 `rebuilt_at/rebuilt_by/version` 或等价字段。
4. 重复 reindex / rebuild 不产生重复 chunk 或重复 sensitive item。

### 验收命令

```powershell
python -m pytest tests/server/test_admin_auth.py tests/server/test_rag*.py tests/server/test_spoiler*.py -q
```

### 验收结果

- `original_file_path` 不扩散到普通响应
- reindex / rebuild 幂等
- 管理重建具备基本审计信息

## Batch WB-7：端到端回归

### 为什么做

WorldBook 的价值不在单个接口，而在导入后能支撑完整跑团链路。

### 验收流程

1. Admin 导入 PDF
2. 系统生成 `knowledge_graph`、`quality_report`、scenario chunk、npc chunk、spoiler index
3. Host 在可用列表看到合格剧本
4. Host 创建房间
5. 玩家加入并提交行动
6. AI / RAG 能检索当前剧本信息
7. 玩家输出不泄露 truth
8. 地图可从世界书场景数据生成
9. Journal / Admin 审计能追溯导入、重建、override 等关键事件

### 验收命令

```powershell
python -m pytest tests/server/test_ai_kp.py tests/server/test_rag*.py tests/server/test_spoiler*.py tests/server/test_quality.py tests/server/test_rooms.py tests/server/test_player_intent.py -q
```

### 完成定义

- 导入链路没有半成品进入 Host 可用列表
- RAG 当前房间隔离正确
- player-facing RAG / AI 不直接返回 `raw_text/truth`
- spoiler index 能拦截未解锁真相
- DeepSeek 后续可以按 Batch WB-0 到 WB-7 逐个执行，不需要重新理解模块边界
