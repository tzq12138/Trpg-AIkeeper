

先把定义钉死：

> **公共桌面是 AI-KP 面向全桌进行公共主持的共享舞台。**  
> 它显示所有玩家都允许看到的场景、叙事、地图、公开行动和公共裁决；不负责输入行动，不是房主后台，也绝不拥有幕后真相。

产品内建议正式命名为：

# **Shared Stage / 公共舞台**

现有代码中的 `HostStage` 可以暂时保留文件名，但产品语义和后续 DTO 应逐步改成 `SharedStage`，避免再把它和房主权限混在一起。

---

# 一、公共桌面的产品合同

公共桌面只做四件事：

```text
1. 呈现当前共同情境
2. 播放 AI-KP 的公共主持内容
3. 展示允许公开的行动和裁决
4. 承载全桌共同决定、暂停和本局总结
```

它不做：

```text
玩家行动输入
角色卡编辑
私人线索查看
桌务事故裁定
完整日志浏览
幕后地图查看
AI-KP 内部计划查看
世界状态编辑
```

一条最重要的规则：

> **公共桌面是 Projection，不是世界状态来源。**

即使公共桌面断线、关闭或播放失败，游戏事实仍由：

```text
Rule
Transaction
State
Journal
```

维护。

公共桌面恢复后只重新同步显示，不重新执行行动、不重复发线索、不重复扣资源。

---

# 二、公共桌面给谁使用

## 本地同桌

```text
电视
投影仪
大显示器
房主电脑共享屏幕
```

所有玩家抬头共同观看。

## 远程团

可以采用：

```text
一名玩家共享公共桌面画面
所有人各自打开只读公共桌面
Discord / QQ / KOOK 中共享窗口
```

## 公共桌面不是必需设备

没有大屏时，公共内容同时出现在玩家手机的 Party 流中。

因此：

> **大屏提升共同体验，但不能成为游戏继续运行的单点依赖。**

---

# 三、公共桌面只使用一条路由

建议：

```text
/stage
```

首次打开进入配对页。

配对成功后进入：

```text
/stage/session/{stageSessionId}
```

这一张页面根据房间状态自动切换模式，不需要玩家在大屏上操作导航。

状态机：

```text
unpaired
→ pairing
→ lobby
→ recap
→ opening
→ live
→ public_resolution
→ public_map
→ public_decision
→ paused
→ recovery
→ session_summary
→ closed
```

其中 `live`、`public_resolution` 和 `public_map` 可以频繁相互切换。

---

# 四、公共桌面的九种核心模式

## 1. 配对模式 `pairing`

页面目标：

> 将当前显示器安全绑定到一个房间。

```text
┌─────────────────────────────────────────────┐
│                  AI-Keeper                  │
│                                             │
│             扫描二维码配对公共桌面           │
│                                             │
│                    [QR]                     │
│                                             │
│               配对码：M7K2Q                 │
│                                             │
│             此代码将在 5 分钟后失效          │
└─────────────────────────────────────────────┘
```

配对流程：

```text
大屏生成一次性 pairingCode
→ 房主在手机“战役准备”页面扫描
→ 服务端验证房主与房间
→ 签发只读 stageSession
→ 大屏获取 Party-safe snapshot
```

安全要求：

- 不使用 `owner_token`；
- 不使用 `player_token`；
- 配对码短时有效且一次性；
- `stage_token` 只能读取公共舞台接口；
- stage token 不能访问 Player、RoomOwner、Admin API；
- 房主可从手机端撤销某块显示器。

---

## 2. 公共大厅 `lobby`

显示：

```text
战役公开名称
公开模组封面
AI-KP 是否就绪
玩家公开名
角色公开名
Ready 状态
连接状态
公共桌面规则摘要
```

示例：

```text
圣玛丽医院

陈默 · 陈默        已准备
林夏 · 安娜        已准备
周启 · 顾云        选择角色中
韩舟 · 林海        已准备

AI-KP             准备就绪
公共桌面           已连接
```

不显示：

```text
角色私密背景
私人目标
私人物品
具体 HP / SAN
隐藏身份
完整角色卡
```

---

## 3. 战役回顾 `recap`

在新 Session 开始前播放 Party 公开回顾。

```text
┌─────────────────────────────────────────────┐
│ 上回 · 圣玛丽医院                           │
├─────────────────────────────────────────────┤
│ 队伍进入了地下档案室。                       │
│ 安娜打开了北侧铁门。                         │
│ 队伍获得了一张旧建筑平面图。                  │
│                                             │
│ 队伍上次决定：                               │
│ 调查图纸上的 B-17 区域。                     │
├─────────────────────────────────────────────┤
│ 当前地点：地下档案室                         │
│ 游戏时间：1926 年 11 月 14 日 23:20          │
└─────────────────────────────────────────────┘
```

这里只显示：

```text
Party 已知事实
Party 确认计划
公共人物和地点变化
公共开放问题
```

每个玩家自己的私密回顾仍在手机 `Continue` 页面。

---

## 4. AI-KP 开场 `opening`

用于首次开局或新 Session 开场。

页面包含：

```text
场景图
场景名称
游戏时间
AI-KP 公共开场叙事
安全的在场人物
公共氛围
```

开场状态必须已经由 Bootstrap 或 Session Start 成功提交。

错误顺序：

```text
大屏先播放 AI 开场
→ 再根据叙事写状态
```

正确顺序：

```text
状态提交成功
→ Projection 生成安全 Opening Cue
→ 公共桌面播放
```

AI 叙事失败时使用模组中的安全 `ReadAloud` 或确定性 fallback，不重新初始化世界。

---

## 5. 实时公共舞台 `live`

这是大屏最常驻的模式。

推荐 16:9 布局：

```text
┌──────────────────────────────────────────────────────────────┐
│ 圣玛丽医院 · Session 4     地下档案室 · 23:20    AI-KP 正常   │
├───────────────────────────────────────┬──────────────────────┤
│                                       │ 当前情境             │
│                                       │                      │
│             场景视觉                   │ 在场人物             │
│          或 Party 公共地图             │ 陈默 / 安娜 / 教授    │
│                                       │                      │
│                                       │ 队伍计划             │
│                                       │ 调查 B-17            │
│                                       │                      │
│                                       │ 公开时钟             │
│                                       │ 距午夜 40 分钟        │
├───────────────────────────────────────┴──────────────────────┤
│ AI-KP                                                        │
│ “铁门后是一条狭窄的档案走廊。远处传来金属轻碰的声音。”          │
├──────────────────────────────────────────────────────────────┤
│ 最近公共事件：安娜打开铁门 · 陈默正在与教授交谈                 │
└──────────────────────────────────────────────────────────────┘
```

固定区域只有四块：

### 顶部状态栏

```text
战役名称
Session
当前公开场景
游戏内时间
AI-KP 公共状态
暂停 / 恢复标记
```

### 主视觉区

根据当前焦点显示：

```text
场景图
公共地图
公共 Handout
角色/NPC 立绘
抽象氛围背景
```

### 公开情境栏

只显示：

```text
公开在场人物
Party 已确认计划
公开倒计时或时钟
公开环境状态
当前全桌等待状态
```

### 叙事下三分之一

显示：

```text
AI-KP 公共叙事
NPC 公共台词
角色公开台词
公共裁决摘要
```

---

## 6. 公共裁决 `public_resolution`

当某次行动允许公开时，大屏进入短暂的裁决聚焦模式。

```text
┌─────────────────────────────────────────────┐
│ 陈默正在观察教授的反应                       │
├─────────────────────────────────────────────┤
│                 心理学                       │
│                                             │
│                    32                       │
│                                             │
│                 普通成功                     │
├─────────────────────────────────────────────┤
│ 陈默注意到教授短暂地停顿了一下。              │
└─────────────────────────────────────────────┘
```

是否显示以下信息，由房间规则决定：

```text
技能名称
权威技能值
骰子结果
成功等级
公开修正
```

不显示：

```text
隐藏难度
隐藏对抗值
NPC 真正意图
玩家私密观察
完整 RuleExecutionPlan
完整 StatePatch
```

例如公开桌面可以显示：

> 陈默注意到教授短暂停顿了一下。

而玩家陈默的手机可能额外收到：

> 仅你可见：教授随后下意识看向北侧书架。

其他玩家甚至不能知道还有一条私密补充。

---

## 7. 公共地图 `public_map`

地图模式可以临时占满主视觉区。

显示：

```text
Party 已知区域
玩家公开位置
公开 NPC
Party 标记
当前公开场景
公开移动结果
```

不显示：

```text
未探索节点
隐藏节点数量
未出现 NPC
未发现线索
秘密通道
地图 Trigger
AI-KP 路径规划
```

```text
┌──────────────────────────────────────────────────────────────┐
│ 地下档案层 · Party 地图                                      │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                      [公共地图]                               │
│                                                              │
│       ● 陈默                    ● 安娜                        │
│                                                              │
│                    北侧铁门                                  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ AI-KP：铁门已经半开，里面没有照明。                            │
└──────────────────────────────────────────────────────────────┘
```

玩家在手机上提交移动意图，大屏只在状态成功后同步新的公开位置。

---

## 8. 公共决定 `public_decision`

全桌决策由手机提交，大屏只展示公共问题和进度。

```text
┌─────────────────────────────────────────────┐
│ 队伍决定                                   │
├─────────────────────────────────────────────┤
│ 是否立即离开医院？                          │
│                                             │
│ A. 立即离开                                │
│ B. 继续搜查                                │
│ C. 暂停讨论                                │
│                                             │
│ 已提交：3 / 4                              │
│                                             │
│ 请在手机上选择                             │
└─────────────────────────────────────────────┘
```

默认采用匿名投票：

```text
大屏显示已提交人数
不显示每个人选了什么
```

可支持：

```text
多数票
一致同意
公开投票
AI-KP 等待讨论后由玩家确认
```

AI-KP 不应自动替队伍投票。

---

## 9. 暂停、恢复和本局结束

### 暂停页

```text
游戏已暂停

AI-KP 正在恢复场景一致性。
你的行动已经保存。
角色状态和物品不会重复变化。
```

### 等待桌务页

```text
游戏暂时暂停

正在等待一项无剧透桌务裁定。
```

不显示：

```text
隐藏剧情冲突
后台错误
模组正确答案
恢复选项详情
```

### 本局总结页

```text
Session 4 完成

本局公开发现：
· 旧建筑图
· B-17 标记
· 地下档案室旧钥匙

仍未解决：
· 教授为什么进入地下室？
· 护士证词为什么矛盾？

队伍下次计划：
调查 B-17

下一场：
7 月 19 日 20:00
```

玩家自己的数值和私密变化只出现在各自手机。

---

# 五、公共舞台卡片系统

公共桌面不应该显示普通聊天应用式的无限气泡。

建议只定义七类展示卡。

## 1. `StageNarrationCard`

AI-KP 公共叙事。

```text
AI-KP

走廊尽头传来一声短促的金属碰撞。
```

## 2. `StageDialogueCard`

公开角色或 NPC 台词。

```text
玛格丽特护士

“教授昨晚没有来过地下室。”
```

## 3. `StageActionCard`

允许公开的行动摘要。

```text
陈默尝试观察护士的反应
```

原始自然语言和私人约束不上大屏。

## 4. `StageResolutionCard`

公开裁决结果。

```text
心理学 · 32 · 普通成功
```

## 5. `StageClueCard`

已公开给 Party 的线索或 Handout。

```text
队伍获得新线索

旧建筑平面图
```

这里只显示 `publicVersion` 和授权素材。

## 6. `StageSystemCard`

安全的系统信息。

```text
所有玩家状态已经同步。
```

## 7. `StageTableRulingCard`

桌务裁定形成的桌面事实。

```text
桌面裁定

铁门保持半开状态。
AI-KP 将据此调整后续场景。
```

---

# 六、公共桌面的显示优先级

公共舞台同时可能收到很多内容，必须有明确队列规则。

建议优先级：

```text
P0 Safety / Pause
P1 Recovery / Table Ruling
P2 Public Decision
P3 Public Resolution
P4 Public Clue Reveal
P5 Scene Narration
P6 Public Dialogue
P7 Atmosphere / Decorative Cue
```

一次只保留一个主要焦点。

不能同时：

```text
播放场景切换
展示骰子
弹出线索
切地图
滚动三条 NPC 台词
```

---

# 七、Stage Cue 展示策略

建议每个公共展示对象带：

```text
displayMode
priority
duration
dismissPolicy
dedupeKey
sourceEventSequences
```

`displayMode`：

```text
replace       替换主视觉
overlay       叠加在当前场景上
lower_third   下三分之一字幕
sticky        保持到明确结束
queue         排队播放
interrupt     中断当前内容
```

`dismissPolicy`：

```text
timed
until_next_cue
until_party_ack
until_decision_closed
manual_replay_available
```

重要原则：

> **关键游戏事务不能依赖公共桌面的 ACK 才成立。**

公共桌面可能关闭，因此：

- Stage ACK 只表示“画面已播放”；
- 不作为 State 成功依据；
- 不作为规则结算依据；
- 不得因为 Stage 断线而重新执行事务。

---

# 八、公共桌面和玩家手机的完整配合示例

玩家陈默在手机输入：

> 我假装整理书桌，观察教授听到“失踪病人”时的反应，但不碰私人信件。

## 第一步：手机私人处理

手机显示：

```text
系统理解
目标：教授
方法：观察反应
掩饰：整理书桌
限制：不碰私人信件
```

公共桌面没有变化。

## 第二步：玩家确认

手机提交 `IntentContract`。

如果行动是公开行为，大屏出现轻量卡：

```text
陈默正在与教授交谈
```

不会显示私人限制和完整原话。

## 第三步：规则裁决

公共桌面显示：

```text
心理学 · 32 · 普通成功
```

前提是该检定按房间规则允许公开。

## 第四步：公共叙事

大屏显示：

> 教授听到“失踪病人”时短暂停顿了一下。

## 第五步：私人补充

陈默手机收到：

> 仅你可见：教授随后下意识看向了北侧书架。

公共桌面和其他玩家手机：

```text
完全不知道还有一条私人补充
```

这就是 Shared Stage 与 Player Companion 的核心分工。

---

# 九、公共桌面不应该展示的内容

必须形成硬禁止清单：

```text
玩家私人笔记
玩家私密线索
玩家私密观察
玩家个人目标
其他玩家私人物品
未确认 IntentContract
隐藏难度
NPC 隐藏数值
NPC 真实动机
完整模组真相
未发现线索
隐藏地图节点
AI-KP 内部计划
恢复选项的幕后影响
错误堆栈
Provider 名称和原始错误
owner_token / player_token / account token
本地路径和 storageKey
```

也不能显示：

```text
“还有 3 条隐藏线索”
“某玩家刚获得了一条私密信息”
“当前场景仍有未发现内容”
```

因为信息存在本身也是剧透。

---

# 十、公共桌面的数据契约

建议最小 DTO 集：

```text
StagePairingCodeDTO
StageSessionDTO
StageSnapshotDTO
StageCueDTO
StageSceneDTO
StagePublicContextDTO
StageNarrationDTO
StageDialogueDTO
StageActionSummaryDTO
StagePublicResolutionDTO
StagePublicMapDTO
StagePublicClueDTO
StagePublicDecisionDTO
StagePauseDTO
StageRecoveryDTO
StageTableRulingDTO
StageSessionSummaryDTO
StageAtmosphereDTO
StageApiErrorDTO
```

## `StageSnapshotDTO`

```json
{
  "schemaVersion": 1,
  "stageSessionId": "stage_xxx",
  "roomId": "room_xxx",
  "stageMode": "live",
  "roomSequence": 1047,
  "stateVersion": 87,
  "scene": {},
  "publicContext": {},
  "activeCue": null,
  "recentPublicCues": [],
  "atmosphere": {},
  "generatedAt": "..."
}
```

## `StageCueDTO`

```json
{
  "cueId": "cue_xxx",
  "type": "public_resolution",
  "priority": 3,
  "displayMode": "overlay",
  "dismissPolicy": "timed",
  "durationMs": 8000,
  "dedupeKey": "action:act_482:resolution",
  "payload": {},
  "sourceEventSequences": [1041, 1042],
  "stateVersion": 87,
  "issuedAt": "..."
}
```

关键要求：

- 每个 Cue 必须有 `dedupeKey`；
- 必须引用已安全投影的事件；
- 不允许 Stage 自己读取 raw events；
- 不允许 Stage 自己查询 ModuleVersion；
- `stateVersion` 只来自 State，不由 Stage 生成。

---

# 十一、Stage 后端架构

建议增加：

# `SharedStageProjectionService`

```text
Engine / State / Journal
          ↓
Projection + Safety
          ↓
Party-safe EngineEvent
          ↓
SharedStageProjectionService
          ↓
StageSnapshot / StageCue
          ↓
Stage WebSocket
```

该服务只接受：

```text
已经通过 Party 可见性裁剪的事件
```

它不应该访问：

```text
keeper_internal
player_private
raw ModuleVersion
raw State mutation
```

同时维护一个非权威的：

# `RoomStagePresentationState`

包括：

```text
当前 stageMode
当前 activeCue
待播放 cue queue
当前公共地图模式
当前公共决定
当前 atmosphere
最近播放 dedupeKey
```

它是可重建的展示状态，不是世界真相：

```text
不推进 rooms.state_version
不作为 Journal 事实来源
不决定规则结果
```

---

# 十二、Stage 重连和去重

公共桌面断线恢复：

```text
1. 使用 stage ticket 重连
2. 请求 StageSnapshot
3. 对齐 roomSequence 和 stateVersion
4. 清理过期 cue
5. 只播放未消费且仍有效的 cue
```

需要防止：

```text
刷新后再次播放一次性 SFX
再次展示旧线索揭示动画
重复播放公共骰子
重复显示 Session Opening
```

每个一次性 Cue 必须有：

```text
dedupeKey
expiresAt
sourceEventSequence
```

公共桌面客户端维护：

```text
consumedCueKeys
```

服务端也要能根据 StageSnapshot 判断哪些内容已经过期。

---

# 十三、公共桌面的视觉规则

这是“十英尺界面”，不是普通网页。

建议最低标准：

```text
正文不小于 26 px
主要叙事 30—38 px
标题 42—56 px
骰子和关键结果 72 px 以上
按钮原则上不出现在大屏
```

其他规则：

- 高对比；
- 不只依赖颜色表达状态；
- 支持减少动画；
- 支持字幕常显；
- 场景图上不叠大量文字；
- 一次只突出一个焦点；
- 远程屏幕分享时仍能读清；
- 16:9 优先，兼容 21:9 和窗口模式；
- 动画不能阻断内容；
- BGM/SFX 失败不影响画面；
- 模组只能提供主题变量，不能注入任意 CSS/JS。

---

# 十四、公共桌面的显示配置

房间规则可以配置：

## 公共角色状态

```text
none
status_only
resource_bars
exact_values
```

默认建议：

```text
status_only
```

例如显示：

```text
正常
轻伤
重伤
昏迷
```

不默认显示所有人的精确 HP / SAN。

## 公共骰子

```text
full
result_only
narrative_only
```

## 公共行动

```text
all_public_actions
result_only
narrative_only
```

## 地图

```text
auto
manual_stage_switch
never
```

这些配置进入 `RoomPolicySnapshot`，不能只保存在前端。

---

# 十五、公共桌面 P0

第一版必须完成：

| 能力 | P0 |
|---|---:|
| 短期配对码和只读 stage session | 是 |
| 公共大厅 | 是 |
| Party 公开 recap | 是 |
| AI-KP 开场 | 是 |
| 实时场景视觉和公共叙事 | 是 |
| 公开 NPC / 角色台词 | 是 |
| 公共行动摘要 | 是 |
| 公共裁决展示 | 是 |
| Party-safe 地图 | 是 |
| 暂停 / 恢复 | 是 |
| 本局公共总结 | 是 |
| WebSocket 重连和 snapshot | 是 |
| Cue 去重 | 是 |
| 手机无大屏 fallback | 是 |
| 字幕和减少动画 | 是 |

---

# 十六、P1 再做

```text
公共 Handout 全屏揭示
全桌投票
公共调查板展示模式
多显示器同步
远程只读 Stage 链接
场景主题包
BGM / SFX
TTS 公共叙事
直播 Overlay
多屏不同布局
高光回放
自定义公共舞台编排
```

基础公共舞台稳定之前，不建议先做复杂特效。

---

# 十七、公共桌面验收清单

```text
1. Stage pairing 不使用 owner_token。
2. stage_token 只能访问 Stage API。
3. Stage Snapshot 不含 player_private。
4. Stage WS 不含 player_private。
5. 私密线索产生时，Stage 不显示任何提示。
6. Stage 不显示隐藏地图节点或数量。
7. Stage 不显示 NPC 隐藏数值或动机。
8. 公开骰子遵守 RoomPolicySnapshot。
9. 隐藏检定不会通过 Stage 泄露难度。
10. Stage 只在 State 成功后显示世界变化。
11. Projection 失败重发时不会重复 State mutation。
12. Stage 刷新不会重复播放线索揭示。
13. Stage 刷新不会重复播放一次性 SFX。
14. 同一 cueId / dedupeKey 不重复消费。
15. Stage 断线不阻断游戏主链路。
16. 没有 Stage 时，公共内容仍进入玩家手机 Party 流。
17. 公共决定只能从玩家手机提交。
18. Stage 不接受世界状态写入。
19. Stage 不查询 raw events。
20. Stage 不查询 raw ModuleVersion。
21. Stage 不显示错误堆栈和 Provider 细节。
22. 暂停页不泄露恢复事故的幕后原因。
23. TableRuling 只显示全桌已经接受的安全结果。
24. Session Summary 不包含任何玩家私密变化。
25. 多块 Stage 同时连接时，内容一致且安全。
```

---

# 最终定义

> **Shared Stage 是 AI-KP 面向全桌的公共主持舞台：它以场景、叙事、公共地图、公开裁决和共同决定为核心，只消费经过 Projection 与 Safety 裁剪的 Party 内容；玩家在手机上输入行动和处理私密信息，桌务在私人设备上处理流程异常，公共桌面本身只读、可重建，并且永远不知道幕后真相。**

下一步建议直接进入最核心的 **`live` 实时公共舞台模式**，把它拆到组件级：主视觉、叙事字幕、角色台词、公共裁决、地图切换、状态栏和 Cue 动画规则。