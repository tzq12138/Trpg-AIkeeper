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
