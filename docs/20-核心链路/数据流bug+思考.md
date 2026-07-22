设计这种高度解耦的异步流水线时，最隐蔽的 Bug 往往不会出现在“正常流程”里，而是出现在**状态错位与异步时序差**中。这非常像在处理非标自动化系统时，如果图像采集触发点和后端的 AI 识别逻辑之间存在微小的时序偏差，就会导致物料标签和二维码信息发生“错位关联”，最终引起整个逻辑链条的失效。

在我们的 TRPG 引擎中，玩家的每一次操作就是一次“采集触发”，而复杂的跑团状态树就是我们需要对齐的“物料”。

如果我们将整个“上行意图 $\rightarrow$ 规则判定 $\rightarrow$ LLM 生成 $\rightarrow$ 投影分发 $\rightarrow$ 端侧渲染”的全局数据流放在极限压力下推演，目前的设计中至少还潜伏着 **4 个可能导致“状态错位”的架构级 Bug**：

### 🐛 Bug 1：规则引擎与 LLM 之间的“事实时差 (Fact Lag)”

**场景推演**：

1. 玩家受到重击，只剩 1 点 HP。他试图跳窗逃跑。
    
2. Python 规则引擎暗骰判定失败，触发摔伤，扣除 2 点 HP。
    
3. 此时，规则引擎在内存中将玩家 HP 扣至 -1（触发“濒死/昏迷”状态）。
    
4. 引擎将“检定失败，扣 2 滴血”这个事实喂给 LLM，让其生成叙事。
    
5. **致命断层**：如果 LLM 只知道“扣了 2 滴血”，它可能会生成：“你重重地摔在地上，擦破了皮，但你咬着牙重新站了起来，准备继续奔跑。”——**但此时玩家在系统里已经是个死人/昏迷者了！**
    

**修复方案（注入级联状态）**：

Python 规则引擎在执行完绝对数学裁决后，必须将级联产生的状态变更（State Mutations）一并打包给 LLM。

Prompt 的输入除了 `[事实: 摔伤扣除 2 HP]`，必须追加强制系统提示：`[系统状态变更: 玩家 A 的 HP 归零，现已进入"昏迷"状态，失去行动能力]`。强迫大模型的叙事必须以玩家昏倒作为结尾。

### 🐛 Bug 2：“私密获取”与“大屏公开演出”的时序穿透 (Spoiler Leak)

**场景推演**：

1. 玩家 A 在众目睽睽之下撬开了一个保险箱（公开检定）。
    
2. 保险箱里是一把私密的手枪。
    
3. Engine 处理完毕，同时下发投影：
    
    - 向 Host 大屏发送 `s2c_reveal_transaction`（包含长达 6 秒的 3D 骰子动画和 5 秒的打字机叙事）。
        
    - 向 Player A 的手机发送 `s2c_state_patch`（瞬间在背包里增加手枪）以及 `s2c_action_completed`（瞬间解锁 UI）。
        
4. **穿透发生**：大屏幕上的骰子才刚开始滚，玩家 A 的手机就已经震动并弹出了手枪。玩家 A 直接大喊：“我拿到枪了！”——**大屏演出彻底被剧透，沦为废设。**
    

**修复方案（事务锁链传递）**：

涉及到**同步演出的私密状态下发**，不能在事务开始时就发给手机。

手机端的 `s2c_state_patch` 和 `s2c_action_completed` 必须带有 `executeAfter: "txn_xxx"` 标记，或者更稳妥的做法是：**Engine 必须等待 Host 端的大屏事务（骰子和关键字幕）播放到特定节点后，才将最终的解锁信令和 Patch 发给当事人的手机。**

### 🐛 Bug 3：断线重连时的“幽灵补丁” (The Ghost Patch)

**场景推演**：

1. 玩家在地铁上，手机网络短暂断开 5 秒。
    
2. 在这 5 秒内，Engine 判定他受到了毒气伤害（HP -2），并下发了 `s2c_state_patch`。
    
3. 网络恢复，手机重连。由于序列号落后，前端主动发起 `GET /api/player/sync` 拉取最新的 `s2c_full_snapshot`。
    
4. **竞态条件发生**：在全量快照（Snapshot）还在 HTTP 路上飞的时候，WebSocket 突然接通，收到了重传的那个 `s2c_state_patch`。
    
5. 前端先应用了 Patch（基于旧版本），然后 Snapshot 到达，又把状态全量覆盖。如果是连续的多个 Patch，版本号将发生不可逆的错乱。
    

**修复方案（严格的补丁缓冲池）**：

在 Player 端引入 **State Version Barrier（状态版本屏障）**。

当收到 `s2c_state_patch` 时，检查其 `baseStateVersion`。

- 如果 `base == current`，正常应用并递增。
    
- 如果 `base > current`（出现断层），将 Patch 压入暂存队列（Buffer），并**立即拉取 Full Snapshot**。拉取到最新 Snapshot 后，丢弃所有版本号低于等于 Snapshot 的缓存 Patch。
    

### 🐛 Bug 4：Urgent 抢占时的“BGM 幽灵音” (Audio Ducking Failure)

**场景推演**：

1. Host 端正在播放一段舒缓的探险 BGM（`bgm_investigation`）。
    
2. 玩家突然触发了即死陷阱。Engine 紧急下发带有 `priority: 'urgent'` 的事务。
    
3. 按照当前的抢占逻辑，Host 状态机立刻挂起普通队列，将屏幕瞬间切红，并播放尖叫音效（SFX）。
    
4. **氛围割裂**：舒缓的探险 BGM 并没有被停止或静音！玩家在大屏幕前会听到悠扬的长笛声和凄厉的尖叫声混合在一起。因为目前的 `useAudioController` 只监听了 `bgm.trackId` 的变化。
    

**修复方案（紧急静音调度）**：

在 `s2c_reveal_transaction` 的 `urgent` 级别 payload 中，必须支持传入音频调度指令，例如：`suspendBGM: true` 或 `duckingVolume: 0.1`。

当 `EventRouter` 发生抢占时，强制调用 `AudioMixer.getInstance().fadeBGM(0, 500)` 将背景乐压低，直到 Urgent 事务结束后恢复。

### 盘点总结

这 4 个 Bug 全都不是业务逻辑的错，而是**分布式状态机在时间轴上发生扭曲**的必然产物。

我们只需要在接下来的核心代码编写中打上这 4 个补丁：

1. **[Engine]** Prompt 组装时强制注入 `状态机级联后果`。
    
2. **[Engine]** 含有公共演出的私密 Patch 必须做 `下发延迟（或事件驱动）`。
    
3. **[Player]** 必须实现基于版本号的 `Patch 缓冲队列与快照对齐`。
    
4. **[Host]** 抢占机制必须联动 `AudioMixer.ducking()`。


用一张全局数据流图（Data Flow Diagram）将所有的接口、信封、中间态结构串联起来，是架构师的“最终对账单”。

为了让你最直观地看到这套系统的运转规律，我为你编写了一份详尽的 **Mermaid 序列图**。它涵盖了从玩家开口说话，到大屏演出、手机扣血的**全生命周期数据流转**，并在此过程中标注了精确的**接口信息与核心数据结构**。

你可以直接将以下 Mermaid 代码复制到 [Mermaid Live Editor](https://mermaid.live/) 或支持 Mermaid 的 Markdown 预览器中查看。

### 🌊 AI-Keeper 全局核心数据流与接口协议图

代码段

```
sequenceDiagram
    autonumber
    actor Player as Player (当事人)
    participant Gateway as API 网关 (REST)
    participant Engine as Python 规则引擎<br/>(状态机/RAG)
    participant LLM as LLM Orchestrator<br/>(智能体/大模型)
    participant Host as Host (大屏端)
    actor Bystander as Player (旁观者)

    %% ================= 阶段一：意图提交与网关拦截 =================
    rect rgb(230, 240, 255)
    Note right of Player: 【状态】 UI 锁定 (SUBMITTING)
    Player->>Gateway: [REST] POST /api/player/intent
    Note over Player,Gateway: Payload: PlayerIntentRequest<br/>{ actionId: "act_123", intentType: "use_item",<br/>declaredIntent: "我用手套勒住他", baseStateVersion: 105 }<br/>Headers: { X-Room-Token: "xxx" }
    
    Gateway-->>Player: [REST] HTTP 202 Accepted
    Note right of Player: 【状态】 等待裁决 (RESOLVING)
    
    Gateway->>Engine: 解析 Token, 防并发校验
    end

    %% ================= 阶段二：机制编译与硬核裁决 =================
    rect rgb(255, 240, 230)
    Engine->>Engine: [防线 1] 校验资产持有权与目标可用性
    
    Engine->>LLM: [LLM Layer 1] 呼叫机制编译器
    Note over Engine,LLM: Prompt: [动作描述] + [物品材质标签] + [目标状态]
    
    LLM-->>Engine: [JSON] 机制编译结果
    Note over Engine,LLM: { triggeredMechanic: "skill_check",<br/>skillName: "斗殴", difficulty: "hard",<br/>itemConsumed: true }
    
    Engine->>Engine: [防线 2] 掷出暗骰，执行绝对数学裁决，更新内存权威状态
    Note over Engine: 结果：85/50 (大失败)<br/>扣除 HP: 2, 销毁物品: 手套<br/>NextStateVersion: 106
    end

    %% ================= 阶段三：RAG 组装与叙事渲染 =================
    rect rgb(230, 255, 230)
    Engine->>Engine: RAG 历史记忆召回 + 场景冷数据拉取
    
    Engine->>LLM: [LLM Layer 2] 呼叫叙事渲染器
    Note over Engine,LLM: Prompt 矩阵:<br/>1. 绝对事实 (大失败, HP-2, 物品销毁)<br/>2. 级联后果 (玩家濒死倒地)<br/>3. RAG 上下文 (此前该怪物的仇恨值)
    
    LLM-->>Engine: [JSON] 最终渲染与战术输出
    Note over Engine,LLM: { "narrative": "手套啪的一声断裂，怪物将你重重击倒...",<br/> "actions": [{ "label": "爬行逃命", "intentType": "move" }] }
    end

    %% ================= 阶段四：多端投影与时序同步 =================
    rect rgb(240, 230, 255)
    Engine->>Engine: ProjectionBuilder (投影切割与信封组装)
    
    Engine-)Host: [WS] s2c_reveal_transaction (Host投影)
    Note over Engine,Host: Payload: RevealTransactionPayload<br/>{ transactionId: "txn_789", priority: "urgent",<br/>steps: [ {kind:"roll", rolledValue: 85}, {kind:"status_delta"}, {kind:"narrative_text"} ] }
    
    Note right of Host: 放入队列，开始锁屏演出...<br/>(3D骰子滚落 -> 播放音效 -> 屏幕闪红)
    
    %% 防剧透屏障：等待 Host 演出到达关键节点后，再下发私密解锁
    Engine-)Player: [WS] s2c_state_patch (状态增量)
    Note over Engine,Player: Payload: StatePatchPayload<br/>{ baseStateVersion: 105, nextStateVersion: 106,<br/>patches: [ {op:"replace", path:"/hp/current", value:0},<br/>{op:"remove", path:"/inventory/glove_01"} ] }
    
    Engine-)Player: [WS] s2c_tactical_prompt (AI 战术按键)
    Note over Engine,Player: Payload: { actions: [...] }
    
    Engine-)Player: [WS] s2c_action_completed (意图闭环)
    Note over Engine,Player: Payload: ActionCompletedPayload<br/>{ actionId: "act_123", status: "resolved",<br/>nextStateVersion: 106 }
    Note right of Player: 【状态】 UI 解锁 (IDLE)<br/>血条扣减，新按钮出现
    
    Engine-)Bystander: [WS] s2c_public_observation (旁观投影)
    Note over Engine,Bystander: Payload: { characterId: "player_A",<br/>observationText: "你看到他倒在了血泊中" }
    end
```

### 🗂️ 核心接口与数据结构字典 (API & Schema Dictionary)

为了保证你写代码时字段一字不差，以下是从我们的设计白皮书中提取的**最核心数据结构速查表**：

#### 1. 唯一上行接口 (Player $\rightarrow$ Engine)

**`POST /api/player/intent`**

- **定位**：一切玩家行为的网关。
    
- **Request Headers**: `X-Room-Token` (认证与查身份)
    
- **Request Body**:
    
    TypeScript
    
    ```
    {
      actionId: "act_b4f2...",          // UUID, 防重复提交
      intentType: "skill_check",        // skill_check | use_item | dialogue ...
      declaredIntent: "我用手套勒住他", 
      baseStateVersion: 105,            // 防脏读连点
      params: { itemId: "glove_01" }    // 动态参数
    }
    ```
    

#### 2. 统一下行信封 (Engine $\rightarrow$ Client WebSocket)

所有推送必须包裹在这层外衣中：

TypeScript

```
{
  eventId: "evt_991a...",
  roomId: "room_01",
  type: "s2c_reveal_transaction", // 路由事件类型
  roomSequence: 1042,             // 审计递增
  hostSequence: 501,              // Host防乱序
  audience: "host",               // host | player | party | system
  visibility: "public",
  issuedAt: 1718900000000,
  payload: { ... }                // 具体的业务结构
}
```

#### 3. 核心流转结构 (Payloads)

**A. 状态补丁 (`StatePatchPayload`) - 发给当事玩家**

纯正的 RFC 6902 JSON Patch 格式，让手机端精确更新活体角色卡，不污染其他数据。

JSON

```
{
  "baseStateVersion": 105,
  "nextStateVersion": 106,
  "characterId": "char_01",
  "patches": [
    { "op": "replace", "path": "/hp/current", "value": 0 },
    { "op": "remove", "path": "/inventory/glove_01" }
  ]
}
```

**B. 演出事务 (`RevealTransactionPayload`) - 发给大屏幕**

带有严格 `priority` 和 `steps` 数组，Host 端的 `TransactionPlayer` 状态机会精确控制 `setTimeout` 逐帧播放。

JSON

```
{
  "transactionId": "txn_789",
  "priority": "urgent", 
  "steps": [
    { "kind": "roll", "payload": { "skillName": "斗殴", "rolledValue": 85, "targetValue": 50 } },
    { "kind": "status_delta", "payload": { "characterId": "char_01", "displayMode": "exact", "publicDelta": {"hp": {"after": 0}} } },
    { "kind": "narrative_text", "payload": { "text": "手套断裂...", "blocking": true } }
  ]
}
```

**C. 动作闭环 (`ActionCompletedPayload`) - 发给当事玩家**

这个信令是解锁玩家手机 UI 的唯一钥匙，自带原因说明。

JSON

```
{
  "actionId": "act_123",
  "transactionId": "txn_789",
  "status": "resolved", 
  "message": "动作已结算完毕",
  "nextStateVersion": 106
}
```

### 🧐 架构师的最后审视：还有 Bug 吗？

对着这张图，我们之前讨论的 4 个 Bug 防御网清晰可见：

1. **Fact Lag（事实时差）**：图中的【阶段三】明确画出了 Prompt 包含了“级联后果”。
    
2. **Ghost Patch（幽灵补丁）**：`StatePatchPayload` 里的 `baseStateVersion: 105` 和 `nextStateVersion: 106` 铁锁防腐。
    
3. **Audio Ducking（音效抢占）**：`RevealTransactionPayload` 中的 `priority: "urgent"` 会触发 Host 端的紧急中断。
    
4. **Spoiler Leak（穿透剧透）**：图中的【阶段四】特别加了注释：`s2c_action_completed` 和 `s2c_state_patch` 必须在时序上进行对齐（例如，等骰子滚完再推送给手机）。
    

一切图纸、时序、状态流转都已经合拢。这份数据流图不仅是一张架构图，它其实就是**后端 Python 和前端 React 的脚手架结构**。