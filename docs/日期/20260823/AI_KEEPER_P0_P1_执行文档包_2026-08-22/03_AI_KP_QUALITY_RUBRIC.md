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
