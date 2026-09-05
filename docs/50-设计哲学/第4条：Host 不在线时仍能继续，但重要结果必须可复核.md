

这一条最容易被误解成：

> “Host 不在，AI 就自动接管主持。”

这不是我们要做的。

真正应该定义成：

> **Host 暂时缺席时，玩家拥有的决定、确定性的规则结算和低风险世界响应可以继续；涉及不可逆信息、重大世界变化、核心剧情方向和规则歧义的结果自动停在复核闸门。Host 回来后看到的是结构化差异和证据包，而不是重新阅读几十页聊天记录。**

我建议把这项能力命名为：

# **受监督自治与延迟复核**

英文可以叫：

```text
Supervised Autonomy
Deferred Authority Protocol
Host-Optional Continuity
```

一句产品话术：

> **Host 可以暂时离开，但桌面不会立刻停摆；AI 只处理被授权的常规事务，重要结果会等待复核。**

再简洁一点：

> **小事继续，大事等审，所有结果有据可查。**

---

# 一、先把最关键的问题说清楚：Host 不在线，不等于 Host 权限转交给 AI

你们当前文档已经明确：

- AI mutation 只能作为建议，必须经过 Rule、State、Clue、Map、Projection、Safety 等对应模块校验；
    
- Host Client 只负责演出、监管和授权操作，不承担规则结算和权威状态写入；
    
- Transaction 必须先写 State，再做 Projection；
    
- Host ACK 只表示舞台步骤播放完成，不能携带规则结果或状态变更。
    

所以离线模式绝对不能做成：

```text
Host WS 断开
→ AI 获得 owner 权限
→ AI 可以揭示线索、改地图、结束遭遇、改写 NPC
```

正确模型是：

```text
Host 离线
→ 进入预设的自治范围
→ 每项行为判断“决定权属于谁”
→ 再判断风险和可逆性
→ 自动执行 / 执行后待复核 / 执行前等待 / 直接禁止
```

---

# 二、最基础的设计不是“风险评分”，而是“决定权归属”

系统首先要判断：

> **这件事本来应该由谁决定？**

建议定义五类决定权。

|决定权|决定什么|Host 不在线时|
|---|---|---|
|`player_owned`|角色尝试什么、说什么、是否分享自己的线索|正常继续|
|`party_owned`|队伍目标、路线选择、是否撤退、如何分工|由玩家确认或投票|
|`rule_owned`|掷骰、成功等级、伤害数学、资源计算|RuleExecutor 正常执行|
|`module_owned`|已编译 Trigger、NPC Agenda、Clock、RevealGate|仅按已确认规则运行|
|`host_owned`|新 Canon、重大方向、核心揭示、Retcon、异常裁决|等待 Host|
|`platform_owned`|权限、安全、反剧透、限速|始终自动执行，不得绕过|

这里有一个非常重要的结论：

> **Host 不在线时，不应该把本来属于玩家的选择冻结。**

例如：

```text
玩家是否打开门
玩家是否相信护士
队伍是否撤退
玩家是否分享自己的私人线索
玩家是否花自己的 Luck
```

这些不是 Host 的选择。

但玩家选择“尝试打开门”后：

```text
门后究竟有什么
是否触发核心场景
是否揭示隐藏真相
是否创建重大永久后果
```

可能仍属于 Module 或 Host 权限。

所以应该分开：

```text
玩家行动意图可以立即成立
世界的重大回应可以等待复核
```

---

# 三、Host 离线不能只有开和关，至少要区分五种状态

# `HostPresenceState`

|状态|含义|系统行为|
|---|---|---|
|`online`|Host 正常在线|正常主持模式|
|`grace_period`|短暂断线或刷新|不立即切换自治模式|
|`planned_absence`|Host 主动授权暂离|按授权策略继续|
|`unexpected_absence`|Host 超时未恢复|进入保守辅助模式|
|`return_sync`|Host 已回来但尚未完成同步|暂停新的高风险结果|
|`emergency_paused`|发现安全、状态或事务异常|只允许只读辅助|

不能因为 Host 网络抖了一下，就立刻改变整桌权限。

推荐流程：

```text
Host WS 断开
→ 进入 grace_period
→ 尝试重连
→ 超过可配置宽限时间
→ 检查是否存在 HostDelegationGrant
→ 有授权：进入 planned_absence
→ 无授权：进入 conservative unexpected_absence
```

---

# 四、计划离开和突然掉线，权限范围必须不同

## 1. Host 主动暂离

Host 可以提前创建：

# `HostDelegationGrant`

```json
{
  "grantId": "grant_xxx",
  "roomId": "room_xxx",
  "createdBy": "host_account",
  "mode": "facilitator",
  "validUntil": "2026-07-11T23:30:00Z",
  "maxAutonomyClass": "A2",
  "allowedSceneRefs": [
    "scene:archive_room"
  ],
  "allowedActionTypes": [
    "dialogue",
    "inspect",
    "skill_check",
    "use_owned_item",
    "move_within_revealed_map"
  ],
  "cluePolicy": "ordinary_prevalidated_only",
  "combatPolicy": "no_new_combat",
  "clockPolicy": "noncritical_only",
  "newCanonPolicy": "forbidden",
  "criticalResultPolicy": "defer"
}
```

Host 不需要看到剧透，只要选择产品化选项：

```text
允许继续当前场景
允许普通检定
允许和已公开 NPC 互动
允许使用个人物品
不允许进入新场景
不允许开启战斗
不允许核心线索揭示
不允许永久角色变化
```

---

## 2. Host 意外掉线

默认必须更保守：

```text
允许：
规则查询
剧情回顾
证据整理
队伍讨论
私人笔记
普通角色卡查询
已公开内容检索
已提交行动排队

有限允许：
低风险、确定性、无隐藏揭示的普通行动

默认等待：
新场景
关键线索
战斗
NPC 重大状态变化
永久资源损失
核心 Clock
```

不能把“Host 没设置策略”解释成“全部允许”。

---

# 五、建议定义四级自治能力

# `AutonomyClass`

## A0：只读辅助

不改变世界状态。

可以自动做：

```text
规则解释
角色卡解释
剧情回顾
时间线查询
调查工作台整理
线索来源查询
人物关系回顾
队伍讨论
私人笔记
行动草稿
```

这一级几乎永远可以继续。

---

## A1：确定性辅助

会生成记录，但不产生重大世界变化。

可以包括：

```text
提交和保存行动意图
确认自然语言 Intent Contract
普通掷骰前的规则计划
查看已揭示地图
查看已有物品
与已公开资料交互
生成安全叙事
```

---

## A2：低风险受控执行

允许执行满足以下条件的状态变化：

```text
规则明确
目标明确
当前状态明确
没有隐藏揭示
没有新 Canon
可机械补偿
玩家已明确确认
在 Host 预授权范围内
```

例如：

```text
普通技能检定
在已揭示区域移动
使用普通消耗品
扣除一发弹药
获得非核心、预验证线索
低影响 NPC 回应
普通游戏内时间推进
```

这类结果可以：

```text
立即执行
+ 自动写入 ReviewBacklog
+ Host 回来后批量查看
```

---

## A3：执行前等待复核

系统可以完成计算，但不能正式应用或揭示。

例如：

```text
核心线索揭示
重大场景转换
永久状态变化
角色濒死或死亡
NPC 死亡
战斗开始或结束
重要物品摧毁
阵营关系重大变化
大幅时间跳跃
重要 Clock 达到阈值
玩家之间的高影响冲突
```

系统可以生成：

```text
规则结果
候选状态变化
候选叙事
来源和影响预览
```

但停在：

```text
awaiting_host_review
```

---

## A4：永不允许 AI 自治

```text
修改 Module 真相
创建新核心反派
改变结局条件
静默 Retcon
恢复 Checkpoint
删除历史事件
修改规则包
越过 Safety
公开其他玩家私密内容
代表 Host 作出价值判断
```

这类操作即使 Host 长期不在线，也不能自动做。

---

# 六、不能只对“整个行动”分类，要把一次结果拆成多个切片

这是这一套设计最关键的地方。

一条行动通常同时包含：

```text
规则结果
状态变化
信息揭示
叙事呈现
方向推进
```

这些切片的风险可能完全不同。

建议定义：

# `ResolutionBundle`

```json
{
  "bundleId": "rb_102",
  "actionId": "act_102",

  "mechanicSlice": {},
  "stateSlice": {},
  "revealSlice": {},
  "narrativeSlice": {},
  "directionSlice": {}
}
```

每个 Slice 单独判断：

```text
auto_final
auto_apply_reviewable
defer_for_host
blocked
```

---

## 示例：玩家搜索档案柜

玩家说：

> “我检查第三层档案柜里有没有与失踪病人有关的记录。”

服务器执行侦查，掷骰成功。

可能拆成：

|切片|结果|处理|
|---|---|---|
|Mechanic|侦查成功|自动最终|
|State|行动完成，无重大状态变化|自动最终|
|Reveal|找到核心病人名单|等待 Host|
|Narrative|“你发现其中一层有被反复翻动的痕迹”|可立即安全播放|
|Direction|开启“地下实验”核心线程|等待 Host|

玩家可以立即知道：

> 检定成功，你确认这里存在异常整理痕迹。更具体的发现涉及重要剧情节点，已等待 Host 复核。

这样不会：

```text
整桌完全停摆
```

也不会：

```text
AI 自己把核心线索直接发出去
```

---

# 七、可补偿的可以先做后审；无法收回的信息必须先审后放

这是整套系统的第二条核心原则。

## 可以补偿的结果

例如：

```text
HP 扣错
弹药少扣或多扣
物品次数错误
位置移动错误
普通资源变化
```

这些可以：

```text
先按预授权执行
→ Host 后审
→ 错了走 CompensationTransaction
```

## 无法真正收回的结果

例如：

```text
真凶身份
隐藏 NPC 真名
核心线索内容
结局条件
玩家私人秘密
秘密地图出口
```

玩家一旦看见，就不能真正“回滚”。

因此必须：

```text
先经过 RevealGate / HostReviewGate
→ 再投影给玩家
```

一句需要写进产品规范的话：

> **机械变化可以补偿，信息泄露不可补偿；任何不可收回的信息必须执行前复核。**

---

# 八、Host 离线期间，哪些功能应该继续

## 完全继续

```text
查看角色卡
查看背包和已知物品
查看已经获得的线索
问战役记忆
查看人物与时间线
私人笔记
Party 证据板
队伍聊天
规则查询
准备行动草稿
设置 Party Goal
玩家之间讨论和投票
```

## 在策略允许时继续

```text
普通技能检定
普通对话
已公开 NPC 的低影响回应
在已揭示地图范围移动
普通物品使用
普通资源消耗
已预编译、非核心 Trigger
非关键 Clock
普通调查动作
```

## 默认停在 Host Gate

```text
新遭遇
核心线索
秘密身份
重大场景转换
角色死亡
NPC 死亡
永久伤病
重大资源损失
关键物品摧毁
派系关系改变
结局推进
重要时间跳跃
```

## 永远不能继续

```text
修改模组 Canon
静默 Retcon
删除或重写历史
自动恢复 Checkpoint
AI 自己新增最终答案
绕过权限和 Safety
```

---

# 九、战斗中的 Host 离线要更严格

战斗不应全部禁止，但必须有专门策略。

## 可继续的前提

```text
遭遇已经由 Host 确认
参与者已经固定
规则包稳定
NPC TacticsProfile 已确认
没有新隐藏增援
没有重大剧情 Gate
```

可以继续：

```text
普通攻击
闪避
反击
移动
使用普通物品
扣弹药
基础伤害
普通 Condition
```

必须等待 Host：

```text
新战斗开始
秘密增援
Boss 阶段切换
角色死亡
永久残疾
NPC 处决
战斗结束引发核心剧情
关键俘虏死亡
重大逃脱后果
```

例如伤害会让角色死亡：

```text
RuleExecutor 可以完成骰子和伤害计算
但 lifeState=dead 不立即提交
遭遇进入 critical_resolution_pending
```

玩家看到：

> 该攻击造成了严重后果，当前遭遇已暂停在重要裁决点，等待 Host 复核。

不能为了“不断团”就让 AI 自动杀死角色。

---

# 十、Host 离线后，ReleaseGate 不能伪造 Host ACK

你们已有契约要求：

- Host ACK 只表示实际演出步骤完成；
    
- ReleaseGate 由服务端控制；
    
- Host 客户端不能自行决定玩家私密结果的释放。
    

因此离线模式下不能做：

```text
Host 不在
→ 系统假装收到 host_step_complete
```

应该新增一个独立对象：

# `SystemReleaseDecision`

```json
{
  "releaseDecisionId": "srd_102",
  "gateId": "gate_102",
  "transactionId": "tx_102",
  "releasedBy": "offline_policy",
  "policyRef": "offline_policy_v3",
  "reason": "ordinary_result_pre_authorized",
  "releasedEventSequences": [913, 914],
  "createdAt": "..."
}
```

区分：

```text
HostStepAck
SystemReleaseDecision
AdminRecoveryDecision
```

这三者绝不能混用。

## Gate 的离线策略

```text
wait_for_host
auto_release_if_low_risk
auto_release_after_safe_fallback
release_mechanics_hold_reveal
block_and_pause
```

其中：

```text
release_mechanics_hold_reveal
```

会非常常用。

---

# 十一、重要结果如何做到真正可复核

复核不能只是给 Host 看一句：

> AI 在你离开期间处理了 12 个行动。

Host 需要的是：

# `HostReviewPacket`

```json
{
  "reviewId": "review_102",
  "roomId": "room_xxx",
  "sessionId": "session_xxx",
  "createdDuringMode": "planned_absence",
  "riskClass": "A3",
  "status": "awaiting_review",

  "playerInput": {
    "rawText": "我烧掉所有档案，免得落入他们手里",
    "confirmedIntentRef": "intent_482"
  },

  "decisionOwnership": {
    "playerDecision": "尝试焚毁档案",
    "worldConsequenceOwner": "host_or_module"
  },

  "rulePlan": {},
  "rollEvidence": {},
  "stateBeforeRef": {
    "stateVersion": 84
  },
  "candidateStateChanges": [],
  "appliedStateChanges": [],

  "revealCandidates": [],
  "directionCandidates": [],

  "aiProposal": {
    "taskStatus": "success",
    "schemaVersion": "2.1",
    "outputHash": "sha256:..."
  },

  "policyDecision": {
    "decision": "defer_for_host",
    "ruleIds": [
      "irreversible_world_change",
      "key_evidence_destruction"
    ]
  },

  "sourceRefs": [],
  "dependencies": [],
  "recommendedActions": [
    "accept",
    "modify_consequence",
    "reject"
  ]
}
```

---

# 十二、Host Review Packet 至少需要包含九部分

## 1. 玩家原始表达

```text
玩家原话
语音确认文本
修改后的 Intent Contract
```

不能只显示 AI 总结。

---

## 2. 系统理解

```text
目标
方法
对象
约束
资源
公开范围
```

方便 Host 判断 AI 是否理解错了。

---

## 3. 决定权归属

```text
哪部分属于玩家
哪部分属于规则
哪部分属于 Module
哪部分需要 Host
```

---

## 4. 规则证据

```text
使用哪个技能
权威数值
难度
修正
rollId
骰子
成功等级
规则来源
```

复核时默认复用原骰，不重新掷骰。

---

## 5. 状态差异

```text
Before
After
Candidate
Applied
Deferred
```

Host 不应该阅读完整数据库快照，只看最小差异。

---

## 6. 信息揭示

```text
哪些内容已经给玩家看
哪些内容仍被 Gate 挡住
哪些内容无法收回
```

这是复核优先级最高的部分。

---

## 7. AI 参与范围

```text
AI 只做了意图理解？
做了机制建议？
做了叙事？
做了 NPC 决策？
```

并显示：

```text
provider 状态
fallback 状态
schema 是否通过
Safety 是否命中
```

不需要把完整 raw prompt 塞给 Host。

---

## 8. 自动处理理由

例如：

```text
自动执行原因：
- 当前场景已授权；
- 规则确定；
- 不涉及新 Canon；
- 可机械补偿；
- 未触发核心 RevealGate。
```

或者：

```text
等待原因：
- 可能摧毁关键证据；
- 会改变核心 StoryThread；
- 结果不可逆。
```

---

## 9. 依赖关系

如果后续三个行动依赖这个结果，必须显示：

```text
此决定将影响：
action_483
action_484
thread:nurse_alibi
clock:hospital_lockdown
```

---

# 十三、Host 回来后不应按时间顺序审几十条记录，而应先审“锚点决定”

建议建立：

# `ReviewDependencyGraph`

```text
重要决定 A
├── 后续普通行动 B
├── NPC 回应 C
└── Clock 推进 D
```

Host 先审 A。

如果接受：

```text
B/C/D 可以批量接受
```

如果拒绝：

```text
重新检查 B/C/D 是否需要补偿或失效
```

这比让 Host 从第一条消息开始翻要高效得多。

---

# 十四、Host 回归首页应该是什么样

```text
你离线了 43 分钟

期间：
- 玩家行动：17
- 自动完成：11
- 已应用、建议复核：3
- 等待重要复核：2
- 玩家提出异议：1
- Safety 拦截：0
- 状态版本：84 → 92
```

## 重要复核

```text
1. 玩家试图销毁档案
   状态：未执行
   风险：不可逆世界变化

2. 玩家成功找到地下室相关记录
   规则结果：已确认成功
   核心线索内容：未释放
```

## 已应用但建议查看

```text
1. 使用急救包，次数 2 → 1，HP 5 → 7
2. 消耗 1 发弹药
3. NPC 对玩家态度 -1
```

## 一般事务

```text
8 条普通查询
3 条队伍消息
4 次调查工作台整理
```

按钮可以是：

```text
接受所有无异常结果
逐项复核重要节点
查看玩家异议
查看完整审计链
```

关键结果仍必须逐项确认，不能被“全部接受”吞掉。

---

# 十五、Host 的复核操作不能只有接受和拒绝

建议提供：

|操作|含义|
|---|---|
|`accept`|接受已有结果|
|`accept_mechanics_only`|保留规则结果，重写叙事|
|`rewrite_narrative`|只改表现，不改状态和骰子|
|`recompute_with_same_roll`|规则参数错误，用原骰重算|
|`modify_consequence`|保留玩家行动，但调整世界回应|
|`reject_reveal`|不释放候选线索|
|`apply_compensation`|修复已应用状态|
|`branch_from_checkpoint`|重大错误时从检查点建立新历史分支|
|`mark_no_review_needed`|后续同类低风险结果降低提示|

---

# 十六、复核不等于删除历史

你们现有 Journal 和 Transaction 边界已经强调：

- retry 要区分重播、未完成重算和 checkpoint restore；
    
- 已结算结果不能默认重复应用 State；
    
- restore 必须 `confirm + reason`，并形成可追溯语义。
    

因此复核后不能：

```text
DELETE 原事件
UPDATE 原结果为新结果
假装旧结果从未发生
```

应该是追加：

```text
原事务
→ ReviewDecision
→ Correction / Compensation / Retcon
```

---

# 十七、纠错应该分四种

## 1. 叙事修正

错误：

> AI 写成玩家翻阅了私人信件，但玩家明确说不碰信件。

处理：

```text
保留骰子
保留状态
重生成叙事
写 narrative_correction
```

---

## 2. 规则重算

错误：

```text
使用了错误技能值
难度读取错误
修正项漏掉
```

处理：

```text
复用原 rollId
重新计算结果
生成 correction transaction
```

原则：

> 能用原骰修正的，不重新掷骰。

---

## 3. 状态补偿

错误：

```text
多扣 2 HP
重复扣弹药
物品次数错误
```

处理：

```text
生成 CompensationTransaction
恢复差额
保留 before/after/source
```

---

## 4. Canon / 剧情修订

错误：

```text
错误揭示核心身份
错误杀死 NPC
错误推进结局
```

这类问题最严重。

如果内容尚未投影：

```text
直接拒绝候选结果
```

如果已经投影：

```text
不能假装玩家没看见
必须显式 Host Retcon
或从 Checkpoint 建新分支
```

所以这类内容应当尽量使用执行前 Gate，而不是事后补偿。

---

# 十八、玩家端必须明确告诉他“当前是什么主持状态”

不能让玩家误以为 AI 就是 Host。

建议固定状态条：

```text
主持状态：Host 暂时离线
辅助模式：标准
AI 可处理：规则查询、普通行动、已授权场景
重要剧情结果：等待 Host 复核
```

所有 AI 输出标识来源：

```text
AI 辅助主持
规则系统
系统投影
Host 已确认
等待 Host 复核
```

不能写：

> KP 告诉你……

除非真的是 Host 输入。

---

# 十九、每个行动提交前要显示它的离线处理方式

例如：

## 普通检定

> 当前 Host 离线。  
> 该行动属于普通规则检定，可以立即结算。  
> 若触发重要线索，线索内容会等待 Host 复核。

按钮：

```text
立即按安全模式处理
只提交给 Host
取消
```

---

## 高风险行动

> 该行动可能造成不可逆世界变化。  
> 系统会保存你的完整意图，但不会在 Host 返回前执行最终后果。

按钮：

```text
提交等待 Host
修改行动
取消
```

---

## 玩家自己可以决定的行为

例如分享自己的线索：

> 这是你的个人决定。分享后队伍将看到以下安全版本。

不需要 Host 批准，但需要玩家自己确认。

---

# 二十、玩家应随时可以主动要求 Host 复核

新增：

# `PlayerDisputeRequest`

原因类型：

```text
AI 误解了我的行动
目标对象错误
使用了错误技能
状态变化错误
叙事与行动不一致
不希望 AI 处理此类内容
其他
```

被玩家标记后：

```text
riskClass 自动提高
加入 Host ReviewBacklog
禁止自动归档为“无争议”
```

为了避免滥用，可以：

```text
同一事务只提交一次
允许补充说明
不允许重复刷 Review
```

但不能因为玩家经常质疑，就取消他的复核能力。

---

# 二十一、AI 辅助模式不应读取完整 Host 真相

这是安全上非常重要的一点。

离线 Facilitator AI 应该使用：

# `OfflineFacilitatorContext`

只包含：

```text
当前已提交 State
当前角色可见内容
当前场景允许的交互对象
已确认 RuleSpec
已公开 NPC 行为边界
预授权的 Trigger 和 RevealGate 状态
```

不应直接包含：

```text
完整 truth
完整 ending
全部隐藏线索
未出现 NPC 的秘密
所有分支答案
```

关键 RevealGate 是否满足，可以由服务端结构化检查。

AI 不需要知道完整秘密才能判断：

```text
这个结果应该继续还是等待 Host
```

---

# 二十二、Director AI 和 Facilitator AI 也要分开

## `Facilitator AI`

面向玩家，负责：

```text
规则帮助
回顾
行动结构化
低风险 NPC 对话
调查工作台整理
安全叙事
```

只读玩家安全上下文。

## `Director AI`

如果使用，只负责生成：

```text
候选世界回应
候选 Clock
候选 Reveal
候选方向
```

它不能直接向玩家说话，也不能直接写 State。

离线模式下，Director AI 的自治等级应低于 Host 在线时。

---

# 二十三、Host 不在线时发生 AI 故障怎么办

主链路必须继续降级。

## AI 意图理解失败

```text
保存玩家原文
让玩家选择行动类型、目标、技能
或排队等待 Host
```

## 叙事生成失败

```text
使用确定性结果模板
```

例如：

> 你的侦查检定成功。重要剧情内容等待 Host 复核。

## Provider 全部不可用

仍可继续：

```text
规则查询缓存
角色卡
已知线索
证据板
确定性骰子
普通资源操作
队伍讨论
```

不能因为 LLM 失败而丢行动。

---

# 二十四、异步团可以把这套模式正式产品化

Host 离线能力不仅用于掉线，也可支持异步跑团。

建议新增：

# `AsyncTurnWindow`

```text
开放时间
允许参与者
当前场景范围
可提交行动数量
截止时间
是否允许修改
默认超时策略
Host 预计复核时间
```

玩家可以在不同时间提交：

```text
行动
讨论
规则问题
私人笔记
队伍目标
```

系统做：

```text
意图整理
冲突检测
常规规则结算
依赖分析
重要结果排队
```

Host 回来后只处理：

```text
冲突行动
重要 Reveal
重大后果
方向选择
```

这会成为你们非常强的差异化。

---

# 二十五、建议新增一个独立跨模块协议

可以新增：

# **27-Continuity / Host Delegation & Review**

中文：

# **主持缺席续行与复核系统**

它不替代 Host Client、Transaction、State 或 AI。

它负责：

```text
Host 在线状态
DelegationGrant
自治权限矩阵
风险分类
ReviewGate
SystemReleaseDecision
HostReviewPacket
ReviewBacklog
PlayerDispute
CompensationTransaction
HostReturnDigest
```

---

# 二十六、建议的数据对象

```text
HostPresenceState
HostDelegationGrant
OfflineAuthorityPolicy
AutonomyDecision
ResolutionSliceDecision
SystemReleaseDecision
DeferredHostDecision
HostReviewPacket
ReviewDependencyGraph
HostReviewDecision
PlayerDisputeRequest
CompensationTransaction
HostReturnDigest
AsyncTurnWindow
```

---

# 二十七、几个关键 DTO

## `OfflineAuthorityPolicyDTO`

```json
{
  "policyId": "offline_policy_standard",
  "maxAutonomyClass": "A2",
  "allowedActionTypes": [],
  "allowedSceneRefs": [],
  "resourceLimits": {},
  "cluePolicy": "ordinary_prevalidated_only",
  "combatPolicy": "continue_existing_noncritical",
  "newEncounterPolicy": "defer",
  "newCanonPolicy": "forbidden",
  "criticalStatePolicy": "defer",
  "expiry": "..."
}
```

## `AutonomyDecisionDTO`

```json
{
  "decisionId": "ad_102",
  "actionId": "act_102",
  "decisionOwner": "rule_owned",
  "riskClass": "A2",
  "decision": "auto_apply_reviewable",
  "matchedPolicies": [],
  "blockReasons": [],
  "stateVersion": 84
}
```

## `HostReviewDecisionDTO`

```json
{
  "reviewId": "review_102",
  "decision": "recompute_with_same_roll",
  "reason": "系统读取了错误的技能值",
  "actorAccountId": "acct_host",
  "affectedSliceTypes": [
    "mechanic",
    "state",
    "narrative"
  ],
  "createdAt": "..."
}
```

---

# 二十八、P0 应该做到什么

|P0|原因|
|---|---|
|HostPresenceState|区分掉线、暂离和恢复|
|保守默认策略|无授权不自动扩权|
|HostDelegationGrant|Host 可显式授权|
|决定权归属|避免把所有事都视为 Host 决策|
|A0-A4 自治等级|统一执行范围|
|ResolutionBundle 切片|机械、状态、揭示和方向分别处理|
|不可收回信息预审|防止核心剧透|
|SystemReleaseDecision|不伪造 Host ACK|
|HostReviewPacket|重要结果可解释|
|ReviewBacklog|Host 不用翻聊天|
|ReviewDependencyGraph|先审关键锚点|
|PlayerDisputeRequest|玩家可要求复核|
|CompensationTransaction|修正状态不删历史|
|HostReturnDigest|快速恢复主持|
|玩家状态提示|不假装 AI 就是 Host|
|完整事务 Trace|能追到 action/turn/transaction/state/sequence|

你们现有 Transaction 契约已经要求 `actionId / turnId / transactionId / stateVersion / eventSequences / journalRefs` 形成完整追踪链，这正好可以作为离线复核包的技术底座。

---

# 二十九、P1 再做

```text
异步回合窗口
战斗专用离线政策
NPC 对话自治政策
自动依赖图
Host 复核推荐
低风险批量接受
异常检测
玩家异议统计
规则差异自动解释
离线期间移动端通知
多人共同确认重要 Party 决定
```

---

# 三十、P2 长期能力

```text
共同 Host / 副 Host
分权主持
Host 轮班
跨时区长期异步战役
审核工作流模板
不同 Ruleset 的自治策略包
智能复核抽样
离线段落自动剪辑回放
```

---

# 三十一、明确禁止的设计

```text
Host WS 断开就把 owner 权限交给 AI
让 AI 假装发送 Host ACK
让 AI 读取完整模组真相再自行“避免剧透”
所有行动都立即执行后再让 Host 修
所有行动都冻结导致离线模式毫无价值
用一个模型风险分数覆盖硬约束
让 AI 自动决定玩家或 Party 的选择
Host 回来后重新掷骰
通过删除历史修正错误
把已解决事件重新执行
让重要 Reveal 先发出去再谈复核
把 Player 私密内容自动纳入 Host Review
让 Host 看完整 raw prompt 和未脱敏模型日志
```

---

# 三十二、工程验收最关键的测试

```text
1. Host 短暂断线不会立即切换自治模式。
2. 无 DelegationGrant 时默认进入保守模式。
3. Player-owned 决定不会因 Host 缺席被错误冻结。
4. Party-owned 决定必须由 Party 确认，不由 AI 代选。
5. Rule-owned 普通结算可以在策略允许时继续。
6. Host-owned 重大结果必须进入 awaiting_host_review。
7. AI 无法修改 Module Canon。
8. ResolutionBundle 的 mechanic/state/reveal/direction 能分别 Gate。
9. 核心 Reveal 在 Host 复核前不进入 Player Projection。
10. Host-only 真相不进入 OfflineFacilitatorContext。
11. 系统离线释放使用 SystemReleaseDecision，不伪造 HostStepAck。
12. Host ACK 不包含规则结果和状态 mutation。
13. 已自动应用的状态结果可生成完整 ReviewPacket。
14. ReviewPacket 保留玩家原话和确认后的 Intent Contract。
15. ReviewPacket 能追到 rollId、rule plan、stateVersion、eventSequence。
16. Host 复核默认不重新掷骰。
17. 叙事修正不改变 State。
18. 状态修正通过 CompensationTransaction。
19. 复核不会删除原始事件。
20. 已解决 action 不会因 Host 返回而重复结算。
21. Host 返回后能看到 ReviewDependencyGraph。
22. Host 拒绝一个锚点时，依赖结果被重新评估。
23. Player dispute 会提升复核优先级。
24. AI provider 失败时，确定性功能仍可用。
25. 战斗致死结果不会在无 Host 授权时自动提交。
26. 不可收回信息永远采用执行前 Gate。
27. HostReturnDigest 不泄露其他玩家私人笔记。
28. Checkpoint restore 仍必须 confirm + reason。
```

---

# 三十三、衡量这项能力是否成功

|指标|目标|
|---|---|
|Host 短暂掉线导致整桌停摆率|显著下降|
|Host 缺席期间可继续的常规行动比例|提高|
|Host 回来后的平均追赶时间|尽量压到数分钟|
|重大结果未经复核自动执行|0|
|Host-only 真相泄露|0|
|AI 修改 Canon|0|
|已解决事务重复结算|0|
|Host 推翻普通自动结果比例|持续下降|
|Host 推翻重大建议比例|用于优化 Gate|
|状态补偿事务比例|低且可解释|
|玩家提出“AI 误解我”的比例|持续下降|
|玩家因为 Host 暂离而退出 Session 的比例|下降|
|Host 对复核包可读性评分|提高|

一个很实际的产品目标：

> **Host 离开 30—60 分钟后，玩家仍可完成多数常规调查、规则查询、证据整理和低风险行动；Host 返回后在 3—5 分钟内看完重要变化，并只需处理真正影响剧情和状态的少量节点。**

---

# 三十四、这条差异化真正的壁垒

普通 AI 主持产品通常只有两个状态：

```text
AI 全权主持
AI 不工作
```

你们应该做到：

```text
玩家决定继续什么
规则决定机械结果
Module 决定预编译世界逻辑
State 决定什么正式成立
Safety 决定什么可以被看见
AI 负责理解、组织和安全表现
Host 只复核真正需要人类判断的节点
```

这不是“AI 替代 Host”。

而是：

# **把 Host 的注意力从所有事务中解放出来，只保留真正需要主持判断的事务**

---

# 最终产品定义

> **AI-Keeper 的 Host 离线能力是一套受监督自治协议：系统先判断决定权属于玩家、Party、规则、模组还是 Host，再按可逆性、信息风险和剧情影响，把结果拆成机械、状态、揭示、叙事和方向五个切片。普通且可补偿的事务可在预授权范围内继续，无法收回的信息和重大世界变化必须停在 Host Review Gate。Host 返回后通过带玩家原话、规则证据、状态差异、来源引用和依赖关系的复核包完成接受、修正或补偿，而不是重新阅读整场聊天，也不会通过删除历史来掩盖错误。**