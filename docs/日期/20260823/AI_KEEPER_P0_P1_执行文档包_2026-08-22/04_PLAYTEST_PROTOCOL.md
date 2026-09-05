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
