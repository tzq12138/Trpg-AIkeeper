# AIKP 玩家行动编排与 Host 演出系统 PRD V1.0

> 文档类型：跨模块核心链路 PRD  
> 建议英文名：Player Action Orchestration Protocol  
> 建议中文名：玩家行动编排与 Host 演出协议  
> 当前阶段：P0 主链路设计 + 行动理解、权威裁决、分层回复与 Host 演出风险识别版

---

## 1. 当前阶段说明

本 PRD 定义 AI-Keeper 如何接收玩家输入，将其转换为可确认的行动意图，经 Engine、Rule、State、Transaction、Projection、Safety、Journal 等模块完成权威裁决，并分别向 Player、Party、Host Stage、Host Console 输出符合权限的结果。

本 PRD 描述的是**目标产品契约**，不代表现有代码已经完整实现。工程执行时必须先复核仓库真实代码、事件类型、接口和测试，再按批次落地。

本协议是跨模块主链路，不替代以下模块：

- Player Client：玩家输入、确认、状态展示与重连；
- AI-Keeper：意图理解、机制建议、叙事生成；
- Rule：权威规则数学与骰子结果；
- Transaction：行动幂等、回合归属、执行顺序与释放屏障；
- State：权威世界状态写入与版本；
- Projection / Safety：分层可见性、反剧透与事件投递；
- Host Client：公共舞台演出、监管与复核；
- Journal：证据链、回放和审计。

---

## 2. 背景

AI-Keeper 的核心体验不是“玩家发一句话，AI 回一句话”，而是把玩家的自然语言表达安全地推进成一条可追踪、可复核的跑团事务：

```text
玩家表达
→ 系统理解
→ 玩家确认
→ 行动入账
→ Engine 选择执行路径
→ Rule 权威裁决
→ State 持久化
→ AI 生成受约束叙事
→ Projection 分层投影
→ Host 舞台演出
→ Player / Party 收到结果
→ Journal 沉淀证据链
```

如果缺少统一协议，会出现以下风险：

- 队伍讨论、玩笑或规则提问被误当成行动；
- AI 自行选择技能、难度、骰子和结果；
- 玩家请求体里的伪造数值覆盖服务器角色卡；
- AI 叙事先宣布成功，State 后续写入失败；
- Host 公共舞台收到玩家私密结果；
- Player、Host、Journal 分别生成不同版本的剧情；
- 重试、断线、重复点击导致重复扣血、重复发线索或重复演出；
- Host ACK 被误当成规则确认或状态写入入口；
- AI Provider 故障导致整条跑团主链路中断。

因此需要一套明确的“玩家行动编排协议”，将输入、意图、行动、规则、状态、叙事、投影和演出严格分层。

---

## 3. 产品定位

本系统负责：

1. 接收玩家的文本、语音确认文本、快捷动作、技能点击、物品操作、地图移动等输入；
2. 判断输入模式，避免聊天、OOC、规则问题被误执行；
3. 使用 AIKP 将自然语言编译成可确认的 `IntentContract`；
4. 根据风险、歧义和影响等级决定自动确认、轻量确认、强制确认或澄清；
5. 将确认后的行动交给 Engine，并绑定 action、turn 或 encounter；
6. 使用 RuleExecutor 产生权威规则结果；
7. 使用 StateService 原子提交权威世界变化；
8. 使用同一个 `ResolutionBundle` 生成不同视角的安全结果；
9. 将公共结果发送到 Host Stage 演出，将复核信息发送到 Host Console；
10. 将本人私密结果、Party 公共结果和审计记录分别投影到正确出口；
11. 支持失败、重试、断线、重连、降级和复核。

本系统不负责：

- 直接定义具体规则数学；
- 让 AI 生成权威骰子或状态；
- 让 Host 前端直接修改 HP、SAN、物品、线索、地图或真相；
- 让聊天自动成为世界事实；
- 让 Projection 自己决定事实是否成立；
- 让 Journal 补写未发生的剧情；
- 让 Host Stage 读取完整玩家私密信息或完整模组真相。

---

## 4. 核心产品原则

### 4.1 玩家原话必须保留

玩家的原始表达是后续复核、纠错和审计的基础。系统可以生成摘要，但不能只保存 AI 摘要而丢弃原话。

### 4.2 输入、意图、行动、结果必须分层

```text
PlayerUtterance
≠ IntentDraft
≠ ConfirmedIntent
≠ ActionLedger
≠ RuleResult
≠ AppliedStateChange
≠ Narrative
```

任何上游对象都不能被当成下游权威事实。

### 4.3 AI 负责理解与表达，不负责权威裁决

AIKP 可以：

- 识别目标、方法、对象、约束和条件；
- 提出机制建议；
- 生成公共和私密叙事；
- 提出状态变化候选。

AIKP 不可以：

- 生成权威骰子；
- 接受玩家自报的技能值作为权威值；
- 直接写数据库；
- 直接修改 HP、SAN、Luck、物品、地图、线索或世界真相；
- 将玩家猜测升级成确认事实。

### 4.4 权威状态必须先持久化，再对外投影

```text
RuleResult
→ StateService.apply_change
→ AppliedStateChange
→ Projection
```

禁止先向 Player 或 Host 宣布成功，再回头尝试写 State。

### 4.5 所有视角必须源于同一个 ResolutionBundle

Host、Player、Party、Journal 不得分别自由生成不同结果。它们都从同一个权威结果包派生，只在字段和叙事可见范围上不同。

### 4.6 Host Stage 与 Host Console 必须分离

- Host Stage：可投屏的公共舞台，只显示公开、安全、已允许演出的内容；
- Host Console：Host 私人监管与复核界面，显示规则计划、隐藏难度、来源和待处理节点。

### 4.7 机械变化可以补偿，信息泄露不可补偿

错误 HP、弹药、位置等可以通过补偿事务修正；隐藏真相、核心线索和玩家秘密一旦公开，无法真正回收。因此敏感信息必须在 Projection 前通过 RevealGate / Safety Gate。

### 4.8 故障不能伪装成角色失败

AI schema 错误、Provider 超时、State 写入失败、Projection 失败、网络超时必须与游戏内失败明确区分。

---

## 5. 产品目标

### 5.1 P0 目标

1. 玩家每次正式行动都有唯一 `actionId`；
2. 系统能可靠区分行动、发言、队伍讨论、OOC、规则提问、私人笔记、线索分享和物品操作；
3. AIKP 能生成结构化 `IntentContract`，但不能直接执行；
4. 高影响行动在确认前不会进入正式事务；
5. Engine 使用服务器权威角色、物品、场景和状态数据；
6. RuleExecutor 产生权威规则结果；
7. State 成功后才产生完成回执和状态投影；
8. Host RevealTransaction 不包含玩家私密 Patch；
9. Host Stage 只演出公共安全内容；
10. Player 能看到行动从提交到完成的清晰状态；
11. 重试、重复点击和重连不会重复执行；
12. AI 不可用时仍可通过确定性降级继续主链路。

### 5.2 长期目标

- 支持复杂复合行动、条件行动、准备动作和协作行动；
- 支持异步回合与 Host 离线自治策略；
- 支持多规则系统统一行动协议；
- 支持 Host 复核、原骰重算、补偿事务和新历史分支；
- 支持 AI 主导节奏但不替玩家作出选择。

---

## 6. 非目标

本轮不实现：

- 完整自主 AI 主持；
- 让 AI 在没有 Engine 的情况下独立裁决；
- 完整多规则平台抽象；
- 完整网格战棋；
- 多 Host 协同导演；
- 复杂多 Agent 自治；
- 观众直播流；
- 通过删除历史修正错误；
- 让客户端本地状态成为权威状态。

---

## 7. 用户角色与权限边界

| 角色 | 可以做 | 不可以做 |
| --- | --- | --- |
| Player | 表达行动、确认意图、使用自己的资源、接收本人和公共结果、提出复核 | 直接写状态、伪造角色、提交权威骰子或技能值、读取他人私密结果 |
| Party | 确认队伍共同目标、投票、讨论、共享公共线索 | 由 AI 代替作出队伍选择 |
| Host | 监管流程、播放公共结果、查看 Host Console、复核重要节点 | 在前端直接改写规则结果或状态、把 Host-only 内容投到公共舞台 |
| AI-Keeper | 理解意图、提出机制建议、生成叙事、检索授权上下文 | 直接写状态、生成权威骰子、修改 Module 真相、泄露未解锁信息 |
| Engine | 校验流程、选择执行路径、编排 Rule/State/Projection | 信任未经校验的 AI JSON 直接执行 |
| Rule | 产生权威规则结果 | 写数据库、决定可见性、生成世界真相 |
| State | 持久化已确认变化、管理 stateVersion | 决定行动是否成功、决定玩家可见范围 |
| Projection / Safety | 分层裁剪与投递、反剧透 | 修改规则和状态结果 |
| Journal | 沉淀证据和回放 | 补写规则结果、改写世界事实 |

---

## 8. 总体架构

```text
Player Client
    │
    ▼
PlayerActionGateway
    │ 身份 / 幂等 / 房间 / 版本校验
    ▼
UtteranceRouter
    │ 输入模式分类
    ├── Channel / OOC / Note / Rule Question
    └── Formal Action
            │
            ▼
       IntentCompiler (AIKP)
            │
            ▼
       ConfirmationPolicy
            │
            ▼
       ActionLedger / Turn / Encounter
            │
            ▼
       ExecutionPolicyManager
            │
            ▼
       MechanicCompiler
            │
            ▼
       RuleExecutor
            │
            ▼
       MutationValidator
            │
            ▼
       StateService
            │
            ▼
       ResolutionBundle
            │
       ┌────┼───────────┬──────────────┐
       ▼    ▼           ▼              ▼
Narrative  Projection  Host Reveal   Journal
Composer   / Safety    Transaction    / Audit
       │                  │
       ▼                  ▼
 Player / Party       Host Stage
                        + Host Console
```

---

## 9. 玩家输入模式

系统至少支持以下 `inputMode`：

| 模式 | 示例 | 是否创建正式 Action |
| --- | --- | ---: |
| `action` | “我检查地下室入口有没有脚印。” | 是 |
| `speech` | “教授，你昨晚在哪里？” | 视房间策略，可生成对话行动 |
| `party_chat` | “我们要不要先查护士？” | 否 |
| `ooc` | “我去拿杯水。” | 否 |
| `rule_question` | “心理学能判断他说谎吗？” | 否 |
| `private_note` | “我怀疑护士在隐瞒。” | 否 |
| `clue_share` | “我把处方内容告诉大家。” | 走 Clue Share 事务 |
| `item_action` | “我用急救包给安娜处理伤口。” | 走 Item / Rule / State |
| `map_move` | “我移动到档案室门口。” | 走 Map / Engine / State |
| `combat_action` | “我躲到门后准备射击。” | 走 Encounter Runtime |
| `safety` | X-card、fade、private feedback | 走 Safety Event，不直接改 State |

### 9.1 模式识别规则

- 客户端显式模式优先；
- AI 可提出模式修正建议；
- 疑问、建议、假设、玩笑、OOC 不得自动升级为正式行动；
- 高影响模式识别不确定时必须澄清；
- `party_chat`、`ooc`、`private_note` 不进入 Rule、State 或世界事实链。

---

## 10. 数据分层

| 层级 | 对象 | 含义 | 禁止混用 |
| --- | --- | --- | --- |
| L0 | `PlayerUtterance` | 玩家原始表达 | 不等于行动 |
| L1 | `IntentDraft` | AIKP 初步理解 | 不等于玩家确认 |
| L2 | `ConfirmedIntent` | 玩家或策略确认后的意图合同 | 不等于已入账 Action |
| L3 | `ActionLedger` | 正式行动事务 | 不等于规则结果 |
| L4 | `MechanicSuggestion` | AI 机制建议 | 不等于权威 Rule Plan |
| L5 | `RuleExecutionPlan` | Engine 校验后的规则执行计划 | 尚未掷骰 |
| L6 | `RuleResult` | 权威规则结果 | 尚未写入 State |
| L7 | `AppliedStateChange` | 已落库的权威变化 | Projection 只能消费此层 |
| L8 | `ResolutionBundle` | 统一输出源 | 不直接等于任一客户端视图 |
| L9 | `ProjectionEnvelope` | 按视角裁剪的事件 | 不修改事实 |
| L10 | `PresentationState` | Host 舞台播放进度 | 不等于世界状态 |
| L11 | `JournalTrace` | 审计和回放证据链 | 不补写事实 |

---

## 11. 核心数据对象与 DTO

### 11.1 `PlayerActionEnvelopeDTO`

```json
{
  "actionId": "act_01HXYZ",
  "roomId": "room_001",
  "inputMode": "action",
  "source": "text",
  "rawText": "我假装翻阅账本，提到北仓库，观察馆长的反应，但不碰私人信件。",
  "baseStateVersion": 84,
  "requestedVisibility": "scene_public",
  "clientSequence": 251,
  "attachments": []
}
```

客户端不得把以下字段作为权威输入：

```text
characterId
skillValue
roll
successLevel
currentHP
targetDifficulty
```

### 11.2 `ActionReceiptDTO`

```json
{
  "actionId": "act_01HXYZ",
  "status": "received",
  "receivedAt": "...",
  "baseStateVersion": 84,
  "executionMode": "turn_collecting"
}
```

### 11.3 `IntentContractDTO`

```json
{
  "intentId": "intent_481",
  "actionId": "act_01HXYZ",
  "actionType": "observe_reaction",
  "goal": "判断馆长听到北仓库后的情绪反应",
  "method": "假装翻阅账本，并在谈话中提及北仓库",
  "targetRefs": [
    {"type": "npc", "id": "npc_curator"}
  ],
  "constraints": ["不触碰私人信件"],
  "resources": [],
  "visibility": "scene_public",
  "conditions": [],
  "assumptions": ["馆长可以听见玩家提到北仓库"],
  "ambiguities": [],
  "impactLevel": "medium",
  "suggestedMechanics": ["psychology"],
  "requiresConfirmation": true
}
```

### 11.4 `ExecutionPolicyDecisionDTO`

```json
{
  "actionId": "act_01HXYZ",
  "route": "turn_action",
  "confirmationMode": "light_preview",
  "hostGate": "none",
  "autonomyClass": "A2",
  "reasonCodes": ["ordinary_skill_check"]
}
```

### 11.5 `RuleExecutionPlanDTO`

```json
{
  "rulePackage": "coc7e@1.0.0",
  "checkType": "skill_check",
  "skillId": "psychology",
  "skillValue": 45,
  "skillValueSource": "character_rule_snapshot",
  "difficulty": "hard",
  "difficultyVisibility": "host_only",
  "modifiers": [],
  "rollVisibility": "public"
}
```

### 11.6 `ResolutionBundleDTO`

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

### 11.7 `HostRevealTransactionDTO`

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
      "publicText": "陈默试图观察馆长听到北仓库后的反应。"
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

### 11.8 `PlayerResolutionReceiptDTO`

```json
{
  "actionId": "act_01HXYZ",
  "transactionId": "tx_481",
  "status": "completed",
  "confirmedIntentSummary": "观察馆长听到北仓库后的反应",
  "mechanicSummary": {
    "skillLabel": "心理学",
    "skillValue": 45,
    "roll": 37,
    "difficultyVisibility": "hidden",
    "resultLabel": "未获得确定结论"
  },
  "privateText": "你注意到短暂停顿，但无法确定原因。",
  "stateChanges": [],
  "stateVersion": 85,
  "reviewAvailable": true
}
```

### 11.9 `HostAckDTO`

```json
{
  "transactionId": "tx_481",
  "stepId": "step_3",
  "stepIndex": 2,
  "actorAccountId": "acct_host"
}
```

Host ACK 只能表示舞台步骤已播放，不能携带规则结果、状态变化或玩家私密内容。

---

## 12. 状态机

### 12.1 Intent 状态机

```text
received
→ parsing
→ needs_clarification
→ awaiting_confirmation
→ confirmed
→ cancelled
→ expired
```

### 12.2 Action 状态机

```text
submitted
→ queued
→ resolving
→ resolved

submitted
→ rejected

queued / resolving
→ timeout
→ cancelled
```

推荐客户端展示状态：

```text
submitting
received
understanding
needs_clarification
awaiting_confirmation
queued
resolving
waiting_for_stage
completed
rejected
timeout
sync_required
```

### 12.3 Host Presentation 状态机

```text
pending
→ queued
→ active
→ waiting_ack
→ completed

active
→ paused
→ replaying

异常：
→ failed
→ recovery_required
```

### 12.4 ReleaseGate 状态机

```text
closed
→ eligible
→ released

closed
→ deferred_for_host
→ released / rejected
```

---

## 13. 端到端核心流程

### 13.1 接收与即时回执

1. Player 提交 `PlayerActionEnvelopeDTO`；
2. `PlayerActionGateway` 校验 token、角色、房间、状态、actionId、stateVersion 和速率；
3. 立即返回 `ActionReceiptDTO(status=received)`；
4. 该回执不依赖 AI Provider。

### 13.2 输入模式分类

1. 优先使用客户端显式 `inputMode`；
2. AIKP 可以提出模式修正；
3. `party_chat/ooc/rule_question/private_note` 不进入正式 Action；
4. 模式不确定且影响较高时，返回澄清问题。

### 13.3 意图编译

AIKP 只读取：

- 玩家原话；
- 本人角色安全视图；
- 当前可见场景；
- 当前可见 NPC、物品、地图和线索；
- 当前规则包摘要；
- 房间确认策略。

AIKP 不读取：

- 完整 truth；
- ending；
- 未发现线索；
- 隐藏 NPC；
- 其他玩家私密行动；
- Host 私密笔记。

输出 `IntentContractDTO`。

### 13.4 确认与澄清

系统根据影响等级决定：

- 自动确认；
- 轻量预览；
- 强制确认；
- 必须澄清。

只有 `confirmed` 的 Intent 才能进入正式 Action 事务。

### 13.5 Action 入账与执行路由

1. 以 `actionId` 做幂等写入；
2. 根据当前场景选择即时 action、turn action、encounter action、decision window、party decision 或 Host review；
3. active turn 中先完成 duplicate 校验，再写入 action；
4. action 入队不推进世界 `stateVersion`。

### 13.6 裁决上下文构造

Engine 构造：

- `CharacterRuleSnapshot`；
- `InventoryCapabilityView`；
- `SceneInteractionView`；
- `ModuleRuntimeView`；
- `RoomPolicySnapshot`；
- `KnowledgeView`。

所有数据来自服务端权威来源和当前版本。

### 13.7 机制编译与规则执行

1. AIKP / MechanicCompiler 提供机制建议；
2. Engine 验证技能、目标、前置条件、资源、范围和规则版本；
3. RuleExecutor 生成权威骰子、成功等级和 RuleResult；
4. AI 不得覆盖 RuleResult。

### 13.8 State 提交

1. RuleResult 转成受控 StateChangeSet；
2. MutationValidator 检查目标、权限、版本和允许写入类型；
3. StateService 原子提交；
4. 无实际 mutation 时默认不推进世界版本；
5. State 失败时 action 不得显示成功。

### 13.9 统一结果包

State 成功后生成 `ResolutionBundleDTO`，作为：

- Host RevealTransaction；
- Player ResolutionReceipt；
- Party PublicObservation；
- Journal Trace；
- Host Review Packet

的唯一来源。

### 13.10 AI 叙事生成

NarrativeComposer 只读取：

- ConfirmedIntent；
- RuleResult；
- AppliedStateChange；
- allowedFacts；
- forbiddenClaims；
- 当前目标视角。

输出：

```text
publicText
privateTexts
keeperNotes
```

公共文本必须经过 SpoilerGuard；私密文本按角色投影；keeperNotes 只进受控 Host Console / Audit。

### 13.11 Host 演出与 Player 释放

1. Host Stage 收到 `HostRevealTransactionDTO`；
2. 按步骤播放行动声明、骰子、公共结果、叙事和媒体；
3. Host ACK 只确认播放进度；
4. Transaction 根据 ReleaseGate 释放 Player 私密 Patch 和 completed；
5. Player 收到本人回执，Party 收到公共观察；
6. Journal 记录完整 trace。

---

## 14. 确认策略

| 风险等级 | 示例 | 默认策略 |
| --- | --- | --- |
| `none` | OOC、规则提问、私人笔记 | 不进入正式 Action |
| `low` | 查看公开物体、无风险发言、已揭示区域普通移动 | 自动确认，可短暂撤回 |
| `medium` | 普通检定、公开提问、可逆互动 | 轻量预览 |
| `high` | 消耗资源、攻击、分享私密线索、物品转移、危险移动 | 强制确认 |
| `critical` | 角色死亡风险、摧毁关键物品、重大不可逆决定 | 强制确认，并可能进入 Host Gate |

以下行为必须强制确认：

- 消耗 Luck 或稀缺资源；
- 使用有限次数道具；
- 攻击友方；
- 公开私密线索；
- 转移或销毁重要物品；
- 影响其他玩家角色；
- 不可逆剧情决定；
- 重大地图、战斗或方向变化。

---

## 15. Engine 执行路由

| 场景 | Route |
| --- | --- |
| 普通调查自由场景 | `immediate_action` |
| 全员提交回合 | `turn_action` |
| 战斗 / 追逐 | `encounter_action` |
| 等待防御、反应或花费资源 | `decision_window` |
| 队伍共同选择 | `party_decision` |
| Host 离线但低风险 | `offline_autonomy` |
| Host 离线且重要结果 | `deferred_host_review` |
| 规则提问 | `rule_query` |
| OOC / Note / Party Chat | `non_state_event` |

路由决策必须是结构化对象，不允许由自由文本直接执行。

---

## 16. Rule 与 State 边界

### 16.1 AI 机制建议可以包含

```text
check type
skill name
suggested difficulty
reason
alternative mechanics
```

### 16.2 AI 机制建议不得包含权威

```text
roll
skillValue
targetValue
successLevel
finalDamage
finalHP
```

### 16.3 RuleExecutor 负责

- 骰子；
- 目标值；
- 成功等级；
- 对抗结果；
- 伤害和资源数学；
- 规则来源；
- State mutation 候选。

### 16.4 StateService 负责

- HP、SAN、MP、Luck；
- 状态标签；
- 地图和场景；
- 物品数量和归属；
- 线索实例和分享结果；
- stateVersion；
- AppliedStateChange。

---

## 17. 叙事与 Projection

### 17.1 公共叙事

只能表达：

- 已提交的事实；
- 当前公共视角允许看到的结果；
- RuleResult 和 State 已确认的变化；
- 不泄露原因、真相或隐藏数值的安全表现。

### 17.2 私密叙事

可以表达：

- 当前角色独有观察；
- 本人私密状态；
- 个人检定结果；
- 本人获得但未分享的线索。

### 17.3 Host 复核信息

可以包含：

- 隐藏难度；
- 完整 Rule Plan；
- RevealGate；
- 候选与已应用 State Change；
- AI Provider 状态和来源；
- 待 Host 决定的重要结果。

### 17.4 禁止混用

- `privateTexts` 不得合并进 `publicText`；
- Host Stage 不得收到完整 Player Patch；
- PublicObservation 不得包含 keeperNotes；
- Journal public view 不得读取 Host Review 数据。

---

## 18. Host Stage 与 Host Console

### 18.1 Host Stage

产品定位：可信公共舞台，可用于投屏和共享屏幕。

显示：

- 公共行动摘要；
- 公开骰子与检定；
- 公共叙事；
- 公共状态变化；
- 已揭示地图和场景；
- 安全的 BGM、SFX、图片和视觉效果。

不显示：

- 玩家私密结果；
- 隐藏难度；
- 敌人真实 HP；
- 未发现线索；
- Host-only truth；
- AI raw prompt / response；
- 完整规则内部参数。

允许操作：

```text
播放
暂停
下一步
跳过视觉步骤
重放演出
查看公共摘要
```

禁止操作：

```text
修改骰子
修改成功等级
直接修改 HP/SAN
直接增删线索
通过 ACK 发起新裁决
```

### 18.2 Host Console

产品定位：Host 私人监管与复核终端。

显示：

- 玩家原话；
- Intent Contract；
- RuleExecutionPlan；
- 隐藏难度与完整骰子；
- State Before / Candidate / Applied；
- RevealGate；
- AI 调用状态；
- 来源引用；
- ReviewBacklog；
- Player Dispute。

Host Console 仍不默认读取无关玩家私人笔记。

---

## 19. Player 端结果体验

玩家至少需要看到：

```text
已收到
正在理解
需要澄清
等待确认
已入队
正在结算
等待舞台演出
已完成
被拒绝
超时
需要同步
```

完成后展示：

- 系统理解的意图摘要；
- 使用的规则和技能；
- 权威骰子；
- 公开或安全解释后的难度；
- 成功等级或安全结果；
- 状态变化；
- 物品消耗；
- 私密叙事；
- 来源与 transactionId；
- 请求复核入口。

隐藏检定时，透明不等于剧透。玩家可以看到：

> 系统执行了一次隐藏观察检定。你没有获得确定结论。

而不能看到隐藏敌人、秘密难度和完整真相。

---

## 20. Host 在线与离线

### 20.1 Host 在线

- 普通事务按 RoomPolicy 自动或演出；
- 重要节点进入 Host Review / RevealGate；
- Host ACK 只控制演出释放点。

### 20.2 Host 短暂断线

- 进入 grace period；
- 不立即切换自治权限；
- 已提交规则事务可继续到安全 Gate；
- Host 回来后恢复 Stage 和 Console。

### 20.3 Host 计划离线

按 `HostDelegationGrant`：

- 允许普通检定；
- 允许已揭示范围移动；
- 允许普通物品使用；
- 核心线索、新战斗、角色死亡、重大场景转换等待 Host。

### 20.4 Host 意外离线

默认保守：

- A0/A1 功能继续；
- A2 仅允许明确、低风险、可补偿事务；
- 不可收回信息和重大状态停在 Host Gate。

---

## 21. 事件与接口方向

### 21.1 REST / Command

| 接口 | 目标 |
| --- | --- |
| `POST /api/player/intent-drafts` | 提交原始输入，生成意图草稿 |
| `POST /api/player/intents/{intent_id}/confirm` | 确认或修改 Intent |
| `POST /api/player/intents/{intent_id}/cancel` | 取消尚未执行的意图 |
| `GET /api/player/actions/{action_id}` | 查询本人行动状态 |
| `POST /api/player/actions/{action_id}/dispute` | 请求 Host 复核 |
| `GET /api/player/reconnect` | 恢复事件、pending action、stateVersion |
| `GET /api/host/{room_id}/review-backlog` | Host 查看待复核节点 |
| `POST /api/host/{room_id}/reviews/{review_id}` | Host 接受、修正、补偿或拒绝 |

是否拆成多个真实接口，可在工程阶段结合现有 `/api/player/intent` 兼容实现决定。PRD 重点是契约分层，不强制本轮立即改全部路由。

### 21.2 事件

| 事件 | 受众 | 说明 |
| --- | --- | --- |
| `s2c_intent_understanding` | Player | AI 正在理解 |
| `s2c_intent_clarification_required` | Player | 需要澄清 |
| `s2c_intent_confirmation_required` | Player | 需要确认 |
| `s2c_action_queued` | Player | 行动入队 |
| `s2c_action_resolving` | Player | 正在结算 |
| `s2c_reveal_transaction` | Host | Host 公共演出事务 |
| `s2c_public_observation` | Party | 公共叙事 |
| `s2c_state_patch` | Player / safe Party | 已持久化状态 Patch |
| `s2c_private_notice` | 指定 Player | 私密结果 |
| `s2c_action_completed` | Player | 完成或失败回执 |
| `s2c_action_review_pending` | Player / Host | 等待重要复核 |
| `s2c_host_stage_state` | Host | 舞台队列和播放状态 |

所有新增事件必须同步：

```text
registry
后端模型
前端类型
可见性 helper
重连
archive
测试
```

---

## 22. 错误模型

| 错误类 | 玩家表现 | 是否消耗行动 |
| --- | --- | ---: |
| `auth_failed` | 身份失效，请重新进入房间 | 否 |
| `room_not_active` | 当前不能提交正式行动 | 否 |
| `state_conflict` | 状态已更新，需要同步后重新确认 | 否 |
| `intent_ambiguous` | 请确认对象或方法 | 否 |
| `intent_schema_fail` | 系统未可靠理解，不会执行 | 否 |
| `precondition_failed` | 目标不在场、物品不存在等 | 否或按规则 |
| `rule_rejected` | 行动不符合当前规则 | 按规则 |
| `provider_timeout` | AI 理解/叙事降级，不影响权威规则 | 否 |
| `state_apply_failed` | 结算未提交，不显示成功 | 否 |
| `projection_failed` | 结果已保存，正在重新同步显示 | 已提交，不重算 |
| `host_review_required` | 已保存意图，等待 Host 处理重要后果 | 视阶段 |

系统故障不得包装成角色失败。

---

## 23. 安全与隐私要求

1. 服务端通过 token 反查角色，不信任请求体身份字段；
2. Player Prompt 不得包含未发现 truth、clue、hidden NPC、ending、KP-only note；
3. RAG 进入 Prompt 前必须按 viewer、room、scenario、character、visibility、unlock state 二次过滤；
4. Public narrative 必须经过 SpoilerGuard；
5. Host Stage 不接收 player-only payload；
6. Player A 的私密结果不得进入 Player B 的 live、reconnect、archive 或 export；
7. AI raw prompt、raw response、token、API key 不进入 Player Journal 或 public export；
8. Host ACK 不得被 Player 伪造；
9. AI Mutation 不能包含 SQL、JSON Patch 或任意数据库写命令；
10. 所有 write tool 必须走服务层并写审计；
11. 失败与被拒绝的 AI / Agent 调用也要审计；
12. 前端隐藏不构成权限控制。

---

## 24. 降级与容错

### 24.1 AI 意图理解失败

```text
保留原始输入
→ 玩家选择行动类型、目标和技能
→ 或提交给 Host
```

### 24.2 AI 叙事失败

使用确定性模板：

> 你的心理学检定已完成。你没有获得确定结论。

### 24.3 Provider 全部不可用

仍可使用：

- 角色卡和背包；
- 规则查询缓存；
- 确定性骰子；
- 结构化动作；
- 地图移动；
- 队伍讨论；
- Journal 和调查工作台。

### 24.4 State 成功、Projection 失败

- 不重新掷骰；
- 不重新写 State；
- 只重放 Projection；
- Player 重连时恢复最终状态和回执。

### 24.5 Host Stage 故障

- 权威状态不回滚；
- PresentationState 标记 recovery_required；
- Host 可 replay_only；
- Player 私密结果是否释放由 ReleaseGate 决定。

---

## 25. 功能需求

### 25.1 行动接入

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PAO-FR-1 | 所有正式输入必须带唯一 actionId。 | P0 |
| PAO-FR-2 | 服务端必须通过 player token 反查角色身份。 | P0 |
| PAO-FR-3 | 客户端必须携带 baseStateVersion。 | P0 |
| PAO-FR-4 | 服务端应即时返回 received 回执，不等待 AI。 | P0 |
| PAO-FR-5 | 重复 actionId 返回幂等结果，不重复执行。 | P0 |

### 25.2 意图理解与确认

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PAO-FR-6 | 系统必须区分 action、speech、party_chat、ooc、rule_question、private_note。 | P0 |
| PAO-FR-7 | IntentContract 至少包含目标、方法、对象、约束、资源、条件、可见性和歧义。 | P0 |
| PAO-FR-8 | 高影响行动必须确认后才能入账。 | P0 |
| PAO-FR-9 | 高影响实体歧义必须澄清，不得自动猜测。 | P0 |
| PAO-FR-10 | AI 失败时支持结构化手工降级。 | P0 |

### 25.3 执行与裁决

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PAO-FR-11 | Engine 必须根据当前 Scene/Turn/Encounter 选择执行路由。 | P0 |
| PAO-FR-12 | RuleExecutor 读取服务器权威角色和物品值。 | P0 |
| PAO-FR-13 | 玩家文本中的技能值、骰子和成功等级不得成为权威输入。 | P0 |
| PAO-FR-14 | AI 机制建议必须经过 Engine 校验。 | P0 |
| PAO-FR-15 | StateService 成功后才能产生成功投影。 | P0 |

### 25.4 回复与演出

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PAO-FR-16 | 所有视角必须从同一个 ResolutionBundle 派生。 | P0 |
| PAO-FR-17 | publicText 与 privateTexts 必须结构化分离。 | P0 |
| PAO-FR-18 | Host RevealTransaction 不得包含完整 Player 私密 Patch。 | P0 |
| PAO-FR-19 | Host Stage 与 Host Console 必须具有不同 DTO。 | P0 |
| PAO-FR-20 | Host ACK 只表示演出进度。 | P0 |
| PAO-FR-21 | Player 完成回执必须包含 actionId、transactionId 和 stateVersion。 | P0 |

### 25.5 重连、复核和审计

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PAO-FR-22 | Player 重连必须恢复 pending action 和本人可见事件。 | P0 |
| PAO-FR-23 | Host 重连不得重复播放已 ACK 的步骤。 | P1 |
| PAO-FR-24 | 玩家可对误解、错误技能、状态变化和叙事不一致提出复核。 | P1 |
| PAO-FR-25 | 规则重算默认复用原 rollId。 | P1 |
| PAO-FR-26 | 状态修正必须通过补偿事务，不删除历史。 | P1 |
| PAO-FR-27 | action、turn、transaction、stateVersion、event sequence 必须可互相追溯。 | P0 |

---

## 26. 非功能需求

### 26.1 性能

- 接收回执不依赖 AI，目标在正常网络下快速返回；
- AI 理解和叙事应支持超时与 fallback；
- Projection 失败不阻塞权威状态查询；
- Host Stage 播放不应阻塞其他低风险事务入队。

### 26.2 一致性

- `actionId` 幂等；
- `stateVersion` 作为状态屏障；
- `roomSequence` 作为事件顺序；
- 所有客户端只应用服务端确认的状态；
- 已 resolved/rejected action 不重复处理。

### 26.3 可观测性

每条主链路至少记录：

```text
actionId
intentId
turnId / encounterId
transactionId
ruleResultId
baseStateVersion
stateVersion
eventSequences
AI task status
Projection status
```

### 26.4 可恢复性

- Player 可从 reconnect 恢复；
- Host 可恢复 active presentation；
- AI Provider 故障可降级；
- State 成功后 Projection 可单独重放；
- 重大错误可以补偿或从 Checkpoint 建新分支。

---

## 27. 实施优先级

### P0：主链路

```text
统一 PlayerActionEnvelope
actionId 幂等
token 反查角色
输入模式分类
IntentContract
确认策略
Action Router
权威 Rule Plan
RuleExecutor
MutationValidator
State-first
ResolutionBundle
public/private narrative
Host RevealTransaction
Player ResolutionReceipt
Host Stage / Console DTO 分离
ReleaseGate
重连恢复
AI fallback
```

### P1：体验和复核

```text
复合行动拆解
条件行动
替代技能协商
Player Dispute
Host Review Packet
原骰重算
补偿事务
Host Stage active transaction 恢复
异步回合
Host 离线自治策略
```

### P2：高级能力

```text
多人协同行动合同
复杂决策窗口
多规则统一协议
方向控制器深度接入
多 Host
观众延迟流
可视化裁决图
```

---

## 28. 关键指标

| 指标 | 目标方向 |
| --- | --- |
| 行动即时接收成功率 | 高 |
| duplicate 导致重复结算 | 0 |
| 玩家确认后意图被推翻率 | 持续下降 |
| AI 误解复核率 | 持续下降 |
| AI 直接写权威状态 | 0 |
| State 失败却显示成功 | 0 |
| Projection 失败导致重复 State mutation | 0 |
| Host Stage 私密泄露 | 0 |
| Player 间私密泄露 | 0 |
| 无解释规则结果比例 | 接近 0 |
| Host 回来后定位重要节点时间 | 持续下降 |
| AI Provider 故障导致整桌停摆率 | 接近 0 |

建议体验目标：

> 玩家在 10 秒内完成自然语言行动声明与必要确认，并在结果完成后快速看懂系统理解了什么、采用了什么规则、发生了什么状态变化。

---

## 29. 核心验收测试

```text
1. Party 讨论不会自动创建 Action。
2. OOC 不进入 Rule 或 State。
3. 请求体伪造 characterId 不生效。
4. 玩家文本中的 skillValue 不覆盖服务器角色值。
5. 同一 actionId 重试不重复入队、掷骰、扣资源或投影。
6. 高影响行动未确认前不会执行。
7. AI IntentCompiler 不能读取隐藏 truth、ending 或未发现 clue。
8. AI MechanicSuggestion 不能输出权威 roll 或 successLevel。
9. RuleExecutor 才能生成权威规则结果。
10. State 写入失败时不发送成功叙事和 completed=success。
11. State 成功后才发送 state patch 和 action completed。
12. Host RevealTransaction 不含完整 Player 私密 Patch。
13. Host Public Stage 不显示 player-only 内容。
14. Player A 的 private result 不发给 Player B。
15. Host ACK 不能触发新规则裁决或状态 mutation。
16. AI 叙事与 RuleResult 冲突时被拒绝或安全重写。
17. AI Provider 失败时使用确定性 fallback。
18. Projection 失败只能重放，不重新写 State。
19. Player 重连恢复 queued/resolving/completed 和 stateVersion。
20. Host 重连不重复播放已 ACK 步骤。
21. 隐藏检定透明但不泄露隐藏难度和真相。
22. 玩家提出复核后，Host 能看到原话、Intent、Rule Plan、State Diff 和来源。
23. 规则参数错误时可复用原骰重算。
24. 状态修正通过补偿事务，不删除原事件。
25. actionId、transactionId、stateVersion、eventSequence 可互相追溯。
```

---

## 30. 完整示例

玩家输入：

> “我假装翻阅账本，提到北仓库，观察馆长的反应，但我不碰他的私人信件。”

### 30.1 接入

```text
身份：陈默
房间：active
当前场景：馆长办公室
当前 turn：collecting
stateVersion：84
```

系统立即返回：

> 已收到行动，正在理解你的意图。

### 30.2 意图合同

```text
目标：观察馆长听到北仓库后的反应
方法：翻阅账本作为掩饰
约束：不碰私人信件
对象：馆长
建议机制：心理学
影响等级：中
```

玩家点击确认。

### 30.3 Action 入账

```text
actionId = act_481
status = queued
turnId = turn_12
```

### 30.4 Rule 裁决

```text
心理学：45
隐藏难度：困难，目标 ≤ 22
服务器骰子：37
结果：失败
```

### 30.5 State

没有世界状态变化，因此：

```text
StateChangeSet = empty
stateVersion 不推进
```

Action 和 Journal 仍记录结果。

### 30.6 AI 叙事

公共：

> 陈默随意翻着账本，话题自然地转向北仓库。馆长的手指在封面上停顿了一瞬。

玩家私密：

> 你注意到那一瞬间的停顿，但无法确定这是紧张、意外，还是单纯在回忆什么。

AI 不得输出：

> 馆长正在撒谎。

因为规则结果和当前证据没有确认这一点。

### 30.7 Host Stage

播放：

```text
玩家行动摘要
→ 心理学骰子 37（若房间策略允许公开）
→ 公共叙事
```

### 30.8 Player 回执

```text
行动完成
技能：心理学 45
骰子：37
难度：隐藏
结果：未获得确定结论
状态变化：无
```

### 30.9 Host Console

显示：

```text
玩家原话
确认后的 IntentContract
心理学 45
困难目标 22
骰子 37
RuleResult=failure
publicText
privateText
sourceRefs
actionId / transactionId / eventSequence
```

---

## 31. 与现有模块的接口

| 模块 | 本协议依赖 | 本协议保证 |
| --- | --- | --- |
| User | account/player/owner 身份 | 不信任前端 characterId |
| Room | 房间状态、成员、当前 Session | 不改变 Room 生命周期 |
| Channel | 输入模式和消息事件 | 聊天不自动变成事实 |
| Character | 规则快照和 runtime | 不信任客户端技能值 |
| Item / Clue | 物品能力、线索分享 | 分享、转移、使用分别走受控事务 |
| Rule | RuleExecutionPlan / RuleResult | 不修改规则数学 |
| AI-Keeper | Intent / Mechanic / Narrative | AI 始终停在建议与表达层 |
| State | AppliedStateChange / stateVersion | State 成功后才投影 |
| Transaction | action/turn/transaction/release gate | 幂等、顺序和恢复 |
| Projection / Safety | 分层 DTO、SpoilerGuard | Host/Player/Party 不越权 |
| Host Client | RevealTransaction / ACK / Review | Host 只演出和复核 |
| Player Client | Intent 确认、状态展示、重连 | Player 以服务端结果为准 |
| Journal | sourceRefs / event sequence | 全链路可追溯 |

---

## 32. 全局禁止事项

```text
禁止把玩家所有文本都当成行动。
禁止让 AI 直接掷权威骰。
禁止使用玩家自报的技能值作为权威值。
禁止 AI 直接写 HP、SAN、Luck、物品、地图、线索或真相。
禁止 State 落库前发送成功结果。
禁止 Host Stage 收到完整 Player 私密 Patch。
禁止 Host ACK 承载规则结果或状态 mutation。
禁止 Projection 失败后重新执行 Rule 或 State。
禁止重连后重复应用已完成 action。
禁止通过删除历史修正错误。
禁止把 private narrative 合并进 public narrative。
禁止让 AI Provider 成为主链路单点故障。
禁止仅依赖前端隐藏保护 Host-only / player-only 内容。
```

---

## 33. 最终产品定义

> AI-Keeper 接收玩家行动时，首先把玩家原话作为必须保留但不具备权威性的输入，经身份校验、模式分类、实体绑定和意图编译形成可确认的 Intent Contract；确认后的行动进入 Engine 管理的事务链，由 RuleExecutor 使用服务器权威角色、物品、场景和规则完成裁决，StateService 原子提交世界变化。AI-Keeper 只能基于已提交结果生成公共与私密叙事，Projection 再拆分为 Host 公共舞台、Host 私人控制台、Player 私密终端、Party 公共信息流和 Journal 审计视图。Host Stage 只负责安全演出，Host Console 负责复核与监管；两者都不能绕过 Engine 修改裁决或状态。

最终主链路：

```text
玩家负责表达意图
AIKP 负责理解和叙事
Engine 负责编排
Rule 负责裁决
State 负责事实
Transaction 负责顺序与释放
Projection / Safety 负责视角
Host 负责演出与复核
Journal 负责证据
```
