# AI-only P0-4 / P0-6A 阶段报告（2026-08-20）

状态：P0-4 运行时字段与编译门禁已完成；P0-6A 已建立首版统一 Resolution Trace，并接入隔离 Golden Suite 的 Trace/Host 硬门禁。尚未宣称真实浏览器 Golden Run 发布通过。

## P0-4 运行时契约

`data/golden_modules/02-short-team-glass-rain/module.json` 现在声明 `runtime_contract_version: v1`，并为场景、NPC、线索、失败推进和结局提供可执行字段：

- 场景：目的、进入/退出条件、可用事实、核心/可选线索、压力时钟、升级事件、即兴边界；
- NPC：重要性、当前目标、知识/秘密引用、对角色态度、杠杆、恐惧、反应策略、离场条件、即兴边界；
- 线索：重要性、揭示条件、替代来源、失败结果、前置事实及公开/私有版本；
- 失败推进：成本、状态/压力/信息影响、NPC 反应和后续行动；
- 结局：`ending_id`、`priority`、`exclusive_group` 与 `mutual_exclusion_group`。

编译器仅对声明 `runtime_contract_version=v1` 的模块启用严格门禁，以保持旧剧本兼容。门禁不可豁免的失败包括：缺少运行时字段、核心线索没有替代来源、一次失败可永久锁死核心线索、失败推进不保留核心线索、结局缺少互斥组。

## P0-6A 首版 Trace

新增 `resolution_traces` 表和 `ResolutionTraceRecorder`：

- 每个 action 幂等绑定一个 `resolution_trace_id`；
- 记录输入摘要/哈希、AI stage、机制计划（提案与 Engine 验证分开）、状态变更、SpoilerGuard、ProjectionDispatcher 和最终状态；
- Trace 与 `ai_call_logs` 可通过 `resolution_trace_id` 关联；
- 管理员可通过 `GET /api/admin/rooms/{room_id}/resolution-traces` 查询有界运行元数据；只返回阶段名、状态、哈希和 authority presence，不返回阶段原文；
- 所有写入做敏感字段过滤，不保存 token、密码、原始安全边界文本或未授权秘密；
- 失败路径也会生成 `failed` Trace，避免只有成功动作可诊断。

## 验证证据

- `python -m pytest tests/server/test_glass_rain_runtime_contract.py tests/server/test_module_compiler.py -q` → **23 passed**；
- `python -m pytest tests/server/test_resolution_trace.py tests/server/test_resolution_pipeline.py tests/server/test_action_lifecycle_v2.py::test_pipeline_does_not_claim_a_retired_room_action_for_resolution -q` → **18 passed**；
- `python -m pytest tests/server/test_glass_rain_golden_flow.py tests/server/test_glass_rain_four_player_flow.py -q` → **2 passed**；
- `python -m pytest tests/server/test_map_draft_v2.py::test_golden_module_install_builds_a_ready_cited_runtime_package -q` → **1 passed**；
- `python -m pytest tests/server/test_ai_decision_audit.py::test_failed_authoritative_provider_call_is_short_lived_diagnostic -q` → **1 passed**；
- `python -m pytest tests/server/test_golden_module_e2e.py -q` → **2 passed**；
- `python scripts/run_golden_module_suite.py --root data/test_assets/六类黄金样本 ...` → **9/9 模组完成，9/9 Trace complete，Host 裁决 0**；规则书链路为隔离确定性分片验证；
- `python -m pytest tests/server/test_resolution_trace.py -q` → **4 passed**（含管理员有界查询与脱敏）；
- `git diff --check` → 退出码 0（仅仓库既有 LF/CRLF 转换提示）。

## 未完成与边界

- 尚未运行真实 380 页规则源导入/发布的端到端浏览器验收；
- 尚未完成自动申诉闭环、Host 离线 Golden、恶意提示注入、并发重复提交和 hash freeze 的完整 Golden 矩阵；
- Trace 查询已具备有界元数据接口；统一指标聚合与 30 场双人/四人 benchmark 仍待执行；
- P0-6B 仍待建立玩家模型、批量样本和质量门槛报告。
