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
