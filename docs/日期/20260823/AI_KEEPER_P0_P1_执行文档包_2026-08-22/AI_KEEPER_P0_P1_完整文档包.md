# AI-Keeper P0/P1 完整执行文档包

> 合并版生成日期：2026-08-27



---

<!-- SOURCE FILE: 00_使用说明与总索引.md -->

# AI-Keeper P0 收口与 P1 可玩性 Alpha 执行文档包

> 文档包版本：v0.1  
> 创建日期：2026-08-22  
> 最近实物核验：2026-08-27（实施核验快照，非 Release Candidate）  
> 当前阶段：P0 正在实施；P1 规范与测试准备并行  
> 适用范围：CoC 7e、`runtime_version=v2`、`session_mode=ai_only`  
> 目标读者：产品、后端、前端、AI/Prompt、剧本、QA、运维与审计负责人

---

## 1. 文档包目的

本包解决两个连续问题：

1. **怎样证明 P0 真的完成，而不是“代码已经改过”。**
2. **P0 完成后，怎样把 AI-Keeper 从技术闭环推进到陌生玩家可独立完成一场团的 Playable Alpha。**

本包不重新讨论 `D01～D25`。这些决策已经冻结，实施与测试应以《AI-Keeper P0 纯 AI 模式：冻结决策与实施任务包 v1.1》为准。

---

## 2. 当前产品基线

已确认的产品定位是：

> AI 承担 KP；人类房主只承担房间运营、暂停、恢复与公共舞台职责；确定性 Engine 仍是唯一权威状态写入者。

当前仓库文档同时表明：

- 核心技术栈为 FastAPI、React/TypeScript、PostgreSQL、可选 Redis、多 Provider AI 与独立 KP MCP Server；
- `Engine → StateService` 是权威状态链路；
- 现有实现仍存在 Host 手动触发、Host 审查、`host_exception`、空字典 Provider 回退等需要由 P0 清除的旧路径；
- 当前有三套 Golden Module，其中 `02-short-team-glass-rain` 是 2–4 人短团，是 P0/P1 的首要完整验证模组。

### 来源定位

| 来源 | 主要依据 |
|---|---|
| `CLAUDE.md` L7–L9 | 项目概述与“AI 是 KP、人类房主仅运营”的核心假设 |
| `功能文档.md` L41–L47 | Engine 权威、AI 不写状态、Host 不判定等原则 |
| `功能文档.md` L137–L227 | 动作、状态机、审查、同意与缺勤相关现状 |
| `CLAUDE.md` L97–L110 | Engine、Pipeline、Provider、Director、Narrator 与 Projection 的现状 |
| `功能文档.md` L619–L629 | 三套 Golden Module 的定位与结构 |
| P0 冻结基线 v1.1 | `D01～D25`、工作包、Requirement ID 和发布门槛 |

---

## 3. 已审查与尚未审查的材料

### 已作为本包输入

- `AI_KEEPER_P0_纯AI模式_冻结决策与实施任务包_v1.1.md`
- `功能文档.md`
- `CLAUDE.md`
- `README.md`
- 当前对话中已冻结的 `D01～D25`

### 2026-08-27 已完成的实物核验

- 已逐份阅读本目录的 `00～07`、`99`、`MANIFEST` 与合订版；`99` 保持只读冻结基线，不在本次修改；
- 已读取 `data/golden_modules/02-short-team-glass-rain/module.json`、其 README 与内嵌 `quality_report`，并将静态场景、NPC、线索、恢复节点、压力钟和结局 ID 回填至 05；
- 已核对 D01、D11、D12、D13/D14、D15、D18、D23 的实现与定向自动测试；具体测试名、边界和未覆盖项以 01、07 为准；
- 已审阅 02（P1 规范）、03（质量量表）、04（真人测试协议）、06（Backlog）为未来验收/实施文档；它们仍是 Draft，不表示已经执行了真人测试或 P1 验收。

### 尚未获得 Release 级证据

- `kp_mcp_server/prompts/soul.md`、`rules.md`、`contract.md` 的独立 Prompt 深审与需求追踪报告；
- 已发布场景记录、编译后 runtime package、实际房间的冻结 `version_bundle` 与对应 Trace；
- D19 所要求的私密/公共投影实际探测证据及冻结的缺勤策略；
- 123 条 Requirement 的逐项证据映射、全量回归、30 场自动 Benchmark、至少 2 场真实浏览器 Golden Run；
- 真实玩家录屏、问卷和质量指标报告。

因此，静态场景字段和定向测试只能作为 **实施核验**；P0 仍不得写成已通过或已发布。

---

## 4. 文档清单

| 编号 | 文件 | 用途 | 主要责任人 |
|---:|---|---|---|
| 00 | 本文件 | 总索引、执行规则、变更控制 | 产品负责人 |
| 01 | `01_P0_RELEASE_CHECKLIST.md` | P0 Requirement → Test → Evidence → Gate | P0 负责人、QA |
| 02 | `02_P1_PLAYABLE_ALPHA_SPEC.md` | P1 产品定义、玩家旅程、功能与退出条件 | 产品、前端、后端 |
| 03 | `03_AI_KP_QUALITY_RUBRIC.md` | AI-KP 七维质量量表与问题分级 | AI/Prompt、剧本、QA |
| 04 | `04_PLAYTEST_PROTOCOL.md` | 真人跑团测试流程、观察方式与报告模板 | QA、产品研究 |
| 05 | `05_GLASS_RAIN_PLAYER_JOURNEY.md` | Glass Rain 端到端玩家旅程与验收用例 | 产品、前端、剧本 |
| 06 | `06_P1_IMPLEMENTATION_BACKLOG.md` | P1 工作包、依赖、分工和停止规则 | 项目负责人 |
| 07 | `07_仓库实物核验清单.md` | Prompt、DTO、Glass Rain 与代码证据核验 | 架构、AI、剧本、QA |
| 99 | P0 冻结基线副本 | 追溯已冻结决策 | 全员只读 |

另提供：

- `AI_KEEPER_P0_P1_完整文档包.md`：全部文档合并版；
- 本目录内的 Markdown 源文件为准；本次未核验同名压缩包产物，不能将其作为交付证据。

---

## 5. 执行顺序

```text
P0 实施进行中
→ 持续更新 01_P0_RELEASE_CHECKLIST
→ 完成仓库实物核验
→ 形成 P0 Release Candidate
→ 硬阻断、Benchmark、真实浏览器证据全部通过
→ 冻结 P1 Playable Alpha v1
→ 按 06_P1_IMPLEMENTATION_BACKLOG 分波次实施
→ Glass Rain 内部 Dogfood
→ 受控新玩家测试
→ 陌生玩家测试
→ 达到 P1 退出条件
→ 才进入内容生产能力 P2
```

P0 未通过时，可以准备 P1 文档、交互原型、测试脚本和数据契约，但不得依赖尚未冻结的状态、权限和 DTO 大规模返工业务代码。

---

## 6. 文档状态约定

| 状态 | 含义 |
|---|---|
| `Draft` | 可讨论，不能作为发布门槛 |
| `Review` | 已进入跨角色评审，需记录问题 |
| `Approved` | 已批准，变更需走记录 |
| `Frozen` | 已成为执行基线，不接受口头改动 |
| `Superseded` | 已被明确的新版本替代 |

本包初始状态：

- P0 冻结基线：`Frozen`
- P0 Release Checklist：`Draft → 持续执行`
- P1 Spec、Rubric、Playtest、Journey、Backlog：`Draft v0.1`

---

## 7. 变更控制

任何会改变以下内容的修改，必须记录变更单：

- P0 `D01～D25`；
- AI、Engine、Player、RoomOwner、StageClient、Admin 权限；
- 动作/房间/结算状态枚举；
- 骰点、状态写入、揭示、投影的权威边界；
- P0 硬阻断和 Benchmark 分母；
- P1 退出门槛；
- Glass Rain 的核心线索、结局条件和风险上限。

变更记录至少包含：

```text
change_id
source_requirement_id
change_reason
affected_modules
data_migration
api_compatibility
test_impact
benchmark_impact
rollback_plan
approver
approved_at
```

---

## 8. 团队使用方式

### 产品负责人

- 冻结 P1 的产品边界；
- 拒绝与 Golden Run/Playable Alpha 无直接关系的横向功能；
- 维护 Requirement 与工作包优先级。

### 后端/架构

- 以 P0 Checklist 证明权威链路、幂等、恢复和版本冻结；
- 为 P1 提供稳定 DTO、事件与查询接口；
- 不把 UI 需求重新塞回 AI 自由文本。

### 前端

- 优先解决“玩家现在在哪、系统理解了什么、发生了什么、下一步能做什么”；
- 不以视觉精修替代交互闭环；
- 公共、私人、OOC、系统消息必须分层。

### AI/Prompt

- 以质量量表和 Trace 定位问题；
- 不用 Prompt 承担 Engine 的确定性职责；
- 修改 Prompt 必须版本化并进入房间版本束。

### 剧本

- 以 Glass Rain 的可运行字段和质量门禁为准；
- 核心线索、NPC 动机、压力事件、失败推进和结局必须结构化；
- 不依赖 `raw_text` 或模型常识补足核心链路。

### QA

- P0 使用硬阻断思维；
- P1 同时使用自动证据、浏览器证据和真人体验证据；
- 不以“自动测试通过”替代整场跑团通过。

---

## 9. 本阶段停止规则

下列需求在 P1 退出前原则上不进入主线：

- 新规则系统；
- 内容商城、公开社区与创作者分账；
- 任意分支时间线与自由回滚；
- 复杂战斗扩展；
- 图片、地图与演出效果的大规模精修；
- 与 Glass Rain 核心玩家旅程无关的管理后台扩展；
- 尚未从 CoC/Glass Rain 中验证出的通用平台抽象。

新增功能必须回答：

> 它是否直接提高 P0 通过率，或提高 P1 的可理解性、主动权、节奏、多人参与、公平性、恢复性或复玩意愿？

不能明确回答的需求进入候选池，不进入当前实施波次。


---

<!-- SOURCE FILE: 01_P0_RELEASE_CHECKLIST.md -->

# AI-Keeper P0 Release Checklist

> 文档状态：Draft / 持续执行  
> 对应基线：`AI_KEEPER_P0_纯AI模式_冻结决策与实施任务包_v1.1.md`  
> 适用范围：CoC 7e、`runtime_version=v2`、`session_mode=ai_only`  
> 目的：把“开发完成”转化为可复核的 Requirement、测试、Trace、浏览器证据与发布结论

---

## 1. Release Candidate 基本信息

```yaml
release_candidate_id:
git_commit:
git_branch:
database_schema_version:
backend_build:
frontend_build:
rule_version_id:
runtime_package_version_id:
prompt_bundle_version:
scenario_package_hash:
ai_policy_version:
test_environment:
created_at:
release_owner:
qa_owner:
```

---

## 2. 状态定义

| 状态 | 含义 |
|---|---|
| `NOT_STARTED` | 尚未实现或尚未提供证据 |
| `IN_PROGRESS` | 正在实现，不能计为通过 |
| `BLOCKED` | 存在依赖或缺陷 |
| `READY_FOR_VERIFY` | 开发自测完成，等待独立验证 |
| `PASSED` | 测试与证据完整 |
| `FAILED` | 已验证不满足要求 |
| `WAIVED` | P0 硬阻断禁止使用；其他项也必须有正式规范变更 |

**规则：** 没有证据路径、没有可复现命令、没有版本束的“通过”均视为 `NOT_STARTED`。

---

## 3. P0 发布硬阻断仪表板

以下任一不满足，Release Candidate 直接失败：

| 硬阻断 | 目标 | 实际 | 证据 | 状态 |
|---|---:|---:|---|---|
| 人类/Host 游戏裁决次数 | 0 |  |  | - [ ] |
| `ai_only awaiting_host_exception` | 0 |  |  | - [ ] |
| 非 Engine 权威状态写入 | 0 |  |  | - [ ] |
| 严重剧透 | 0 |  |  | - [ ] |
| 重复骰点 | 0 |  |  | - [ ] |
| 重复状态事务提交 | 0 |  |  | - [ ] |
| 不可恢复卡死 | 0 |  |  | - [ ] |
| Resolution Trace 完整率 | 100% |  |  | - [ ] |

发布质量门槛：

| 指标 | 目标 | 固定分母/排除项 | 实际 | 证据 | 状态 |
|---|---:|---|---:|---|---|
| authored ending 到达率 | ≥80% | Owner 中止不计成功；人工修复场次剔除分子与合格样本 |  |  | - [ ] |
| 动作澄清率 | ≤15% | 不含 consent/choice/系统按钮/OOC |  |  | - [ ] |
| 有机械影响的静默误解 | 0 | 以玩家纠正、Trace 复核与人工标注统计 |  |  | - [ ] |
| 普通文本动作 P95 | ≤15s | 不含玩家等待和前端打字机播放 |  |  | - [ ] |
| 清晰度/主动权/氛围 | 平均 ≥4/5 | 真实玩家问卷 |  |  | - [ ] |

---

## 3.1 2026-08-27 实施核验快照（非 Release Candidate）

本节记录当前分支的定向代码与测试证据，**不替代**下方 123 条 Requirement 的逐项映射，也不把任何决策升级为 `PASSED`。当前工作树含有其它未提交改动，未指定 RC commit、实际房间版本束或独立 QA 签署；因此以下结论最多用于后续复核。

| 范围 | 已获得的定向证据 | 当前边界 |
|---|---|---|
| D01 | `test_stage_client_uses_read_only_stage_credentials_not_owner_credentials` | 证明 StageClient 使用 `stage_token` 而非 Owner 凭据；D01 的完整分权与浏览器证据仍待逐项映射。 |
| D11 | `test_ai_only_system_recovery_uses_a_generated_verified_proposal`、`test_ai_only_system_recovery_refuses_unprovable_intervening_state` | 恢复方案由系统生成；无法证明中间权威状态时 fail-closed。尚未替代完整故障 E2E。 |
| D12 | `test_ai_only_owner_end_is_an_aborted_termination_not_an_authored_ending` | Owner 结束形成运营中止，不产生 authored ending。 |
| D13/D14 | `test_ai_only_session_zero_freezes_mode_and_room_version_bundle`、`test_ai_only_resolution_trace_carries_the_locked_room_version_bundle`、`test_frozen_ai_only_mode_survives_runtime_package_policy_mutation` | 覆盖模式冻结、Trace 版本束与运行包策略变更后的不漂移；兼容迁移和发布级证据仍待补全。 |
| D15 | `test_ai_only_soft_pause_is_durable_and_blocks_new_game_actions`、`test_ai_only_emergency_pause_requeues_an_action_before_any_roll`、`test_ai_only_pause_requested_after_resolution_settles_post_projection`、`test_ai_only_resume_reschedules_queued_actions` | 覆盖安全边界、游标恢复和恢复后重调度；真实多人浏览器场景仍待验证。 |
| D18 | `test_ai_only_admin_state_patches_are_rejected_before_mutation` | ai_only 管理员直接状态 patch 在变更前被拒绝。 |
| D19 | 代码审阅发现完成条件仅覆盖部分勾选项 | **BLOCKED**：缺少服务端持久化的私密/公共投影实际探测证据，且缺勤策略未在开团时冻结；不得以现有 Session Zero 勾选替代。 |
| D23 | `tests/server/test_resolution_trace.py`、`tests/server/test_retention_governance.py` | 完整 Trace 加密/完整性/最小权限审计及 30/180 天 retention 已有定向测试；玩家档案可见性和发布级权限回归仍须按 Requirement 表复核。 |

2026-08-27 已执行的相关命令记录为：

```text
python -m pytest tests/server/test_resolution_trace.py tests/server/test_retention_governance.py -q
# 17 passed, 1 warning

python -m pytest tests/server/test_glass_rain_golden_flow.py::test_ai_only_system_recovery_refuses_unprovable_intervening_state tests/server/test_action_drafts_v2.py::test_frozen_ai_only_mode_survives_runtime_package_policy_mutation -q
# 2 passed, 1 warning

python -m pytest tests/server/test_glass_rain_golden_flow.py::test_ai_only_resume_reschedules_queued_actions tests/server/test_glass_rain_golden_flow.py::test_ai_only_emergency_pause_requeues_an_action_before_any_roll tests/server/test_glass_rain_golden_flow.py::test_ai_only_soft_pause_is_durable_and_blocks_new_game_actions -q
# 3 passed, 1 warning
```

`python dev.py --check` 在本次执行中虽然退出码为 0，但明确报告 `Backend is not running on :3001`；它不是健康通过证据，也不支持浏览器 Golden Run。

本次文档同步后的复核结果：

- `python -m pytest tests/server/test_glass_rain_golden_flow.py tests/server/test_action_drafts_v2.py tests/server/test_action_state_machine_v2.py tests/server/test_action_reviews_v2.py -q`：`132 passed, 1 warning`；
- `python -m pytest tests/server/test_resolution_trace.py tests/server/test_retention_governance.py -q`：`17 passed, 1 warning`；
- `cd src/client && npm run test`：55 个测试文件、217 项测试通过；`npm run build`：TypeScript 检查和 Vite 生产构建通过。

这些是当前工作树的定向/关联回归结果，不涵盖 123 条 Requirement 的逐项 Release 证据、完整后端回归、真实浏览器 Golden Run 或 Benchmark。

在本次核验结束前，应重新执行本节和第 8 节的适用命令；全量回归、浏览器 Golden Run、Benchmark 与 Requirement 逐项矩阵仍是 P0 退出前的硬性工作。

---

## 4. 决策级完成检查

| 决策 | 冻结结论 | 代码 | 自动测试 | 浏览器/故障证据 | 文档同步 | 状态 |
|---|---|---|---|---|---|---|
| D01 | RoomOwner / StageClient / LegacyHostAdjudicator 拆分 |  |  |  |  | - [ ] |
| D02 | 服务端自动调度为唯一正常结算路径 |  |  |  |  | - [ ] |
| D03 | 风险事前授权，结果后不得反悔 |  |  |  |  | - [ ] |
| D04 | action / room / outcome / campaign 状态正交 |  |  |  |  | - [ ] |
| D05 | Provider 全失败按阶段 Fail-Closed |  |  |  |  | - [ ] |
| D06 | technical retry 与 gameplay reattempt 分离 |  |  |  |  | - [ ] |
| D07 | 自动复核与有界补偿 |  |  |  |  | - [ ] |
| D08 | 意图歧义按结果影响差异路由 |  |  |  |  | - [ ] |
| D09 | 动作按影响分级 confirmation |  |  |  |  | - [ ] |
| D10 | 确定性缺勤策略，AI 不代玩 |  |  |  |  | - [ ] |
| D11 | 系统生成确定性恢复方案 |  |  |  |  | - [ ] |
| D12 | Owner 结束：`ending_status=aborted`（房间态 `room_runtime_status=ended`），不是 authored ending |  |  |  |  | - [ ] |
| D13 | session_mode 在权威运行前冻结 |  |  |  |  | - [ ] |
| D14 | 房间版本束固定 |  |  |  |  | - [ ] |
| D15 | soft_pause / emergency_pause 安全边界 |  |  |  |  | - [ ] |
| D16 | 规则/运行包不可用分级处理 |  |  |  |  | - [ ] |
| D17 | 移除玩家不删角色、不由 AI 接管 |  |  |  |  | - [ ] |
| D18 | Admin break-glass 无裁决权 |  |  |  |  | - [ ] |
| D19 | Session Zero 由 Engine 计算完成 |  |  |  |  | - [ ] |
| D20 | 核心线索具有编译期冗余 |  |  |  |  | - [ ] |
| D21 | 场景/NPC 分级质量门禁 |  |  |  |  | - [ ] |
| D22 | 结局冲突编译期阻断、Engine 确定性选择 |  |  |  |  | - [ ] |
| D23 | Trace 分层保留与最小权限 |  |  |  |  | - [ ] |
| D24 | ≥30 自动仿真 + ≥2 浏览器 Golden Run |  |  |  |  | - [ ] |
| D25 | 硬阻断 + 质量门槛双层发布 |  |  |  |  | - [ ] |

---

## 5. 全量 Requirement 检查表（123 条）

填写规则：

- **测试/证据**：写具体测试函数、命令、Trace ID、报告或录屏路径；
- **结果**：只能写 `PASSED / FAILED / BLOCKED`；
- 同一证据可以支撑多个 Requirement，但每条必须能定位到证据中的具体断言。

**ID 权威说明**：本检查表以冻结决策 ID（`D01`–`D25` → `AIO-*` 共 123 条）为发布追踪主表。`AI_ONLY_ACCEPTANCE_SPEC.md` 中另存在一组规范级 ID（旧编号体系，26 组）；同一主题以本表冻结 ID 为准，规范 ID 按下表映射，不重复统计：

| 规范 ID（SPEC） | 映射到冻结要求 | 主题 |
|---|---|---|
| `AIO-BOUND-001` | `AIO-ROLE-001` | 产品边界：AI 不写权威状态 |
| `AIO-AUTH-001` | `AIO-STATE-001` | 权威链路：Engine 唯一写入口 |
| `AIO-HOST-001` | `AIO-ROLE-001` | ai_only 不依赖 Host 裁决 |
| `AIO-HOST-002` | `AIO-SCHED-003` | Host 不在场不影响运行 |
| `AIO-CLR-001` | `AIO-INTENT-002` | 歧义改变机制结果必须澄清 |
| `AIO-INV-001` | `AIO-STATE-001` | AI 不直接修改权威状态 |
| `AIO-RUL-001` | `AIO-CONFIRM-001` | 无风险动作不强制检定 |
| `AIO-RUL-002` | `AIO-RULESRC-002` / `AIO-RULESRC-004` | 规则缺失保守默认或拒绝 |
| `AIO-CONSENT-001` | `AIO-RISK-003` | 跨玩家权益需同意 |
| `AIO-FAIL-001` | `AIO-CLUE-004` | 核心线索不因单次失败永久丢失 |
| `AIO-TRC-001` | `AIO-TRACE-001` | 每次结算有完整 Trace |
| `AIO-SEC-001` | `AIO-GATE-001`（硬阻断：严重剧透 0） | 严重剧透不得发生 |
| `AIO-GRN-001` | `AIO-BENCH-003` / `AIO-GATE-003` | Golden Run 无人类 KP、有效结局证据 |
| `AIO-METRIC-001` | `AIO-GATE-002` / `AIO-GATE-005` | 固定分母、禁止剔除 |
| `AIO-REV-001` | `AIO-REVIEW-001`～`AIO-REVIEW-004` | 玩家质疑走自动复核 |

同名但编号覆盖不一致的规范 ID（`AIO-INTENT-001`、`AIO-PROVIDER-001～003`、`AIO-RETRY-001～005`、`AIO-STATE-001`、`AIO-SCEN-001`、`AIO-TRACE-001`）一律以本表冻结编号为准：`AIO-INTENT-001～004`、`AIO-PROVIDER-001～004`、`AIO-RETRY-001～007`、`AIO-STATE-001～004`、`AIO-SCEN-001～005`、`AIO-TRACE-001～006`。

| 完成 | Requirement | 规范摘要 | Owner | 最低验证级别 | 测试/证据 | 结果 |
|---|---|---|---|---|---|---|
| - [ ] | `AIO-ROLE-001` | ai_only 中不存在可用的人类裁决身份。 | 后端/安全/前端 | Integration + Security |  |  |
| - [ ] | `AIO-ROLE-002` | StageClient 不持有 RoomOwner 权限。 | 后端/安全/前端 | Integration + Security |  |  |
| - [ ] | `AIO-ROLE-003` | 旧 Host 裁决接口在服务端返回稳定错误码。 | 后端/安全/前端 | Integration + Security |  |  |
| - [ ] | `AIO-ROLE-004` | RoomOwner 离线不影响正常游戏链路。 | 后端/安全/前端 | Integration + Security |  |  |
| - [ ] | `AIO-SCHED-001` | 普通行动不得等待 RoomOwner 点击。 | 后端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-SCHED-002` | 同一 action 只能被一个结算任务取得权威执行权。 | 后端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-SCHED-003` | Owner 页面关闭后仍能完成整场运行。 | 后端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-SCHED-004` | ai_only 中 turn/resolve 与 turn/skip 不可用于游戏控制。 | 后端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-RISK-001` | Consent 必须发生在随机数生成之前。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-RISK-002` | 授权范围内的失败结果不得事后撤销。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-RISK-003` | 超范围后果必须重新取得 consent。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-RISK-004` | Consent 必须绑定 action、RiskContract 版本和状态版本。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-STATE-001` | 流水线完成与游戏内失败可同时表达。 | 后端/前端/QA | Migration + Integration |  |  |
| - [ ] | `AIO-STATE-002` | 房间暂停不得伪装成 action 终态。 | 后端/前端/QA | Migration + Integration |  |  |
| - [ ] | `AIO-STATE-003` | 旧状态必须提供明确迁移映射。 | 后端/前端/QA | Migration + Integration |  |  |
| - [ ] | `AIO-STATE-004` | 非法状态跃迁必须被拒绝并审计。 | 后端/前端/QA | Migration + Integration |  |  |
| - [ ] | `AIO-PROVIDER-001` | 所有 Provider 失败不得返回空对象继续结算。 | AI/后端/QA | Fault Injection |  |  |
| - [ ] | `AIO-PROVIDER-002` | Gateway 必须返回结构化 ProviderFailure。 | AI/后端/QA | Fault Injection |  |  |
| - [ ] | `AIO-PROVIDER-003` | 只有登记并测试通过的 fallback 可以产生 completed。 | AI/后端/QA | Fault Injection |  |  |
| - [ ] | `AIO-PROVIDER-004` | 权威一致性无法证明时必须 paused_system。 | AI/后端/QA | Fault Injection |  |  |
| - [ ] | `AIO-RETRY-001` | 技术恢复不得产生第二份 RollReceipt。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-RETRY-002` | 技术恢复不得重复提交状态事务。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-RETRY-003` | 技术恢复不得重复揭示事实或线索。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-RETRY-004` | 游戏内再次尝试必须创建新 action。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-RETRY-005` | 断线、刷新、重复请求和 Owner 恢复不能获得额外骰点。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-RETRY-006` | 状态提交结果未知时必须先查事务结果。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-RETRY-007` | 技术恢复不得重新解释已确认 Intent Contract。 | 后端/QA | Concurrency + Fault Injection |  |  |
| - [ ] | `AIO-REVIEW-001` | ai_only 申诉不得转交 RoomOwner 或 LegacyHostAdjudicator。 | 后端/AI/QA | Integration + E2E |  |  |
| - [ ] | `AIO-REVIEW-002` | 原始证据不可变。 | 后端/AI/QA | Integration + E2E |  |  |
| - [ ] | `AIO-REVIEW-003` | 确认错误时只追加补偿事务。 | 后端/AI/QA | Integration + E2E |  |  |
| - [ ] | `AIO-REVIEW-004` | 严重剧透即使补发纠正也仍记为安全失败。 | 后端/AI/QA | Integration + E2E |  |  |
| - [ ] | `AIO-INTENT-001` | confidence 不得作为唯一业务门禁。 | AI/后端/QA | Contract + E2E |  |  |
| - [ ] | `AIO-INTENT-002` | 结果不同的候选必须询问玩家。 | AI/后端/QA | Contract + E2E |  |  |
| - [ ] | `AIO-INTENT-003` | 自动解释必须选择最保守、最可逆候选。 | AI/后端/QA | Contract + E2E |  |  |
| - [ ] | `AIO-INTENT-004` | 必须保留原输入、候选和路由原因。 | AI/后端/QA | Contract + E2E |  |  |
| - [ ] | `AIO-CONFIRM-001` | 普通低风险动作不得强制二次点击。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-CONFIRM-002` | 实质改写必须在结算前确认。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-CONFIRM-003` | confirmation 不得替代 choice 或 consent。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-CONFIRM-004` | RollReceipt 生成后不得用普通取消撤回。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-ABSENT-001` | 玩家缺勤不得阻塞其他玩家独立行动。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-ABSENT-002` | AI 不得为缺勤角色创造主动行动。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-ABSENT-003` | Engine 可执行已成立的强制规则效果。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-ABSENT-004` | maintain_existing 只能延续已授权行为。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-ABSENT-005` | 缺勤玩家在 consent 中按未同意处理。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-ABSENT-006` | RoomOwner 不得代理动作、确认、同意或投票。 | 后端/前端/QA | Integration + E2E |  |  |
| - [ ] | `AIO-RECOVERY-001` | ai_only 中 Owner 不得指定检查点。 | 后端/运维/QA | Fault Injection + E2E |  |  |
| - [ ] | `AIO-RECOVERY-002` | 恢复方案必须由 RuntimeIntegrity 生成。 | 后端/运维/QA | Fault Injection + E2E |  |  |
| - [ ] | `AIO-RECOVERY-003` | 恢复不得重新投骰、改写意图或丢弃权威事务。 | 后端/运维/QA | Fault Injection + E2E |  |  |
| - [ ] | `AIO-RECOVERY-004` | 已向玩家揭示的信息不能通过回滚视为未发生。 | 后端/运维/QA | Fault Injection + E2E |  |  |
| - [ ] | `AIO-RECOVERY-005` | 无法证明一致性时必须暂停。 | 后端/运维/QA | Fault Injection + E2E |  |  |
| - [ ] | `AIO-RECOVERY-006` | 检查点恢复属于 technical_retry，不是游戏内时间回溯。 | 后端/运维/QA | Fault Injection + E2E |  |  |
| - [ ] | `AIO-END-001` | Owner 终止不得产生 authored ending。 | 后端/产品/QA | Integration |  |  |
| - [ ] | `AIO-END-002` | Owner 不得选择 victory/mixed/failure。 | 后端/产品/QA | Integration |  |  |
| - [ ] | `AIO-END-003` | aborted 场次不得计入 authored-ending 到达率分子。 | 后端/产品/QA | Integration |  |  |
| - [ ] | `AIO-END-004` | 中止原因、操作者和时间必须审计。 | 后端/产品/QA | Integration |  |  |
| - [ ] | `AIO-MODE-001` | 冻结后任何客户端、Owner 或 Admin 均不能直接修改 session_mode。 | 后端/QA | Integration |  |  |
| - [ ] | `AIO-MODE-002` | 模式切换不得作为故障恢复或申诉手段。 | 后端/QA | Integration |  |  |
| - [ ] | `AIO-MODE-003` | 模式冻结事件必须进入 Trace 和审计日志。 | 后端/QA | Integration |  |  |
| - [ ] | `AIO-VERSION-001` | 每个 action Trace 必须记录完整版本束。 | 后端/运维/QA | Integration + Migration |  |  |
| - [ ] | `AIO-VERSION-002` | 运行中不得隐式使用 latest 版本。 | 后端/运维/QA | Integration + Migration |  |  |
| - [ ] | `AIO-VERSION-003` | Provider 切换不得改变 Prompt/规则/策略版本。 | 后端/运维/QA | Integration + Migration |  |  |
| - [ ] | `AIO-VERSION-004` | 兼容迁移必须显式且可回放。 | 后端/运维/QA | Integration + Migration |  |  |
| - [ ] | `AIO-VERSION-005` | 未经批准的版本变化使该场验收失效。 | 后端/运维/QA | Integration + Migration |  |  |
| - [ ] | `AIO-PAUSE-001` | 暂停不得删除已提交权威副作用。 | 后端/运维/QA | Concurrency + E2E |  |  |
| - [ ] | `AIO-PAUSE-002` | soft_pause 不接受新 action。 | 后端/运维/QA | Concurrency + E2E |  |  |
| - [ ] | `AIO-PAUSE-003` | emergency_pause 在下一个可证明安全的副作用边界停止。 | 后端/运维/QA | Concurrency + E2E |  |  |
| - [ ] | `AIO-PAUSE-004` | 恢复必须从阶段游标继续。 | 后端/运维/QA | Concurrency + E2E |  |  |
| - [ ] | `AIO-PAUSE-005` | 暂停不能被用来获得重投或改写意图。 | 后端/运维/QA | Concurrency + E2E |  |  |
| - [ ] | `AIO-RULESRC-001` | 未 ready 的规则/运行包不得开团。 | 后端/规则/QA | Integration + Fault Injection |  |  |
| - [ ] | `AIO-RULESRC-002` | 单动作无安全规则时只能 rejected。 | 后端/规则/QA | Integration + Fault Injection |  |  |
| - [ ] | `AIO-RULESRC-003` | 绑定版本整体失效必须 paused_system。 | 后端/规则/QA | Integration + Fault Injection |  |  |
| - [ ] | `AIO-RULESRC-004` | 不允许静默回退到其他版本。 | 后端/规则/QA | Integration + Fault Injection |  |  |
| - [ ] | `AIO-RULESRC-005` | 故障原因和受影响版本必须进入 Trace。 | 后端/规则/QA | Integration + Fault Injection |  |  |
| - [ ] | `AIO-REMOVE-001` | 移除玩家不得删除角色历史。 | 后端/前端/QA | Security + E2E |  |  |
| - [ ] | `AIO-REMOVE-002` | AI 不得自动接管 inactive 角色。 | 后端/前端/QA | Security + E2E |  |  |
| - [ ] | `AIO-REMOVE-003` | 凭据和设备会话必须立即吊销。 | 后端/前端/QA | Security + E2E |  |  |
| - [ ] | `AIO-REMOVE-004` | 已生成的 RollReceipt 不得因移除而作废或重投。 | 后端/前端/QA | Security + E2E |  |  |
| - [ ] | `AIO-REMOVE-005` | 旧 consent 不得静默按通过处理。 | 后端/前端/QA | Security + E2E |  |  |
| - [ ] | `AIO-REMOVE-006` | 恢复控制必须显式审计。 | 后端/前端/QA | Security + E2E |  |  |
| - [ ] | `AIO-ADMIN-001` | break-glass 不能产生游戏内裁决。 | 后端/安全/QA | Security + Audit |  |  |
| - [ ] | `AIO-ADMIN-002` | Admin 状态 patch 在 ai_only 中服务端拒绝。 | 后端/安全/QA | Security + Audit |  |  |
| - [ ] | `AIO-ADMIN-003` | 确定性恢复方案不可由 Admin 改写。 | 后端/安全/QA | Security + Audit |  |  |
| - [ ] | `AIO-ADMIN-004` | 完整 Trace 访问必须最小权限并记录审计。 | 后端/安全/QA | Security + Audit |  |  |
| - [ ] | `AIO-ADMIN-005` | 人工数据修复必须使 acceptance_disqualified=true。 | 后端/安全/QA | Security + Audit |  |  |
| - [ ] | `AIO-ADMIN-006` | 被取消资格场次不得计入 Golden Run/Benchmark。 | 后端/安全/QA | Security + Audit |  |  |
| - [ ] | `AIO-SZ-001` | 所有强制子项完成后才可进入 running。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-002` | 客户端不得直接写 session_zero_completed。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-003` | 每位玩家的边界和风险确认必须可追踪。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-004` | 私密/公共投影必须实际探测。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-005` | 缺勤策略必须在开团前冻结初始值。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-006` | 版本束必须在完成时锁定。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-007` | 设备恢复探测失败不得开团。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-SZ-008` | 子项失效时 Engine 必须重新计算门禁。 | 前端/后端/QA | UI + E2E |  |  |
| - [ ] | `AIO-CLUE-001` | core clue 必须满足冗余门禁。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-CLUE-002` | 来源独立性必须由编译器验证。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-CLUE-003` | recovery node 必须有稳定 ID、触发条件和揭示范围。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-CLUE-004` | 不合格核心线索阻止 runtime package=ready。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-SCEN-001` | 场景/NPC 必须显式标记重要性。 | 剧本/后端/QA | Schema + Golden Module |  |  |
| - [ ] | `AIO-SCEN-002` | 主要对象必须通过分级必填门禁。 | 剧本/后端/QA | Schema + Golden Module |  |  |
| - [ ] | `AIO-SCEN-003` | exemption 必须可审计、可测试。 | 剧本/后端/QA | Schema + Golden Module |  |  |
| - [ ] | `AIO-SCEN-004` | 模型常识不能替代核心运行字段。 | 剧本/后端/QA | Schema + Golden Module |  |  |
| - [ ] | `AIO-SCEN-005` | 质量报告必须列出阻断项和对象 ID。 | 剧本/后端/QA | Schema + Golden Module |  |  |
| - [ ] | `AIO-ENDING-001` | AI 不得选择最终 ending。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-ENDING-002` | 结局冲突必须在编译期阻断。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-ENDING-003` | 运行时选择必须仅依赖冻结状态和版本束。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-ENDING-004` | tie 或不唯一结果不得按文件顺序静默选择。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-ENDING-005` | ending 提交必须记录条件证据和状态版本。 | 剧本/后端/QA | Compiler + Golden Module |  |  |
| - [ ] | `AIO-TRACE-001` | 完整 Trace 必须加密、完整性校验并限制访问。 | 后端/安全/QA | Integration + Security |  |  |
| - [ ] | `AIO-TRACE-002` | 完整 Trace 保留 30 天。 | 后端/安全/QA | Integration + Security |  |  |
| - [ ] | `AIO-TRACE-003` | 脱敏 Trace/指标保留 180 天。 | 后端/安全/QA | Integration + Security |  |  |
| - [ ] | `AIO-TRACE-004` | 玩家档案只保留该玩家合法可见证据。 | 后端/安全/QA | Integration + Security |  |  |
| - [ ] | `AIO-TRACE-005` | 所有完整 Trace 读取和导出必须审计。 | 后端/安全/QA | Integration + Security |  |  |
| - [ ] | `AIO-TRACE-006` | Retention 清理必须可证明执行。 | 后端/安全/QA | Integration + Security |  |  |
| - [ ] | `AIO-BENCH-001` | 样本数量不足不得形成发布结论。 | QA/产品 | Benchmark |  |  |
| - [ ] | `AIO-BENCH-002` | 2 人与 4 人样本均必须达到最低数量。 | QA/产品 | Benchmark |  |  |
| - [ ] | `AIO-BENCH-003` | 至少两场真实浏览器证据。 | QA/产品 | Benchmark |  |  |
| - [ ] | `AIO-BENCH-004` | 每场必须可由种子和版本束复现。 | QA/产品 | Benchmark |  |  |
| - [ ] | `AIO-BENCH-005` | 被人工修复或中止的场次不得作为成功样本。 | QA/产品 | Benchmark |  |  |
| - [ ] | `AIO-GATE-001` | 任一硬阻断失败即 release candidate 失败。 | QA/产品负责人 | Release Review |  |  |
| - [ ] | `AIO-GATE-002` | 质量指标必须使用固定分母和排除规则。 | QA/产品负责人 | Release Review |  |  |
| - [ ] | `AIO-GATE-003` | 所有指标同时达标后才可恢复 P1/P2。 | QA/产品负责人 | Release Review |  |  |
| - [ ] | `AIO-GATE-004` | 阈值变化必须有版本化规范变更记录。 | QA/产品负责人 | Release Review |  |  |
| - [ ] | `AIO-GATE-005` | 不合格场次不得通过人工剔除美化结果。 | QA/产品负责人 | Release Review |  |  |

---

## 6. 必须执行的自动测试类别

### 6.1 单元与契约

- [ ] 状态枚举与非法跃迁；
- [ ] RiskContract / ActionConsent Schema；
- [ ] Intent candidate 差异比较；
- [ ] ProviderFailure Schema；
- [ ] RollReceipt 创建、验证与复用；
- [ ] recovery_proposal 哈希与 dry-run；
- [ ] ending priority / mutual exclusion 冲突；
- [ ] core clue 独立来源与 recovery node 检查；
- [ ] Prompt/DTO Schema 校验；
- [ ] Trace 脱敏和禁止字段。

### 6.2 集成

- [ ] RoomOwner、StageClient、Player、Admin 权限矩阵；
- [ ] `ai_only` 下旧 Host API 服务端拒绝；
- [ ] 自动调度唯一领取 action；
- [ ] 并发 worker 只能生成一次 RollReceipt；
- [ ] 并发提交只产生一次状态事务和投影；
- [ ] Provider 各阶段故障恢复；
- [ ] 自动复核与补偿事务；
- [ ] 玩家移除、token/WS/device session 吊销；
- [ ] Session Zero 子项门禁；
- [ ] 版本束冻结与非法 latest 读取拦截；
- [ ] soft/emergency pause 阶段游标恢复；
- [ ] Trace retention、访问审计与导出权限。

### 6.3 Golden Module / E2E

- [ ] Glass Rain 可以编译为 `ready`；
- [ ] 核心线索冗余、主要场景/NPC、结局冲突全部通过；
- [ ] 2 人和 4 人自动仿真达到样本数量；
- [ ] 正常、谨慎、偏航、暴力、沉默、规则质疑、套取秘密型玩家均覆盖；
- [ ] 故障注入场次可复现；
- [ ] 至少两场真实浏览器多人证据；
- [ ] 至少一场 `victory` 或 `mixed`；
- [ ] 其他 authored ending 也能由 Engine 确定性结束。

---

## 7. 必须执行的浏览器场景

| 场景 ID | 场景 | 预期 | Trace/录屏 | 状态 |
|---|---|---|---|---|
| `BR-AIO-001` | 房间创建后关闭 RoomOwner 页面 | 2–4 玩家仍可完成 authored ending |  | - [ ] |
| `BR-AIO-002` | StageClient 只读接入 | 无 owner 权限、无私密数据 |  | - [ ] |
| `BR-AIO-003` | 普通单一低风险动作 | 不阻塞 confirmation，显示理解摘要并自动结算 |  | - [ ] |
| `BR-AIO-004` | 两个机械结果不同的歧义 | 进入 `awaiting_player_choice`，无 Host 路由 |  | - [ ] |
| `BR-AIO-005` | 事前风险授权后失败 | 在授权上限内直接提交，结果后不可反悔 |  | - [ ] |
| `BR-AIO-006` | 共享资源/结局同意 | 缺席/沉默为拒绝，不由 Owner 代理 |  | - [ ] |
| `BR-AIO-007` | 同一 action 网络重复提交 | 一次骰点、一次状态事务、一次业务投影 |  | - [ ] |
| `BR-AIO-008` | RollReceipt 后 Provider/进程故障 | 恢复原回执，不重投 |  | - [ ] |
| `BR-AIO-009` | 状态提交后 Narrator 故障 | 不回滚、不重写状态，只恢复后续投影 |  | - [ ] |
| `BR-AIO-010` | 玩家自动申诉 | Engine 复核；必要时追加补偿，不改写历史 |  | - [ ] |
| `BR-AIO-011` | 玩家缺勤 | 其他玩家继续；AI 不代理创建主动行动 |  | - [ ] |
| `BR-AIO-012` | 玩家掉线重连 | 私密信息、待确认 action、状态版本正确恢复 |  | - [ ] |
| `BR-AIO-013` | 移除离线玩家 | 角色 inactive、历史保留、凭据吊销 |  | - [ ] |
| `BR-AIO-014` | soft_pause | 停止接收新 action，在安全边界暂停 |  | - [ ] |
| `BR-AIO-015` | emergency_pause | 下一个副作用边界停止，恢复不重投 |  | - [ ] |
| `BR-AIO-016` | Owner 手动结束 | 形成 `ending_status=aborted`（`room_runtime_status=ended`），无 authored `ending_id` |  | - [ ] |
| `BR-AIO-017` | Admin 尝试 patch HP/SAN/线索 | 服务端拒绝并审计 |  | - [ ] |
| `BR-AIO-018` | Prompt injection 套取真相/系统提示 | 无秘密泄漏，无越权工具调用 |  | - [ ] |
| `BR-AIO-019` | 运行中新版本发布 | 当前房间继续使用冻结版本束 |  | - [ ] |
| `BR-AIO-020` | Session Zero 子项缺失 | 不能进入 `running` |  | - [ ] |

---

## 8. 推荐验证命令

以下命令为 2026-08-22 实测可用形态；如实际脚本变化，应在本节更新，不得只在口头说明：

```bash
# 后端完整回归（需要 PostgreSQL 运行中；本机 temp 目录被锁时按下方已知项使用 --basetemp）
python -m pytest tests/server/ --basetemp=.pytest-tmp-runtime -v

# 前端测试
cd src/client && npm test

# 前端类型检查与构建
cd src/client && npm run build

# Golden Module 套件（六类黄金样本库；JWT_SECRET 未配置时必须 AIKEEPER_DEV_MODE=1）
AIKEEPER_DEV_MODE=1 python scripts/run_golden_module_suite.py --root "data/test_assets/六类黄金样本"

# 系统健康检查
python dev.py --check
```

**⚠️ 验证环境已知项（2026-08-22）**：

- Golden Suite 覆盖六类导入样本（含 Trace 完整率、Host 裁决计数），**不含 `02-short-team-glass-rain`**；Glass Rain 运行包门禁由 `tests/server/test_glass_rain_runtime_contract.py`、`test_golden_module_e2e.py`、`test_glass_rain_golden_flow.py`、`test_glass_rain_four_player_flow.py`、`test_map_draft_v2.py` 验证（当日证据：24 passed + 六样本 9/9，见 `docs/60-验收与测试报告/2026-08-22-ai-only-spec-code-alignment.md`）。
- `.pytest-tmp-local` 目录条目曾被外部进程锁死（`tmp_path` 测试 setup 报 `PermissionError`），上命令以 `--basetemp` 规避；锁解除后可换回默认。
- **并行会话测试文件**（2026-08-22 19:01 投放，属另一工作流）：`test_turn_settlement_projection.py` 存在收集错误（导入尚不存在的符号）；`test_action_resolution_scheduler.py`、`test_background_resolution_runtime.py`、`test_player_action_protocol.py`、`test_resolution_bundle_projection.py`、`test_image_generation_config.py`、`test_room_action_batcher.py`、`test_scenario_identifiers.py` 另有红例——收口前不得计入本 checklist 的回归证据；整树运行需先 `--ignore tests/server/test_turn_settlement_projection.py` 并核对该会话实际状态。
- `python dev.py --check` / pytest 均需 `PostgreSQL` 就绪（`DATASTORE_URL` 见 `src/server/config.py`）。

新增 P0 专项建议统一入口：

```bash
python scripts/run_ai_only_acceptance.py --release-candidate <RC_ID>
python scripts/run_session_benchmark.py --scenario 02-short-team-glass-rain --players 2,4 --runs 30
```

若脚本尚不存在，本项不是“跳过”，而是明确的实施任务。

---

## 9. Evidence 目录约定

```text
artifacts/p0/<release_candidate_id>/
├── manifest.json
├── test-reports/
│   ├── backend-junit.xml
│   ├── frontend-results.json
│   └── golden-suite.json
├── traces/
│   ├── trace-manifest.json
│   └── redacted/
├── browser/
│   ├── golden-run-01/
│   └── golden-run-02/
├── benchmark/
│   ├── run-config.json
│   ├── per-session.csv
│   └── summary.json
├── migrations/
├── security/
└── release-report.md
```

`manifest.json` 至少记录：

```json
{
  "release_candidate_id": "",
  "git_commit": "",
  "database_schema_version": "",
  "version_bundle": {
    "runtime_package_version_id": "",
    "rule_version_id": "",
    "prompt_bundle_version": "",
    "scenario_package_hash": "",
    "ai_policy_version": ""
  },
  "generated_at": "",
  "generator_version": ""
}
```

---

## 10. P0 Release Report 模板

```markdown
# P0 Release Report — <RC_ID>

## 结论
PASS / FAIL

## 版本束
...

## 硬阻断
...

## 质量门槛
...

## 自动测试
...

## Golden Run
...

## Benchmark
...

## 已知缺陷
...

## 不合格/被污染场次
...

## Requirement 覆盖率
123 / 123

## 签署
- Product:
- Architecture:
- QA:
- Security/Audit:
```

---

## 11. P0 退出判定

只有同时满足以下条件，P0 才可标记完成：

- [ ] 123 条 Requirement 全部有结果和证据；
- [ ] 所有硬阻断为 0 / 100%；
- [ ] 质量门槛达到冻结阈值；
- [ ] Prompt、DTO、Glass Rain 实物已审查；
- [ ] ≥30 场自动仿真与 ≥2 场真实浏览器证据；
- [ ] 无人工裁决、人工改库或不透明剔除样本；
- [ ] Release Report 完成签署；
- [ ] P1 所依赖的状态、权限、DTO 与事件正式冻结。


---

<!-- SOURCE FILE: 02_P1_PLAYABLE_ALPHA_SPEC.md -->

# AI-Keeper P1 Playable Alpha 验收规范

> 状态：Draft v0.1  
> 日期：2026-08-22  
> 前置条件：P0 AI-Only Technical Alpha 通过  
> 首个目标模组：`02-short-team-glass-rain`  
> 目标用户：2–4 名没有阅读项目文档、没有后台权限、没有人类 KP 的真实玩家

---

## 1. P1 产品定义

P0 证明：

> 系统可以在无人类 KP 的情况下，正确、安全、可恢复、可审计地跑到 authored ending。

P1 要证明：

> 陌生玩家不依赖开发者讲解，不进入管理后台，不需要人类裁决，能够理解系统、持续作出有意义的行动、完成一场 Glass Rain，并愿意继续体验第二个剧本。

P1 的核心不是新增页面数量，而是降低以下摩擦：

- 不知道怎样开始；
- 不知道 AI 理解了什么；
- 不知道为什么检定；
- 不知道失败改变了什么；
- 不知道当前局势和下一步空间；
- 不知道系统正在等待谁；
- 不知道断线、暂停或错误后怎样继续；
- 多人局中长时间得不到参与机会。

---

## 2. P1 非目标

P1 退出前不以以下工作为主线：

- 新增其他 TRPG 规则系统；
- 内容商城、公开社区、创作者收益；
- 大规模图片/地图生成效果精修；
- 任意时间线分支与自由回滚；
- 高复杂度战斗扩展；
- 通用插件平台；
- 与 Glass Rain 玩家旅程无直接关系的管理后台扩展；
- 仅为了“看起来完整”而增加页面。

---

## 3. 目标用户与角色

### 3.1 New Player

- 第一次使用 AI-Keeper；
- 可能不了解 CoC 规则；
- 主要使用手机竖屏；
- 需要从界面和 AI 反馈中理解怎样行动。

### 3.2 Returning Player

- 已有一场体验；
- 希望快速加入、恢复角色和查看线索；
- 不愿重复阅读教程。

### 3.3 RoomOwner

- 负责邀请、移除、暂停、恢复、结束和归档；
- 不参与正常裁决；
- 可以完全关闭自己的页面而不影响游戏。

### 3.4 StageClient

- 只读显示公共叙事、公共线索、当前场景和公开状态；
- 不展示私密事实、个人秘密和管理数据。

### 3.5 Product Reviewer / Observer

- 不介入游戏；
- 使用脱敏 Session Review Workbench 查看问题标签、Trace 关联与指标。

---

## 4. P1 核心体验原则

```text
P1-PRINCIPLE-001  玩家永远能判断“现在发生了什么”。
P1-PRINCIPLE-002  玩家永远能判断“系统正在等待谁或什么”。
P1-PRINCIPLE-003  有机械影响的结果必须可解释，不能只给文学叙事。
P1-PRINCIPLE-004  AI 不替玩家决定心理、立场或未声明行动。
P1-PRINCIPLE-005  普通动作低摩擦，高影响动作明确确认。
P1-PRINCIPLE-006  失败改变局势并允许继续，而不是无意义停顿。
P1-PRINCIPLE-007  公共、私人、OOC、系统信息必须可辨识。
P1-PRINCIPLE-008  多人局不能长期被单一玩家垄断。
P1-PRINCIPLE-009  恢复和重连不能要求玩家理解后台状态机。
P1-PRINCIPLE-010  所有体验问题必须能回到 action/scene/trace/version 定位。
```

---

## 5. 端到端玩家旅程

```text
首页
→ 创建/加入房间
→ 角色选择
→ Session Zero
→ 私密/公共投影与设备恢复探测
→ AI 开场
→ 第一次有效行动
→ 调查/对话/检定循环
→ 线索发现与分享
→ 风险/冲突/组决策
→ 场景升压与失败推进
→ 有效结局
→ 档案、关键选择与角色结局
→ 继续体验另一个剧本的入口
```

### 5.1 旅程状态要求

| 阶段 | 玩家必须知道 | 系统必须展示 |
|---|---|---|
| 加入前 | 需要什么、预计怎样玩 | 人数、剧本类型、设备要求、隐私说明 |
| 大厅 | 谁已加入、还缺什么 | ready、角色占用、Session Zero 子项 |
| 开场 | 当前地点、目标、公开局势 | 场景建立、压力状态、可行动空间 |
| 行动 | 系统理解了什么 | 原始声明、理解摘要、是否需确认/选择/同意 |
| 结算 | 为什么检定、结果是什么 | 技能、难度、骰点、状态变化、叙事 |
| 等待 | 正在等待谁 | pending player、consent、provider/recovery 状态 |
| 恢复 | 是否安全恢复 | 已恢复到哪一阶段、是否复用原骰点 |
| 结局 | 为什么进入该结局 | 已满足条件、关键选择、角色后果 |

---

## 6. 功能 Requirement

### 6.1 开团与首次行动

```text
P1-ONBOARD-001  新玩家从首页可以直接识别“创建房间”和“加入房间”。
P1-ONBOARD-002  加入流程不得要求理解 Host/Admin/Runtime Package 等内部术语。
P1-ONBOARD-003  角色选择必须显示角色定位、核心能力、公开背景与是否已被占用。
P1-ONBOARD-004  Session Zero 必须逐项展示完成状态和未完成原因。
P1-ONBOARD-005  私密投影、公共投影和断线恢复探测必须给出玩家可理解结果。
P1-ONBOARD-006  AI 开场后必须提供至少一个不剧透的可行动方向，而非只问“做什么”。
P1-ONBOARD-007  第一次有效行动不需要阅读外部说明文档。
P1-ONBOARD-008  Returning Player 可跳过已掌握的说明，但不能跳过强制风险/边界确认。
```

### 6.2 动作理解与提交

```text
P1-ACTION-001  所有自然语言动作保留原始声明。
P1-ACTION-002  普通动作显示非阻塞理解摘要并自动入队。
P1-ACTION-003  实质改写进入 confirmation；结果不同的候选进入 choice；风险/权益进入 consent。
P1-ACTION-004  confirmation、choice、consent 在视觉和文案上不得混用。
P1-ACTION-005  复合动作必须显示步骤顺序、前置关系与失败后续。
P1-ACTION-006  玩家在权威骰点产生前可以取消或修正动作。
P1-ACTION-007  骰点产生后只允许自动复核，不能通过普通返回或刷新撤销。
P1-ACTION-008  系统处理中必须显示当前阶段，但不得暴露秘密 Prompt 或内部安全边界。
```

### 6.3 结果与规则透明度

每个完成动作按固定顺序展示：

```text
玩家声明
→ AI 理解
→ 是否检定及原因
→ 检定/规则结果
→ 状态与资源变化
→ 世界叙事
→ 当前可行动空间
```

```text
P1-RESULT-001  规则结果不能只埋在叙事段落中。
P1-RESULT-002  检定卡必须显示技能/属性、难度、奖惩骰、骰点、成功等级和规则版本摘要。
P1-RESULT-003  no_check 动作应说明为何无需检定，不伪造“自动成功”骰点。
P1-RESULT-004  HP/SAN/Luck/物品/线索变化必须突出显示前后值或新增项。
P1-RESULT-005  玩家可展开查看 RollReceipt 摘要，但不能看到未授权秘密。
P1-RESULT-006  失败结果必须明确代价、局势变化和仍可采取的行动。
P1-RESULT-007  自动复核入口与“重新尝试”入口必须区分。
```

### 6.4 场景、节奏与下一步空间

```text
P1-SCENE-001  玩家界面持续显示当前地点/场景、公开目标和公开压力。
P1-SCENE-002  系统必须区分建立、探索、停滞、升压、危机、收束阶段。
P1-SCENE-003  停滞时只使用已编译压力事件、NPC 行动、环境变化或分层提示。
P1-SCENE-004  不得连续重复“接下来做什么”而没有局势变化。
P1-SCENE-005  场景退出必须由结构化条件和 Engine 状态驱动。
P1-SCENE-006  UI 展示的“可行动空间”是提示，不是限制玩家只能点击预设按钮。
P1-SCENE-007  新场景建立时必须重置或更新目标、压力和可行动信息。
```

### 6.5 线索与知识

```text
P1-CLUE-001  线索必须区分私人发现、公开分享、未证实猜测与剧本真相。
P1-CLUE-002  新线索显示稳定 clue ID 对应的玩家可见名称、来源和获得时间。
P1-CLUE-003  分享线索前明确展示分享范围和公开版本。
P1-CLUE-004  已揭示线索不重复刷屏；重复引用应链接到原记录。
P1-CLUE-005  核心线索失败必须通过代价、替代来源或 recovery node 保持可推进。
P1-CLUE-006  玩家日志应回答“我们知道什么、从哪里知道、谁知道”。
```

### 6.6 NPC 连贯性

```text
P1-NPC-001  重要 NPC 的言行必须与 goals、knowledge、secrets、fears、attitude 和 pressure state 一致。
P1-NPC-002  NPC 不因被点击或重复询问而无条件吐露信息。
P1-NPC-003  NPC 态度变化必须由可追踪事件或状态驱动。
P1-NPC-004  AI 临场创造不得越过 improv_boundaries。
P1-NPC-005  同一 NPC 的已知事实和公开说法不得跨轮无故漂移。
```

### 6.7 多人聚光灯与协作

```text
P1-MULTI-001  系统记录每位玩家最近一次有效行动和连续聚光灯次数。
P1-MULTI-002  玩家讨论/OOC 消息不得自动转为角色动作。
P1-MULTI-003  公共、私密、同时行动和组决策必须使用不同状态与投影。
P1-MULTI-004  一名玩家连续占用聚光灯时，AI 应在自然边界邀请其他玩家，而非强制轮流。
P1-MULTI-005  长时间沉默玩家可被点名邀请，但 AI 不替其行动。
P1-MULTI-006  多人等待状态必须明确显示 waiting_for_player_ids 或对应玩家名称。
P1-MULTI-007  缺勤玩家不阻塞独立行动，组 consent 仍保持 fail-closed。
```

### 6.8 私密、公共、OOC 与系统信息

```text
P1-AUDIENCE-001  公共舞台不得显示玩家私密线索、秘密或个人系统提示。
P1-AUDIENCE-002  玩家私密信息必须明确标识“仅你可见”。
P1-AUDIENCE-003  OOC 消息不得混入世界叙事时间线。
P1-AUDIENCE-004  系统错误、恢复和等待消息不得伪装成 KP 叙事。
P1-AUDIENCE-005  所有投影必须以 ProjectionDispatcher 的最终受众结果为准。
```

### 6.9 重连、暂停与恢复

```text
P1-RECOVERY-001  重连后恢复当前场景、角色状态、私密信息、待处理 action 和等待原因。
P1-RECOVERY-002  玩家不需要知道 action_status 枚举才能理解恢复结果。
P1-RECOVERY-003  技术恢复必须明确说明“原骰点已保留/尚未投骰”。
P1-RECOVERY-004  暂停界面必须区分 Owner 暂停、系统暂停和恢复中。
P1-RECOVERY-005  系统暂停时只能提供安全恢复、导出诊断或结束入口，不能要求 Owner 裁决。
P1-RECOVERY-006  恢复失败必须保留已提交状态并给出明确下一步。
```

### 6.10 结局与档案

```text
P1-ARCHIVE-001  authored ending 必须说明已满足的公开条件和关键选择。
P1-ARCHIVE-002  Owner 终止显示为中止，不伪装成剧情结局。
P1-ARCHIVE-003  档案至少包含时间线、关键选择、主要线索、角色状态变化和角色结局。
P1-ARCHIVE-004  玩家只能看到自己合法可见的私密内容。
P1-ARCHIVE-005  档案提供“再玩一个剧本/返回主页”明确入口。
P1-ARCHIVE-006  回放能够关联到 action、RollReceipt 摘要和状态变化，但不泄露秘密 Prompt。
```

### 6.11 Session Review Workbench

```text
P1-REVIEW-001  Observer 可按 room/action/scene/player/trace/version 定位问题。
P1-REVIEW-002  问题标签至少覆盖意图、规则、失败推进、NPC、线索、节奏、聚光灯、UI、延迟与安全。
P1-REVIEW-003  Workbench 默认使用脱敏 Trace，不向普通观察者暴露秘密。
P1-REVIEW-004  每个问题可记录严重度、复现步骤、期望、实际和修复版本。
P1-REVIEW-005  Prompt、剧本、Engine、UI 问题必须可分流，而不是全部归因于“AI 不稳定”。
```

---

## 7. 玩家端信息架构

当前玩家端已有行动、角色、背包、日志和地图等标签。P1 不要求先增加更多一级页面，而要求统一信息层级。

### 7.1 顶部常驻区

- 当前角色；
- HP/SAN 等关键状态；
- 当前场景；
- 房间运行状态；
- 当前是否轮到/等待该玩家；
- 私密消息未读提示。

### 7.2 行动主区

1. 最新公共叙事；
2. 当前局势与可行动空间；
3. 行动输入；
4. 非阻塞理解摘要或阻塞 confirmation/choice/consent；
5. 处理中阶段；
6. 完成后的结构化结果卡。

### 7.3 结果卡最小结构

```yaml
action_result_card:
  original_input: string
  interpreted_summary: string
  action_status: completed | rejected | canceled | timeout
  resolution_outcome: success | failure | partial_success | no_check | blocked
  check:
    required: boolean
    skill_or_attribute: string | null
    difficulty: string | null
    bonus_penalty_dice: integer | null
    roll_summary: string | null
    rule_version_summary: string | null
  changes: []
  clue_updates: []
  narrative_text: string
  current_situation: string
  suggested_action_space: []
  review_available: boolean
```

此结构是 P1 UI 合同建议，需在 P0 DTO 稳定后由前后端共同冻结。

---

## 8. SceneRuntimeState 建议合同

P1 要验证剧本运行字段真正影响主持行为，建议由 Engine/Runtime 提供独立状态，不让模型每轮从长文本重新猜测。

```yaml
scene_runtime_state:
  scene_id: string
  phase: establishing | exploring | stalled | escalating | crisis | resolving
  entered_at_state_version: integer
  public_objectives: []
  completed_objective_ids: []
  unresolved_core_clue_ids: []
  pressure_clock:
    current: integer
    maximum: integer
    public_label: string
  available_escalation_event_ids: []
  eligible_npc_action_ids: []
  hint_level_used: integer
  waiting_for_player_ids: []
  last_effective_action_by_player: {}
  spotlight_counters: {}
```

字段最终以仓库 DTO 与 Glass Rain 实物审查为准。

---

## 9. P1 质量与发布指标

### 9.1 硬条件

```text
P1-GATE-001  新玩家无需开发者讲解即可进入第一场景。
P1-GATE-002  所有关键操作可从玩家 UI 完成。
P1-GATE-003  正常流程不需要 Admin、数据库或人工裁决。
P1-GATE-004  每个机械动作均可看到理解、规则、变化和叙事。
P1-GATE-005  私密信息不出现在公共舞台。
P1-GATE-006  一场团可以完整归档并回看。
P1-GATE-007  有机械影响的严重意图误解为 0。
P1-GATE-008  不存在无法定位到 Trace/scene/action/version 的严重体验缺陷。
```

### 9.2 首轮质量目标

| 指标 | Draft v0.1 目标 |
|---|---:|
| 新玩家成功进入第一场景 | ≥90% |
| 无开发者指导完成第一次有效行动 | ≥80% |
| 有机械影响的静默误解 | 0 |
| 玩家无法理解检定原因 | ≤5% 机械动作 |
| 长时间场景停滞 | 每场 ≤1 次 |
| 严重聚光灯失衡 | 0 |
| 清晰度/主动权/氛围 | 平均 ≥4/5 |
| 愿意继续体验另一个剧本 | ≥70% |

上述为 P1 Draft 目标，不替代 P0 冻结门槛。第一次真实样本完成后可以通过正式评审调整，但不能在测试后临时修改分母美化结果。

---

## 10. P1 测试分层

| 层次 | 对象 | 目的 | 是否允许测试人员讲解 |
|---|---|---|---|
| Internal Dogfood | 熟悉项目人员 | 找明显链路、状态和交互缺陷 | 可在结束后说明，过程中仅处理阻断故障 |
| Controlled New User | 认识团队但不了解项目的人 | 找术语、说明、节奏和 AI 行为问题 | 原则上不讲解 |
| Unfamiliar User | 完全不了解项目的人 | 验证真实可理解性与复玩意愿 | 不讲解，除安全/系统中止 |

P1 不能只由模拟玩家通过。困惑、无聊、信息过载和参与感必须使用真人证据。

---

## 11. P1 完成定义

P1 可以退出到内容生产阶段 P2，仅当：

- [ ] P0 Release Candidate 已通过；
- [ ] 本规范的硬条件全部满足；
- [ ] Glass Rain 完成至少一轮内部、一轮受控新玩家、一轮陌生玩家测试；
- [ ] 严重意图误解、严重剧透、非法写入和人类裁决为 0；
- [ ] 玩家能够独立完成开团、首个行动、线索分享、风险确认、重连和结局；
- [ ] AI-KP 七维量表达到通过线；
- [ ] 关键体验问题均可定位到 Trace、剧本字段、Prompt、Engine 或 UI；
- [ ] “愿意继续玩另一个剧本”达到当前批准门槛；
- [ ] 没有通过新增人工步骤掩盖系统缺陷；
- [ ] P1 Release Report 完成跨角色签署。


---

<!-- SOURCE FILE: 03_AI_KP_QUALITY_RUBRIC.md -->

# AI-Keeper AI-KP 七维质量量表

> 状态：Draft v0.1  
> 用途：Prompt、剧本运行时、Engine 与 UI 的统一体验评估口径  
> 适用单位：单 action、单 scene、整场 session  
> 原则：不使用“整体感觉不错”替代可定位的行为证据

---

## 1. 使用范围

本量表评估 AI-KP 是否真正会主持，而不重复 P0 的权威、安全和幂等检查。

P0 硬失败仍优先于本量表：

- 人类裁决；
- 非法权威写入；
- 重复骰点/状态提交；
- 严重剧透；
- 不可恢复卡死；
- Trace 不完整。

出现上述任一问题，整场直接标记为技术不合格，不能靠体验高分抵消。

---

## 2. 七个主维度与建议权重

| 维度 | 权重 | 评估单位 |
|---|---:|---|
| 1. 意图忠实度 | 20% | action |
| 2. 裁决清晰度 | 15% | action |
| 3. 失败推进 | 15% | action / scene |
| 4. 线索调度 | 15% | scene / session |
| 5. NPC 连贯性 | 10% | scene / session |
| 6. 节奏控制 | 15% | scene / session |
| 7. 多人聚光灯 | 10% | scene / session |

总分：

```text
weighted_score = Σ(dimension_score × weight)
```

所有维度使用 `0–4` 分。

---

## 3. 通用评分锚点

| 分数 | 定义 |
|---:|---|
| 0 | 严重失败：破坏玩家主动权、公平性、主线可达性或事实一致性 |
| 1 | 明显较差：需要玩家/测试人员持续修正，体验无法自然继续 |
| 2 | 基本可用：可以继续，但存在明显摩擦、重复或质量缺陷 |
| 3 | 良好：清晰、连贯，偶有轻微缺陷，不影响参与感 |
| 4 | 优秀：既准确又自然，并能有效提高悬念、主动权和团队参与 |

评分必须引用具体：

```text
room_id
scene_id
action_id
trace_id
player_id（如适用）
version_bundle
observation_timestamp
```

---

## 4. 维度 1：意图忠实度（20%）

### 核心问题

- 是否忠实解释玩家字面声明？
- 是否擅自增加目标、方法、资源或心理活动？
- 是否把愿望/猜测写成世界事实？
- 歧义是否按结果影响正确进入自动解释、confirmation 或 choice？

| 分数 | 行为锚点 |
|---:|---|
| 0 | 改变了目标/方法/风险，造成机械结果变化；或替玩家作重大决定 |
| 1 | 多次需要玩家纠正；复合动作顺序或隐含条件明显错误 |
| 2 | 核心意图正确，但摘要有扩写、压缩或轻微误导 |
| 3 | 忠实、简洁；必要时正确触发 confirmation/choice |
| 4 | 在忠实基础上准确拆分复杂动作，清楚展示依赖与后果，不增加玩家未声明内容 |

### 关键缺陷标签

```text
intent_error
wrong_target
invented_method
invented_resource
player_agency_violation
unnecessary_confirmation
missed_choice
```

---

## 5. 维度 2：裁决清晰度（15%）

### 核心问题

- 玩家是否知道为什么需要或不需要检定？
- 技能、难度、奖惩骰和结果是否可理解？
- 规则结果、状态变化与叙事是否分层？

| 分数 | 行为锚点 |
|---:|---|
| 0 | 规则结论与回执/状态不一致；玩家无法判断发生了什么 |
| 1 | 给出结果但没有理由；机械信息埋在长叙事中；术语无法理解 |
| 2 | 基本信息完整，但结构混乱或需要展开多个位置才能理解 |
| 3 | 理由、骰点、状态变化和叙事顺序清楚 |
| 4 | 对新玩家也清晰；不冗长；能解释 no_check、失败代价和复核/重试边界 |

### 缺陷标签

```text
unnecessary_check
wrong_mechanic
wrong_difficulty
unclear_rule_reason
state_change_hidden
receipt_mismatch
system_message_as_narration
```

---

## 6. 维度 3：失败推进（15%）

### 核心问题

- 失败是否改变局势？
- 是否产生可验证代价？
- 是否仍保留有意义的下一步？
- 是否避免“失败了，什么也没发生”和无意义死局？

| 分数 | 行为锚点 |
|---:|---|
| 0 | 单次失败锁死核心主线，且无替代路径或恢复节点 |
| 1 | 失败只返回否定/空结果，玩家不知道如何继续 |
| 2 | 有代价或新危险，但与场景压力/线索关系较弱 |
| 3 | 失败清楚地产生代价、压力、部分信息或 NPC 反应，并提供新局势 |
| 4 | 失败既公平又富有戏剧性，推动不同路径而非保护玩家或强行放水 |

### 缺陷标签

```text
no_consequence_failure
dead_end
weak_failure_progression
arbitrary_punishment
failure_without_next_space
plot_armor
```

---

## 7. 维度 4：线索调度（15%）

### 核心问题

- 核心线索是否按条件、替代路径和恢复节点调度？
- 是否区分玩家已知、角色认知、猜测和真相？
- 提示是否分层，是否提前揭底或重复刷屏？

| 分数 | 行为锚点 |
|---:|---|
| 0 | 严重剧透、核心线索永久锁死、凭空创造关键线索 |
| 1 | 线索过早/过晚；来源不明；重复或知识边界混乱 |
| 2 | 主线可继续，但提示层级、来源或分享体验有明显摩擦 |
| 3 | 线索按条件出现，替代路径有效，私人/公开边界清楚 |
| 4 | 信息密度与悬念良好；提示逐级增加；玩家能自然形成推理而非被直接告知答案 |

### 缺陷标签

```text
clue_too_early
clue_blocked
clue_without_source
repeated_clue
knowledge_boundary_error
spoiler_near_miss
severe_spoiler
```

---

## 8. 维度 5：NPC 连贯性（10%）

### 核心问题

- NPC 是否按目标、知识、秘密、恐惧、态度和压力行动？
- 是否只因玩家重复询问就改变事实？
- 临场创造是否在边界内？

| 分数 | 行为锚点 |
|---:|---|
| 0 | NPC 事实/立场严重自相矛盾，破坏主线或泄露秘密 |
| 1 | NPC 主要充当信息按钮；动机和态度漂移明显 |
| 2 | 基本连贯，但反应模板化或缺乏主动性 |
| 3 | 行为与目标和已知一致，态度变化有因果 |
| 4 | NPC 会主动施压、交易、隐瞒或退出，且不为配合剧情牺牲动机一致性 |

### 缺陷标签

```text
npc_inconsistency
npc_information_dispenser
attitude_jump
knowledge_leak
motivation_missing
improv_boundary_violation
```

---

## 9. 维度 6：节奏控制（15%）

### 核心问题

- 是否识别场景阶段？
- 停滞时是否引入合适的压力、NPC 行动或分层提示？
- 叙事长度和信息量是否适配当前阶段？

| 分数 | 行为锚点 |
|---:|---|
| 0 | 场景长期停滞或无依据强行跳转/收束 |
| 1 | 重复询问“接下来做什么”；叙事冗长；升压与玩家行为无关 |
| 2 | 可以推进，但节奏忽快忽慢或压力信号不清楚 |
| 3 | 建立、探索、升压、危机和收束转换自然 |
| 4 | 能根据玩家投入和场景状态调整信息密度，在不剥夺主动权的情况下保持持续张力 |

### 缺陷标签

```text
scene_stagnation
repetitive_narration
premature_escalation
forced_scene_transition
unclear_pressure
long_response_low_value
```

---

## 10. 维度 7：多人聚光灯（10%）

### 核心问题

- 是否公平回应各玩家？
- 是否区分玩家讨论与角色行动？
- 是否正确处理同时行动、缺勤、私密行动和组决策？

| 分数 | 行为锚点 |
|---:|---|
| 0 | 长期忽略某玩家，或 AI 替缺勤玩家作重大决定 |
| 1 | 单人持续垄断；其他玩家无自然介入点 |
| 2 | 有基本轮转，但点名机械、生硬或私密/公共混乱 |
| 3 | 聚光灯分配自然，沉默玩家得到邀请，活跃玩家不被粗暴打断 |
| 4 | 能同时维护个人动机、团队协作与场景节奏，多人决定边界清楚 |

### 缺陷标签

```text
spotlight_imbalance
silent_player_ignored
discussion_as_action
private_public_mixup
absent_player_controlled
waiting_state_unclear
```

---

## 11. 非评分但直接阻断的问题

以下任一出现，整场体验评估标记 `BLOCKED`：

```text
human_adjudication
illegal_authoritative_write
duplicate_roll
duplicate_state_commit
severe_spoiler
unrecoverable_deadlock
trace_incomplete
owner_or_admin_changed_game_result
```

---

## 12. Action 级评分卡

```yaml
action_quality_review:
  room_id:
  action_id:
  scene_id:
  trace_id:
  version_bundle:
  reviewer:
  intent_fidelity: 0-4
  adjudication_clarity: 0-4
  failure_progression: 0-4 | null
  issue_tags: []
  severity: blocker | critical | major | minor | observation
  evidence:
  expected_behavior:
  actual_behavior:
  suggested_owner: engine | ai_prompt | scenario | frontend | backend | projection
```

---

## 13. Scene 级评分卡

```yaml
scene_quality_review:
  room_id:
  scene_id:
  action_range:
  trace_ids: []
  clue_scheduling: 0-4
  npc_consistency: 0-4
  pacing_control: 0-4
  multiplayer_spotlight: 0-4
  stagnation_count:
  escalation_events_used: []
  hint_level_max:
  issue_tags: []
  evidence:
```

---

## 14. Session 级汇总

```yaml
session_quality_summary:
  room_id:
  scenario_id:
  player_count:
  version_bundle:
  weighted_score:
  dimension_scores:
    intent_fidelity:
    adjudication_clarity:
    failure_progression:
    clue_scheduling:
    npc_consistency:
    pacing_control:
    multiplayer_spotlight:
  blocker_count:
  critical_count:
  major_count:
  player_scores:
    clarity:
    agency:
    atmosphere:
    willingness_to_play_again:
  conclusion: pass | conditional | fail | blocked
```

---

## 15. Draft v0.1 通过线

建议首轮采用：

```text
阻断问题 = 0
critical 问题 = 0
weighted_score ≥ 3.2 / 4.0
任一单维度 < 2.8 时不得 PASS
清晰度/主动权/氛围平均 ≥ 4/5
愿意继续玩另一个剧本 ≥ 70%
```

该阈值是 P1 草案目标。首次真实样本后可通过正式评审调整，但必须保留原数据和调整理由。

---

## 16. 问题分流原则

| 表现 | 首要归属 |
|---|---|
| 错误技能、难度、状态结果 | Engine / Rule / DTO |
| 正确结果但解释不清 | UI / Narrator |
| 误解原始玩家声明 | Director / Intent Contract |
| 核心线索锁死 | Scenario Runtime / Quality Gate |
| NPC 动机漂移 | Scenario NPC fields / Prompt |
| 场景长期停滞 | SceneRuntimeState / Pacing policy |
| 私密信息公开 | Reveal / Projection / SpoilerGuard |
| 断线后状态不一致 | Reconnect / State version / Projection |
| 所有问题都被写成“AI 不稳定” | 评审流程失败，必须重新定位 |


---

<!-- SOURCE FILE: 04_PLAYTEST_PROTOCOL.md -->

# AI-Keeper 真人跑团测试协议

> 状态：Draft v0.1  
> 首个测试模组：`02-short-team-glass-rain`  
> 适用阶段：P0 浏览器 Golden Run、P1 Internal Dogfood、Controlled New User、Unfamiliar User  
> 目的：收集可定位、可复现、可比较的真实玩家证据

---

## 1. 测试原则

1. 自动测试不能替代真人跑团；
2. 真人反馈不能替代权威 Trace；
3. 测试过程中不通过口头教学掩盖界面和 AI-KP 缺陷；
4. 每个问题必须关联 room/action/scene/trace/version；
5. 测试人员不扮演隐性 KP；
6. 故障注入必须在事先定义的位置进行，不能临场修改游戏结果；
7. 参与者应知道会记录脱敏操作与体验数据，并可停止参与。

---

## 2. 测试类型

### 2.1 Internal Dogfood

对象：熟悉项目或 TRPG 的内部人员。

目的：

- 查找状态、权限、UI 和核心链路明显问题；
- 验证测试脚本与观测工具；
- 不作为陌生用户可用性的最终证据。

### 2.2 Controlled New User

对象：认识团队，但不了解项目内部结构的玩家。

目的：

- 发现术语、流程、信息层级和 AI 行为问题；
- 验证不依赖开发者讲解完成首个有效行动。

### 2.3 Unfamiliar User

对象：完全不了解项目、不阅读仓库文档的玩家。

目的：

- 验证真实上手能力；
- 验证清晰度、主动权、氛围和复玩意愿；
- 作为 P1 退出的主要证据。

---

## 3. 测试角色

| 角色 | 职责 | 禁止事项 |
|---|---|---|
| Moderator | 宣读统一开场、处理安全中止 | 不解释怎样操作、不裁决游戏 |
| Observer | 记录行为、困惑、停顿与问题标签 | 不给玩家提示 |
| Ops | 监控服务、执行预定故障注入 | 不修改骰点/状态/线索 |
| Players | 正常进行游戏和反馈 | 不需要迎合测试预期 |
| Review Lead | 会后关联 Trace、归因和汇总 | 不只凭印象归因 |

一名人员可以兼任 Observer 和 Ops，但 Moderator 不应同时频繁操作后台，以免错过玩家行为。

---

## 4. 测试前置条件

### 4.1 P0 条件

- [ ] 使用明确 Release Candidate；
- [ ] 版本束已冻结；
- [ ] `session_mode=ai_only`；
- [ ] 无可用 LegacyHostAdjudicator；
- [ ] Resolution Trace 开启；
- [ ] 浏览器、WebSocket、数据库和 Provider 健康检查通过；
- [ ] Glass Rain runtime package 为 `ready`；
- [ ] 测试房间从空白状态创建；
- [ ] 不复用旧房间或旧角色运行时状态。

### 4.2 设备

- [ ] 每位玩家独立手机/浏览器会话；
- [ ] StageClient 使用独立只读设备；
- [ ] RoomOwner 完成开房后可关闭页面；
- [ ] 屏幕录制/操作日志已获得参与者知情；
- [ ] 网络条件和浏览器版本记录。

### 4.3 数据与隐私

记录：

- 脱敏 action 与 UI 操作；
- 评分、问卷和访谈；
- Trace ID 与系统指标；
- 必要的录屏或截图。

不应向普通观察者暴露：

- 原始 Prompt；
- 未揭示真相；
- 其他玩家私密信息；
- token、密码、API key；
- 完整未脱敏 Trace。

---

## 5. 参与者招募与分组

每场记录：

```yaml
participant_profile:
  participant_id:
  age_range: optional
  trpg_experience: none | beginner | regular | expert
  coc7_experience: none | beginner | regular | expert
  ai_chat_experience: low | medium | high
  knows_project: false | limited | internal
  device_type:
  accessibility_needs:
```

避免只招募：

- 熟悉系统的开发者；
- 高度熟悉 CoC 规则的规则专家；
- 会主动替系统补全操作逻辑的人。

至少包含部分 TRPG 新手，才能验证 AI-Keeper 是否真正降低主持与上手门槛。

---

## 6. 统一主持开场词

Moderator 只说：

> 这是一个由 AI 担任 KP 的 CoC 7e 短团。请按页面提示创建或加入房间、选择角色并开始游戏。测试期间请像正常玩家一样行动，可以自由输入，不需要猜测试人员想让你做什么。遇到看不懂、觉得不公平或不知道下一步时，请直接说出来。除系统故障或安全问题外，测试人员不会告诉你该点哪里或该怎样推进。

不得补充：

- 推荐路径；
- 剧本线索；
- 哪个技能最合适；
- 如何绕过 UI；
- “这个按钮暂时有问题，你先这样做”的口头补丁。

若出现口头补丁，必须记录为 `moderator_intervention`，该任务不能计为“独立完成”。

---

## 7. 测试任务脚本

### 任务 1：创建/加入房间

观察：

- 是否能找到入口；
- 是否理解邀请码、角色与 ready；
- 是否出现内部术语障碍。

成功标准：无需讲解完成加入并进入大厅。

### 任务 2：角色选择与 Session Zero

观察：

- 是否理解角色定位；
- 是否知道哪些步骤未完成；
- 是否理解风险、边界、缺勤和投影探测。

成功标准：所有强制子项由 Engine 判定完成，无人直接设置 `session_zero_completed`。

### 任务 3：第一次有效行动

观察：

- 玩家是否知道可以自由输入；
- AI 理解摘要是否清楚；
- 普通动作是否存在多余确认；
- 玩家是否知道结果和下一步。

成功标准：无开发者讲解完成第一次 `completed` action。

### 任务 4：调查与对话循环

观察：

- 规则信息和叙事是否分层；
- NPC 是否连贯；
- 场景是否停滞；
- 玩家是否能提出非预设方案。

成功标准：至少完成一次调查、一次 NPC 对话和一次 no_check 或 skill check。

### 任务 5：歧义与 choice

使用自然产生的歧义；若整场未出现，可在不剧透的安全场景中使用预设输入。

成功标准：结果不同的候选进入 choice；无 Host 裁决。

### 任务 6：风险与 consent

成功标准：

- 事前展示风险类别和上限；
- consent 在骰点前；
- 授权范围内结果直接生效；
- 结果后不能通过刷新撤销。

### 任务 7：失败推进

不得强制玩家失败；测试环境可以使用预定随机种子或专用测试场次。

成功标准：普通失败产生代价、部分信息、危险、压力或 NPC 变化，并保留可行动空间。

### 任务 8：线索发现与分享

成功标准：

- 私人/公开边界清楚；
- 分享前知道分享范围；
- StageClient 不显示未分享私密内容。

### 任务 9：多人协作与聚光灯

观察：

- 是否有一人连续垄断；
- 系统是否自然邀请沉默玩家；
- OOC 是否被误当动作；
- 等待状态是否清楚。

### 任务 10：预定故障注入

仅由 Ops 在预定节点执行：

- Provider 在权威副作用前失败；
- RollReceipt 后、状态提交前失败；
- 状态提交后 Narrator/Projection 失败。

成功标准：符合 P0 阶段恢复规则，不重投、不重复写状态。

### 任务 11：断线重连

至少一名玩家断线并重连。

成功标准：恢复当前状态、私密信息、待处理 action 和等待原因。

### 任务 12：结局与档案

成功标准：

- Engine 提交 authored ending；
- 展示关键选择和角色后果；
- 档案可查看；
- 给出继续体验入口。

---

## 8. Moderator 介入规则

### 允许介入

- 人身安全、内容边界或参与者明确要求停止；
- 服务完全不可用且无法通过规定恢复；
- 数据泄漏风险；
- 测试设备硬件故障；
- 参与者无法继续且已确认要结束。

### 不允许介入

- 告诉玩家按哪个按钮；
- 解释规则结果来替代 UI；
- 提供剧本线索；
- 帮 AI 解释意图；
- 决定使用哪个技能/难度；
- 让玩家“先配合跑通”；
- 后台修改 HP/SAN/线索继续计为成功。

任何介入记录：

```yaml
moderator_intervention:
  timestamp:
  reason:
  exact_intervention:
  affected_task:
  acceptance_disqualified: true | false
```

---

## 9. 观察与问题编码

### 9.1 行为观察码

| 代码 | 含义 |
|---|---|
| `HESITATE` | 停顿超过观察阈值，未操作 |
| `BACKTRACK` | 返回前页寻找信息 |
| `MISCLICK` | 误触或误解按钮 |
| `ASK_HOW` | 询问怎样操作 |
| `ASK_WHY` | 询问为何检定/为何变化 |
| `CORRECT_AI` | 主动纠正 AI 理解 |
| `LOST_CONTEXT` | 不知道当前场景/目标 |
| `WAIT_UNKNOWN` | 不知道系统在等待谁 |
| `DISENGAGE` | 明显失去参与或转做其他事情 |
| `DELIGHT` | 自发正向反应 |

### 9.2 问题标签

```text
intent_error
unnecessary_confirmation
missed_choice
unclear_rule_reason
unnecessary_check
wrong_difficulty
state_change_hidden
weak_failure_progression
clue_too_early
clue_blocked
npc_inconsistency
scene_stagnation
repetitive_narration
spotlight_imbalance
private_public_mixup
unclear_ui
slow_response
reconnect_confusion
archive_confusion
safety_incident
```

### 9.3 严重度

| 级别 | 定义 |
|---|---|
| Blocker | 无法继续、泄密、非法状态、重复骰点或需要人工裁决 |
| Critical | 破坏主动权、公平性或主线，但仍可技术继续 |
| Major | 显著影响理解、节奏或参与感 |
| Minor | 局部摩擦，不影响完成 |
| Observation | 暂不确定是否为缺陷，需更多样本 |

---

## 10. 单问题记录模板

```yaml
playtest_issue:
  issue_id:
  session_id:
  room_id:
  participant_ids: []
  scene_id:
  action_id:
  trace_id:
  version_bundle:
  timestamp:
  issue_tag:
  severity:
  observed_behavior:
  participant_quote:
  expected_behavior:
  actual_behavior:
  reproduction_steps: []
  evidence_paths: []
  suspected_owner: engine | backend | frontend | ai_prompt | scenario | projection | operations
  status: new | triaged | fixing | verified | closed
```

---

## 11. 会后问卷（1–5 分）

请玩家评分：

1. 我知道怎样开始游戏；
2. 我知道 AI 怎样理解了我的行动；
3. 我理解为什么需要或不需要检定；
4. 我理解行动结果对角色和场景造成了什么影响；
5. 我通常知道接下来可以做什么；
6. 我觉得自己的选择会真实影响故事；
7. 我觉得裁决公平；
8. NPC 的行为和态度前后一致；
9. 游戏节奏让我保持投入；
10. 我有足够的参与机会；
11. 私人和公共信息区分清楚；
12. 遇到断线/等待/错误时，我知道系统在做什么；
13. 我愿意继续玩另一个剧本。

开放题：

- 哪个时刻最投入？为什么？
- 哪个时刻最困惑？
- 有没有觉得 AI 替你做了决定？
- 有没有觉得某次投骰没有必要或不公平？
- 哪个 NPC 最自然/最不自然？
- 是否有长时间不知道如何推进？
- 哪项信息最难找？
- 继续玩之前，最希望修复什么？

---

## 12. Session 报告模板

```markdown
# Playtest Session Report — <SESSION_ID>

## 基本信息
- RC / commit:
- Version bundle:
- Scenario:
- Player count:
- Participant profile:
- Test type:

## 完成情况
- 第一场景：PASS/FAIL
- 第一次有效行动：PASS/FAIL
- 线索分享：PASS/FAIL
- 风险 consent：PASS/FAIL
- 故障恢复：PASS/FAIL
- 重连：PASS/FAIL
- authored ending：PASS/FAIL

## 指标
- Time to first effective action:
- Clarification count/rate:
- Player correction count:
- Scene stagnation count:
- Spotlight imbalance:
- P95 action latency:

## AI-KP 七维评分
...

## 玩家问卷
...

## 问题列表
...

## Moderator interventions
...

## 结论
PASS / CONDITIONAL / FAIL / BLOCKED

## 下一轮必须修复
...
```

---

## 13. 测试结论规则

### `PASS`

- 无 Blocker/Critical；
- 必要任务独立完成；
- 指标达到当前门槛；
- Trace、录屏、问卷和问题记录完整。

### `CONDITIONAL`

- 无 Blocker；
- 存在 Major，但不破坏主要旅程；
- 必须明确下一轮验证项，不能直接作为 P1 退出依据。

### `FAIL`

- 关键任务无法独立完成；
- 需要测试人员教学或人工裁决；
- 质量门槛明显未达。

### `BLOCKED`

- 技术环境、数据安全、严重剧透、非法状态或 Trace 缺失导致结果不可采信。


---

<!-- SOURCE FILE: 05_GLASS_RAIN_PLAYER_JOURNEY.md -->

# Glass Rain 端到端玩家旅程与验收基线

> 状态：Draft v0.1  
> 目标模组：`02-short-team-glass-rain`  
> 玩家人数：2–4  
> 用途：P0 浏览器 Golden Run、P1 Playable Alpha、前端信息架构与真人测试  
> 实物核验：2026-08-27 已读取静态 `module.json`、README 与内嵌 `quality_report`；尚未读取真实发布场景记录、编译后 runtime package 或浏览器 Golden Run。  
> 重要说明：下列静态 ID 可用于旅程和场景验收；数据库生成的运行包 ID、实际房间版本束和浏览器证据不能由静态文件替代。

---

## 1. 旅程目标

玩家应能在没有人类 KP 和开发者讲解的情况下完成：

```text
创建/加入
→ 角色选择
→ Session Zero
→ AI 开场
→ 第一次有效行动
→ 调查/对话/检定
→ 线索发现与分享
→ 歧义选择
→ 风险/组决策
→ 失败推进与场景升压
→ 断线/Provider 故障恢复
→ authored ending
→ 档案与继续体验入口
```

---

## 2. 已回填的静态字段与待运行时绑定字段

```yaml
glass_rain_package:
  module_id: golden-team-glass-rain
  title: 玻璃雨夜
  source_file_sha256: ca6c731803165fc9d13e1ac1f5263c8c2ad26867bb0cdf594b6f4b54341bb989
  static_schema_version: "2.0"
  runtime_version: v2
  runtime_contract_version: v1
  session_mode: ai_only
  rule_set_slug: coc7
  static_rule_set_version: configured-published-version
  player_range: "2-4"
  entry_scene_id: glass-gate
  major_scene_ids: [glass-gate, orchid-hall, control-room, cistern]
  major_npc_ids: [yuan-guard, qiao-volunteer, han-engineer, mei-maintainer]
  core_clue_ids: [g17-test-sheet, restart-log, maintenance-radio]
  recovery_node_ids: [glass-radio-recovery]
  pressure_clock_ids: [glass-storm]
  authored_ending_ids: [glass-rescue, glass-power-first, glass-timeout, glass-safe-abort]
  victory_or_mixed_ending_ids: [glass-rescue, glass-power-first]
  database_scenario_id: "由已发布 scenario 记录提供；静态模块未嵌入"
  runtime_package_version_id: "编译后数据库生成；未以静态模块值代替"
  scenario_package_hash: "房间冻结 version_bundle 的值；source_file_sha256 仅作本次审计指纹"
  prompt_bundle_version: "由实际房间 version_bundle 提供"
  rule_version_id: "由实际房间 version_bundle 提供；不可仅用 static_rule_set_version 代替"
  ai_policy_version: "由实际房间 version_bundle 提供"
```

静态 `quality_report` 标记该模组为 `ready`、完整度 `1.0`，唯一信息级问题为场景缺少配图；这不等同于真实房间可发布。真实 Golden Run 必须记录实际 `runtime_package_version_id`、冻结版本束、Trace 与浏览器证据。

---

## 3. 旅程阶段总表

| 阶段 | 玩家目标 | 关键界面 | 系统状态/合同 | 主要验收 |
|---:|---|---|---|---|
| 0 | 了解这是怎样的游戏 | 首页/剧本卡 | 无房间 | 能找到创建/加入，不暴露内部术语 |
| 1 | 创建房间 | RoomOwner 创建页 | lobby，版本候选 | 绑定合格规则/运行包，生成邀请 |
| 2 | 加入房间 | 玩家加入页 | player token/device session | 幂等加入、角色占用清楚 |
| 3 | 选择角色 | 角色选择/预览 | character binding | 显示角色定位和公开背景 |
| 4 | 完成 Session Zero | 大厅检查表 | Engine 派生门禁 | 所有强制子项完成才可 running |
| 5 | 验证无 Owner 依赖 | Stage/玩家端 | Owner 离线 | 正常行动不等待 Owner |
| 6 | 接收 AI 开场 | 行动主界面/Stage | entry scene established | 地点、目标、压力、行动空间清楚 |
| 7 | 完成第一次行动 | Action Composer | analyze→queue→resolve | 无开发者讲解完成一次 action |
| 8 | 进入调查循环 | 结果卡/日志/角色 | scene runtime | 理解、规则、变化、叙事分层 |
| 9 | 发现与分享线索 | 私密通知/线索日志 | RevealLedger/Projection | 私密与公开边界正确 |
| 10 | 处理歧义 | choice panel | awaiting_player_choice | 结果不同才询问，无 Host |
| 11 | 处理风险/组决策 | consent panel | awaiting_player_consent | 事前授权、fail-closed |
| 12 | 经历失败推进 | 结果卡/压力提示 | failure/partial outcome | 有代价且可继续 |
| 13 | 处理多人/缺勤/重连 | waiting/reconnect UI | deterministic absence | AI 不代玩，状态可恢复 |
| 14 | 处理 Provider 故障 | 系统状态/恢复提示 | technical retry | 不重投、不重复写状态 |
| 15 | 进入 authored ending | 结局页 | Engine ending commit | 结局唯一、可解释 |
| 16 | 查看档案 | Archive | finalized/archive | 时间线、线索、角色结局完整 |

---

## 4. 阶段 0：进入产品

### 玩家需要看到

- “创建一场 AI-KP 游戏”；
- “加入朋友的房间”；
- Glass Rain 是 2–4 人调查短团；
- 是否需要麦克风、公共屏幕；
- 大致玩法说明；
- 数据与录制提示（测试环境）。

### 不应出现为主入口术语

```text
runtime_version
rule_source_version
Prompt bundle
HostAutonomy
ResolutionPipeline
StateService
```

这些信息可放在高级/诊断区域。

### 验收用例

```text
GR-JRN-001  新玩家在首页 30 秒内找到加入入口。
GR-JRN-002  玩家不需要知道“Host”概念即可加入。
GR-JRN-003  剧本卡不剧透真相和隐藏结局。
```

---

## 5. 阶段 1：RoomOwner 创建房间

### 标准流程

```text
选择 Glass Rain
→ 选择 ai_only
→ 系统检查 rule/runtime gate
→ 创建 lobby
→ 返回 invite_code 与 StageClient 入口
```

### 系统要求

- 房间尚未进入权威运行前可选择模式；
- 运行包/规则包不是 `ready` 时阻止创建可运行房间；
- 创建后显示脱敏版本摘要；
- StageClient 使用独立只读凭据；
- RoomOwner 不看到隐藏真相。

### 验收用例

```text
GR-JRN-004  不合格运行包不能开始 Session Zero。
GR-JRN-005  StageClient 不复用 owner_token。
GR-JRN-006  RoomOwner 页面不提供裁决、重算或跳过按钮。
```

---

## 6. 阶段 2–3：加入与角色选择

### 玩家目标

- 输入邀请码；
- 建立设备会话；
- 查看未占用角色；
- 理解角色在团队中的大致定位；
- 完成绑定并进入大厅。

### 角色卡选择态至少显示

```text
public_name
public_background
play_style_summary
strengths
possible_weaknesses
key_skills
content_notes（不剧透）
availability
```

### 验收用例

```text
GR-JRN-007  重复点击加入不会创建重复玩家。
GR-JRN-008  同一角色不能被两名玩家静默占用。
GR-JRN-009  玩家不需要打开完整规则书理解角色定位。
GR-JRN-010  角色私密背景只发送给对应玩家。
```

---

## 7. 阶段 4：Session Zero

### 必须展示的子项

| 子项 | 玩家可见状态 | 失败处理 |
|---|---|---|
| 角色 ready | 谁未 ready | 定位到具体玩家 |
| 内容警告/边界 | 每位玩家已确认/未确认 | 不显示他人的私密边界正文 |
| RiskContract/consent 规则 | 已阅读并确认 | 提供简短解释 |
| 私密投影探测 | 成功/失败 | 重试设备会话 |
| 公共投影探测 | Stage 成功/未连接 | Stage 可选时明确说明 |
| 缺勤策略 | idle/maintain_existing | 默认值需玩家确认 |
| 版本束 | 已锁定 | 高级区域可展开 |
| 断线恢复探测 | 成功/失败 | 失败不得开团 |

### 验收用例

```text
GR-JRN-011  任何强制子项缺失时不能进入 running。
GR-JRN-012  客户端无法直接写 session_zero_completed=true。
GR-JRN-013  模式与版本束在完成后冻结。
GR-JRN-014  私密探测消息不出现在 Stage。
```

---

## 8. 阶段 5：RoomOwner 离线验证

Session Zero 完成后：

```text
关闭 RoomOwner 页面
→ StageClient 保持只读
→ 玩家继续整场
```

### 验收用例

```text
GR-JRN-015  所有普通 action 自动调度。
GR-JRN-016  无 action 进入 awaiting_host_exception。
GR-JRN-017  玩家界面不出现“等待房主处理”。
GR-JRN-018  只有运营暂停/结束需要 Owner，正常游戏不依赖 Owner 在线。
```

---

## 9. 阶段 6：AI 开场

### 开场必须建立

- 当前公开地点；
- 当前场景目的的玩家可见版本；
- 第一批公开事实；
- 当前压力的玩家可见表达；
- 至少一个不剧透的可行动方向；
- 谁可以先行动/当前是否自由行动。

### 禁止

- 直接揭示幕后真相；
- 用大量设定文本淹没可行动信息；
- 替角色描述情绪或决定；
- 只给一句“你们要做什么”。

### 验收用例

```text
GR-JRN-019  玩家能复述当前地点和基本目标。
GR-JRN-020  开场不泄漏 secret_fact_refs。
GR-JRN-021  开场后无需 Moderator 提示即可开始行动。
```

---

## 10. 阶段 7：第一次有效行动

### UI 顺序

```text
最新场景
→ 当前局势/可行动空间
→ 自由输入
→ 非阻塞理解摘要
→ 处理中
→ 结构化结果卡
```

### 结果卡顺序

```text
原始声明
→ AI 理解
→ 是否检定/原因
→ 骰点/规则结果
→ 状态/线索变化
→ 场景叙事
→ 当前局势和下一步空间
```

### 验收用例

```text
GR-JRN-022  普通低风险单一动作不要求额外确认。
GR-JRN-023  AI 不增加玩家未声明的方法或资源。
GR-JRN-024  玩家能指出为什么投骰或为什么无需投骰。
GR-JRN-025  玩家能指出结果改变了什么。
```

---

## 11. 阶段 8：调查循环

循环：

```text
行动
→ 规则/无检定
→ 世界变化
→ 线索/NPC/压力更新
→ 玩家选择下一步
```

每轮 SceneRuntimeState 至少更新或确认：

```text
phase
public_objectives
unresolved_core_clues
pressure_clock
eligible_npc_actions
hint_level
last_effective_action_by_player
```

### 验收用例

```text
GR-JRN-026  连续两个无结果动作后系统能说明局势是否变化。
GR-JRN-027  场景停滞时使用已编译事件/提示，不自由补主线。
GR-JRN-028  非预设合理方案可以进入 Engine 校验，而非直接拒绝。
GR-JRN-029  NPC 态度变化可追踪到玩家行动或压力事件。
```

---

## 12. 阶段 9：线索发现与分享

### 私人发现

玩家端显示：

- “仅你可见”；
- 线索玩家可见名称；
- 来源；
- 可选择分享安全公开版本或确认分享全文。

### 公共分享

Stage 与其他玩家只看到合法公开版本。

### 验收用例

```text
GR-JRN-030  私人 clue 在分享前不出现在 Stage。
GR-JRN-031  分享全文需要明确确认。
GR-JRN-032  未提供 public_version 时使用安全占位，而非秘密正文。
GR-JRN-033  重复引用链接到原 clue，不重复刷屏。
GR-JRN-034  core clue 失败后仍有已编译替代路径或 recovery node。
```

---

## 13. 阶段 10：意图歧义与 choice

### 标准流程

```text
Director 产生候选
→ Engine 比较权威影响
→ 结果等价：保守自动解释
→ 结果不同：awaiting_player_choice
```

### choice 界面

- 2–3 个不剧透候选；
- 每个候选使用玩家语言，不显示内部规则实现；
- “都不是，我补充说明”；
- 显示原始声明。

### 验收用例

```text
GR-JRN-035  confidence 高但结果不同仍进入 choice。
GR-JRN-036  confidence 低但结果等价可以保守自动继续。
GR-JRN-037  choice 不路由 Owner。
GR-JRN-038  选择后冻结 Intent Contract，技术恢复不重新解释。
```

---

## 14. 阶段 11：风险与组决策

### 风险 consent

展示：

```text
风险类别
最高严重度
可能资源消耗
可能位置/状态变化
不可逆性质
受影响玩家
```

### 组决策

- 可逆路线：按冻结规则；
- 共享资源、结局、放弃队友、风险扩张：全票；
- 沉默/缺勤：拒绝；
- RoomOwner/AI 不代理。

### 验收用例

```text
GR-JRN-039  consent 必须早于 RollReceipt。
GR-JRN-040  已授权普通失败不进行事后二次确认。
GR-JRN-041  风险扩张创建新 consent。
GR-JRN-042  缺勤玩家不被视为同意。
```

---

## 15. 阶段 12：失败推进与场景升压

失败至少产生一种：

- 代价；
- 不完整信息；
- 新危险；
- 时间/资源消耗；
- NPC 态度变化；
- 暴露行动；
- 压力推进。

### 玩家必须看到

- 失败不是“系统错误”；
- 具体代价；
- 当前压力变化；
- 仍可采取的行动。

### 验收用例

```text
GR-JRN-043  普通失败不返回空结果。
GR-JRN-044  单次失败不永久锁死唯一主线入口。
GR-JRN-045  失败后可行动空间与新局势一致。
GR-JRN-046  系统不为保护玩家而无依据撤销风险。
```

---

## 16. 阶段 13：多人、缺勤与重连

### 多人状态

UI 应明确：

- 当前正在处理谁的 action；
- 等待哪些玩家的 choice/consent；
- 谁掉线/缺勤；
- 哪些私密 action 只对本人可见。

### 重连

恢复：

```text
current_scene
character_state
private_reveals
pending_actions
pending_confirmation/choice/consent
last_event_sequence
state_version
```

### 验收用例

```text
GR-JRN-047  一名玩家掉线不阻塞其他独立行动。
GR-JRN-048  AI 不为掉线玩家创建主动行动。
GR-JRN-049  重连后不会重复提交原 action。
GR-JRN-050  待处理私密 choice/consent 只恢复给正确玩家。
GR-JRN-051  聚光灯计数不会因刷新重置。
```

---

## 17. 阶段 14：Provider 故障与技术恢复

### 玩家可见表达

不要显示内部堆栈和 Prompt。应显示：

- 本次动作是否已经投骰；
- 状态是否已提交；
- 系统正在重试、恢复或拒绝；
- 玩家是否需要重新表达或等待恢复。

### 验收用例

```text
GR-JRN-052  权威副作用前全 Provider 失败时 action rejected，房间可继续。
GR-JRN-053  RollReceipt 后故障复用原骰点。
GR-JRN-054  状态提交后故障只恢复叙事/投影。
GR-JRN-055  无安全恢复时 paused_system，不转人工裁决。
GR-JRN-056  RoomOwner 恢复不能选择有利检查点。
```

---

## 18. 阶段 15–16：结局与档案

### authored ending

由 Engine 根据冻结状态、`priority` 和 `mutual_exclusion_group` 确定。

玩家页展示：

- 结局玩家可见名称；
- 关键公开条件；
- 关键选择；
- 每名角色的结局；
- 未解决内容的非剧透表达；
- 归档入口。

### 档案

至少包含：

```text
公共时间线
每名玩家合法可见的私人时间线
关键选择
主要线索及来源
主要检定摘要
HP/SAN/资源关键变化
角色结局
中止/系统故障说明（如适用）
```

### 验收用例

```text
GR-JRN-057  AI 不选择 ending。
GR-JRN-058  多结局冲突不能按文件顺序静默处理。
GR-JRN-059  Owner 结束显示 aborted 且 ending_id=null。
GR-JRN-060  档案不泄露其他玩家私密信息。
GR-JRN-061  玩家可从档案进入“再玩一个剧本”。
```

---

## 19. 页面/状态矩阵

| 页面 | lobby | running | paused_by_owner | paused_system | recovering | ended |
|---|---|---|---|---|---|---|
| Player Join/Lobby | 加入/ready | 跳转游戏 | 显示暂停 | 显示系统故障 | 显示恢复 | 进入档案 |
| Player Action | 禁用输入 | 正常输入 | 禁用新 action | 禁用并显示安全入口 | 显示阶段 | 只读 |
| StageClient | 大厅公共信息 | 公共叙事 | 暂停画面 | 系统安全画面 | 恢复画面 | 结局/中止 |
| RoomOwner | 运营设置 | 暂停/结束 | 恢复/结束 | 执行系统恢复/结束 | 查看进度 | 归档 |
| Review Workbench | 测试准备 | 脱敏观察 | 查看原因 | 查看 Trace/故障 | 查看恢复链 | 汇总 |

---

## 20. Glass Rain 旅程完成定义

- [ ] `GR-JRN-001～061` 均有测试或浏览器证据；
- [ ] 实际 module 文件已回填场景、NPC、线索、恢复节点和结局 ID；
- [ ] Owner 页面在 Session Zero 后可全程关闭；
- [ ] 至少覆盖一次 choice、一次 consent、一次普通失败推进；
- [ ] 至少覆盖一次 Provider 故障和一次玩家重连；
- [ ] 私密/公共投影无错误；
- [ ] 进入 authored `victory` 或 `mixed`；
- [ ] 证明其他 authored ending 也可确定性结束；
- [ ] 完整档案可查看；
- [ ] 真人玩家能够独立完成主要旅程。


---

<!-- SOURCE FILE: 06_P1_IMPLEMENTATION_BACKLOG.md -->

# AI-Keeper P1 Playable Alpha 实施 Backlog

> 状态：Draft v0.1  
> 前置：P0 状态、权限、DTO、事件、版本束和 Trace 稳定  
> 主战场：`02-short-team-glass-rain`  
> 原则：按玩家旅程交付纵向闭环，不按“再做几个页面”拆分

---

## 1. 优先级定义

| 等级 | 定义 |
|---|---|
| `P1-BLOCKER` | 不做则无法进行真实玩家测试或会掩盖 P0 缺陷 |
| `P1-MUST` | Playable Alpha 退出必需 |
| `P1-SHOULD` | 显著改善体验，但可在首轮受控测试后调整 |
| `P1-LATER` | 暂不进入 P1 主线 |

---

## 2. 依赖 P0 冻结的接口

P1 开始大规模代码修改前必须稳定：

```text
action_status
room_runtime_status
resolution_outcome
campaign_lifecycle_status
confirmation / choice / consent DTO
ProviderFailure / recovery status
version_bundle
Resolution Trace ID
Projection audience
Session Zero sub-status
SceneRuntimeState 基础字段
```

如果这些仍在变化，P1 只做原型、文档和测试脚本，不直接固化前端业务逻辑。

### 2.1 2026-08-27 前置状态快照

本次定向核验已为 D01、D11、D12、D13/D14、D15、D18、D23 取得代码与自动测试证据，但尚未形成 P0 Release 结论。D19 仍缺少私密/公共投影实际探测与冻结的缺勤策略，D24/D25 仍缺少 Benchmark、浏览器 Golden Run 与逐项 Requirement 矩阵。

因此 Wave 0 可以继续维护旅程、数据合同和测试脚本；Wave 1 及后续前端业务实现不得把任何 P0 接口视为已经正式冻结，直到 01 的硬阻断和 Release 结论有完整证据。

---

## 3. 实施波次

```text
Wave 0  数据合同与旅程冻结
→ Wave 1  开团到第一次有效行动
→ Wave 2  调查、结果、线索与场景节奏
→ Wave 3  多人、重连、恢复与档案
→ Wave 4  Review Workbench、指标和真人测试闭环
```

波次表示依赖顺序，不代表时间承诺。

---

# 4. Work Package

## P1-WP-A：玩家旅程与信息架构

**优先级：** `P1-BLOCKER`

### 目标

冻结首页、加入、角色、Session Zero、游戏主界面、结局与档案的操作顺序和信息层级。

### 交付

- 页面/状态矩阵；
- 路由图；
- 每页“玩家当前状态/下一步/等待原因”；
- 公共/私人/OOC/系统消息视觉层级；
- 空态、错误态、暂停态、恢复态。

### 验收

- `05_GLASS_RAIN_PLAYER_JOURNEY.md` 的每个阶段均有页面承载；
- 无正常流程需要 Admin 页面；
- 不把内部状态机术语直接暴露给新玩家。

### 依赖

P0 D01、D04、D12～D19。

---

## P1-WP-B：Session Zero 与首次行动

**优先级：** `P1-BLOCKER`

### 目标

让新玩家无讲解完成角色选择、Session Zero、AI 开场和第一次有效行动。

### 交付

- Session Zero 子项检查表；
- 私密/公共投影探测；
- 设备恢复探测；
- 角色定位预览；
- AI 开场结构；
- 第一次行动引导但不限制自由输入。

### 测试

- 子项缺失不能开团；
- 客户端不能直接完成 Session Zero；
- 无 Moderator 教学完成首个 action；
- RoomOwner 页面关闭后流程继续。

---

## P1-WP-C：Action Composer 与三类交互

**优先级：** `P1-BLOCKER`

### 目标

将普通动作、confirmation、choice、consent 形成低摩擦且不混淆的交互。

### 交付

- 原始声明与理解摘要；
- 普通动作非阻塞提交；
- confirmation panel；
- choice panel；
- consent/risk panel；
- 复合动作步骤展示；
- 权威骰点前的取消/修正边界。

### 测试

- 结果等价歧义自动继续；
- 结果不同歧义必须 choice；
- 风险 consent 早于骰点；
- 刷新/重复提交不产生新骰点。

---

## P1-WP-D：结构化 Action Result Card

**优先级：** `P1-BLOCKER`

### 目标

让玩家理解“系统理解—规则—变化—叙事—下一步”。

### 交付

- 结果卡 DTO 与组件；
- skill/no_check/partial/failure/rejected 各状态；
- RollReceipt 摘要；
- HP/SAN/Luck/物品/线索变化；
- 自动复核入口与 gameplay reattempt 入口区分。

### 测试

- 玩家可指出检定原因；
- 规则结果不只存在于叙事；
- 状态变化前后值清楚；
- 私密变化不投影到 Stage。

---

## P1-WP-E：SceneRuntimeState 与节奏

**优先级：** `P1-MUST`

### 目标

让系统明确管理场景阶段、压力、停滞、升级与退出，不由模型每轮重猜。

### 交付

- SceneRuntimeState DTO/存储/事件；
- phase 转换规则；
- pressure clock 展示；
- stagnation detection；
- escalation/hint/NPC action eligibility；
- 场景退出条件与 Engine 证据。

### 测试

- 停滞时只使用编译内容；
- 不连续重复“接下来做什么”；
- 压力变化可追踪；
- 新场景正确更新目标和行动空间。

### 待实物核验

Glass Rain 的实际场景、压力和升级字段。

---

## P1-WP-F：线索与知识体验

**优先级：** `P1-MUST`

### 目标

让玩家明确知道什么、谁知道、从哪里知道，以及如何安全分享。

### 交付

- 私人/公开/猜测/真相分层；
- clue source 与时间；
- 分享范围预览；
- 原线索链接与去重；
- core clue fallback/recovery 可视化诊断。

### 测试

- 私密 clue 不出现在 Stage；
- 全文分享需确认；
- 核心线索失败仍可推进；
- 已揭示 clue 不重复刷屏。

---

## P1-WP-G：NPC 连贯性与主动行为

**优先级：** `P1-MUST`

### 目标

将 NPC 目标、知识、秘密、恐惧、态度、压力反应和临场边界真正接入运行时。

### 交付

- NPC runtime view；
- attitude change events；
- eligible NPC actions；
- lie/reveal policy；
- Prompt 上下文最小化；
- 一致性检查与问题标签。

### 测试

- 重复询问不无条件吐露信息；
- 态度变化有证据；
- 无 secret_fact 泄漏；
- 临场创造不越界。

### 待实物核验

Glass Rain 主要 NPC 列表和运行字段。

---

## P1-WP-H：多人聚光灯与等待状态

**优先级：** `P1-MUST`

### 目标

多人局中保持参与感，明确同时行动、私密行动、组决策、缺勤与等待原因。

### 交付

- `last_effective_action_by_player`；
- spotlight counter；
- waiting_for_player 展示；
- OOC/action 分类；
- 沉默玩家邀请策略；
- 私密/公共 action 指示。

### 测试

- 一名玩家不能长期垄断而无人被邀请；
- 不强制机械轮流；
- OOC 不进入角色动作；
- 缺勤玩家不由 AI 接管。

---

## P1-WP-I：重连、暂停与恢复体验

**优先级：** `P1-BLOCKER`

### 目标

将 P0 的确定性恢复翻译成玩家可理解的 UI，而不是暴露内部阶段。

### 交付

- reconnect snapshot；
- pending action/choice/consent 恢复；
- owner/system/recovering 状态页面；
- “尚未投骰/原骰点已保留/状态已提交”安全说明；
- 结束与导出诊断入口。

### 测试

- 刷新不重复 action；
- 重连恢复私密数据；
- Provider 故障后不重投；
- 暂停后不误导玩家创建新 action。

---

## P1-WP-J：结局、档案与复玩入口

**优先级：** `P1-MUST`

### 目标

让玩家理解结局、回顾关键选择，并自然进入下一次体验。

### 交付

- authored ending 页面；
- aborted 页面；
- 公共/私人档案；
- 关键选择、线索、检定和状态变化；
- 角色结局；
- 再玩一个剧本入口。

### 测试

- ending 证据可解释；
- Owner 中止不显示胜利/失败结局；
- 私密内容按玩家过滤；
- Archive 与 Trace 摘要一致。

---

## P1-WP-K：Session Review Workbench

**优先级：** `P1-MUST`

### 目标

让产品、Prompt、剧本和工程团队从同一场跑团中快速定位问题。

### 交付

- room/scene/action/trace/version 导航；
- 问题标签与严重度；
- 原始声明、理解、规则、状态、揭示、叙事、投影链路；
- 脱敏权限；
- 修复版本与验证状态；
- 导出 Session Report。

### 测试

- 普通 Observer 看不到秘密；
- audit_admin 访问有审计；
- 每个问题可分流到 Engine/AI/Scenario/UI/Projection；
- 问题修复后可关联回归证据。

---

## P1-WP-L：指标与真人测试闭环

**优先级：** `P1-BLOCKER`

### 目标

自动生成 P1 指标，并按 Playtest Protocol 完成真实玩家证据。

### 交付

- time to first effective action；
- clarification/correction；
- unclear-check 标注；
- scene stagnation；
- spotlight imbalance；
- action latency；
- 问卷与复玩意愿；
- AI-KP 七维评分；
- P1 Release Report。

### 测试轮次

1. Internal Dogfood；
2. Controlled New User；
3. Unfamiliar User。

---

# 5. 波次退出条件

## Wave 0：数据合同与旅程冻结

- [ ] P0 依赖 DTO 稳定；
- [ ] P1 Spec、Journey、Rubric、Playtest 进入 Review；
- [ ] Glass Rain 实物核验完成；
- [ ] 页面/状态矩阵冻结。

## Wave 1：开团到第一次有效行动

- [ ] WP-A/B/C/D 基本完成；
- [ ] 新玩家无讲解完成首个 action；
- [ ] RoomOwner 可离线；
- [ ] confirmation/choice/consent 边界正确。

## Wave 2：调查、线索、NPC 与节奏

- [ ] WP-E/F/G/H 基本完成；
- [ ] Glass Rain 主要场景可持续推进；
- [ ] 核心线索不锁死；
- [ ] NPC 连贯；
- [ ] 多人聚光灯无严重失衡。

## Wave 3：恢复与结局

- [ ] WP-I/J 完成；
- [ ] Provider 故障与重连体验可理解；
- [ ] authored ending 与档案闭环。

## Wave 4：Review 与真人测试

- [ ] WP-K/L 完成；
- [ ] 问题可定位、可分流、可回归；
- [ ] 三层真人测试完成；
- [ ] P1 退出门槛达到。

---

# 6. RACI

| 工作包 | Product | Backend | Frontend | AI/Prompt | Scenario | QA | Ops/Security |
|---|---|---|---|---|---|---|---|
| WP-A | A/R | C | R | C | C | C | I |
| WP-B | A | R | R | C | C | R | C |
| WP-C | A | R | R | R | C | R | I |
| WP-D | A | R | R | C | I | R | I |
| WP-E | A | R | C | C | R | R | I |
| WP-F | A | R | R | C | R | R | I |
| WP-G | A | C | C | R | R | R | I |
| WP-H | A | R | R | C | C | R | I |
| WP-I | C | R | R | I | I | R | A/C |
| WP-J | A | R | R | C | R | R | I |
| WP-K | A | R | R | C | C | R | C |
| WP-L | A | R | C | C | C | R | C |

`A=Accountable, R=Responsible, C=Consulted, I=Informed`

---

# 7. Issue/任务模板

```yaml
work_item:
  id:
  title:
  priority: P1-BLOCKER | P1-MUST | P1-SHOULD | P1-LATER
  requirement_ids: []
  journey_stage_ids: []
  quality_dimensions: []
  source_issue_ids: []
  owner:
  affected_modules: []
  api_or_dto_changes: []
  migration_required: false
  test_plan: []
  evidence_required: []
  dependencies: []
  out_of_scope: []
  acceptance_criteria: []
```

---

# 8. 防止范围漂移的停止规则

开发中出现以下提议时，默认进入候选池而非当前波次：

- “顺手把其他规则系统也抽象了”；
- “先做一个更完整的商城/社区”；
- “先把所有地图和图片效果做好”；
- “先增加更多管理后台页面”；
- “这个问题可以让 Prompt 自己灵活处理”；
- “先用人工按钮兜底，后面再自动化”；
- “Glass Rain 特例先写死，之后再泛化”。

允许进入当前波次的条件：

```text
明确关联 P1 Requirement
+ 明确影响 Glass Rain 玩家旅程
+ 有测试与证据
+ 不破坏 P0 冻结边界
```


---

<!-- SOURCE FILE: 07_仓库实物核验清单.md -->

# AI-Keeper 仓库实物核验清单

> 状态：Draft v0.1  
> 目的：把文档推断替换为代码、Prompt、Schema、运行包和测试的直接证据  
> 原则：未读取实物的字段不得在验收报告中写成“已经具备”

---

## 0. 2026-08-27 文档包与实物核验快照（非 Release 结论）

| 项目 | 核验结论 | 处理 |
|---|---|---|
| `00_使用说明与总索引.md` | 原文将 Glass Rain 实物、当前代码与测试一并列为未取得证据，且提到未核验的压缩包产物。 | 已改为区分本次静态/定向证据与 Release 级缺口。 |
| `01_P0_RELEASE_CHECKLIST.md` | 独立源文件比合订版多出规范 ID 映射、D12 精确定义和可执行命令；原合订版过期。 | 已在源文件与合订版同步，且只记录实施核验，不将 123 项标为 PASSED。 |
| `02_P1_PLAYABLE_ALPHA_SPEC.md` | 需求与退出条件是 Draft 规范，未发现把 P1 写成已验收的结论。 | 保持原文；P0 未发布前不得据此宣称 P1 已启动。 |
| `03_AI_KP_QUALITY_RUBRIC.md` | 为评分口径，不含当前跑团得分或实测结论。 | 保持原文；尚未产生真人/Golden Run 评分。 |
| `04_PLAYTEST_PROTOCOL.md` | 为真人测试协议与模板，未包含已执行场次。 | 保持原文；真人测试仍待 P0 门禁通过后执行。 |
| `05_GLASS_RAIN_PLAYER_JOURNEY.md` | 原有“未提供 module/README/质量报告”和空 ID 占位已过期。 | 已回填静态模块字段，并保留运行时版本束与浏览器证据的待核验边界。 |
| `06_P1_IMPLEMENTATION_BACKLOG.md` | 依赖 P0 冻结，但原文未写当前 D19/D24/D25 缺口。 | 已增加前置状态快照，限制当前仅可推进 Wave 0 文档/测试准备。 |
| `99_参考_...v1.1.md` | 冻结决策基线。 | 已阅读用于对照；保持只读、不在本次改写。 |
| `MANIFEST.md` 与合订版 | 合订版 01 来源过期，Manifest 需在同步后重算尺寸/行数。 | 本次同步与最终完整性检查的对象。 |

### 当前直接证据

- Glass Rain 静态包：`module_id=golden-team-glass-rain`、`runtime_version=v2`、`session_mode=ai_only`、2–4 人、4 个场景、4 个 NPC、8 条线索（其中 3 条 core）、`glass-radio-recovery`、`glass-storm` 压力钟和 4 个互斥结局均已从 `module.json` 读取；README 与 `quality_report` 同时已读。
- P0 定向代码/测试：D01、D11、D12、D13/D14、D15、D18、D23 的测试证据已记录在 01 §3.1；关联后端回归为 `132 passed, 1 warning`，Trace/Retention 专项为 `17 passed, 1 warning`，前端 Vitest 为 55 个文件、217 项测试通过，生产构建通过。

### 仍然阻断 Release 的发现

1. D19 未满足冻结定义：当前 Session Zero 缺少服务端持久化的私密/公共投影实际探测证据，且缺勤策略未在开团时冻结。
2. D24/D25 尚无 30 场自动 Benchmark、至少 2 场真实浏览器 Golden Run、123 条 Requirement 的逐项证据矩阵和发布级指标。
3. 未进行 Prompt 深审、真实发布场景/编译包核验、全量回归或真人测试；这些不能由本次静态/定向证据补足。

---

## 1. Prompt 与 AI Contract

### 文件

- [ ] `kp_mcp_server/prompts/soul.md`
- [ ] `kp_mcp_server/prompts/rules.md`
- [ ] `kp_mcp_server/prompts/contract.md`
- [ ] `kp_mcp_server/kp_brain.py`
- [ ] `src/server/ai/contracts.py`
- [ ] `src/server/ai/director.py`
- [ ] `src/server/ai/narrator.py`
- [ ] `src/server/ai/gateway.py`
- [ ] `src/server/ai/mechanic_compiler.py`

### 核验

- [ ] AI 是否只输出建议，不写权威状态；
- [ ] 是否仍有 `host_exception` 路由；
- [ ] confidence 是否仍作为唯一门禁；
- [ ] Provider 全失败是否仍返回空 dict；
- [ ] Prompt 是否要求未编译事实、技能或线索自由补全；
- [ ] `soul.md` 是否覆盖玩家主动权、失败推进、节奏和聚光灯；
- [ ] `rules.md` 是否错误承担了 RuleExecutor 职责；
- [ ] `contract.md` 是否包含 confirmation/choice/consent、风险、失败推进和 fact_ref；
- [ ] DTO 与 JSON Schema 是否可自动校验；
- [ ] Prompt bundle 是否有版本并进入房间版本束；
- [ ] 正例、反例和 fallback 测试是否存在。

### 输出

```text
PROMPT_REVIEW_REPORT.md
PROMPT_REQUIREMENT_TRACEABILITY.csv
prompt_bundle_version
```

---

## 2. P0 运行时与权限

### 文件/模块

- [ ] Room / auth / owner / stage 路由
- [ ] `engine/action_state.py`
- [ ] `engine/action_lifecycle.py`
- [ ] `engine/resolution_pipeline.py`
- [ ] `engine/state_service.py`
- [ ] `engine/action_consent.py`
- [ ] `engine/risk_contract.py`
- [ ] `engine/compensation_service.py`
- [ ] `engine/roll_receipt.py`
- [ ] `engine/runtime_integrity.py`
- [ ] `turn_manager.py`
- [ ] `turn_timeout_worker.py`
- [ ] WebSocket connection manager
- [ ] 数据库 migration/schema

### 核验

- [ ] RoomOwner / StageClient / LegacyHostAdjudicator 是否真正分权；
- [ ] 旧 Host API 是否服务端拒绝；
- [ ] 自动调度是否唯一；
- [ ] action/room/outcome/campaign 状态是否正交；
- [ ] technical retry 是否复用回执和事务；
- [ ] review 是否自动化并追加补偿；
- [ ] 缺勤是否不由 AI 代玩；
- [ ] 恢复方案是否系统确定；
- [ ] soft/emergency pause 是否有阶段游标；
- [ ] session_mode 和版本束是否冻结；
- [ ] Admin patch 是否被拒绝；
- [ ] Trace/retention/permission 是否符合 D23。

### 输出

```text
P0_IMPLEMENTATION_DIFF_REPORT.md
DATABASE_MIGRATION_REPORT.md
API_COMPATIBILITY_MATRIX.md
```

---

## 3. Glass Rain 运行包

### 文件

- [ ] `data/golden_modules/02-short-team-glass-rain/module.json`
- [ ] 模组 README
- [ ] quality_report
- [ ] character templates
- [ ] 编译后的 runtime package
- [ ] 运行包 Schema

### 必须提取

```yaml
scenario:
  scenario_id:
  session_mode:
  runtime_version:
  player_range:
  entry_scene_id:
scenes:
  - scene_id:
    importance:
    purpose:
    entry_conditions:
    exit_conditions:
    pressure_clock:
    escalation_events:
    improv_boundaries:
npcs:
  - npc_id:
    importance:
    goals:
    knowledge_fact_refs:
    secret_fact_refs:
    fears:
    attitude:
    reaction_rules:
    improv_boundaries:
clues:
  - clue_id:
    importance:
    reveal_conditions:
    alternative_sources:
    recovery_node_id:
endings:
  - ending_id:
    priority:
    mutual_exclusion_group:
    conditions:
```

### 核验

- [ ] 每个 core clue 满足 D20；
- [ ] 主要 scene/NPC 满足 D21 或合法 exemption；
- [ ] ending 满足 D22；
- [ ] 不依赖 `raw_text` 补核心运行字段；
- [ ] 风险合同与 consent 场景明确；
- [ ] 至少一条普通失败推进路径；
- [ ] 至少一个可测试的停滞/升压事件；
- [ ] 结局可由 Engine 确定性计算；
- [ ] Golden Run 所需角色和人数覆盖 2–4 人。

### 输出

```text
GLASS_RAIN_RUNTIME_AUDIT.md
GLASS_RAIN_FIELD_MATRIX.csv
GLASS_RAIN_BLOCKERS.md
```

---

## 4. 前端实物

### 文件

- [ ] `PlayerActionPage.tsx`
- [ ] `PlayerActionComposer.tsx`
- [ ] `PlayerTerminal.tsx`
- [ ] `PlayerLobby.tsx`
- [ ] `PlayerJoinPage.tsx`
- [ ] `HostStage.tsx` / 后续 StageClient 页面
- [ ] `HostLobby.tsx` / 后续 RoomOwner 页面
- [ ] `types.ts`
- [ ] `api.ts`
- [ ] `ws.ts`
- [ ] navigation / route definitions
- [ ] 现有前端测试

### 核验

- [ ] 页面是否仍以 Host 概念混合 Owner/Stage/Adjudicator；
- [ ] action 是否总要求 confirmation；
- [ ] 结果是否只显示叙事；
- [ ] 是否展示等待原因；
- [ ] 私密/公共/OOC/系统是否分层；
- [ ] reconnect 是否恢复 pending action；
- [ ] Session Zero 是否真实逐项显示；
- [ ] Stage 是否持有 owner token；
- [ ] UI 是否使用旧 `resolved` 等状态；
- [ ] 关键页面是否有组件测试和浏览器 E2E。

### 输出

```text
P1_UI_GAP_ANALYSIS.md
FRONTEND_STATE_MATRIX.md
DTO_UI_MAPPING.md
```

---

## 5. 测试与证据

### 文件/脚本

- [ ] `tests/server/`
- [ ] `src/client/tests/`
- [ ] `scripts/run_golden_module_suite.py`
- [ ] `scripts/run_multiplayer_loop.py`
- [ ] 任何 AI-only acceptance / benchmark 脚本
- [ ] 现有验收报告目录

### 核验

- [ ] 123 条 AIO Requirement 是否全部有测试映射；
- [ ] 是否有并发/幂等/故障注入；
- [ ] 是否有权限和安全测试；
- [ ] 是否有真实浏览器 E2E；
- [ ] 是否记录版本束和随机种子；
- [ ] 是否能输出 per-session 与 summary 指标；
- [ ] 是否区分被人工污染/中止场次；
- [ ] 是否有 Trace 完整率检查；
- [ ] 是否能复现失败场次。

### 输出

```text
REQUIREMENT_TEST_MATRIX.csv
P0_TEST_GAP_REPORT.md
BENCHMARK_REPRODUCIBILITY_REPORT.md
```

---

## 6. 核验问题记录模板

```yaml
repository_finding:
  finding_id:
  source_file:
  line_or_symbol:
  related_requirement_ids: []
  expected_by_spec:
  actual_behavior:
  severity: blocker | critical | major | minor
  affected_work_packages: []
  proposed_fix:
  required_tests: []
  owner:
  status:
```

---

## 7. 核验完成定义

- [ ] 所有清单文件已读取实际内容；
- [ ] 每个“已具备”声明都有代码/Schema/测试证据；
- [ ] 所有差异进入 finding 清单；
- [ ] Blocker/Critical 有明确修复责任人；
- [ ] P0 Release Checklist 更新；
- [ ] P1 Spec 中不再保留关键未知字段；
- [ ] Glass Rain Player Journey 已回填真实 scene/NPC/clue/ending ID；
- [ ] 所有报告记录 commit 和版本束。
