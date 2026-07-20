# 黄金样本全量导入与通关实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `G:\hermes-agent-workplace\D&D\CodeX-aikeeper\data\test_assets\六类黄金样本` 的全部九个模组目录导入隔离环境，并经由正常玩家行动链把每个测试房结算为 `completed`。

**Architecture:** 新增一个受约束的黄金样本清单，按“完整剧本”“剧本加素材”和“仅素材包”声明来源能力。导入器继续保留原始文件和 citation；对于没有剧情正文的素材包，编译器生成带 `derived_from_materials_only` 标识、可回溯到素材来源的测试运行包。自动玩家只调用既有草稿分析、确认和结算接口；结局由新的证据约束通用终局计划结算，禁止脚本直接更新房间状态。

**Tech Stack:** FastAPI、PostgreSQL、现有 `ContentPackage`/`ScenarioImportService`、`ResolutionPipeline`、pytest、PowerShell 隔离运行脚本。

## 全局约束

- 使用名称含 `test` 的独立 PostgreSQL 数据库和独立素材根目录，不操作 `:3001`/`:5186` 正在使用的数据。
- 原始资料仅用于本机验收；报告记录来源文件哈希、格式、解析能力和 citation，绝不导出原文或 API Key。
- 所有结局必须由玩家确认的 action 进入 `rooms.status = 'completed'`；测试脚本不得直接写该字段。
- 原文包含明确结局时，终局证据必须指向原文；仅素材包只能使用 `derived_from_materials_only=true` 的测试结局，报告不得称其为原文结局。
- 先写失败测试并验证失败，再写最小实现；不修改无关的既存脏文件。

---

### Task 1: 定义黄金样本清单和输入边界

**Files:**
- Create: `src/server/scenario/golden_suite.py`
- Test: `tests/server/test_golden_suite.py`

**Interfaces:**
- Produces `GoldenModuleSpec(slug, title, source_paths, source_mode, expected_completion_mode)`。
- Produces `iter_golden_module_specs(root: Path) -> list[GoldenModuleSpec]`，返回九个模组目录。

- [ ] **Step 1: 写失败测试**
  - 断言样本根目录返回九个唯一 slug。
  - 断言 `EN_Gateways-to-Terror`、`EN_Doors-to-Darkness` 与 `EN_Mansions-of-Madness` 是 `materials_only`，其余为 `scenario` 或 `scenario_with_assets`。
  - 断言不存在的目录抛出可读错误。

- [ ] **Step 2: 运行失败测试**
  - Run: `python -m pytest tests/server/test_golden_suite.py -q`
  - Expected: FAIL，因为清单模块不存在。

- [ ] **Step 3: 写最小实现**
  - 只扫描 `模组库` 的一级目录，按文件扩展名和已知素材文件名生成稳定清单。
  - 不把规则书和角色卡伪装成可开房模组；它们进入后续独立导入验收。

- [ ] **Step 4: 验证通过**
  - Run: `python -m pytest tests/server/test_golden_suite.py -q`
  - Expected: PASS。

### Task 2: 扩展输入适配并保留格式诊断

**Files:**
- Modify: `src/server/scenario/content_package.py`
- Modify: `src/server/scenario/import_service.py`
- Test: `tests/server/test_scenario_import_workflow.py`

**Interfaces:**
- `build_content_package()` 接受 PDF、DOCX、图片和已转换的旧 DOC 结果。
- 超大来源的错误包含文件名、大小和限制；批处理限制可由测试环境覆盖。

- [ ] **Step 1: 写失败测试**
  - 断言 64.88MB 与 84.83MB 的 PDF 可在黄金验收配置中进入导入流水线。
  - 断言旧 `.doc` 在可用转换器存在时转换为可审计页面/图片部件；转换器不可用时任务状态为 `awaiting_converter`，不丢失原件。
  - 断言普通上传默认限制仍拒绝超额请求。

- [ ] **Step 2: 运行失败测试**
  - Run: `python -m pytest tests/server/test_scenario_import_workflow.py -k 'golden or legacy_doc or size_limit' -q`
  - Expected: FAIL，因尚无黄金配置与旧 DOC 适配。

- [ ] **Step 3: 写最小实现**
  - 把大小限制提取为服务构造参数，默认值保持 `50MiB/100MiB`。
  - 黄金运行器使用 `100MiB/200MiB`，常规 API 保持原有限制。
  - 旧 DOC 适配器仅调用本机可用的转换器；没有转换器时返回显式可恢复状态，不伪造 OCR 文本。

- [ ] **Step 4: 验证通过**
  - Run: `python -m pytest tests/server/test_scenario_import_workflow.py -k 'golden or legacy_doc or size_limit' -q`
  - Expected: PASS。

### Task 3: 复用正式结局 API 的自动玩家结算

**Files:**
- Create: `tests/server/test_golden_module_e2e.py`
- Create: `scripts/run_golden_module_suite.py`

**Interfaces:**
- 自动玩家先通过 `POST /api/player/action-drafts/analyze` 与确认接口提交一条调查行动。
- 结束时调用既有 `POST /api/rooms/{room_id}/end`，请求体含选中的运行包终局、citation 和来源模式。

- [ ] **Step 1: 写失败测试**
  - 断言每个自动玩家房先有一条已完成 action，再通过正式结局 API 生成 `s2c_campaign_ended` 并令房间变为 `completed`。
  - 断言结局回执包含选择的名称、来源模式和不剧透 citation。

- [ ] **Step 2: 运行失败测试**
  - Run: `python -m pytest tests/server/test_golden_module_e2e.py -q`
  - Expected: FAIL，因为运行器不存在。

- [ ] **Step 3: 写最小实现**
  - 运行器从已发布版本选取一个带 citation 的终局；仅素材包附加 `derived_from_materials_only`。
  - 运行器只走 HTTP/测试客户端的正式接口，不直接更新 rooms、actions 或 events。

- [ ] **Step 4: 验证通过**
  - Run: `python -m pytest tests/server/test_golden_module_e2e.py -q`
  - Expected: PASS。

### Task 4: 建立隔离全量导入与自动玩家运行器

**Files:**
- Create: `scripts/run_golden_module_suite.py`
- Create: `tests/server/test_golden_module_e2e.py`
- Create: `docs/loop_runs/2026-07-16-golden-module-suite-report.md`

**Interfaces:**
- `python scripts/run_golden_module_suite.py --root <path> --report <path>` 输出每个模组的哈希、导入/编译/发布/开房/行动/结局证据。
- 运行器使用独立数据库、独立 storage/asset 根目录和确定性测试 Gateway；可选 `--provider live` 只用于代表性浏览器验收。

- [ ] **Step 1: 写失败测试**
  - 断言九个目录各产生一个隔离 scenario、运行包和 room。
  - 断言每个 room 有至少一条玩家 action 和最终 `completed` 状态。
  - 断言报告逐项注明 `original` 或 `derived_from_materials_only`，并记录规则书和角色卡的独立解析结果。

- [ ] **Step 2: 运行失败测试**
  - Run: `python -m pytest tests/server/test_golden_module_e2e.py -q`
  - Expected: FAIL，因为运行器不存在。

- [ ] **Step 3: 写最小实现**
  - 每个模组使用一名测试玩家；先发调查动作，再发与已编译终局匹配的行动并确认。
  - 完整剧本采用原文 citation 的终局；素材包由编译阶段生成的受限测试终局完成，且绝不覆盖原文声明。
  - 规则书逐本走规则资料解析，角色卡逐份走表单/XLSX 提取；它们不创建房间。

- [ ] **Step 4: 验证通过**
  - Run: `python scripts/run_golden_module_suite.py --root 'G:\hermes-agent-workplace\D&D\CodeX-aikeeper\data\test_assets\六类黄金样本' --report 'docs/loop_runs/2026-07-16-golden-module-suite-report.md'`
  - Expected: 报告含九个 `completed` 房间和十九个非剧本资料的解析结果。

### Task 5: 浏览器见证和回归验证

**Files:**
- Modify: `docs/loop_runs/2026-07-16-golden-module-suite-report.md`

- [ ] **Step 1: 浏览器验收**
  - 在隔离前端打开一间完整剧本房和一间素材包推导房。
  - 验证玩家只看见叙事、判定卡、地图投影和终局回执；不泄露文件路径、条目号或隐藏原文。

- [ ] **Step 2: 运行回归**
  - Run: `python -m pytest tests/server/test_golden_suite.py tests/server/test_ending_runtime.py tests/server/test_golden_module_e2e.py tests/server/test_scenario_import_workflow.py -q`
  - Run: `cd src/client && npm run test -- --run`
  - Run: `cd src/client && npm run build`
  - Run: `git diff --check`

- [ ] **Step 3: 固化证据**
  - 为每个模组记录 scenario/version/room ID、源哈希、终局 citation、动作数量、房间终态和任何保留风险。
