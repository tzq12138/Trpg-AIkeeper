# AI-Only v1.1 规范—程序对齐报告

日期：2026-08-22
分支：`codex/20260813-rag-corpus-audit`
依据：`docs/日期/20260820/AI_KEEPER_P0_纯AI模式_冻结决策与实施任务包_v1.1.md`（D01～D25 决策冻结基线）
状态：冻结决策与程序的不一致处已全部修复；全量回归与 Golden Suite 证据见下文。

## 本轮结论

按任务包 §0 执行规则：**任何实现与冻结决策冲突时，修改实现；验收规范与冻结决策冲突时，修订规范**（WP-J 回填）。本轮共修正 9 处规范—程序不一致，全部采用 TDD（先改测试 RED → 最小实现 GREEN），并把验收规范回填为冻结口径。

## 修复清单（报告 vs 程序不一致）

### 1. D04 状态枚举（`src/server/engine/action_state.py`）

程序与旧版草稿规范一致地使用了 `aborted`/`partial`/`rejected`，与冻结 D04 冲突。

```text
room_runtime_status: running | paused_by_owner | paused_system | recovering | aborted
  → lobby | running | paused_by_owner | paused_system | recovering | ended
  （aborted 属于 ending_status：Owner 终止写入 ending_status=aborted，不再用作房间状态）

resolution_outcome: success | failure | partial | no_check | rejected
  → success | failure | partial_success | no_check | blocked | not_applicable
  （rejected 是动作生命周期终态，不进入结算结果枚举）
```

测试：`test_action_room_and_resolution_dimensions_are_distinct` 先改断言 → RED → 常量更新 → GREEN。

### 2. D04 Trace 枚举去重（`src/server/engine/resolution_trace.py`）

`resolution_trace.py` 持有一份独立的 `_ALLOWED_OUTCOMES`（同样含旧值）。已删除，改为从 `action_state` 导入 `RESOLUTION_OUTCOMES`，杜绝再漂移。新增测试锁定：`rejected` 归一化为 `None`、`partial_success` 正常入 Trace。

### 3. D21 NPC 字段名（`module_compiler.py` + Glass Rain `module.json`）

编译器运行时契约与模块使用旧名 `current_goal` / `attitude_by_character` / `reaction_policy`，与冻结 D21（`goals` / `attitude` / `reaction_rules`）冲突——按 D21 命名填写的主 NPC 反而会编译失败。

```text
current_goal: str        → goals: [str]
attitude_by_character    → attitude
reaction_policy          → reaction_rules
```

4 个主 NPC（袁保安、乔志愿者、韩岑、梅冬）与编译器字段表同步改名；`test_map_draft_v2.py` 运行时包断言同步。已验证 `runtime_contract_version=v1` 仅 Glass Rain 声明（其它黄金模块不受影响）。

### 4. D20 核心线索来源独立性（`module_compiler.py`）

原门禁只检查 `alternative_sources` 非空：声明一个与主来源相同来源的"替代"（如 `reveal_conditions=[talk han-engineer]` + `alternative_sources=["han-engineer"]`）即可通过。门禁升级为：

```text
唯一来源数（揭示条件锚点 + 替代来源，去重）≥ 2
或
clue 携带已编译 recovery_node（稳定 ID + trigger_conditions + reveal_scope）
```

否则产生阻断项 `core_clue_non_independent_sources`。Glass Rain 全部核心线索满足（已验证）。

### 5. D22 结局冲突编译期检测（`module_compiler.py`）

编译器此前只检查 `mutual_exclusion_group` 存在。现已增加：同组同优先级 → 阻断项 `ending_group_priority_conflict`；priority 必须为整数，否则 `missing_runtime_ending_field`。Glass Rain 四个结局（300/200/100/1000000）同组不同优先级，通过。

### 6. D22 Engine 读取冻结字段（`engine/ending_conditions.py`）

`_matching_decision` 原只读 `exclusive_group`；现优先读 `mutual_exclusion_group`，`exclusive_group` 仅为历史包兼容回退。

### 7. D22 module.json 字段去重

四个结局删除冗余的 `exclusive_group`，仅保留冻结字段 `mutual_exclusion_group`。

### 8. D24/D25 Benchmark 门禁缺失项（`scenario/ai_only_benchmark.py`）

冻结 D24/D25 要求而测量器缺失的三项已补齐：

```text
real_browser_session_count ≥ 2        → 不足记 release_blocker "real_browser_evidence"
silent_misinterpretation_count = 0    → 大于 0 记 observe_threshold_breach（有机械影响的静默误解零容忍）
player_rating_average ≥ 4.0          → 评分(清晰度/主动权/氛围 5 分制)均值不足进入 breach
```

### 9. D24/D25 有效结局率口径（`scenario/ai_only_benchmark.py`）

原口径只把 `victory`/`mixed` 计入有效结局率。冻结口径为"任何被确定性触发并提交的作者结局"（含 `defeat`/`safe_abort`），已改为 `_AUTHORED_ENDING_TYPES` 全计数，避免系统被激励回避失败（总评 §8 指出过同一风险）。

### 10. 回归修复：Trace 写入与并发请求的游标竞争（`engine/resolution_trace.py` + `engine/resolution_pipeline.py`）

全量回归暴露：`test_character_delete_waits_for_queued_consent_action_lifecycle` 确定性失败（`psycopg2.InterfaceError: cursor already closed`）。用 HEAD 工作树隔离验证：**本会话 5 个源文件排除嫌疑**（HEAD + 本会话文件 → 通过），确认为此前会话接入的 Trace 写入所致——`ResolutionTraceRecorder` 直接使用流水线的共享 `PgConnection`（单游标槽，生产端 `app.state.db` 同构：`main.py:102`），而 FastAPI 同步端点在线程池中与事件循环后台结算并发执行；Trace 在结算前后的 `execute`/`commit` 会关闭在途请求的游标。

修复：Trace 记录器改为**在连接池中取专用连接**（`PgConnection(conn._pool)`，辅助日志不再共用权威游标槽），并在 `resolve_action`/`_record_trace_stage` 中以 `finally` 归还原连接，防止池耗尽。无池连接（如 SQLite 单连）时保持原行为回退。

```text
修复前（工作树）  1 failed（cursor already closed，3/3 次复现）
修复后           被复现测试 + Trace 测试 6 passed；
                 全量回归重跑见"自动化证据"
```

## 验收规范回填（WP-J，`AI_ONLY_ACCEPTANCE_SPEC.md`）

按冻结口径修订 8 处（§2.1 Host 门禁 end room 行、§3 决策矩阵两行、§3.1 三层状态枚举块两行、动作语义词、房间状态写入行、Benchmark 样本描述）：`partial→partial_success`、房间态 `aborted→ended`（`aborted` 仅保留为 `ending_status` 语境）。规范全文已无旧枚举残留（已复查）。

## 自动化证据

### TDD 记录（每项均为 先 RED 后 GREEN）

| 修复 | RED 证明 | GREEN 证据 |
|---|---|---|
| D04 action_state 枚举 | 状态机测试失败（旧枚举断言错） | 34 passed |
| D04 Trace 枚举 | 新测试 RED（rejected 未归一化） | 39 passed（含状态机） |
| D21 NPC 字段 | 3 个 runtime contract 测试失败 | 9 passed |
| D22 冲突检测 + Engine 字段 | 2 个新测试 RED | 16 passed |
| D24/D25 Benchmark | 2 个新测试 RED + 数据类字段缺失 | 6 passed |
| 有效结局率口径 | 新测试 RED（1.0 vs 0.9667） | 同上 |

### 受影响文件批次

```text
python -m pytest tests/server/test_action_state_machine_v2.py \
  tests/server/test_resolution_trace.py tests/server/test_ending_conditions.py \
  tests/server/test_glass_rain_runtime_contract.py tests/server/test_ai_only_benchmark.py \
  tests/server/test_map_draft_v2.py tests/server/test_host_autonomy.py \
  tests/server/test_ai_gateway.py -q
116 passed —— 其中 1 error 为环境问题，见"环境事项"
```

```text
python -m pytest tests/server/test_map_draft_v2.py -q   （--basetemp 绕过环境锁后）
10 passed
```

```text
python -m compileall -q <5 个本次修改模块>   通过
git diff --check                            退出码 0（仅既有 LF/CRLF 提示）
```

### Golden Suite（六类黄金样本 9/9）

```text
AIKEEPER_DEV_MODE=1 python scripts/run_golden_module_suite.py --root "data/test_assets/六类黄金样本"
退出码 0；9/9 模组 = 导入 draft_ready | 运行包 ready | 房间 completed | Trace complete | Host 裁决 0
（报告：docs/loop_runs/2026-07-16-golden-module-suite-report.md）
```

本轮编译器改动（D20/D22 门禁）未影响六样本导入与结算。

### 全量回归（`tests/server/`，`--basetemp` 绕过环境锁）

- **第 1 轮**（修复 Trace 回归前，18:23 启动）：`1661 passed, 1 failed`——唯一失败为 Trace 游标竞争（见修复 #10），其余全部通过。
- **第 2 轮**：被**并行会话**干扰——19:01:09 有另一个工作会话（codex worktree 活动）向同工作树投放了 8 个新测试文件与 9 个新/改源文件，其中 `test_turn_settlement_projection.py` 导入尚不存在的 `build_turn_resolved_projection`，收集阶段中断。
- **第 3 轮（最终）**：`--ignore` 残缺文件后重跑：**`1668 passed, 15 failed`**。
- **15 个失败全部精确对账为并行会话 19:01+ 新功能文件的未完成测试**（`test_player_action_protocol`×8、`test_resolution_bundle_projection`×2、`test_image_generation_config`×3、`test_action_resolution_scheduler`×1、`test_background_resolution_runtime`×1；其对应 src 亦与 `resolution_pipeline.py` 正面交叉——19:05/19:06 并行会话曾重写该文件与 `resolution_trace.py`）。 **本会话与 08-20 会话的全部既有测试（1662 个）零失败**，含修复后的 bulk-delete 并发用例。

⚠️ **重要提示（并行会话协调）**：19:01:09 起同工作树有另一会话在活动中（`tools/`、`src/server/engine/resolution_bundle.py`、`action_protocol.py`、`room_action_batcher.py` 等均为其新产物，且有 19:05–19:06 对 `resolution_pipeline.py`/`resolution_trace.py` 的写入——本会话的 Trace 修复经检查仍完整存在）。本报告证据以本会话时间线为准；该会话的未完成功能不建议合入，`tests/server/` 整树运行在此之前将保持 15 个红例。

## 尚未宣称完成（任务包已声明、程序尚未实现）

以下与任务包波次计划一致，属"尚未实现"而非"实现不一致"，不构成本轮修复：

- **D07 自动复核闭环**：整改法只能 fail-closed（409 稳定错误码），自动重新解释→原 RollReceipt 复核→upheld/corrected/compensated 未接入（第二波 WP-G）。
- **D08/D09 候选路由与分级确认**：`awaiting_player_choice`/`awaiting_player_consent` 状态存在，但 Director 候选生成与按差异路由逻辑未接入（第二波 WP-D）。
- **D10 缺勤策略 / D11 recovery_proposal**：未实现（第二波 WP-H/WP-I）。
- **D12 Owner 终止字段**：`termination_reason`/`ending_status` 在库表与代码中均不存在——Owner 结束房间 API 未实现；Glass Rain 的 safe_abort 结局是 Engine 依据运行包条件提交的，不是 Owner 终止路径（第一波 WP-K 缺口）。
- **D13 `session_mode` 冻结 / D15 soft_pause/emergency_pause**：未实现（WP-K）。
- **D19 Session Zero**：未实现（WP-N）。
- **D23 完整 Trace 加密 30 天 + audit_admin 访问**：当前为脱敏 Trace（含 trace_hash 完整性校验、admin 元数据查询、30/180 天 retention 尚未配置）（WP-P）。
- **D24 真实执行**：30 场固定种子仿真与 2 场真实浏览器 Golden Run 尚未执行——测量器与门禁已齐（本轮补齐剩余三项门禁），不因其未执行而宣称通过。

结论：**本轮为"规范—程序对账"轮，不代表 P0 发布通过**；剩余未实现在任务包第二/第三波范围内。

## 环境事项

`.pytest-tmp-local`（pytest 本地 temp 目录）被外部进程目录级锁死（`Permission denied`，无法打开/删除目录条目），任何使用 `tmp_path` 的测试都会在 setup 报 `PermissionError`。本轮以 `--basetemp=.pytest-tmp-runtime` 绕过；建议排查 8/20 遗留的 `qwen-mm-plugins-core.exe` 进程或重启后恢复常规运行。此问题与本次代码修改无关（纯环境）。
