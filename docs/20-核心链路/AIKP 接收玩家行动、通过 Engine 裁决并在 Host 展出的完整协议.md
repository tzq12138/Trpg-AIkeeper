# 

这一块应该成为整个系统最核心的一条协议。

它不能是：

```text
玩家发一句话
→ AIKP 读取整个剧本
→ AI 自己判断结果
→ AI 回复玩家
→ 顺便在 Host 页面显示
```

正确模型应该是：

# **AI 理解，Engine 管理，Rule 裁决，State 落地，Projection 分发，Host 演出**

主链路可以固定为：

```text
玩家原始输入
    ↓
行动接入与身份校验
    ↓
AIKP 编译意图合同
    ↓
玩家确认 / 系统安全自动确认
    ↓
Action 事务入账
    ↓
Engine 选择执行路径
    ↓
Rule 权威裁决
    ↓
State 原子提交
    ↓
AIKP 根据已提交结果生成叙事
    ↓
Projection 拆分不同视角
    ↓
Host 公共舞台演出
Player 私密结果
Party 公共结果
Journal 审计记录
```

你们现有文档已经明确：AI 只能停留在可校验建议层，不能直接改状态；Rule 负责权威数学结果；State 成功后才能产生版本化投影；Host 只负责播放和监管，不负责裁决。

建议把这一整套协议命名为：

# **Player Action Orchestration Protocol**

中文：

# **玩家行动编排协议**

---

# 一、先把 AIKP 拆开，不能让一个 AI 调用包办全部工作

AIKP 不应该是一个什么都做的“大脑”。

建议拆成四种明确任务：

|AI 任务|负责什么|不负责什么|
|---|---|---|
|`IntentCompiler`|理解玩家想做什么|不决定成功失败|
|`MechanicAdvisor`|建议可能使用的机制|不生成权威骰子和数值|
|`DirectorAdvisor`|建议世界如何回应|不直接写世界状态|
|`NarrativeComposer`|把已确定结果写成叙事|不修改 RuleResult|

其中真正能产生权威结果的是：

```text
Engine
RuleExecutor
StateService
Transaction
```

而不是 AIKP。

可以理解为：

```text
AIKP = 翻译官 + 编剧 + 建议者
Engine = 总调度
Rule = 裁判
State = 记分台
Projection = 导播
Host Stage = 舞台
```

---

# 二、整个系统最好分成六个管理器

## 1. `PlayerActionGateway`

负责接收玩家请求：

```text
文本行动
语音确认文本
快捷动作
技能点击
物品使用
地图移动
线索分享
战斗动作
```

它首先验证：

```text
玩家 token
角色归属
房间归属
角色 status
房间状态
当前 turn
当前 encounter
stateVersion
actionId 幂等
速率限制
```

服务器必须通过 `player_token` 反查角色，不能相信请求体中的 `characterId`。玩家端也必须以 `action_id` 做幂等显示，并展示 submitting、queued、resolving、completed、rejected、timeout 等状态。

---

## 2. `IntentManager`

负责把玩家原话变成结构化意图合同。

```text
玩家原话
→ 输入模式分类
→ 实体绑定
→ 目标、方法、约束提取
→ 风险判断
→ 确认策略
```

---

## 3. `ExecutionPolicyManager`

负责判断：

```text
这条输入是不是行动？
当前用即时模式还是回合模式？
是否进入战斗协议？
是否需要玩家确认？
是否需要 Host 确认？
Host 不在线时能否继续？
是否包含不可逆或私密操作？
```

---

## 4. `ResolutionEngine`

负责真正执行：

```text
前置条件
机制编译
规则裁决
状态变化
线索释放
物品变化
地图变化
NPC 变化
```

---

## 5. `ResponseComposer`

把已经确定的结果拆成：

```text
公共结果
玩家本人私密结果
指定角色私密结果
Host 复核信息
规则回执
状态 Patch
```

---

## 6. `HostPresentationManager`

把公共结果编排成 Host 舞台步骤：

```text
玩家行动声明
骰子演出
结果演出
状态变化摘要
地图或场景变化
BGM / SFX
公共叙事
```

它只负责演出，不负责裁决。

---

# 三、玩家输入不能都走同一条管线

首先应该识别玩家当前输入的语义模式。

建议支持这些模式：

```text
action          正式行动
speech          角色发言
party_chat      队伍讨论
ooc             场外信息
rule_question   规则提问
private_note    私人笔记
clue_share      分享线索
item_action     物品操作
map_move        地图移动
combat_action   战斗行动
safety          X-card / fade 等安全输入
```

例如：

|玩家输入|正确路由|
|---|---|
|“我们要不要搜地下室？”|Party Chat，不执行|
|“我现在搜查地下室入口。”|Action|
|“心理学能判断他撒谎吗？”|Rule Question|
|“我怀疑护士在撒谎。”|Private Note 或 Hypothesis|
|“我把信件内容告诉大家。”|Clue Share|
|“我把信件交给安娜。”|Item Transfer|
|“我去拿杯水。”|OOC|

Channel 文档已经明确，聊天不能自动升级成世界事实，OOC、玩家聊天、系统事件和叙事要分开进入 AI 上下文。

因此第一条硬规则是：

> **AI 可以建议这句话属于哪一种模式，但疑问、建议、玩笑和讨论不能自动升级成正式行动。**

---

# 四、玩家请求的数据结构

客户端提交时建议使用统一信封：

```json
{
  "actionId": "act_01HXYZ",
  "roomId": "room_001",
  "inputMode": "action",
  "source": "text",
  "rawText": "我假装翻看账本，提到北仓库，观察馆长的反应，但不碰私人信件。",
  "baseStateVersion": 84,
  "requestedVisibility": "scene_public",
  "clientSequence": 251,
  "attachments": []
}
```

不建议让客户端提交权威字段：

```text
characterId
skillValue
roll
successLevel
currentHP
targetDifficulty
```

即使为了 UI 显示传了，也只能作为非权威提示。

服务器自行确定：

```text
actorCharacterId
accountId
room membership
角色技能值
当前装备
当前 HP/SAN
当前地点
可操作目标
```

---

# 五、玩家输入后的第一份回复不是剧情，而是接收回执

玩家点下提交后，应该立刻收到：

# `ActionReceipt`

```json
{
  "actionId": "act_01HXYZ",
  "status": "received",
  "receivedAt": "...",
  "baseStateVersion": 84,
  "executionMode": "turn_collecting"
}
```

玩家 UI：

```text
已收到行动
正在理解你的意图
```

这个响应不依赖 AI，不能因为模型慢或失败而让玩家不知道请求有没有收到。

随后才进入：

```text
理解中
需要澄清
等待确认
已入队
正在结算
等待演出
已完成
```

---

# 六、AIKP 如何生成意图合同

`IntentCompiler` 不能读取完整模组真相。

它只读取：

```text
玩家原话
玩家自己的角色行动视图
当前可见场景
当前可见 NPC
玩家已知地图
玩家已知线索
玩家当前物品
当前规则包摘要
房间行动策略
```

不读取：

```text
完整 truth
ending
未发现线索
隐藏 NPC
其他玩家私密行动
Host 私密笔记
```

RAG 可以先召回较宽内容，但进入 AI prompt 前必须按 viewer、room、scenario、character、visibility 和 unlock state 再过滤。

AI 返回：

# `IntentContract`

```json
{
  "actionId": "act_01HXYZ",
  "actionType": "observe_reaction",
  "goal": "判断馆长听到“北仓库”后的情绪反应",
  "method": "假装翻阅账本，并在谈话中提及北仓库",
  "targetRefs": [
    {
      "type": "npc",
      "id": "npc_curator"
    }
  ],
  "constraints": [
    "不触碰私人信件"
  ],
  "resources": [],
  "visibility": "scene_public",
  "conditions": [],
  "assumptions": [
    "馆长可以听到玩家提及北仓库"
  ],
  "ambiguities": [],
  "impactLevel": "medium",
  "suggestedMechanics": [
    "psychology"
  ]
}
```

AI 机制建议中可以有：

```text
技能名称
建议难度
理由
可选机制
```

但不得有权威：

```text
骰子
技能最终数值
目标值
成功等级
```

你们现有 AI DTO 方向也是这样设计：`MechanicSuggestionDTO` 只能提供机制建议，而不能提供权威 roll、targetValue 或 successLevel；`NarrativePayloadDTO` 则需要明确拆分 `publicText` 和 `privateTexts`。

---

# 七、什么时候需要玩家确认

不应该所有行动都强制二次确认，否则很烦。

建议按风险处理。

## 低风险、无歧义

例如：

```text
查看公开告示
询问 NPC 姓名
在已揭示区域走到门口
```

可以：

```text
自动确认
+
给短暂撤回入口
```

## 中风险

例如：

```text
普通检定
公开提问
移动到可能危险的位置
```

显示轻量预览：

> 你会在谈话中提到“北仓库”，并观察馆长的反应。  
> 可能使用：心理学。

按钮：

```text
确认
修改
取消
```

## 高风险

必须确认：

```text
消耗 Luck
使用有限物品
攻击
公开私密线索
摧毁物品
进入危险区域
影响其他玩家
不可逆决定
```

## 有歧义

必须先澄清：

> 你说的“教授”是陈教授还是杨教授？

不能让 AI 自行猜高影响目标。

---

# 八、确认后才创建正式 Action 事务

建议把“意图草稿”和“正式行动”分开。

## 意图状态机

```text
received
→ parsing
→ needs_clarification
→ awaiting_confirmation
→ confirmed
→ cancelled
```

## 行动状态机

```text
submitted
→ queued
→ resolving
→ resolved

submitted
→ rejected

queued / resolving
→ timeout
```

这样可以避免：

```text
AI 还没理解清楚
但 action 已经进入正式回合
```

确认后：

```text
IntentContract
→ ActionLedger
→ 当前 Turn / Encounter
```

`actionId` 是幂等键。重复提交同一个 `actionId` 应返回同一份回执，不能重复入队、重复掷骰或重复修改状态。现有 Transaction 设计也要求 active 房间先完成 duplicate 校验，再写入 action；已 resolved/rejected 的行动再次执行时只能幂等返回。

---

# 九、Engine 怎么决定这条行动走哪条路线

`ExecutionPolicyManager` 根据当前运行状态选择执行模式：

|当前状态|执行方式|
|---|---|
|自由调查场景|即时 Action Transaction|
|全员行动回合|加入当前 collecting turn|
|战斗|进入 Encounter Activation|
|等待反应|进入 DecisionWindow|
|Host 离线|按 Autonomy Policy|
|Party 共同决策|创建 Party Decision|
|规则提问|不创建世界状态事务|
|OOC / 私人笔记|不进入 Engine 裁决|

例如：

```text
当前处于普通调查：
立即处理

当前是“全员先声明”：
加入当前回合

当前是战斗且没轮到该玩家：
生成准备动作或返回等待

当前 Host 离线且行动会揭示核心线索：
完成规则计算，但停在 Host Review Gate
```

---

# 十、Engine 构造真正的裁决上下文

进入正式裁决时，Context Manager 应分别构建：

## `CharacterRuleSnapshot`

```text
权威属性
权威技能
当前 HP/SAN/MP/Luck
临时修正
当前状态
可用能力
```

## `InventoryCapabilityView`

```text
当前持有物品
已验证能力
剩余次数
弹药
装备状态
```

## `SceneInteractionView`

```text
当前位置
可见目标
可交互对象
环境状态
地图区域
```

## `ModuleRuntimeView`

```text
当前 ModuleVersion
当前场景已启用 Trigger
当前可用 RevealGate
已实例化对象
```

## `RoomPolicySnapshot`

```text
骰子公开策略
隐藏检定策略
确认策略
House Rule
Host 在线状态
AI 自治等级
```

## `KnowledgeView`

```text
该角色当前已知信息
Party 已共享信息
```

不能把整个角色原始表、整个模组和全部 RAG 塞给 AI。

---

# 十一、MechanicCompiler 和 RuleExecutor 的边界

## AI / MechanicCompiler 可以给出

```json
{
  "triggeredMechanic": "skill_check",
  "skillName": "psychology",
  "suggestedDifficulty": "regular",
  "reason": "玩家试图通过观察 NPC 的反应判断其情绪"
}
```

## Engine 校验

```text
技能是否存在
目标是否存在
玩家当前是否能执行
场景条件是否满足
是否需要隐藏难度
是否存在规则覆盖
```

## RuleExecutor 生成权威结果

```json
{
  "ruleResultId": "rule_481",
  "skillId": "psychology",
  "skillValue": 45,
  "difficulty": "hard",
  "difficultyVisibility": "host_only",
  "roll": 37,
  "successLevel": "failure",
  "modifiers": [],
  "stateMutationProposal": []
}
```

AI 只能决定“可能是什么机制”，不能成为裁判。当前 Rule 文档也把 Rule 定义为 Engine 内部的规则事实层：接收 PlayerIntent、MechanicCompileResult 和权威角色/物品/剧本上下文，输出 ResolutionResult，而不直接写数据库。

---

# 十二、结果必须先写 State，再让 AI 讲故事

正确顺序：

```text
RuleResult
    ↓
MutationValidator
    ↓
StateService.apply_change
    ↓
AppliedStateChange
    ↓
NarrativeComposer
    ↓
Projection
```

不能：

```text
AI 先说“你成功打开了门”
→ 后面 State 写入失败
```

单个 action 的目标事务顺序已经在现有设计中明确：

1. action 进入 resolving；
    
2. 读取 character、room、scenario、inventory；
    
3. 前置校验；
    
4. MechanicCompiler 和 RuleExecutor 生成 ResolutionResult；
    
5. 失败则 rejected，不发公共剧情；
    
6. 成功后 StateService 写权威状态；
    
7. State 成功后 Projection 才发送 Host reveal、state patch、public observation 和 action completed。
    

---

# 十三、State 写完后生成统一的 ResolutionBundle

建议内部生成：

# `ResolutionBundle`

```json
{
  "actionId": "act_01HXYZ",
  "turnId": "turn_12",
  "transactionId": "tx_481",
  "ruleResult": {},
  "appliedStateChange": {},
  "publicFacts": [],
  "privateFacts": {
    "char_a": []
  },
  "hostReviewFacts": [],
  "publicNarrativeCandidate": "",
  "privateNarrativeCandidates": {},
  "mediaCandidates": [],
  "sourceRefs": [],
  "baseStateVersion": 84,
  "stateVersion": 85
}
```

它是所有输出的共同来源。

不能让：

```text
Host 叙事一个 AI 调用
Player 叙事另一个 AI 调用
Journal 又自己总结
```

最后三个版本互相矛盾。

应该是：

```text
同一 ResolutionBundle
→ 不同视角的安全投影
```

---

# 十四、AIKP 最终回复玩家时，只能使用已提交结果

`NarrativeComposer` 接收到：

```text
玩家确认的意图
RuleResult
AppliedStateChange
allowedFacts
forbiddenClaims
玩家视角
叙事风格
```

不能接收到：

```text
完整模组 truth
隐藏结局
与当前行动无关的秘密
```

输出：

```json
{
  "publicText": "陈默随意翻着账本，谈话中提到了北仓库。馆长的手指在封面上停顿了一瞬。",
  "privateTexts": {
    "char_a": "你注意到他的短暂反应，但无法确定这是紧张、意外还是别的原因。"
  },
  "keeperNotes": "隐藏困难检定失败，不得确认馆长的真实情绪。"
}
```

其中：

- `publicText` 经过 Safety / SpoilerGuard；
    
- `privateTexts` 按角色单独投影；
    
- `keeperNotes` 不进 Host 公共舞台，更不能发给玩家。
    

AI 文档要求 `publicText` 与 `privateTexts` 语义硬隔离，public narrative 必须经过 SpoilerGuard；AI 任何 mutation 建议也必须先通过统一校验点，不能直接写 State。

---

# 十五、一定要把 Host 分成两个界面

这一点非常重要。

# 1. Host Public Stage

这是可以：

```text
投屏
共享屏幕
让现场玩家观看
```

的公共舞台。

它只能显示：

```text
Party 公共叙事
公开骰子
公开状态摘要
地图已揭示区域
公共人物和物品
安全媒体效果
```

不能显示：

```text
玩家私密结果
隐藏难度
敌人真实 HP
未发现线索
Host-only truth
AI keeper note
完整规则内部参数
```

---

# 2. Host Console / Review Console

这是 Host 私人控制台。

显示：

```text
行动原文
Intent Contract
规则计划
隐藏难度
完整骰子
候选和已应用状态
RevealGate
AI 调用状态
来源引用
等待 Host 的重要结果
```

但它也不应默认读取无关的玩家私人笔记。

## 为什么必须拆开

现有 Host 文档把 Host Client 定义为“公共舞台 + 房主控制台”，同时明确玩家私密 patch 不能进入 Host 舞台。Host 公共演出只应消费 reveal/public 事件，`s2c_state_patch`、private notice 和 private completed 等事件应由后端隔离，而不是只靠前端不显示。

建议最终路由也拆开：

```text
/host/{roomId}/stage
/host/{roomId}/console
```

这样 Host 分享屏幕时不会意外剧透。

---

# 十六、Host 展出使用 RevealTransaction

State 成功后，Projection 给 Host Stage 的不是一句自由文本，而是：

# `RevealTransaction`

```json
{
  "transactionId": "tx_481",
  "actionId": "act_01HXYZ",
  "turnId": "turn_12",
  "priority": "normal",
  "baseStateVersion": 84,
  "stateVersion": 85,
  "steps": [
    {
      "stepId": "step_1",
      "type": "action_declaration",
      "publicText": "陈默试图观察馆长听到“北仓库”后的反应。"
    },
    {
      "stepId": "step_2",
      "type": "roll",
      "visibility": "public",
      "payload": {
        "skillLabel": "心理学",
        "roll": 37
      }
    },
    {
      "stepId": "step_3",
      "type": "narrative",
      "publicText": "馆长的手指在账本封面上停顿了一瞬。"
    }
  ],
  "summaryText": "陈默观察了馆长的反应。"
}
```

现有事件契约中：

```text
s2c_action_queued       → Player 行动已入队
s2c_reveal_transaction → Host 演出事务
s2c_state_patch         → Player 私密状态 Patch
s2c_action_completed    → Player 完成回执
s2c_public_observation  → Party 公共叙事
```

并且 `actions` 与 `room_turns` 是事务账本，`events` 只负责投影和审计，不能反过来当未落库状态的唯一事实。

---

# 十七、Host 舞台怎么播放

建议 HostStage 只支持：

```text
播放
暂停
下一步
跳过视觉步骤
重播演出
查看公共摘要
```

不支持：

```text
修改骰子
修改成功等级
直接修改 HP
直接增删线索
通过 ACK 重新裁决
```

建议演出步骤：

```text
1. 玩家行动摘要
2. 目标或冲突对象
3. 骰子 / 检定动画
4. 公开结果
5. 公共叙事
6. 公共状态变化
7. 地图 / 场景 / 媒体变化
8. 完成
```

其中某些步骤可以按房间策略隐藏。

例如隐藏检定：

```text
Host Public Stage：
系统执行了一次隐藏观察检定。

Player 私密端：
你没有获得确定结论。

Host Console：
心理学 45，隐藏困难难度，骰子 37，失败。
```

---

# 十八、Host ACK 只能表示“演出完成”

HostStage 播放完成后发送：

```json
{
  "transactionId": "tx_481",
  "stepId": "step_3",
  "stepIndex": 2
}
```

它只能表示：

> 这一步已经在舞台上播放完成。

不能携带：

```text
骰子结果
State Patch
新的裁决
玩家私密内容
```

当前 Host 契约已经明确：Host ACK 必须绑定 transactionId 和 step，且不承载规则或状态变化；玩家私密结果是否释放，由 Transaction 的 ReleaseGate 决定，而不是 Host 客户端自行决定。

---

# 十九、Player 的结果什么时候释放

建议由 `ReleaseGate` 决定。

例如：

```text
Host Stage 播放行动声明
→ 显示骰子
→ 显示公共结果
→ ReleaseGate 打开
→ Player 收到私密结果和状态 Patch
```

玩家收到：

## 公共结果

```text
馆长听到“北仓库”时短暂停顿。
```

## 本人私密结果

```text
你确认他有反应，但无法判断原因。
```

## 状态回执

```text
状态无变化
```

## 裁决回执

```text
心理学 45
骰子 37
隐藏难度
结果：未获得确定结论
```

Host reveal transaction 本身不能包含完整 Player patch。当前 Transaction 计划也要求 Host reveal 只包含 roll、status 摘要、scene transition 和 narrative 等安全步骤，Player-only patch、private notice 和 completed 应进入 delayed queue 或显式 ReleaseGate。

---

# 二十、不是所有失败都需要在 Host 展出

## 前置条件失败

例如：

```text
目标不在场
玩家没有该物品
当前位置无法到达
```

玩家收到明确错误：

> 馆长当前不在这个场景中，无法观察他的反应。

默认不进入 Host 公共舞台。

---

## AI 理解失败

玩家收到：

> 系统没有可靠理解你的行动，不会消耗本回合。请确认目标或选择结构化动作。

不进入正式 Action。

---

## Rule 拒绝

例如行动不合法：

```text
action rejected
```

可以只给玩家安全回执，必要时给 Host Console 审计。

---

## State 写入失败

必须：

```text
不发送成功叙事
不发送 action completed=success
不推进状态版本
不重复扣资源
```

---

## Projection 失败

如果 State 已成功：

```text
不重新裁决
不重新写 State
只重放 Projection
```

---

# 二十一、一个完整示例

玩家输入：

> “我假装翻阅账本，提到北仓库，观察馆长的反应，但我不碰他的私人信件。”

## 1. PlayerActionGateway

确定：

```text
玩家身份：陈默
当前房间：active
当前场景：馆长办公室
当前 turn：collecting
stateVersion：84
```

---

## 2. IntentCompiler

生成：

```text
目标：观察馆长听到北仓库后的反应
方法：翻阅账本作为掩饰
约束：不碰私人信件
对象：馆长
可能机制：心理学
```

---

## 3. 玩家确认

> 你会提到“北仓库”，同时观察馆长的反应。你不会触碰私人信件。

玩家点击确认。

---

## 4. Action 入账

```text
actionId = act_481
status = queued
turnId = turn_12
```

玩家看到：

```text
行动已进入本回合
```

---

## 5. Engine 裁决

读取：

```text
角色心理学 45
馆长在场
当前场景可交互
隐藏难度：困难
```

RuleExecutor：

```text
骰子 37
困难成功线 22
结果：失败
```

---

## 6. State

没有世界数值变化：

```text
StateChangeSet = empty
不推进 stateVersion
```

但 Action 结果和 Journal 仍会记录。

---

## 7. AI Narrator

只允许使用：

```text
馆长存在
玩家提到北仓库
玩家观察到短暂停顿
玩家不能确认真实原因
```

输出：

### 公共

> 陈默随意翻着账本，话题自然地转向了北仓库。馆长的手指在封面上停顿了一瞬。

### 玩家私密

> 你注意到了那一瞬间的停顿，但无法确定这是紧张、意外，还是单纯在回忆什么。

---

## 8. Host Stage

播放：

```text
陈默尝试观察馆长
→ 心理学骰子 37
→ 公共叙事
```

如果房间设置隐藏骰，则不显示数值。

---

## 9. Player

收到：

```text
私密观察结果
裁决回执
action completed
```

---

## 10. Host Console

记录：

```text
玩家原话
Intent Contract
心理学 45
隐藏困难 22
骰子 37
失败
公共文本
私密文本
sourceRefs
actionId / transactionId / eventSequence
```

---

# 二十二、建议的数据对象

## 输入层

```text
PlayerUtteranceDTO
PlayerActionEnvelopeDTO
IntentDraftDTO
IntentContractDTO
IntentConfirmationDTO
```

## 事务层

```text
ActionReceiptDTO
ActionLedgerDTO
TurnBindingDTO
ExecutionPolicyDecisionDTO
```

## 裁决层

```text
MechanicSuggestionDTO
RuleExecutionPlanDTO
RuleResultDTO
ResolutionBundleDTO
AppliedStateChangeDTO
```

## 输出层

```text
NarrativePayloadDTO
HostRevealTransactionDTO
PlayerResolutionReceiptDTO
PartyObservationDTO
HostReviewPacketDTO
```

## 审计层

```text
ActionTraceDTO
AIProviderResultDTO
AICallLogDTO
SpoilerAuditDTO
HostAckDTO
```

完整追踪链：

```text
utteranceId
→ intentId
→ actionId
→ turnId / encounterId
→ transactionId
→ ruleResultId
→ stateVersion
→ eventSequences
→ resolutionReceiptId
```

---

# 二十三、建议的 P0 工程范围

## P0-1：行动接入协议

```text
统一 PlayerActionEnvelope
actionId 幂等
token 反查角色
baseStateVersion
输入模式
```

## P0-2：Intent Compiler

```text
目标
方法
对象
约束
资源
风险
歧义
```

## P0-3：确认策略

```text
低风险自动
中风险预览
高风险强制确认
歧义必须澄清
```

## P0-4：Action Router

```text
Channel
Rule Question
普通 Action
Map
Item
Clue
Combat
Safety
```

## P0-5：Engine 执行链

```text
Precondition
MechanicCompiler
RuleExecutor
MutationValidator
StateService
```

## P0-6：统一 ResolutionBundle

所有后续输出必须来自同一个结果包。

## P0-7：Host RevealTransaction

```text
安全步骤
公共叙事
公开骰子
公共状态摘要
媒体候选
```

## P0-8：Player 私密回执

```text
state patch
private narrative
rule receipt
action completed
```

## P0-9：Host Stage / Console 分离

公共舞台不显示私密和真相。

## P0-10：重连和恢复

```text
Action 状态
当前 Presentation step
stateVersion
delayed events
```

---

# 二十四、最关键的验收测试

```text
1. Party 讨论不会自动创建 Action。
2. OOC 不会进入 Rule 或 State。
3. 请求体伪造 characterId 不生效。
4. 玩家文本中的 skillValue 不会覆盖服务器角色值。
5. 同一 actionId 重试不会重复入队。
6. 高影响行动未确认前不会执行。
7. AI IntentCompiler 不能读取隐藏真相。
8. AI MechanicSuggestion 不能提供权威骰子和成功等级。
9. RuleExecutor 才能生成权威结果。
10. State 写入失败时不发送成功叙事。
11. State 成功后才发送 state patch 和 completed。
12. Host RevealTransaction 不含 Player 私密 Patch。
13. Host Public Stage 不显示 player-only 内容。
14. Player A 的 private result 不发给 Player B。
15. Host ACK 不能触发新的规则裁决。
16. Host ACK 不携带状态变化。
17. AI 叙事与 RuleResult 冲突时必须拒绝或重写。
18. AI Provider 失败时使用确定性 fallback。
19. Projection 失败只能重放，不能重新写 State。
20. Player 重连后恢复 queued/resolving/completed 状态。
21. Host 重连后不会重复播放已 ACK 的步骤。
22. actionId、transactionId、stateVersion、eventSequence 可以互相追溯。
```

---

# 最终定义

> **AIKP 接收玩家行动时，首先把玩家原话作为不可信但必须保留的输入，经身份校验、模式分类、实体绑定和意图编译形成可确认的 Intent Contract；确认后的行动进入 Engine 管理的事务链，由 RuleExecutor 使用服务器权威角色、物品、场景和规则完成裁决，StateService 原子提交世界变化。AIKP 只能基于已提交结果生成公共与私密叙事，Projection 再拆分为 Host 公共舞台、Player 私密终端、Party 公共信息流和 Journal 审计视图。Host Stage 只负责安全演出，Host Console 才负责复核与监管；两者都不能绕过 Engine 修改裁决或状态。**

这条链路可以最终浓缩成：

```text
玩家负责表达意图
AIKP 负责理解和叙事
Engine 负责编排
Rule 负责裁决
State 负责事实
Projection 负责视角
Host 负责演出和复核
Journal 负责证据
```