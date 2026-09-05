

先把核心定义固定下来：

> **Live Shared Stage 是 AI-KP 面向全桌进行实时公共主持的主舞台。**  
> 它不是聊天记录，不是房主后台，也不是状态编辑器；它负责维持全桌的共同注意力：现在在哪里、谁在说话、发生了什么、公开裁决结果是什么。

它应满足五条硬原则：

```text
一屏一个焦点
只展示 Party-safe 内容
状态成功后才展示结果
大屏断线不阻断游戏
大屏永远不参与世界状态写入
```

---

# 一、`live` 不是一个固定版面，而是一个舞台编排器

不要给它设计十几个互斥页面状态。建议将实时舞台拆成三个相互独立的状态轴。

## 1. Session 状态

```text
live
paused
recovering
ended
```

决定整个舞台是否允许继续播放正常 Cue。

## 2. 基础画布

```text
scene
map
handout
neutral
```

决定屏幕背景和主要视觉内容。

## 3. 当前焦点 Cue

```text
none
narration
dialogue
action
resolution
clue_reveal
decision
table_ruling
system_notice
```

最终画面是三者组合：

```text
SessionStatus = live
BaseSurface = scene
FocusCue = dialogue
```

或者：

```text
SessionStatus = live
BaseSurface = map
FocusCue = resolution
```

这样不会出现几十种难以维护的页面状态。

---

# 二、默认实时舞台长什么样

推荐以 16:9 为默认设计。

```text
┌──────────────────────────────────────────────────────────────┐
│ 圣玛丽医院 · Session 4    地下档案室 · 23:20      AI-KP 正常  │
├───────────────────────────────────────┬──────────────────────┤
│                                       │ 当前情境             │
│                                       │                      │
│                                       │ 在场人物             │
│             主视觉画布                 │ 陈默、安娜、陈教授    │
│                                       │                      │
│      场景图 / 公共地图 / Handout       │ 队伍已确认计划       │
│                                       │ 调查 B-17            │
│                                       │                      │
│                                       │ 公开时钟             │
│                                       │ 距午夜 40 分钟        │
│                                       │                      │
├───────────────────────────────────────┴──────────────────────┤
│ AI-KP                                                        │
│ 铁门后是一条狭窄的档案走廊，远处传来一声短促的金属碰撞。       │
├──────────────────────────────────────────────────────────────┤
│ 最近公共事件：安娜打开铁门 · 陈默正在与陈教授交谈             │
└──────────────────────────────────────────────────────────────┘
```

固定结构只有五个区域：

```text
StageHeader
VisualCanvas
PublicContextRail
NarrativeDock
RecentEventRibbon
```

临时裁决、对话、线索揭示等内容，通过 `FocusLayer` 叠加在主画布上。

---

# 三、五个固定组件

## 1. 顶部状态栏 `StageHeader`

固定显示：

```text
战役公开名称
Session 编号
当前公开场景
游戏内时间
AI-KP 公共状态
房间暂停 / 恢复状态
```

正常情况下要非常克制：

```text
AI-KP 正常
```

不要显示：

```text
正在调用 DeepSeek
RAG 检索 17 条
Provider timeout
状态机 step 4
```

AI-KP 的公共状态只允许：

```text
正常主持
正在处理
等待玩家决定
暂时降级
恢复中
游戏已暂停
```

内部 Provider 和错误信息不进入公共舞台。

---

## 2. 主视觉画布 `VisualCanvas`

主视觉按当前基础模式显示：

### Scene

```text
场景图片
安全的环境视觉
公开 NPC 立绘
场景主题背景
```

### Map

```text
Party 已知地图
公开玩家位置
公开 NPC
Party 标记
```

### Handout

```text
已向 Party 揭示的文件
线索公开版本
授权素材
```

### Neutral

没有素材或素材加载失败时：

```text
场景名称
安全文字描述
模组主题背景
```

不能因为场景图片加载失败就显示：

```text
本地路径
Asset ID
错误堆栈
空白页面
```

---

## 3. 公共情境栏 `PublicContextRail`

它只回答：“现在大家共同知道什么？”

建议包含四块。

### 当前在场

```text
陈默
安娜
陈教授
```

只显示公开在场对象。不能因为 AI-KP 内部知道某个隐藏 NPC 在墙后，就显示：

```text
还有一名未知人物
```

### 队伍已确认计划

```text
调查 B-17 的旧建筑记录
```

必须来自玩家确认过的 `PartyPlan`，不能是 AI 自己推断的下一步。

### 公开时钟

例如：

```text
距午夜 40 分钟
警戒等级 2/4
暴雨正在增强
```

只展示玩家已知且允许公开的 Clock。

### 当前阶段

```text
自由行动
等待全员决定
正在结算
公共投票中
```

---

## 4. 叙事字幕区 `NarrativeDock`

这是整个公共舞台最重要的文字区域。

需要区分：

```text
AI-KP 叙事
NPC 台词
玩家角色公开台词
公共系统说明
```

示例：

```text
陈教授

“你们最好不要再追查 B-17。”
```

或者：

```text
AI-KP

教授说完后，下意识地把手伸向了西装内袋。
```

建议：

- 文本立即完整出现，不使用缓慢打字机效果；
- 使用轻微淡入；
- 支持持续字幕；
- 一次只显示一个主要说话者；
- 较长内容分页，不滚成聊天记录；
- 手机端同时收到 Party-safe 文本。

---

## 5. 最近公共事件条 `RecentEventRibbon`

只保留最近 2—3 条简短公共事件：

```text
安娜打开北侧铁门
队伍获得旧建筑图
当前时间推进至 23:20
```

它的作用是帮助刚抬头的玩家快速恢复，不是代替 Journal。

禁止显示：

```text
完整聊天历史
私人事件缺口
“某玩家获得了私密线索”
未确认行动草稿
```

---

# 四、焦点层 `FocusLayer`

实时舞台的关键不是不断换页面，而是在基础画布之上播放一个主焦点。

## 1. 公共叙事焦点

适合：

```text
场景变化
环境描述
剧情过场
公共后果
```

效果：

- 背景轻微变暗；
- 文本居中或下三分之一；
- 无需遮掉所有场景信息；
- 展示完成后回到普通 Live。

---

## 2. NPC 对话焦点

```text
┌─────────────────────────────────────────────┐
│                [NPC 公开立绘]                │
│                                             │
│ 玛格丽特护士                                │
│                                             │
│ “教授昨晚从来没有去过地下室。”              │
└─────────────────────────────────────────────┘
```

只允许使用玩家已知身份：

```text
玛格丽特护士
戴帽子的陌生人
医院管理员
```

不能因 AI-KP 知道真实身份而提前显示：

```text
邪教成员玛格丽特
伪装中的院长
```

---

## 3. 公共行动焦点

玩家确认公开行动后，大屏可以显示：

```text
陈默正在试探陈教授

目标：
观察他听到“B-17”时的反应
```

但不应显示：

```text
完整原始输入
私人约束
玩家未公开的真实目的
私人物品
```

如果行动本身是秘密行动，则公共舞台什么也不显示，直到产生公共后果。

---

## 4. 公共裁决焦点

```text
┌─────────────────────────────────────────────┐
│ 陈默 · 心理学                               │
│                                             │
│                    32                       │
│                                             │
│                 普通成功                    │
│                                             │
│ 教授听到“B-17”时短暂地停顿了一下。           │
└─────────────────────────────────────────────┘
```

显示内容由 `RoomPolicySnapshot` 决定：

```text
full
result_only
narrative_only
```

### Full

```text
技能名
权威技能值
公开骰子
公开修正
结果等级
```

### Result only

```text
技能名
骰子
结果等级
```

### Narrative only

只显示公共叙事。

绝对不能显示：

```text
隐藏难度
NPC 隐藏对抗值
真实动机
玩家私人观察
完整 StatePatch
```

---

## 5. 公共线索揭示

当线索正式向 Party 公开时：

```text
┌─────────────────────────────────────────────┐
│              队伍获得新线索                 │
│                                             │
│              [旧建筑图图片]                 │
│                                             │
│ 公开摘要：                                  │
│ 图纸中标记了一个名为 B-17 的区域。           │
└─────────────────────────────────────────────┘
```

只使用：

```text
Clue publicVersion
Party-safe Asset URL
安全标题
```

不能使用：

```text
clue.text 原始私密内容
Host-only 描述
隐藏关联
最终用途
```

线索揭示至少保持一个最低展示时间，并可由桌务手机重新播放。

---

## 6. 公共地图焦点

地图模式时：

```text
主视觉切为 PartyMapView
公开移动结果用轻量动画表示
当前事件目标可以短暂高亮
```

但高亮只来自公开行动：

```text
陈默移动到北侧铁门
```

不能根据隐藏剧情的重要性高亮某个区域。

---

## 7. 公共决定焦点

当需要全桌在手机上做决定时：

```text
队伍决定

是否立即离开医院？

A. 立即离开
B. 继续调查
C. 暂停讨论

已提交：3 / 4
请在手机上选择
```

默认不显示每个人投了什么。

公共舞台不接受点击；所有输入都从玩家手机提交。

---

## 8. 桌面裁定焦点

桌务完成无剧透裁定后，公共舞台只显示结果：

```text
桌面裁定

铁门保持半开状态。
该状态已经成为本桌当前事实。
AI-KP 将据此调整后续场景。
```

不显示：

```text
哪个选项更接近模组
原始隐藏设定
未来剧情影响
```

---

# 五、Live 状态下的 Cue 编排系统

公共舞台不能直接把每条 EngineEvent 渲染成 UI。

应增加：

# `StagePresentationOrchestrator`

链路：

```text
Rule / State / Journal
        ↓
Projection + Safety
        ↓
Party-safe Event
        ↓
SharedStageProjectionService
        ↓
StagePresentationOrchestrator
        ↓
StageCue Queue
        ↓
SharedStagePage
```

公共舞台只消费 `StageCueDTO`，不读取 raw events。

---

# 六、`StageCueDTO`

建议契约：

```json
{
  "cueId": "cue_xxx",
  "roomId": "room_xxx",
  "type": "public_resolution",
  "priority": 60,
  "displayMode": "overlay",
  "dismissPolicy": "timed",
  "minDurationMs": 5000,
  "maxDurationMs": 12000,
  "presentAt": "2026-07-12T20:15:31.200Z",
  "expiresAt": "2026-07-12T20:16:00.000Z",
  "dedupeKey": "action:act_482:public_resolution",
  "sourceTransactionId": "tx_482",
  "sourceEventSequences": [1041, 1042],
  "stateVersion": 87,
  "payload": {},
  "fallback": {
    "type": "text",
    "text": "陈默的行动已完成。"
  }
}
```

关键字段：

| 字段 | 用途 |
|---|---|
| `dedupeKey` | 防止刷新后重复播放 |
| `sourceTransactionId` | 将同一次行动的 Cue 归组 |
| `sourceEventSequences` | 可追溯来源 |
| `stateVersion` | 确认 Cue 基于哪个已提交状态 |
| `presentAt` | 多设备同步播放 |
| `expiresAt` | 避免重连后播放过期动画 |
| `fallback` | 图片、音频加载失败时仍可显示 |

---

# 七、Cue 类型

P0 建议固定这些类型：

```text
scene_update
public_narration
public_dialogue
public_action
public_resolution
public_clue_reveal
public_map_update
public_decision
table_ruling
party_plan_update
game_time_update
system_notice
safety_pause
recovery_status
session_summary
atmosphere
```

不要允许任意字符串 Cue。

每种 Cue 都有独立 payload schema。

---

# 八、Cue 优先级

建议：

| 等级 | Cue |
|---:|---|
| 100 | `safety_pause` |
| 90 | `recovery_status` |
| 80 | `public_decision` |
| 75 | `table_ruling` |
| 70 | `public_clue_reveal` |
| 60 | `public_resolution` |
| 50 | `public_dialogue` |
| 40 | `public_narration` |
| 30 | `public_action` |
| 20 | `map_update / plan_update` |
| 10 | `atmosphere` |

规则：

- Safety 可以立即中断一切；
- 恢复状态可以替换当前普通 Cue；
- 普通裁决不打断正在显示的重要线索；
- 同一事务内严格按顺序播放；
- 低优先级氛围 Cue 可合并或丢弃；
- 过期 Cue 不补播。

---

# 九、Cue 的展示模式

```text
replace
overlay
lower_third
sticky
background_update
queue_only
interrupt
```

示例：

| Cue | 展示模式 |
|---|---|
| 场景切换 | `replace` |
| NPC 台词 | `lower_third` |
| 公共骰子 | `overlay` |
| 公开线索 | `sticky` |
| 地图移动 | `background_update` |
| Safety Pause | `interrupt` |
| BGM | `background_update` |

---

# 十、Cue 生命周期

```text
scheduled
→ active
→ presented
→ expired

或：
scheduled
→ cancelled

或：
active
→ interrupted
```

这里的 `presented` 只表示：

```text
公共桌面尝试展示过
```

它不是游戏事实。

必须写死：

> **Stage ACK 不能作为规则、State 或线索释放成功的依据。**

---

# 十一、公共桌面与玩家手机如何同步

AI-KP 运行的核心结果必须同时投影到：

```text
Shared Stage
Player Party Feed
目标玩家 Private Feed
```

建议服务端生成：

```text
PresentationTimeline
```

示例：

```text
T+0.0s  大屏和所有手机显示公共行动摘要
T+2.0s  大屏显示公共骰子
T+6.0s  大屏和手机显示公共叙事
T+7.0s  目标玩家手机显示私密观察结果
```

但要注意：

> **私密结果不能等待公共大屏真实 ACK。**

因为：

```text
大屏可能没开
大屏可能断线
远程团可能根本不用大屏
```

正确逻辑是：

```text
服务端按 PresentationTimeline 释放
```

而不是：

```text
Stage 播放成功
→ 大屏 ACK
→ 才允许玩家收到私密结果
```

Stage ACK 只用于：

```text
播放监控
去重
分析延迟
重播判断
```

---

# 十二、手机有无大屏时的差异

## 有公共桌面

玩家手机更偏向：

```text
输入
意图确认
私人裁决
待处理决定
角色和物品
私人线索
```

公共叙事可用紧凑模式显示。

## 没有公共桌面

玩家手机自动进入：

```text
Full Party Feed
```

显示完整公共叙事、公共裁决和地图。

因此需要一个：

```text
StagePresence
```

但 `StagePresence` 只影响前端布局，不影响游戏事实和事件投递。

---

# 十三、并发行动如何展示

调查型 TRPG 不一定始终有严格回合。

## 玩家自由行动阶段

可以显示：

```text
等待玩家行动
```

若房间允许显示进度：

```text
已提交：3 / 4
```

默认不建议显示谁还没提交，避免公共压力。

## 多个行动同时结算

P0 不做复杂并行动画。

按照权威事务顺序：

```text
Action A
→ Resolution A
→ Narration A
→ Action B
→ Resolution B
→ Narration B
```

如果 AI-KP 将多个行动合并成一个公共场景结果，可以生成：

```text
group_resolution
```

但仍必须引用各自的 `actionId` 和 `transactionId`。

---

# 十四、隐藏行动如何处理

如果玩家执行秘密行动：

```text
秘密观察
隐藏物品
给 AI-KP 私下留言
只对某玩家可见的行为
```

公共舞台默认：

```text
不显示任何行动摘要
不显示“某玩家正在进行秘密行动”
不显示隐藏骰提示
```

只有产生公共后果时才显示公共后果。

因为即使显示：

> 陈默正在进行一项秘密行动。

也已经泄露了信息存在。

---

# 十五、AI-KP 处理时间的舞台表现

正常处理时间较短时，不需要弹出大 Spinner。

只在顶部使用轻量状态：

```text
AI-KP 正在回应
```

超过阈值后显示：

```text
AI-KP 正在整理当前行动。
所有输入已经保存。
```

进入降级模式时：

```text
AI-KP 已切换到保守模式。
当前状态和行动不会丢失。
```

禁止显示：

```text
DeepSeek 超时
MCP 503
RAG 查询失败
JSON schema error
```

---

# 十六、场景和叙事切换规则

## 场景切换

```text
旧场景淡出 300—600ms
新场景视觉加载
若加载失败使用文字 fallback
更新场景名称和游戏时间
播放公共开场叙事
```

不建议使用长时间黑屏或电影式转场。

## 叙事文本

建议持续时间按文本长度计算，但不强制玩家等待。

例如中文：

```text
duration = clamp(4500ms, 字数 × 160ms, 18000ms)
```

文本立即全部出现，只决定自动收起时间。

玩家可从手机或桌务控制中重播上一条公共 Cue。

---

# 十七、React 组件结构建议

```text
SharedStagePage
├─ StageSessionGuard
├─ StageConnectionBoundary
├─ StageShell
│  ├─ StageHeader
│  ├─ VisualCanvas
│  │  ├─ SceneBackdrop
│  │  ├─ PublicMapLayer
│  │  ├─ PublicHandoutLayer
│  │  ├─ AtmosphereLayer
│  │  └─ FocusCueRenderer
│  │     ├─ NarrationCue
│  │     ├─ DialogueCue
│  │     ├─ ActionCue
│  │     ├─ ResolutionCue
│  │     ├─ ClueRevealCue
│  │     ├─ DecisionCue
│  │     └─ TableRulingCue
│  ├─ PublicContextRail
│  ├─ NarrativeDock
│  ├─ RecentEventRibbon
│  └─ SessionStatusOverlay
├─ StageAccessibilityLayer
└─ LocalDisplayControls
```

`LocalDisplayControls` 只允许：

```text
全屏
字幕开关
音量
减少动画
重新配对
```

不能允许：

```text
修改角色状态
触发剧情
查看隐藏内容
完成裁决
```

---

# 十八、Stage ViewModel

```typescript
interface SharedStageViewModel {
  stageSessionId: string;
  roomId: string;

  sessionStatus: "live" | "paused" | "recovering" | "ended";
  baseSurface: "scene" | "map" | "handout" | "neutral";

  roomSequence: number;
  stateVersion: number;

  header: StageHeaderView;
  scene: StageSceneView | null;
  publicMap: StageMapView | null;
  publicContext: StagePublicContextView;

  activeCue: StageCue | null;
  queuedCueCount: number;
  recentPublicEvents: StageRecentEventView[];

  atmosphere: StageAtmosphereView;
  connection: StageConnectionView;
}
```

前端只根据 ViewModel 渲染，不自行拼接底层事件。

---

# 十九、完整动作示例

玩家陈默在手机输入：

> 我提到 B-17，观察教授的反应，但不碰他桌上的信。

## 1. 未确认阶段

手机显示意图合同。

公共舞台：

```text
无变化
```

## 2. 玩家确认

如果该动作公开，舞台收到：

```json
{
  "type": "public_action",
  "payload": {
    "actorPublicName": "陈默",
    "safeSummary": "陈默正在试探陈教授。"
  }
}
```

舞台显示：

> 陈默正在试探陈教授。

不显示：

```text
不碰信件
真正意图是观察
完整自然语言
```

除非玩家选择公开这些内容。

## 3. 规则完成

Rule 和 State 已成功提交。

舞台收到：

```text
public_resolution
```

显示：

```text
心理学 · 32 · 普通成功
```

## 4. 公共叙事

舞台显示：

> 教授听到“B-17”时短暂地停顿了一下。

## 5. 私密补充

仅陈默手机收到：

> 教授随后下意识地看向了北侧书架。

公共舞台和其他玩家终端：

```text
不知道该私密补充存在
```

---

# 二十、断线恢复

Stage 重连不能重播整个事件历史。

正确流程：

```text
stage ticket 重连
→ 请求 StageSnapshot
→ 对齐 roomSequence / stateVersion
→ 载入当前基础画布
→ 恢复仍有效的 activeCue
→ 丢弃已过期一次性 Cue
```

以下内容不自动重播：

```text
旧骰子动画
旧线索揭示动画
Session Opening
一次性音效
已经结束的投票
```

想重播必须由桌务手机显式发送：

```text
ReplayPresentationCue
```

它只重播展示，不重放游戏事务。

---

# 二十一、无素材和加载失败时

任何视觉 Cue 都必须有文本 fallback。

例如场景图失败：

```text
地下档案室

空气中弥漫着潮湿纸张的霉味。
```

线索图片失败：

```text
新线索：旧建筑平面图

图纸中标记了 B-17 区域。
```

音频失败：

```text
不中断字幕
不影响游戏
只在桌务控制中显示“音频播放失败”
```

---

# 二十二、无障碍和十英尺界面

P0 就应包含：

```text
主要叙事字号 30—40px
关键裁决数字 72px 以上
高对比
不只依赖颜色
字幕常显
减少动画模式
关闭闪烁
音频不作为唯一信息来源
安全的图片替代文本
16:9、21:9 和窗口模式兼容
```

推荐三个显示预设：

```text
平衡模式
电影模式
无障碍模式
```

P0 可以先实现：

```text
平衡模式
无障碍模式
```

---

# 二十三、P0 实现顺序

| 顺序 | 能力 |
|---:|---|
| 1 | Stage 配对与只读 Session |
| 2 | StageSnapshot + WebSocket 重连 |
| 3 | Header / Scene / Context / Narrative 基础布局 |
| 4 | Narration 和 Dialogue Cue |
| 5 | Public Action 和 Resolution Cue |
| 6 | Public Map |
| 7 | Public Clue / Handout Reveal |
| 8 | Pause / Recovery / TableRuling |
| 9 | Cue 队列、优先级、去重和过期 |
| 10 | 手机无大屏 fallback |
| 11 | 字幕、减少动画和可读性 |
| 12 | Session Recap / Summary |

---

# 二十四、P0 验收标准

```text
1. Shared Stage 永远不接收 player_private。
2. Shared Stage 永远不接收 keeper_internal。
3. 玩家私密事件产生时，大屏没有任何存在性提示。
4. 大屏只从 SharedStageProjectionService 读取安全 DTO。
5. Stage 不读取 raw events。
6. Stage 不读取原始 ModuleVersion。
7. Stage 不修改 State。
8. Stage 断线不阻断玩家行动。
9. Stage 缺失不阻断私密结果释放。
10. Cue 重连后不重复播放。
11. 一次性线索和音效不会重复。
12. 公开裁决遵守 RoomPolicySnapshot。
13. 隐藏检定不会泄露难度或 NPC 数值。
14. 场景图加载失败仍有安全文本 fallback。
15. 多块 Stage 同时连接时内容一致。
16. Player 手机在无 Stage 时能完整显示 Party Feed。
17. Public Map 不含隐藏节点、NPC、线索或数量。
18. TableRuling 只显示裁定结果，不显示幕后影响。
19. AI-KP 错误不会在大屏显示 Provider 或堆栈。
20. 所有关键 Cue 都能追到 eventSequence 和 stateVersion。
```

---

# 最终定义

> **Live Shared Stage 是由服务器编排的 Party-safe 展示系统：它在一块共同屏幕上维持当前场景、公共叙事、公共地图、公开裁决和共同决定；所有内容都来自已经提交的状态和经过 Safety 裁剪的事件，玩家在手机上操作和接收私密内容，大屏只负责让全桌共同看到正在发生的桌面现实。**