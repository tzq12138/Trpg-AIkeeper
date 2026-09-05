---
status: candidate
version: 0.1
doc_owner: Product + Architecture
proposed_date: 2026-07-12
release_scope: M0
sources:
  - AI-Keeper 工程总览（2026-07-12）
  - AI-Keeper 产品设计文档顶层审计（2026-07-12）
  - docs/60-开发执行/Batch-0 至 Batch-5
supersedes: []
last_validated: 2026-07-12
---

# AI-Keeper 下一阶段工作总计划

## M0 产品收敛与可信核心闭环

**建议仓库路径：** `docs/60-开发执行/M0-产品收敛与可信核心闭环.md`  
**建议生效方式：** 评审通过后，作为 `docs/60-开发执行/README.md` 的唯一当前执行入口；原 Batch 0–5 保留为历史执行证据或拆分素材，不再单独决定产品方向。

---

# 0. 一页结论

AI-Keeper 当前已经拥有较完整的工程资产：房间、玩家加入、行动、规则结算、状态、投影、防剧透、日志、检查点、剧本导入、地图和前后端基础链路均已有实现，工程总览记录的测试基线约为后端 580 项、前端 17 项。

但下一阶段不应继续横向增加语音、地图、长期战役、社区、插件或更多独立模块。当前真正需要完成的是：

> **把已经存在的能力收敛成一条定义一致、权威清楚、无大屏也能运行、可以解释和纠错、能够完整跑完一次短模组的可信 AI-KP 主链路。**

因此，当前阶段判定为：

| 维度 | 当前判断 |
|---|---|
| 产品方向 | 已有明确倾向，但规范仍有冲突 |
| 功能实现 | 核心能力已广泛实现 |
| 核心闭环 | 已能运行，但尚未完成统一语义下的验证 |
| 测试 | 数量可观，但不能代替黄金路径与权限不变量验收 |
| 生产安全 | 尚未完成 |
| 下一里程碑 | `M0-Verified：可信文字主链路内部验证通过` |

本计划是原路线图中 **Phase 1 与 Phase 2 之间的强制收口门槛**。在本计划通过前，不进入下一轮功能扩张。

---

# 1. M0 产品裁决

以下内容在本阶段视为规范性结论。若需要改变，必须新增 ADR，不能在模块 PRD 或代码实现中自行改写。

## 1.1 核心产品命题

> **2–4 名玩家无需真人 KP，使用一个经过验证的 CoC 7e 短模组，通过私人玩家终端完成一场可解释、可恢复、不剧透的调查游戏；Shared Stage 是可选公共镜像，不是运行依赖。**

M0 首先验证五件事：

1. AI 是否能正确理解玩家行动；
2. 规则、骰子和状态结果是否可信；
3. 公共和私密信息是否公平且不会泄露；
4. 没有真人 KP、没有 Shared Stage 时游戏是否仍能继续；
5. 玩家能否完整结束一场游戏，并理解发生了什么。

## 1.2 M0 固定决策

| ADR 候选 | 决策 | 直接影响 |
|---|---|---|
| ADR-001 | M0 只支持 `ai_only` 运行模式 | 不建设 HumanKeeper 后台，不允许人类房主承担剧情裁决 |
| ADR-002 | 首版使用经过人工验证的参考短模组 | 任意 PDF 自动导入可以保留，但不是 M0 验收前提 |
| ADR-003 | 文字输入是唯一验收基线 | 语音可以作为输入适配器存在，但不得产生另一条业务链路 |
| ADR-004 | Shared Stage 永远可选 | 大屏断线、关闭或从未连接，均不得阻塞行动完成 |
| ADR-005 | 人、设备和服务角色彻底拆分 | `Host` 只保留为旧代码兼容名，不再作为规范概念 |
| ADR-006 | Engine 是唯一权威写入者 | AI、Player、Shared Stage、RoomOwner 均不能直接改变世界状态 |
| ADR-007 | M0 运行时禁止 AI 创造新 Canon | 重大揭示和状态转换必须来自已版本化模组与 Engine 约束，不进入房主剧情复核队列 |
| ADR-008 | M0 以可信短团为目标，不以长期战役为目标 | Continuity、Campaign Governor、Host 缺席自治等级等进入 Later |

## 1.3 角色与设备

| 名称 | 类型 | 是否接触幕后真相 | M0 权限 |
|---|---|---:|---|
| `ScenarioPreparer` | 人，开局前角色 | 是 | 准备或校验参考模组；不参与房间运行时裁决 |
| `RoomOwner` | 人 | 否 | 建房、邀请、成员管理、开始与结束 Session；可以同时是 Player，但身份凭证分离 |
| `TableSteward` | 人，可与 RoomOwner 同一人 | 否 | 暂停、继续、X-card、故障恢复和无剧透急救 |
| `Player` | 人 | 仅角色获知内容 | 提交行动、确认意图、查看回执、管理与分享自己的线索 |
| `SharedStage` | 公共显示设备 | 否 | 只读播放 party-safe 公共投影；不拥有业务权力 |
| `AIKeeper` | 服务 | 受控读取 | 机制建议、澄清建议、叙事生成；不掷权威骰、不写状态 |
| `Engine` | 服务 | 读取必要事实 | 身份校验、规则结算、状态提交、事件生成、权限与可见性执行 |

M0 不存在“既不看真相、又复核核心剧情”的房主。RoomOwner 只能复核操作性问题，例如是否暂停、是否重新连接、是否提交纠错请求；不能判断隐藏真相是否正确。

## 1.4 领域层级

概念层统一为：

```text
ScenarioPackage / ScenarioVersion
    -> Campaign
        -> Room
            -> Session
                -> Scene
                    -> PlayerAction
                        -> ResolutionTransaction
                            -> RuleResult + StateChange + Event + Projection
```

M0 可以继续兼容当前“一间 Room 绑定一次游玩实例”的实现，不要求立即进行大规模数据迁移；但文档、API 语义和后续设计必须区分：

- `ScenarioPackage`：不可变、版本化的内容定义；
- `Campaign`：某一组玩家对某个 ScenarioVersion 的实际游玩实例；
- `Room`：成员、连接和实时访问容器；
- `Session`：一次实际开团过程；
- `ResolutionTransaction`：一次可审计的权威裁决。

---

# 2. M0 黄金路径

任何功能若无法说明自己在以下路径中的位置，不进入 M0。

| 步骤 | 用户可见结果 | 权威拥有者 | 必须覆盖的失败分支 |
|---:|---|---|---|
| 1. 准备参考模组 | 模组版本和质量状态明确 | ScenarioPackage | 模组缺必要真相、线索或结局时禁止开局 |
| 2. 创建 Campaign/Room | 得到房间码和玩家入口 | Room | 重复创建、无效模组、权限失败 |
| 3. 玩家加入与绑定角色 | 玩家看到自己的角色和 ready 状态 | Room + Character | token 无效、角色重复绑定、重连 |
| 4. Session 0 | 内容提示、边界与暂停方式被全员确认 | Safety | 玩家未确认、私密反馈、立即退出 |
| 5. 开场 | Player 进入行动页；Shared Stage 可有可无 | Session + Projection | 大屏未连接、玩家迟到、开场重放 |
| 6. 提交行动 | 行动进入可查询状态 | Transaction | 重复提交、版本冲突、无权限 |
| 7. 意图确认 | 模糊或高影响行动先确认系统理解 | Intent Contract | 目标歧义、实体绑定错误、玩家取消 |
| 8. 权威裁决 | 规则、骰子、状态以原子事务提交 | Rule + State | AI 超时、规则不适用、提交失败、幂等重试 |
| 9. 揭示与回执 | 公共/私密结果按权限到达；玩家知道为何如此 | Projection + Journal | 大屏断线、Player 断线、事件重放 |
| 10. 线索分享 | 私密线索可由拥有者主动生成团队摘要 | Clue | 非拥有者分享、原文误广播、重复分享 |
| 11. 断线恢复 | 快照与补丁最终收敛到同一状态 | State + Journal | ghost patch、旧 patch、重复 effect |
| 12. 结束 Session | 队伍摘要与角色私密摘要正确生成 | Journal + Projection | 中途退出、未决行动、暂停后结束 |

---

# 3. M0 范围

## 3.1 必须进入验收

| 能力 | M0 最小切片 |
|---|---|
| 内容 | 一个原创、获授权或内部可合法使用的参考短模组；版本固定，人工校验 |
| 房间 | 创建、邀请、加入、成员状态、开始、暂停、结束 |
| 身份 | RoomOwner、Steward、Player、SharedStage 凭证和权限分离 |
| 角色 | 选择或绑定角色；基础属性、技能、HP/SAN 与必要状态 |
| 安全 | 内容提醒、边界确认、X-card/暂停、淡出、私密反馈 |
| 行动 | 文字输入、幂等提交、状态查询、取消尚未提交的确认动作 |
| 理解 | 模糊或高影响动作生成 Intent Contract 并由玩家确认 |
| 规则 | CoC 7e 核心技能检定、SAN 和 M0 所需的最小状态后果 |
| 权威 | Engine 唯一提交；RuleResult 先于叙事；所有变更有来源 |
| 投影 | 公共、队伍、角色私密和内部秘密严格分离 |
| 线索 | 私密获得、来源引用、主动分享、团队公开摘要 |
| 恢复 | action 幂等、stateVersion 屏障、快照/补丁收敛、无大屏 fallback |
| 信任 | Resolution Receipt、澄清/申诉入口、追加式纠错记录 |
| 结束 | Session 摘要、安全退出、只读回顾 |

## 3.2 可以保留，但不作为 M0 阻塞项

这些能力已有代码或设计，可以继续存在，但默认关闭、降级或不进入黄金路径：

- PDF 自动导入和复杂质量报告；
- 地图、Token、复杂场景视图；
- STT、TTS、BGM、音频避让和多媒体 Cue；
- 完整战役归档与长期连续性；
- 复杂遭遇、战棋和可插拔战斗运行时；
- 多 provider、MCP 工具扩展和自主 Agent；
- 调查工作台的高级推理辅助。

## 3.3 明确后置

- HumanKeeper 或 AI 辅助真人 KP 模式；
- Host 缺席自治等级与剧情 ReviewBacklog；
- 运行时新 Canon、自动世界扩写和战役方向控制器；
- 任意 PDF 的可靠全自动编译；
- 完整模组编辑器；
- 长期可信记忆大系统、Continuity Packet；
- 独立 Semantic、Item、Combat、Continuity 新模块；
- Schedule、Community、Plugin、Market；
- 动态光照、直播、完整素材 CDN。

---

# 4. 工作组织原则

## 4.1 当前执行状态

从本计划生效起，所有工作使用三个正交维度，不再使用含义不明的“P0 已完成”或“工程验收通过”。

| 维度 | 枚举 |
|---|---|
| 发布范围 | `M0 / M1 / M2 / Later` |
| 风险严重度 | `S0 / S1 / S2 / S3` |
| 成熟度 | `Idea / Draft / Reviewed / Normative / Implemented / Verified / Pilot-ready / Production-ready` |

每份回执必须分别报告：设计状态、实现状态、自动测试状态、手动验收状态和生产状态。

## 4.2 冻结规则

在 M0-Verified 前：

1. 不新增 25、26、27 等平台模块；
2. 不扩展社区、插件、市场、复杂日程和长期战役；
3. 不把视觉、声音或 Shared Stage 演出作为业务完成条件；
4. 不为语音、按钮和文字建立不同裁决链路；
5. 不继续细化任意 PDF 的长尾格式兼容；
6. 不进行全仓一次性 `Host -> SharedStage` 大改名，先以规范术语和兼容别名过渡；
7. 不把测试数量或局部用例通过包装成产品闭环完成。

## 4.3 模块采用“切片”，不追求整模块完成

M0 只启用下列模块的最小切片：

| 类型 | 模块 |
|---|---|
| 核心切片 | 01 Room、02 User、04 Rule、05 Character、07 WorldBook、08 Clue、11 Journal、12 AI-Keeper、13 State、14 Transaction、15 Projection、16 Player Client、17 SharedStage、21 Safety |
| 兼容切片 | 09 Scene 仅保留场景标识与文本；19 Module 仅用于准备参考 ScenarioPackage |
| 非 M0 | 03 高级聊天、06 NPC Agenda、10 WorldClock、18 Asset、20 Voice/Media、22 Schedule、23 Community、24 Plugin/Admin/Ops 的平台化部分 |

“进入核心切片”不代表该模块完整 PRD 都进入 M0，只代表黄金路径所需的最小能力进入验收。

---

# 5. Gate G0：产品与规范收敛

## 5.1 目标

在继续改核心代码前，先建立唯一现行产品口径，关闭顶层 S0 矛盾。

## 5.2 任务

| ID | 任务 | 主要输出 | 退出证据 |
|---|---|---|---|
| G0-01 | 建立产品宪法 | `docs/00-产品规范/00-产品宪法.md` | 目标用户、问题、主命题、非目标和验证指标获评审 |
| G0-02 | 建立运行模式、角色与权限总表 | `01-运行模式角色与权限.md` | AI-only、Owner、Steward、Player、SharedStage、AIKeeper、Engine 权限无重叠 |
| G0-03 | 建立用户旅程与领域生命周期 | `02-核心用户旅程与生命周期.md` | Campaign/Room/Session/Action/Transaction 语义唯一 |
| G0-04 | 建立唯一权威矩阵 | `03-领域对象与唯一权威矩阵.md` | 每类事实、状态、规则、线索、投影和日志只有一个 owner |
| G0-05 | 建立 M0 范围与指标 | `04-M0范围里程碑与指标.md` | Must、Non-gating、Later 清晰；删除式评审完成 |
| G0-06 | 建立安全与非功能基线 | `05-跨域安全与非功能基线.md` | 内容安全、隐私、可访问性、性能、恢复和成本有统一入口 |
| G0-07 | 建立 ADR 目录并录入 ADR-001 至 ADR-008 | `docs/00-产品规范/ADR/` | 所有固定决策有背景、选项、决定和影响 |
| G0-08 | 增加文档元数据与失效关系 | 更新 README 和冲突文档头部 | `normative / exploratory / deprecated / archived` 可见 |
| G0-09 | 修正文档入口和失效链接 | `docs/README.md`、各目录 README | 阅读路径不再把旧 MCP 设计当现行权威 |

## 5.3 必须立即标记的文档

| 文档 | 建议状态 | 处理方式 |
|---|---|---|
| `20-核心架构/AI-Keeper核心链路架构.md` | `normative`，待更新 | 吸收本计划的唯一行动链和角色术语 |
| `20-核心架构/KP_MCP_Design.md` | `deprecated` | MCP 只保留 provider/工具适配价值；删除其业务权威地位 |
| `20-核心架构/soul.md` | `candidate` | 重写为受平台约束的 Narrative Policy，不再允许玩家口述权威骰值或 AI 代骰 |
| `20-核心架构/数据流.md` | `candidate -> normative` | 更新 commit、reveal、complete 三阶段语义 |
| `30-平台子系统/17-Host-Client.../PRD.md` | `candidate` | 改称 SharedStage；房主控制台拆出 |
| `30-平台子系统/14-Transaction.../PRD.md` | `candidate` | 删除 SharedStage ACK 对业务完成的阻塞 |
| `30-平台子系统/11-Journal.../PRD.md` | `candidate` | Owner 默认只看脱敏审计，不看玩家私密原文 |
| `50-设计哲学/*` | `exploratory` | 只有被 ADR 接纳的部分才能进入规范 |
| `60-开发执行/AI-Keeper最终版本开发文档.md` | `exploratory / long-term` | 不再作为当前 M0 范围依据 |

## 5.4 G0 退出条件

- 八项产品裁决全部形成 ADR；
- 现行规范中不再同时存在三种 Host 定义；
- 现行规范中不再存在“AI 直接写状态”或“先叙事后掷骰”的合法路径；
- 现行规范中不再存在 SharedStage ACK 决定业务完成；
- Campaign、Room、Session、Action、Transaction 有唯一含义；
- 所有 M0 模块引用顶层定义，而不是自行重定义。

---

# 6. Gate G1：权威裁决链与 AI 边界

## 6.1 目标

把“AI 不写状态”从设计口号落实为不可绕过的运行不变量。

## 6.2 唯一合法链路

```text
PlayerAction
-> 身份、角色拥有权、场景与资产校验
-> Mechanic / Semantic Compile
-> 必要时 Intent Contract 确认
-> RuleExecutor 产生权威 RuleResult
-> StateService 原子提交 StateChange
-> 形成 RevealPlan
-> AI 基于已提交结果生成叙事
-> ProjectionDispatcher 分发
-> Journal 写入 Receipt 与事件引用
```

无规则动作也必须先通过 Engine 验证并形成可追踪事务，AI 不能因为“不需要掷骰”就拥有直接写场景、NPC 或标签的权力。

## 6.3 任务

| ID | 任务 | 关键要求 | 验收证据 |
|---|---|---|---|
| G1-01 | 统一服务端 Action/Transaction 状态机 | `submitted -> needs_confirmation? -> queued -> resolving -> committed -> revealed -> completed`；失败与取消有终态 | 状态转换测试和非法转换测试 |
| G1-02 | 明确客户端状态与服务端状态分离 | `idle/submitting` 只属于 UI，不写入权威业务状态 | 前后端契约说明和类型检查 |
| G1-03 | 移除或封禁 MCP `direct mutation` | MCP 只能返回建议或调用受控 Engine 工具 | 全仓检索、单测、拒绝路径记录 |
| G1-04 | 保证 RuleResult 和级联状态先于叙事 | 叙事输入包含最终 HP/SAN/倒地等后果 | “事实滞后”回归用例 |
| G1-05 | 重写 Narrative Policy | AI 不接受玩家口述骰值，不自行生成权威骰值，不宣告未提交结果 | Prompt 契约测试和坏输出测试 |
| G1-06 | 定义 retry 语义 | commit 前可重试；commit 后只能重渲染叙事或生成纠错事务，不得静默重掷 | 幂等与重试测试 |
| G1-07 | 将 `keeperNotes` 标为 non-canonical | 计划、猜测和摘要不得自动升级为事实 | 上下文构造测试 |
| G1-08 | 统一来源追踪 | 每个 StateChange 关联 action、transaction、rule result 和 event | 事件链可重建样例 |

## 6.4 G1 硬性不变量

1. 数据库中不存在来源为 AI 文本的直接权威写入；
2. 任何 HP、SAN、物品、线索、场景进度或状态标签变化均能追溯到 Engine 事务；
3. Narrative 永远消费已提交结果，不先行宣布；
4. 失败重试不会产生第二次骰子、第二份奖励或重复扣减；
5. 玩家自报骰值只能作为聊天内容，不能成为 RuleResult。

---

# 7. Gate G2：状态一致性、投影时序与可选 Shared Stage

## 7.1 目标

解决幽灵补丁、重复效果、私密结果过早揭示和大屏阻塞业务的问题。

## 7.2 三种状态必须分离

| 层 | 含义 | 是否等待 SharedStage |
|---|---|---:|
| `committed` | 权威状态已经原子提交 | 否 |
| `revealed` | 服务端已经按 RevealPlan 发布允许公开的事件 | 否 |
| `played` | 某个 SharedStage 客户端已经播放到某一步 | 可以记录，但只属于表现层 |

`completed` 表示该 PlayerAction 的服务端业务结果已经可被相关客户端消费，不得依赖某块大屏的播放 ACK。

## 7.3 任务

| ID | 任务 | 关键要求 | 验收证据 |
|---|---|---|---|
| G2-01 | 实现 stateVersion 屏障 | patch 带 base/current version；超前进入 buffer；落后丢弃或触发 sync | 前端纯函数单测和后端重连测试 |
| G2-02 | 统一 snapshot 与 patch 合并规则 | full snapshot 到达后按版本处理剩余 patch，禁止覆盖新状态 | 乱序、重复、断线场景测试 |
| G2-03 | 服务器端 RevealPolicy | 先发布公共 reveal，再发布私密结果；发布不等于大屏播完 | 无 SharedStage 的完整行动测试 |
| G2-04 | 移除 Host ACK 业务门控 | ACK 只用于播放恢复、去重和观测 | 大屏中途断线不阻塞 Player |
| G2-05 | 拆分投递目标与可见范围 | 逻辑上区分 `deliveryTarget` 与 `visibilityScope`，避免 `host` 同时表示设备和权限 | 事件契约 ADR 与投影测试 |
| G2-06 | 明确 HostStore 数据归属 | 权威数据迁出表现层；播放游标可从事件重建 | 重启/刷新恢复测试 |
| G2-07 | 完成 Action 幂等与终态查询 | HTTP 重试、WS 重放、刷新均只产生一次效果 | action_id 重复提交测试 |
| G2-08 | 建立 phone-only fallback | 只有 Player 终端时仍能看到公共叙事的文本版本 | 两玩家无大屏手动验收 |

建议的逻辑事件维度：

```text
deliveryTarget: shared_stage | player_terminal | owner_console | internal
visibilityScope: public | party | character_private | system_private | scenario_secret
recipientIds: []
```

短期可以继续兼容现有 `audience=host/player/party/system` 字段，但规范和新逻辑不得继续混淆“投给什么设备”和“谁有权限知道”。

## 7.4 G2 退出条件

- SharedStage 从未连接也能完成整场黄金路径；
- SharedStage 在行动中断线，Player 不会永久停在 resolving；
- Player 断线期间发生多次变化，重连后最终状态只应用一次；
- 重复 HTTP 请求和重复 WS 事件不产生重复状态效果；
- 私密线索不会因为投影时序错误提前出现在其他玩家端或公共舞台。

---

# 8. Gate G3：Intent Contract、Resolution Receipt 与纠错

## 8.1 目标

让玩家不仅得到结果，还能确认系统理解了什么、为什么这样判、哪里可以纠正。

## 8.2 Intent Contract 最小结构

M0 不建设完整 Semantic 大模块，只定义一份最小合约：

| 字段 | 含义 |
|---|---|
| `actor` | 实际行动角色，由服务端绑定 |
| `rawIntent` | 玩家原始输入 |
| `interpretedAction` | 系统对动作的简明理解 |
| `target` | 绑定后的目标实体或目标描述 |
| `method` | 玩家采用的方式 |
| `constraints` | 已知限制、物品或场景条件 |
| `mechanicSuggestion` | 建议使用的技能、难度或无需检定 |
| `riskFlags` | 不可逆、信息揭示、稀缺资源、重大状态变化等 |
| `confirmRequired` | 是否需要玩家确认 |
| `confirmReason` | 需要确认的原因 |

必须确认的典型情况：目标有歧义、系统绑定了不同实体、动作会消耗稀缺资源、动作会造成不可逆状态、动作会触发重大信息揭示。普通移动、查看已经公开的信息和无歧义低风险动作不应反复打断。

## 8.3 Resolution Receipt 最小结构

| 字段 | 含义 |
|---|---|
| `actionId / transactionId` | 可追踪标识 |
| `understoodAs` | 系统最终采用的行动理解 |
| `ruleApplied` | 使用的规则、技能和难度 |
| `rollResult` | 权威骰值和成功等级；无检定时明确写 none |
| `stateChanges` | 提交前后差异 |
| `publicOutcome` | 团队可见结果摘要 |
| `privateOutcome` | 仅当前角色可见结果 |
| `sourceRefs` | 规则、模组节点、线索或事件引用 |
| `correctionStatus` | 正常、争议中、已纠正 |

## 8.4 任务

| ID | 任务 | 主要输出 | 验收证据 |
|---|---|---|---|
| G3-01 | 定义 Intent Contract 契约和确认策略 | 后端 schema、前端确认 UI、ADR | 模糊/非模糊输入测试 |
| G3-02 | 将确认纳入 Action 状态机 | `needs_confirmation` 不得提前执行 | 取消、修改、确认测试 |
| G3-03 | 建立 Resolution Receipt | Player 可查看；Journal 可追踪 | 技能检定、SAN、无检定三类回执 |
| G3-04 | 建立最小申诉入口 | “系统理解错了”“规则应用有误”两种类型 | 提交、受理、拒绝和纠正测试 |
| G3-05 | 使用追加式纠错 | 原事务保留，生成 correction transaction；不静默覆盖历史 | 回放与审计测试 |
| G3-06 | 统一房主急救语义 | RoomOwner 只能暂停、重试传输或发起纠错，不能直接编辑事实 | 权限测试 |
| G3-07 | 采集理解质量指标 | 确认率、取消率、澄清率、纠错率 | 指标日志样例 |

## 8.5 G3 退出条件

- 玩家可以在执行前发现系统误解；
- 任何已执行行动都有可读回执；
- 纠错不会抹去原始历史，也不会绕过 Engine；
- 房主无法通过“急救”直接改变 HP、SAN、线索、骰值或隐藏真相。

---

# 9. Gate G4：事实、认知、线索与防剧透

## 9.1 目标

让反幻觉从 Prompt 约束升级为数据和投影约束，并使用可控内容验证完整调查链路。

## 9.2 M0 最小事实类型

| 类型 | 含义 | 能否改写 Canon |
|---|---|---:|
| `CanonicalFact` | ScenarioPackage 或 Engine 确认的客观事实 | 仅受控流程可以 |
| `Observation` | 某角色实际感知的内容 | 否 |
| `Evidence` | 有来源引用的线索或物证 | 否 |
| `Testimony` | NPC、文档或其他主体的陈述，可能不真实 | 否 |
| `Hypothesis` | 玩家或 AI 的推测 | 否 |
| `Summary` | 从已有内容派生的压缩表述 | 否 |
| `KeeperPlan` | AI 的计划、候选方向或节奏建议 | 否，永久 non-canonical |

每条可进入 AI 上下文的声明至少带：类型、来源、可见范围、有效状态和关联实体。M0 不需要建立完整长期记忆系统，但不能继续用无类型的文本笔记混合事实和计划。

## 9.3 参考 ScenarioPackage

M0 使用一份固定测试模组，建议满足：

- 原创、获授权或内部可合法使用；
- 适合 2–4 名玩家的一次短团；
- 有明确开场、调查中段和结局；
- 包含公共线索、至少一条角色私密线索、至少一次 SAN 事件；
- 包含至少一个需要 Intent Contract 确认的模糊动作；
- 包含至少两个 Reveal Gate 和两个可判定结局；
- 不依赖战棋、复杂地图或语音才能完成；
- 所有 Canon、线索来源、揭示条件和结局条件可被自动校验。

现有 PDF/Scenario Pipeline 可以用于生成这份包，但验收对象是最终的固定版本，不是导入器对任意文档的泛化能力。

## 9.4 任务

| ID | 任务 | 关键要求 | 验收证据 |
|---|---|---|---|
| G4-01 | 定义最小事实类型和来源字段 | WorldBook、Clue、Journal、AI Context 使用同一语义 | schema/ADR 和迁移说明 |
| G4-02 | 建立上下文最小化规则 | AI 只收到当前任务需要且当前可见的事实 | 角色 A/B 不同上下文测试 |
| G4-03 | 完成线索证据链 | 获得、拥有、分享、公开摘要、解析都有事件引用 | 线索生命周期测试 |
| G4-04 | 固定参考 ScenarioVersion | 版本、哈希、质量报告、测试 fixture 可复现 | 内容包和校验报告 |
| G4-05 | 禁止运行时新 Canon | AI 新设定只能作为建议被拒绝或映射到已有节点 | 越界输出测试 |
| G4-06 | 强化 SpoilerGuard | 输出前检查；命中后安全降级，不把秘密写入日志或错误回显 | 红队用例 |
| G4-07 | 绑定 model/prompt/schema 版本 | 每次 AI 结果可复现地知道使用了什么版本 | Journal 样例 |
| G4-08 | 建立反剧透红队集 | 猜凶手、诱导真相、跨角色套取、日志导出、重连补丁等 | 独立测试报告 |

## 9.5 G4 退出条件

- 玩家猜测不会被升级成 Canon；
- 未发现真相不会进入 Player 上下文、Player 事件、SharedStage 或 RoomOwner 日志；
- 私密线索只有拥有者可见，分享后只公开授权摘要；
- AI 输出非法新事实时被拒绝或安全重写；
- 一次叙事可以追溯到 ScenarioVersion、上下文来源和 prompt/schema 版本。

---

# 10. Gate G5：最小安全与 Session 闭环

## 10.1 目标

对 AI 主持的恐怖题材产品，桌面安全不是上线后运营功能，而是 M0 主链的一部分。

## 10.2 任务

| ID | 任务 | 关键要求 | 验收证据 |
|---|---|---|---|
| G5-01 | Session 0 内容提示 | 模组级内容标签、强度说明和退出方式 | 未确认不得开始 |
| G5-02 | 边界设置 | 玩家可私密设置 lines/veils 或等价最小结构 | AI Context 不接收被禁止内容 |
| G5-03 | X-card / 全局暂停 | 任一玩家可触发；SharedStage 立即清屏或淡出；不需要说明理由 | 多端同步测试 |
| G5-04 | 私密反馈 | Steward 只看操作信号，不默认看到敏感原文 | 权限和脱敏测试 |
| G5-05 | 淡出与替代叙事 | AI 收到安全指令后不继续扩写受限内容 | Prompt/输出测试 |
| G5-06 | Session 结束 | 处理未决行动，生成 party-safe 与 player-private 摘要 | 正常结束和中途结束测试 |
| G5-07 | 最小可访问性 | 核心信息不依赖音频；可减少动画；手机小屏可完成主链 | 手动检查清单 |

## 10.3 G5 退出条件

- 任一玩家能立即暂停，不依赖 RoomOwner 在线；
- 安全操作不会泄露是谁、为什么或其私密说明；
- 音频、动画或大屏不可用时仍有等价文字反馈；
- Session 可以正常结束，也可以从暂停状态安全结束；
- 摘要不会混入角色未知事实或其他玩家私密信息。

---

# 11. Gate G6：黄金路径验收与 M0-Verified

## 11.1 目标

用一条固定可复现路径证明产品闭环，而不是继续以模块数量和测试数量替代验收。

## 11.2 自动化测试矩阵

| 类别 | 必测场景 |
|---|---|
| 权限 | 伪造 characterId、伪造 RoomOwner、SharedStage 尝试写状态、跨玩家读取私密线索 |
| 权威 | AI direct mutation、先叙事后规则、重复 action、commit 后重试 |
| 状态 | snapshot/patch 乱序、Player 离线多次更新、旧 patch、重复 WS 事件 |
| 投影 | party/private/secret 分层、无 SharedStage、SharedStage 中途断线 |
| 理解 | 明确行动、模糊目标、高影响动作、取消确认、修改确认 |
| 规则 | 普通成功/失败、困难/极难、SAN 后果、无检定动作 |
| 线索 | 私密获得、非拥有者分享、授权分享、公开摘要、回放 |
| 防剧透 | 猜测真相、诱导提示、日志导出、错误回显、RAG 跨角色污染 |
| 安全 | X-card、淡出、私密反馈、暂停后恢复、暂停后结束 |
| 恢复 | 服务端/前端重连、action 查询、检查点恢复、幂等终态 |

## 11.3 手动黄金路径

至少完成两套固定验收：

### 场景 A：两玩家、无 SharedStage

```text
建房
-> 两名玩家加入并绑定角色
-> Session 0
-> 开场
-> 提交明确行动
-> 提交模糊行动并确认
-> 完成一次检定和一次 SAN 结果
-> 获得私密线索并分享摘要
-> 一名玩家断线后恢复
-> 发起一次纠错请求
-> 结束 Session 并查看摘要
```

### 场景 B：四玩家、有 SharedStage

重点验证公共演出、并发行动、私密投影、Stage 断线与恢复、X-card 和最终摘要。SharedStage 在中途关闭后，主链必须继续。

## 11.4 M0 硬性发布门槛

| 门槛 | 通过条件 |
|---|---|
| 顶层决策 | 无未裁决 S0；所有现行规范引用同一角色、权威和生命周期定义 |
| 权威写入 | 自动化和手动验收中，AI/Player/Stage 未发生任何越权状态写入 |
| 剧透 | 固定红队集与两次手动场景中无未授权真相泄露 |
| 一致性 | 无重复 effect、ghost patch 或重连后状态分叉 |
| 可选舞台 | 无 SharedStage 可以完整结束；Stage 断线不阻塞业务 |
| 可解释性 | 每个权威行动均有 Intent/Rule/State/Receipt 链路 |
| 纠错 | 所有纠错均追加记录，不静默覆盖历史 |
| 安全 | X-card、暂停、淡出和私密反馈全程可用 |
| 回归 | M0 自动化用例、前端类型检查与构建通过；失败项必须逐项披露 |
| 证据 | 生成统一 M0 验收报告、事件轨迹样例和剩余风险清单 |

## 11.5 首轮学习指标

这些指标在 M0 先建立基线，不因缺少历史数据随意设定漂亮阈值：

- 从建房到开场的耗时；
- 行动端到端 P50/P95 延迟；
- Intent Contract 触发率、取消率和修改率；
- 玩家澄清率、纠错率和人工急救率；
- provider fallback 率；
- 每玩家小时模型成本；
- Session 完成率；
- 玩家对“系统正确理解我”“结果可信”“没有被剧透”的评分。

M0 验收报告必须给出实测值和样本量，不能只写“体验良好”。

---

# 12. M0-Verified 之后：Closed Pilot Gate

M0-Verified 只表示内部可信主链路成立，不表示可以面向外部用户。以下事项在封闭试用前必须完成，但不应抢在 G0–G6 前分散资源：

| ID | 能力 | 最低要求 |
|---|---|---|
| P-01 | Token 安全 | 替换敏感 localStorage；RoomOwner、Player、SharedStage 凭证分离和撤销 |
| P-02 | WebSocket 安全 | 短效票据、重放防护、连接权限校验、失效处理 |
| P-03 | 数据迁移与备份 | 可重复 migration；备份、恢复和删除语义有演练证据 |
| P-04 | 可观测性 | request/action/transaction/event 关联；敏感字段脱敏；S0 告警 |
| P-05 | 成本与降级 | provider 超时、限流、fallback、单房间成本上限和熔断 |
| P-06 | 内容权利与隐私 | 上传授权声明、第三方模型披露、保留周期、删除和语音同意策略 |
| P-07 | 滥用与限流 | 邀请码、行动提交、导入和 AI 调用的限流与审计 |
| P-08 | 浏览器与可访问性 | 目标设备矩阵、键盘/触控、对比度、减少动画和纯文字模式 |

只有 Closed Pilot Gate 通过后，状态才可从 `Verified` 提升为 `Pilot-ready`。

---

# 13. 与现有执行文档的关系

| 现有文档 | 新处理方式 |
|---|---|
| `Batch-0-文档归档与索引.md` | 被 G0 实质取代；保留为历史整理记录 |
| `Batch-1-开发态稳定性与实时闭环.md` | 房间、WS、Lobby 和 provider 诊断保留；语音、多媒体和非黄金路径内容不再优先 |
| `Batch-2-状态版本屏障与投影时序.md` | 合并到 G2；原“等待 Host 关键节点再释放”改为服务端 RevealPolicy，不等待实际播放 ACK |
| `Batch-3-AI反幻觉与真相锁定.md` | 拆入 G1 和 G4；以权威链和事实类型为基础，不只依赖 Prompt |
| `Batch-4-线索证据链与防剧透.md` | 合并到 G4；补充统一事实类型与参考 ScenarioVersion |
| `Batch-5-验收与回归.md` | 被 G6 扩展；从十步技术链升级为完整产品黄金路径 |
| `AI-Keeper最终版本开发文档.md` | 作为长期能力参考，不再决定当前发布范围 |
| `数据流bug+思考.md` 中事实滞后 | G1 的首要回归项 |
| `数据流bug+思考.md` 中剧透时序 | G2 + G4 解决，但不使用大屏 ACK 作为业务锁 |
| 幽灵补丁 | G2 的首要回归项 |
| 音频避让失败 | 语音/媒体非 M0，关闭相关功能即可不阻塞 M0 |

---

# 14. 依赖与并行顺序

```text
G0 产品与规范收敛
 ├─> G1 权威裁决链 ──> G3 Intent / Receipt
 ├─> G2 状态与投影 ──┐
 └─> G5 安全闭环      ├─> G4 事实与防剧透 ──> G6 黄金路径验收
                      └──────────────────────> G6

G6 通过 -> Closed Pilot Gate
```

执行规则：

- G0 必须先完成 ADR-001、ADR-004、ADR-005、ADR-006，G1/G2 才能进入实现；
- G1 与 G2 可以并行，但必须共同使用同一 Transaction 状态机；
- G3 依赖 G1 的 Action/Transaction 契约；
- G4 依赖 G1 的权威边界和 G2 的可见性语义；
- G5 在角色权限确定后可以并行；
- G6 之前禁止引入新的产品能力。

---

# 15. 每个任务的完成定义

任何任务标记为 Done，必须同时给出以下内容：

```yaml
task_id:
release_scope: M0
risk_severity: S0 | S1 | S2 | S3
design_status: Reviewed | Normative
implementation_status: Not-needed | Implemented
automated_test_status: Passed | Failed | Not-applicable
manual_acceptance_status: Passed | Failed | Not-run
production_status: Not-ready | Pilot-ready | Production-ready
evidence:
  - changed_files
  - test_commands_and_fresh_outputs
  - manual_steps_and_result
  - screenshots_or_event_trace_if_needed
remaining_risks:
rollback_or_disable_strategy:
```

以下情况不得写“通过”：

- 只完成设计，没有实现，却称工程完成；
- 局部测试通过，但全量回归存在未解释失败；
- 依赖前端隐藏来实现后端权限；
- 手动路径未跑，只根据单测推断体验可用；
- 仍有 S0 未裁决或无法复现的剧透事故；
- 生产安全事项未完成，却称生产就绪。

---

# 16. 首批开工清单

本计划通过后，第一批只做规范和任务切分，不直接扩功能：

1. 将本文件加入 `docs/60-开发执行/`，更新当前执行入口；
2. 创建 `docs/00-产品规范/` 和六份顶层规范骨架；
3. 完成 ADR-001 至 ADR-008；
4. 给 `KP_MCP_Design.md`、`soul.md`、`AI-Keeper最终版本开发文档.md` 和 `50-设计哲学` 添加状态头；
5. 更新核心链路图，明确 `committed / revealed / played / completed`；
6. 完成 M0 模块切片和“删 M0”评审；
7. 从现有 Batch 1–4 中抽取 G1、G2 的具体代码任务包；
8. 固定参考 ScenarioVersion 和黄金路径测试数据；
9. 只有上述入口条件满足后，开始 G1/G2 工程改动。

---

# 17. 最终完成定义

当且仅当以下陈述都成立，下一阶段才算完成：

> AI-Keeper 可以让 2–4 名玩家在没有真人 KP、没有 Shared Stage、使用固定短模组的情况下，从建房走到 Session 结束；每个行动都经过统一权威链，模糊动作可确认，结果可解释，私密信息不泄露，断线后状态能收敛，安全工具随时可用，任何纠错都有追加式审计记录。

达到该状态后，项目才适合选择下一条路线：

- 扩展文字基础体验；
- 把语音接入同一 Intent Contract；
- 提升模组生产能力；
- 或进入 Closed Pilot 安全与运维补强。

在此之前，继续增加页面、模块或沉浸表现，只会放大当前边界不清和验收失真的成本。
