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
