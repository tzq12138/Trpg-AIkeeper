# WorldBook 世界书系统 DeepSeek 计划 V2.0

## 执行目标

把 WorldBook 从“能导入 PDF 的雏形”修成“导入后可被 AI/RAG/Safety 稳定使用的世界书链路”。本计划只覆盖 `07-WorldBook世界书系统`，不做完整模组编辑器，不改玩家运行态状态系统。

## 总体禁止事项

- 不让玩家接口返回 `raw_text`、`knowledge_graph.truth`、未发现线索或本地文件绝对路径。
- 不让 AI 直接写 `scenarios` 或房间状态。
- 不把 WorldBook 修成 Module 编辑器大重构。
- 不绕过 Admin/Host 权限。
- 不用前端隐藏作为安全边界。

## Batch WB-0：现状基线和乱码修正

### 为什么做

当前结构化 prompt、fallback 文案、部分错误文案存在乱码。乱码会直接影响 DeepSeek 结构化质量，也会让测试断言和日志不可读。

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
5. 保持现有字段名兼容：`scenes`、`npcs`、`clues`、`truth`、`endings`。

### 验收命令

```powershell
python -m pytest tests/server/test_ai_kp.py -q
```

### 验收结果

- mock 结构化返回可读中文。
- AI 结构化 prompt 不再乱码。
- 现有 `test_structure_scenario_mock` 和 `test_structure_scenario_with_ai` 通过。

## Batch WB-1：导入链路状态收口

### 为什么做

当前导入失败时多处 fallback 会让半成品看起来像成功；`requires_ocr` 有状态，但 `failed`、索引缺失、spoiler index 缺失没有进入统一状态口径。

### 允许修改

- `src/server/scenario/router_scenarios.py`
- `src/server/scenario/quality.py`
- 相关测试

### 具体任务

1. 明确导入状态：`already_imported`、`requires_ocr`、`structured`、`failed`。
2. `structured` 只在 `knowledge_graph` 和 `quality_report` 完成后返回。
3. RAG 或 spoiler index 失败时，不要静默吞掉；返回体或日志要包含诊断字段。
4. `quality_report.level=blocked` 时，导入可以保存，但不能作为普通可用剧本。
5. 临时 PDF 文件处理要保持可清理，不影响 `original_file_path`。

### 验收命令

```powershell
python -m pytest tests/server/test_pdf_parser.py tests/server/test_ai_kp.py -q
```

### 验收结果

- 扫描 PDF 进入 `requires_ocr`。
- 结构化失败不产生可用剧本。
- 重复导入返回 `already_imported`。

## Batch WB-2：RAG 索引闭环

### 为什么做

导入时计算了 chunk 数，但没有调用 `RAGStore.index_scenario`；只调用了 `index_npc_graph`。同时 `search(room_id)` 当前只允许本房间 chunk、全局 rule、当前 scenario chunk，不包含 `source_type=npc`，导致 NPC 图谱可能检索不到。

### 允许修改

- `src/server/scenario/router_scenarios.py`
- `src/server/ai/rag.py`
- `src/server/router_admin.py`
- RAG 测试

### 具体任务

1. 导入成功后调用 `rag.index_scenario(scenario_id, raw_text)`。
2. 保留并修正 `rag.index_npc_graph(scenario_id, knowledge_graph)`。
3. 修改 `RAGStore.search(room_id=...)`，允许当前房间的 `scenario_id` 命中 `source_type=scenario` 和 `source_type=npc`。
4. 确认 `source_types` 过滤与 room/scenario 过滤同时生效。
5. Admin `rag_reindex` 与导入链路保持一致。

### 验收命令

```powershell
python -m pytest tests/server/test_rag*.py tests/server/test_rag_security.py -q
```

### 验收结果

- 当前剧本房间能搜到本剧本 scenario chunk。
- 当前剧本房间能搜到本剧本 NPC chunk。
- 其他剧本房间不能搜到不属于自己的 NPC chunk。
- 全局 rule 仍可被允许搜索。

## Batch WB-3：质量报告进入可用剧本筛选

### 为什么做

`QualityReportGenerator` 能输出 `blocked/highRisk/warning/ready`，但 `GET /api/scenarios/available` 只按 `import_status='structured'` 过滤，无法阻止 blocked 剧本被 Host 使用。

### 允许修改

- `src/server/scenario/router_scenarios.py`
- `src/server/router_rooms.py`
- `src/server/router_admin.py`
- 相关测试

### 具体任务

1. `available` 默认排除 `quality_report.level=blocked`。
2. 返回列表增加 `qualityLevel` 和 `completeness`，方便 Host UI 提示。
3. `create-room` 对 blocked 剧本拒绝普通创建。
4. Admin 调试场景可保留显式 override，但必须是 Admin-only，并写日志。
5. 如果历史数据没有 `quality_report`，按 `warning` 或重新计算处理。

### 验收命令

```powershell
python -m pytest tests/server/test_rooms.py tests/server/test_room_security.py -q
```

### 验收结果

- blocked 剧本不出现在 Host 可用列表。
- Host 不能普通开 blocked 剧本。
- Admin 可看到风险说明。

## Batch WB-4：防剧透索引和 unlock 逻辑回归

### 为什么做

WorldBook 是真相源。`SpoilerGuard.build_sensitive_index` 已能提取 truth 和 hidden clue，但 unlock 逻辑里查询 `clue_shares.room_id`，而当前 `clue_shares` 表没有 `room_id` 字段，虽被 try/pass 包住，但会影响解锁准确性。

### 允许修改

- `src/server/engine/spoiler_guard.py`
- `src/server/player/router_clues.py`
- `src/server/engine/state_service.py`
- 相关 spoiler/clue 测试

### 具体任务

1. 确认 truth 永远不因普通玩家发现线索而完整解锁。
2. 修正 shared clue unlock 查询，改为通过 `clue_shares -> clues` join 限定 room。
3. `StateService._apply_clue_changes` 写 `clue_shares` 时补齐 `public_version`。
4. rebuild spoiler index 保持幂等：先删当前 scenario，再重建。
5. 增加测试：未发现 hidden clue 不进玩家输出；分享后只允许 public version。

### 验收命令

```powershell
python -m pytest tests/server/test_spoiler*.py tests/server/test_clues.py tests/server/test_state_service*.py -q
```

### 验收结果

- truth 命中时被拦截。
- hidden clue 未解锁时被拦截。
- clue share 不需要 `clue_shares.room_id` 字段也能正确计算房间范围。

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
3. 统一 scene 字段：`name`、`description`、`order`、`npcsPresent`、`cluesAvailable`、`imageUrl`。
4. 不把未公开线索正文写入玩家地图节点。
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

- 导入后的剧本可直接生成地图草稿。
- 地图节点不暴露 hidden clue 正文。

## Batch WB-6：端到端回归

### 为什么做

WorldBook 的价值不在单个接口，而在导入后能支撑完整跑团链路。

### 验收流程

1. Admin 导入 PDF。
2. 系统生成 `knowledge_graph`、`quality_report`、RAG chunk、spoiler index。
3. Host 在可用列表看到合格剧本。
4. Host 创建房间。
5. 玩家加入并提交行动。
6. AI/RAG 能检索当前剧本信息。
7. 玩家输出不泄露 truth。
8. Journal 能追溯导入后核心事件。

### 验收命令

```powershell
python -m pytest tests/server/test_ai_kp.py tests/server/test_rag*.py tests/server/test_spoiler*.py tests/server/test_rooms.py tests/server/test_player_intent.py -q
```

### 完成定义

- 导入链路没有半成品进入 Host 可用列表。
- RAG 当前房间隔离正确。
- spoiler index 能拦截未解锁真相。
- DeepSeek 后续可以按 Batch WB-0 到 WB-6 逐个执行，不需要重新理解模块边界。
