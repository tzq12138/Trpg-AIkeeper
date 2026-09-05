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
