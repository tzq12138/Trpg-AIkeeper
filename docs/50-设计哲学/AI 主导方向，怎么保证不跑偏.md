
这是整个产品最核心、也最危险的一层。

如果处理不好，AI-Keeper 会从“辅助主持”变成：

```text
AI 自己编剧情
AI 自己决定玩家该去哪
AI 自己补真相
AI 自己制造关键线索
AI 自己宣布高潮
```

最后玩家只是被 AI 推着看故事。

所以第一原则应该是：

> **固定真相，开放路径；玩家决定行动方向，AI 只决定世界如何在既有规则内回应。**

你们现有文档已经把 AI 限制在建议层，把权威规则、状态写入、事务提交、投影安全和模组运行态分别交给 Rule、State、Transaction、Projection、Module；这正好可以作为方向控制的底座。

我建议新增一套跨模块协议：

# **Narrative Governor / 叙事方向控制器**

它不负责直接写剧情，也不负责生成最终叙事。

它只负责回答：

```text
当前故事正在解决什么问题？
玩家现在主动选择了什么目标？
世界中哪些力量正在行动？
当前有哪些合法的下一步方向？
哪些方向不能走？
这个方向是否需要 Host 批准？
```

---

# 一、先定义“谁能决定什么”

这是防止跑偏的根本。

|内容|谁决定|
|---|---|
|世界真相|ModuleVersion、Host 正式修订|
|规则结果|RuleExecutor|
|当前世界状态|State / Transaction|
|玩家角色做什么|玩家|
|玩家当前目标|玩家或 Party 明确确认|
|NPC 如何回应|AI 在 NPC Agenda 约束内建议|
|世界压力如何推进|Clock / Trigger / State 规则|
|场景如何表现|AI Narrator|
|是否揭示核心线索|RevealGate + Rule/State|
|是否发生重大不可逆事件|Host 或预先确认的规则|
|故事最终走向|玩家选择 + 世界后果，而不是 AI 单方面决定|

最重要的三条：

```text
AI 不能替玩家选择目标。
AI 不能替规则决定结果。
AI 不能替模组创造真相。
```

AI 可以主导的是：

```text
组织节奏
呈现机会
推动世界回应
管理 NPC 行动
维护未解决线程
在玩家卡住时提供不剧透的推动
```

---

# 二、不要用“一条剧情主线”，要用“方向包络”

错误思路：

```text
场景 A
→ 必须去场景 B
→ 必须找到线索 C
→ 必须见 NPC D
→ 进入结局 E
```

这一定会铁路化。

正确思路是：

# **Narrative Envelope / 叙事方向包络**

固定的是：

```text
世界真相
人物目标
规则边界
关键因果
可揭示内容
结局成立条件
```

可以变化的是：

```text
场景顺序
调查路径
与谁合作
从哪里获得证据
冲突何时发生
NPC 如何调整计划
玩家如何解决问题
```

由玩家决定的是：

```text
追哪条线
相信谁
冒什么风险
选择什么方法
是否放弃某个目标
最终站在哪一边
```

一句话：

> **不是让 AI 把玩家带回作者写好的路，而是让世界对玩家选择作出一致回应。**

---

# 三、模组导入时，要多编译一层“方向 IR”

前面我们讨论了 Module Compiler。

除了 Scene、NPC、Clue、Rule、Trigger，还要编译一套：

# **Narrative Direction IR**

至少包含以下对象。

## 1. `CampaignPromise`

这场模组承诺给玩家什么体验：

```text
类型：调查恐怖
核心体验：在医院失踪案中辨别互相矛盾的证词
主题：记忆、信任、伦理
节奏：慢调查 -> 压力升级 -> 最终抉择
禁止偏移：不要变成纯战斗地城
```

它不是剧情答案，而是产品方向。

---

## 2. `StoryThread`

一条可以被玩家推进、暂停或放弃的故事线程。

```json
{
  "threadId": "thread:missing_patients",
  "safeLabel": "失踪病人调查",
  "dramaticQuestion": "病人失踪与医院地下区域有什么关系？",
  "status": "active",
  "importance": "core",
  "entryConditions": [],
  "closureConditions": [],
  "relatedEntityRefs": [
    "location:hospital",
    "npc:head_nurse"
  ],
  "sourceRefs": []
}
```

注意：

```text
dramaticQuestion 是问题
不是答案
```

---

## 3. `BeatTemplate`

Beat 不是固定场景，而是一种可发生的推进单位。

```json
{
  "beatId": "beat:conflicting_testimony",
  "threadId": "thread:missing_patients",
  "purpose": "让玩家意识到证词存在矛盾",
  "preconditions": [
    "party_knows:nurse_testimony",
    "party_knows:professor_basement_observation"
  ],
  "playerOpportunity": "比较两条证词",
  "allowedRevealRefs": [],
  "forbiddenClaims": [
    "nurse_is_lying",
    "professor_true_motive"
  ],
  "possibleTransitions": [
    "thread:verify_nurse_alibi",
    "thread:investigate_basement"
  ]
}
```

这里定义的是：

> 玩家可以意识到信息冲突。

而不是：

> AI 告诉玩家护士在撒谎。

---

## 4. `NpcAgenda`

NPC 不能被 AI 每次临时现编动机。

```json
{
  "npcRef": "npc:head_nurse",
  "publicRole": "夜班护士",
  "currentGoal": "避免医院丑闻扩大",
  "allowedMethods": [
    "回避问题",
    "转移话题",
    "请求玩家离开"
  ],
  "forbiddenBehaviors": [
    "主动透露地下室真相",
    "无条件攻击玩家"
  ],
  "escalationClockRef": "clock:hospital_lockdown"
}
```

AI 可以在这里选择：

```text
回避
拖延
警告
寻求帮助
```

但不能突然让她：

```text
承认所有秘密
掏枪杀人
变成幕后主使
```

除非模组和状态允许。

---

## 5. `WorldClock`

世界压力不能靠 AI 心情推进。

```json
{
  "clockId": "clock:hospital_lockdown",
  "segments": 6,
  "current": 1,
  "advanceConditions": [
    "players_cause_public_disturbance",
    "game_time_after:23:00",
    "security_warned_twice"
  ],
  "thresholdEffects": {
    "3": "security_patrol_increases",
    "6": "hospital_lockdown"
  }
}
```

Clock 的推进必须来自：

```text
玩家行为
游戏内时间
已经确认的世界事件
显式 Trigger
```

不是：

> AI 觉得现在该紧张了。

---

## 6. `RevealGate`

每个关键线索必须有揭示门槛。

```json
{
  "gateId": "gate:basement_key",
  "revealRef": "clue:brass_key",
  "eligiblePaths": [
    "successful_search:director_desk",
    "npc_share:assistant_director",
    "host_authorized_fallback"
  ],
  "minimumEvidence": 1,
  "visibility": "player_private_then_shareable"
}
```

AI 可以选择合法路径之一。

不能因为玩家卡住就：

```text
让钥匙从天花板掉下来
```

---

## 7. `ChoicePoint`

```json
{
  "choicePointId": "choice:expose_or_conceal",
  "question": "是否公开医院实验记录？",
  "optionsArePlayerAuthored": true,
  "irreversible": true,
  "requiresExplicitPartyDecision": true
}
```

ChoicePoint 只定义：

```text
这里存在一个重大选择
```

不能让 AI替玩家选择。

---

# 四、运行时需要一份 Direction Snapshot

模组 Direction IR 是模板。

房间运行中要生成：

# **DirectionSnapshot / 当前方向快照**

```json
{
  "roomId": "room_xxx",
  "moduleVersionId": "mod_hospital@1.2.0",
  "branchId": "branch_main",
  "currentSceneRef": "scene:archive_room",
  "currentDramaticQuestion": "地下脚步声来自谁？",

  "partyGoal": {
    "goal": "确认失踪病人的共同点",
    "confirmedAtSequence": 810
  },

  "activeThreads": [
    "thread:missing_patients",
    "thread:nurse_alibi"
  ],

  "pausedThreads": [
    "thread:old_ring"
  ],

  "openQuestions": [
    "护士为什么否认教授进入地下室？"
  ],

  "eligibleDirectionMoves": [],
  "blockedDirectionMoves": [],

  "pacing": {
    "tension": 0.55,
    "sceneActionCount": 8,
    "newEvidenceCount": 1,
    "stalled": false
  },

  "spotlight": {
    "char_a": 0.31,
    "char_b": 0.24,
    "char_c": 0.45
  },

  "improvisationBudget": "low",
  "stateVersion": 84,
  "lastEventSequence": 917
}
```

这份 Snapshot 是派生视图，不是世界真相。

它可以重建，不能反向替代 State。

---

# 五、AI 主导方向时，必须经过七步控制循环

```text
已确认玩家行动
        ↓
1. 读取已提交世界状态
        ↓
2. 判断玩家当前选择的方向
        ↓
3. 找出所有合法 Direction Move
        ↓
4. 硬约束过滤
        ↓
5. 软目标排序
        ↓
6. 审批 / 自动执行
        ↓
7. 通过 Rule / State / Transaction 落地
```

AI 只是其中的候选生成器和排序助手。

---

## 第一步：只能读取已提交状态

方向 AI 只能使用：

```text
当前 ModuleVersion
当前 branch
AppliedState
Journal 已发生事件
当前 NPC Agenda
当前 Clock
玩家已确认目标
```

不能使用：

```text
尚未提交的 AI 草稿
失败的事务
未触发线索
其他历史分支
玩家未确认的讨论
```

---

## 第二步：确认“玩家在往哪走”

系统需要从玩家行为中提取：

# `PlayerVector`

```text
当前目标
当前方法
当前优先级
主动避开的方向
接受的风险
是否希望继续调查/逃离/谈判/战斗
```

例如玩家说：

> “我们暂时不去地下室，先查护士昨晚的行踪。”

系统应记录：

```text
partyGoal = 验证护士不在场证明
deprioritizedThread = 地下室探索
```

然后 AI 就不能下一回合强行：

> 地下室突然传来巨响，所有出口关闭，你们只能下去。

除非已有 Clock 或 Trigger 支持。

---

## 第三步：生成合法 Direction Move

建议只允许这些标准类型：

```text
respond_to_player_goal
advance_npc_agenda
advance_world_clock
surface_available_evidence
offer_meaningful_choice
apply_consequence
shift_spotlight
increase_pressure
decrease_pressure
reframe_open_question
close_resolved_thread
recap_and_reorient
stall_recovery
scene_transition
```

AI 不可以输出自由文字：

> 下一步让教授出现并承认罪行。

而要输出结构化候选：

```json
{
  "moveType": "advance_npc_agenda",
  "npcRef": "npc:head_nurse",
  "agendaAction": "request_security_assistance",
  "basisRefs": [
    "event:915",
    "clock:hospital_lockdown"
  ],
  "impactLevel": "medium"
}
```

---

# 六、硬约束必须先过滤，评分不能覆盖硬规则

不能只做：

```text
给候选打分，最高分执行
```

因为一个剧透候选即使分数很高也不能执行。

正确顺序：

```text
Hard Filter
    ↓
Soft Ranking
```

## 硬约束

任何候选只要违反一项，直接拒绝：

```text
不符合当前 ModuleVersion
引用不存在的实体
违反当前 State
读取错误历史分支
泄露未解锁真相
替玩家作出决定
跳过 RevealGate
绕过 Rule
绕过 Transaction
修改 Module 模板
违反 Safety
超过 AI 自治级别
制造未经允许的永久 Canon
```

你们现有 Safety 和 Projection 已经要求实时、重连、归档、导出复用统一的可见性边界；方向提案也应在生成后进入同一套安全体系。

---

# 七、通过硬过滤后，再做多目标排序

排序不应该只看：

```text
是否接近主线
```

建议排序考虑：

|维度|含义|
|---|---|
|玩家目标契合|是否回应玩家当前主动选择|
|连续性|是否延续已发生事件|
|证据成熟度|是否达到揭示条件|
|世界一致性|是否符合 NPC Agenda、Clock、State|
|玩家自主性|是否提供选择而非强迫|
|节奏需要|当前是否卡住、过快或过慢|
|聚光公平|是否长期忽略某名玩家|
|模组体验|是否仍符合 CampaignPromise|
|新鲜度|是否反复使用同一种推动方式|
|风险|是否可能造成剧透、误伤或不可逆变化|

可以有一个示意评分：

```text
方向分 =
玩家目标契合
+ 线程连续性
+ 证据成熟度
+ 节奏适配
+ 聚光公平
+ 模组体验
- 剧透风险
- 铁路化风险
- 重复风险
- Canon 风险
```

但必须明确：

> **任何软分数都不能越过硬约束。**

---

# 八、AI 要“提供压力和机会”，不能“命令玩家”

建议采用：

# **Offer–Pressure–Consequence**

## Offer：提供机会

```text
护士今晚会换班
档案室暂时无人
教授愿意谈话
地图上出现一条可探索路线
```

## Pressure：世界施加压力

```text
警戒 Clock 推进
NPC 开始销毁证据
天色变暗
医院即将封锁
```

## Consequence：回应玩家已经做出的选择

```text
他们制造噪音，所以保安来了
他们拖延太久，所以 NPC 改变位置
他们公开指控，所以关系恶化
```

AI 不应该：

```text
把角色移动到某处
替角色接受交易
替 Party 决定追谁
替玩家公开私密线索
替玩家使用资源
```

最简单的产品原则：

> **AI 可以移动世界，不能移动玩家的意志。**

---

# 九、方向自动化必须分等级

建议为每个房间提供：

```text
Host 主导
AI 协助
AI 代理
Host 离线辅助
```

但底层统一使用权限矩阵。

|方向动作|自动执行|需通知 Host|必须 Host 确认|永不允许 AI|
|---|--:|--:|--:|--:|
|生成 recap|是||||
|询问玩家目标|是||||
|提醒开放问题|是||||
|重述已知线索|是||||
|NPC 低影响反应|是||||
|感官环境描述|是||||
|切换到玩家明确前往的场景|是|可选|||
|推进非关键 Clock||是|||
|揭示已满足 Gate 的普通线索||是|视房间策略||
|引入持久 NPC|||是||
|创建新持久地点|||是||
|大幅时间跳跃|||是||
|重大资源损失|||是||
|核心线索揭示|||是或预授权||
|角色死亡/退役|||是||
|改写 Module 真相||||永不允许|
|替玩家作出选择||||永不允许|
|静默 Retcon||||永不允许|
|绕过 Rule/State||||永不允许|

---

# 十、必须把“导演 AI”和“叙事 AI”分开

这是非常重要的架构。

## Director AI

可以读取 Host 级结构化信息：

```text
StoryThread
NpcAgenda
WorldClock
RevealGate
EndingCondition
当前 State
```

但它只能输出：

```text
DirectionProposal
```

不能直接输出给玩家看的叙事。

## Narrator AI

只接收：

```text
已经批准的 Direction Move
已提交的 State
allowedFacts
当前玩家可见内容
```

它负责生成玩家叙事。

不能读取：

```text
完整 ending
完整 truth
未解锁 clue
Director 的全部秘密理由
```

流程：

```text
Director Context
      ↓
Director AI
      ↓
DirectionProposal
      ↓
Policy Engine / Host Gate
      ↓
Rule / State / Transaction
      ↓
AllowedFacts
      ↓
Narrator AI
      ↓
SpoilerGuard
      ↓
Projection
```

即使使用同一个模型 Provider，也必须是两个独立请求、两个独立上下文、两个独立 Schema。

> **规划模型知道真相，但不能直接说话；说话模型只能看到允许说的事实。**

---

# 十一、DirectionProposal 必须是结构化对象

```json
{
  "proposalId": "dir_102",
  "roomId": "room_xxx",
  "stateVersion": 84,
  "eventSequence": 917,

  "currentQuestion": "护士的不在场证明是否可信？",
  "targetThreadRef": "thread:nurse_alibi",
  "moveType": "advance_npc_agenda",

  "basisRefs": [
    "event:915",
    "npc_agenda:head_nurse",
    "clock:hospital_lockdown"
  ],

  "preconditions": [
    "players_questioned_nurse_twice"
  ],

  "worldResponse": {
    "type": "npc_requests_security"
  },

  "playerOpportunity": "玩家可以继续追问、离开或公开质疑",

  "allowedFactRefs": [
    "fact:nurse_is_under_pressure"
  ],

  "forbiddenClaims": [
    "nurse_is_lying",
    "nurse_true_motive"
  ],

  "impactLevel": "medium",
  "approvalMode": "auto_with_host_notice",
  "expiresAfterSequence": 925
}
```

AI 输出的 Proposal 不是事件，也不是 State。

必须经过验证后才能形成实际结果。

---

# 十二、AI 主导方向不能直接写状态

方向 Proposal 可以建议：

```text
NPC 想要叫保安
Clock 可能推进
场景可能切换
```

但必须分别进入：

```text
NPC 行为 -> Rule / NPC Service
Clock 变化 -> StateService
场景切换 -> State / Map
叙事 -> Projection
日志 -> Journal
```

你们现有 Transaction 文档已经要求“先 State、后 Projection”，并且 AI 的 ResolutionResult 也不等于已落库事实；方向控制必须完全继承这条原则。

---

# 十三、玩家跑到模组外时怎么处理

这是最容易跑偏的情况。

例如模组发生在医院，但玩家突然决定：

> “我们去火车站调查。”

不能简单：

```text
强行让所有线索都指回医院
```

也不能：

```text
AI 临时编一个火车站邪教据点
```

建议引入：

# **Improvisation Budget / 即兴预算**

## Level 0：装饰性即兴

可以自动：

```text
路人姓名
天气
普通店铺
场景气味
无长期影响的小细节
```

## Level 1：可逆局部即兴

可自动或通知 Host：

```text
普通服务员
临时交通阻碍
没有核心信息的小场景
```

这些对象标记：

```text
room_scoped
non_canonical
reversible
```

## Level 2：持久房间 Canon

必须 Host 确认：

```text
新持久 NPC
新重要地点
新组织关系
新关键物品
```

## Level 3：Module Canon

AI 永远不能自动创建或修改：

```text
真凶
核心动机
结局条件
主要历史
原模组因果
```

---

# 十四、玩家偏航时，不要“拉回主线”，要让世界给出真实结果

玩家去火车站时，系统应判断：

```text
当前有没有已知证据支持火车站？
是否有模块实体或线程关联？
是否只是玩家假说？
```

## 有关联

正常生成相关场景。

## 无关联，但可安全即兴

允许玩家调查，可能获得：

```text
没有发现支持证据
普通环境信息
与当前假说相关的否定证据
```

## 会制造重大新 Canon

暂停：

> 这一方向将需要创建新的持久剧情内容。当前 AI 可继续提供非关键场景，重大剧情推进需等待 Host 确认。

这样不会铁路化，也不会无限乱编。

---

# 十五、玩家卡住时要有“推动阶梯”，不能直接塞答案

建议按以下顺序逐级处理。

## Level 1：重新定向

```text
总结当前目标
列出开放问题
提醒已经知道的事实
```

## Level 2：质询

```text
哪条证词还没有被验证？
你们是否检查过时间上的冲突？
哪件物品尚未确认用途？
```

## Level 3：重新呈现已有机会

```text
NPC 再次出现
之前开放的地点重新可访问
已知线索从另一个角度被提及
```

注意：

```text
只能重新呈现已存在机会
不能创造答案
```

## Level 4：推进世界压力

```text
非关键 Clock 推进
NPC 执行既定 Agenda
环境发生合理变化
```

## Level 5：合法备用线索路径

只有 RevealGate 预先允许时，才可使用：

```text
另一名 NPC 提供安全版本
同一线索从另一场景出现
失败前进机制
```

## Level 6：暂停等待 Host

如果核心推进仍需要创造新 Canon：

```text
生成 Host Review Packet
不继续擅自编写
```

---

# 十六、Host 不在线时，AI 能做什么

Host 不在线模式不能等于：

```text
AI 全权主持
```

更合理的是：

# **Facilitator Mode / 辅助主持模式**

允许：

```text
规则查询
角色卡说明
剧情回顾
调查工作台整理
玩家讨论
低影响 NPC 对话
已批准场景探索
已批准普通检定
已满足 Gate 的普通线索
低风险 Clock
```

不允许自动：

```text
核心真相揭示
不可逆角色状态
重大 NPC 死亡
新持久 Canon
结局推进
关键阵营变化
重大时间跳跃
Retcon
```

遇到这些情况：

```text
Direction Gate = host_required
```

系统保存：

# `HostReviewPacket`

```text
玩家做了什么
当前 State
候选方向
涉及哪些隐藏内容
为什么需要 Host
如果等待，玩家还能进行哪些安全活动
```

玩家端看到：

> 当前行动已推进到需要主持确认的重要节点。  
> 在 Host 返回前，你们仍可以整理线索、讨论方案、查询规则和处理低风险行动。

---

# 十七、方向性还要防止“AI自己陷入循环”

常见循环：

```text
反复提醒同一条线索
反复让 NPC 回避
反复制造敲门声
反复说“气氛越来越紧张”
反复让玩家做同一种检定
```

需要记录：

```text
lastDirectionMoves
lastNpcResponses
lastEvidenceSurfaces
lastSceneTransitions
lastSpotlightTargets
```

并设置：

```text
repetitionPenalty
cooldown
maxSameMovePerScene
```

例如：

```text
同一 NPC 连续两次回避后
第三次必须：
- 升级 Agenda
- 明确拒绝
- 离开场景
- 请求援助
```

不能继续生成同义句。

---

# 十八、还要控制聚光灯偏差

AI 很容易持续回应：

```text
输入最多的人
角色技能最强的人
剧情关联最多的人
```

最终冷落安静玩家。

建议维护：

# `SpotlightLedger`

记录每个角色最近：

```text
主动行动次数
收到私人结果次数
获得关键选择次数
与 NPC 互动次数
获得线索次数
叙事篇幅
```

AI 可以在不违背剧情的前提下：

```text
给长期缺少聚光的角色一个可回应机会
```

但不能为了平衡，凭空给他关键线索。

更适合的方式：

```text
NPC 向他提问
环境首先被他注意到
其背景提供一个非关键关联
给他一个方法选择
```

---

# 十九、方向控制需要“场景结束检查点”

每个场景结束后生成：

# `DirectionCheckpoint`

```text
玩家在本场选择了什么
世界发生了什么
哪些线程推进
哪些线程暂停
哪些 Clock 变化
哪些问题仍未解决
下一个合法方向有哪些
哪些方向需要 Host
哪些内容不能在下一场揭示
```

它不是剧情总结，而是方向控制状态。

下一场 AI 只能基于最新 Checkpoint 和 State 继续。

---

# 二十、玩家要能明确表达“我们不想走这条方向”

建议提供：

```text
设为当前队伍目标
暂时搁置这条线
我们不想继续这个方向
降低恐怖强度
返回上一开放问题
请求 Host 复核
```

这些操作只改变：

```text
Party Goal
Thread Priority
Pacing Preference
```

不改变世界真相。

例如玩家点击：

> 暂时搁置“地下室探索”。

AI 后续仍可以让地下室相关 Clock 合理推进，但不能每轮强行把玩家送回地下室。

---

# 二十一、产品界面要让方向可感知，但不能剧透

玩家端可以显示：

## 当前目标

```text
验证护士昨晚的行踪
```

## 当前开放问题

```text
护士为什么否认教授进入地下室？
旧钥匙对应哪扇门？
```

## 当前世界压力

不显示隐藏 Clock 数值，可以显示安全表现：

```text
医院警戒正在提高
距离换班时间不多了
```

## 可以继续处理

```text
核对时间记录
询问另一名护士
检查员工签到表
暂时调查别的线索
```

这些是：

```text
已有机会
```

不是：

```text
AI 推荐的唯一正确路线
```

---

# 二十二、Host 端要有 Direction Console

Host 不需要每次亲自导演，但需要能看懂 AI 为什么这么推进。

建议显示：

```text
当前玩家目标
当前活跃线程
NPC Agenda
World Clock
上一条 Direction Move
下一步候选方向
风险等级
自动/需批准
来源引用
```

Host 可以：

```text
批准
拒绝
修改
暂停 AI 方向控制
降低自治等级
锁定某条线程
禁止某个 Move 类型
```

不能直接让 Host 在这个界面改写 State。

修改仍应形成：

```text
DirectionPolicyChanged
actor
reason
before
after
```

---

# 二十三、建议的数据对象

```text
CampaignDirectionPolicy
CampaignPromise
StoryThreadTemplate
StoryThreadRuntime
BeatTemplate
SceneAgenda
NpcAgenda
WorldClock
RevealGate
ChoicePoint
PlayerVector
DirectionSnapshot
DirectionMoveCandidate
DirectionDecision
ImprovisationProposal
DirectionCheckpoint
HostReviewPacket
SpotlightLedger
```

其中：

```text
Module 层：
CampaignPromise
StoryThreadTemplate
BeatTemplate
NpcAgenda
RevealGate

Room 层：
StoryThreadRuntime
WorldClock
PlayerVector
DirectionSnapshot
DirectionCheckpoint
```

运行态不能反写 Module 模板。这个边界与你们现有 Module 文档保持一致。

---

# 二十四、工程流程建议

```text
PlayerIntent
    ↓
Rule / Resolution
    ↓
State Commit
    ↓
DirectionEvaluator
    ↓
DirectionMoveCandidates
    ↓
Hard Policy Filter
    ↓
Soft Ranker
    ↓
DirectionDecision
    ↓
Auto / Host Gate
    ↓
Rule / State / Transaction
    ↓
Narrator Context
    ↓
Narrative
    ↓
Safety / Projection / Journal
```

注意：

> DirectionEvaluator 必须在当前行动的 State 已提交之后运行。

否则它会基于尚未成立的结果决定下一步。

---

# 二十五、P0 应该做到什么

|P0 功能|原因|
|---|---|
|CampaignPromise|防止类型和主题漂移|
|StoryThread|防止主线变成单路径|
|NpcAgenda|防止 NPC 性格和目标漂移|
|WorldClock|防止 AI 随意升级压力|
|RevealGate|防止随意塞线索|
|PlayerVector|尊重玩家主动目标|
|DirectionMove Schema|不允许自由文字直接执行|
|Hard Policy Filter|安全和 Canon 底线|
|AI 自治等级|限制自动化范围|
|Director / Narrator 分离|规划知道真相，叙事不泄露|
|HostReviewPacket|Host 不在线时安全暂停|
|Improvisation Budget|控制模组外即兴|
|DirectionCheckpoint|防止跨场景漂移|
|审计链|能解释 AI 为什么推进|

---

# 二十六、P1 再做

```text
动态节奏检测
SpotlightLedger
多线程自动优先级
卡局检测与推动阶梯
复杂 Faction Clock
多人目标冲突
跨 Session 方向摘要
AI 方向质量评分
Host 一键修正 Direction Snapshot
不同模组类型的方向模板
```

---

# 二十七、明确禁止的实现方式

```text
把完整模组全文直接给一个 AI，让它决定下一步
让 AI 同时负责规划和玩家叙事
用“接近结局程度”给方向评分
让 AI根据隐藏真相排序最重要线索
让 AI替玩家选目标
玩家偏航时强行制造事件拉回主线
玩家卡住时直接生成核心线索
AI 自行创建永久 NPC、地点和组织
AI 自行推进重大 Clock
AI 自行选择结局
AI 叙事直接写 State
Host 不在线时默认全自动主持
AI 生成失败后换一个模型继续乱猜
```

---

# 二十八、最关键的工程测试

```text
1. AI 不能替玩家设置 Party Goal。
2. 玩家明确搁置的线程不会被连续强推。
3. DirectionProposal 不能直接写 State。
4. Proposal 引用的实体必须存在于当前 ModuleVersion 或 Room Canon。
5. 未满足 RevealGate 的线索不能被揭示。
6. Director 输出不能直接发给 Player。
7. Narrator Context 不含完整 truth 和 ending。
8. AI 不得控制玩家角色的行动、思想和选择。
9. 玩家偏航时不会自动生成重大新 Canon。
10. 低置信度即兴只能成为 reversible room-scoped 内容。
11. Host 不在线遇到 major gate 时必须暂停。
12. Clock 只能在满足 condition 时推进。
13. NPC 行为不能超出 Agenda。
14. State 未提交时不能计算下一方向。
15. Restore 后只使用当前 branch 的 DirectionSnapshot。
16. 相同 Move 连续重复超过阈值时被拒绝。
17. Spotlight 调整不能凭空发关键线索。
18. Safety 拒绝的 Proposal 不能通过高分绕过。
19. DirectionCheckpoint 能追溯 basisRefs、stateVersion、eventSequence。
20. Module 更新不会改变 active room 的方向模板版本。
```

---

# 二十九、衡量 AI 有没有跑偏

不要只看：

```text
玩家是否推进到结局
```

建议看：

|指标|目标|
|---|---|
|无来源持久事实|0|
|AI 修改 Module Canon|0|
|未满足 Gate 的线索揭示|0|
|Host-only 真相泄露|0|
|AI 替玩家作出决定|0|
|Host 推翻重大 DirectionProposal 比例|持续下降|
|玩家“被强推剧情”的反馈|持续下降|
|玩家主动目标被回应比例|持续提高|
|同类方向 Move 重复率|持续下降|
|卡局后恢复成功率|持续提高|
|Host 离线时 major gate 自动越过|0|
|不同玩家聚光差异|控制在合理范围|
|Off-module 即兴转成错误 Canon|0|

---

# 最终收敛

AI 主导方向不能理解为：

> AI 决定故事接下来发生什么。

更准确的定义是：

> **玩家决定想做什么；模组和世界状态决定什么是可能的；AI 在这些边界内选择合理的世界回应、节奏和机会；规则与状态系统决定结果；重要且不可逆的方向变化必须经过 Host 或预先授权的 Gate。**

最终产品定义可以是：

> **AI-Keeper 使用叙事方向控制器维护 CampaignPromise、StoryThread、NPC Agenda、WorldClock、RevealGate 和玩家当前目标；AI 只能从合法 Direction Move 中提出或执行世界回应，不能替玩家选择、不能创造未经确认的真相、不能绕过规则与状态。规划层和叙事层严格分离，重大节点自动停在 Host Review Gate，因此 AI 可以主动维持故事运转，但不会把战役带离模组、玩家选择和既有因果。**