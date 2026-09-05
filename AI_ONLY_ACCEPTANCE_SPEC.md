# AI-Keeper 纯 AI 模式验收规范

状态：草案 v1.1 — 架构评审通过，发布门禁已定义，执行证据进行中（2026-08-20）  
适用范围：CoC 7e、`runtime_version=v2`、`session_mode=ai_only`

本文件是下一阶段产品、Prompt、Engine、UI 和测试的唯一验收口径。已有 PRD、`soul.md`、`rules.md`、`contract.md` 和黄金模组文件仍是实现输入，但与本文件冲突时必须先修订本文件或明确记录例外。

## 1. 产品定义与边界

纯 AI-Keeper 的定义不是让模型直接写入 HP、SAN、物品或线索，而是：

> 2–4 名玩家在没有人类 KP 理解意图、裁定规则、处理争议或推动剧情的情况下，从创建房间跑到有效结局；确定性 Engine 仍是唯一权威状态写入者。

人类房主可以存在，但只承担房间运营和安全控制：邀请/移除、暂停、重试、结束、归档、公共舞台控制和故障恢复。房主不得成为正常行动的裁判，不得修改骰点、角色数值、线索揭示或剧情结局。

### 1.1 纯 AI 模式的硬约束

对 `session_mode=ai_only` 的游戏行动：

- 不得产生 `awaiting_host_exception` action，也不得发出要求 Host 裁决的事件；
- 低置信度或有实质歧义时，必须进入玩家澄清/玩家选择，不得转 Host；
- 已由当前 `RiskContract` 明确授权的普通规则后果（包括正常失败、已声明的资源消耗和规则定义的伤害）不要求结果后再次确认；
- 超出 `RiskContract` 的风险、PvP、共享资源变化、限制另一名玩家、放弃队友或结局选择，必须由受影响玩家按 `ActionConsent` 确认；玩家不能否决已经按契约授权、且已完成检定/结算的普通失败结果；
- 规则缺失或规则源不可用时，只能使用已绑定规则版本的保守默认、拒绝该行动，或暂停为只读恢复；
- Provider 失败时必须按运行包的降级策略执行；不得让模型编造规则、事实、线索或状态；
- 系统不可恢复错误可以暂停房间，但不能把裁决工作转交给人类 Host；
- 管理员审计接口可以读取历史 `awaiting_host_exception`，但不得把它当作纯 AI 游戏的运行路径。

### 1.2 非目标

在 AI-Only Golden Run 通过前，不扩展新的规则系统、通用平台能力、复杂战斗、内容商城、图片/地图效果或任意时间线回滚。

## 2. 角色边界与权威链路

| 角色 | 可以做什么 | 明确不能做什么 |
| --- | --- | --- |
| Player | 声明意图、补充澄清、确认自己的风险、接受或拒绝玩家同意 | 把声明直接写成事实；修改数值或隐藏事实 |
| Director | 解释意图、提出有限候选、引用已授权上下文、提出机制计划 | 直接提交状态 patch；越过 RevealLedger；创造未编译线索 |
| Engine | 校验前置条件、执行 CoC 检定、生成随机数、提交状态和事件 | 依赖模型口头结果；让 Host 改骰点或结果 |
| Narrator | 将已提交结果转成玩家可见叙事，按受众过滤 | 增加未验证事实、秘密或机械效果 |
| Room Owner | 邀请/移除、暂停、重试、结束、归档、公共舞台控制、系统恢复 | 正常裁决、修改 HP/SAN/物品/线索/结局 |
| Stage Client | 展示公共/私密投影、连接恢复、只读状态提示 | 改写权威状态、代替玩家确认或代替 Engine 裁决 |
| Legacy Host Adjudicator | 仅在非 `ai_only` 房间处理历史 Host review/exception | 在 `ai_only` 房间接受裁决、改骰点或修改结果 |
| Admin | 发布/隔离规则与运行包、审计、恢复服务 | 通过后台替代游戏内裁决 |

权威链路固定为：

```text
玩家原始输入
→ Director 意图解释
→ Intent Contract / 玩家澄清或确认
→ Engine 机制计划与规则版本
→ Engine 随机数和规则回执
→ Engine 事务状态变更
→ RevealLedger 揭示结果
→ SpoilerGuard 受众/秘密边界校验
→ Narrator 叙事
→ ProjectionDispatcher Player/Stage 最终投影
```

Director 提出的 `mechanic_plan` 只是建议；只有经过 Engine 前置条件、规则绑定和风险契约校验后生成的 `authoritative_mechanic_plan` 才可驱动检定和状态写入。`SpoilerGuard` 与 `ProjectionDispatcher` 是权威链上的强制节点，不是可选展示层。

每一步都必须保留稳定 ID、规则版本、状态版本、审计结果和失败原因，供重连、回放和 Golden Run 指标使用。

### 2.1 `ai_only` Host API 门禁

| Host/Owner API | `ai_only` 语义 | 稳定门禁 |
| --- | --- | --- |
| action review resolve | 不允许 Host 裁决 | `409 AI_ONLY_HOST_ADJUDICATION_DISABLED` |
| action recalculate | 不允许 Host 重算 | `409 AI_ONLY_HOST_ADJUDICATION_DISABLED` |
| action exception resolve | 不允许 Host 处理例外 | `409 AI_ONLY_HOST_ADJUDICATION_DISABLED` |
| turn skip | 不允许 Host 跳过；缺席按 `absent_policy` | `409 AI_ONLY_HOST_ADJUDICATION_DISABLED` |
| turn resolve | 仅允许幂等后台唤醒任务，不新增裁决，不是正常必经路径 | 非裁决唤醒或 `409` |
| checkpoint recovery | 只做系统恢复，必须审计，不能选择性改结果 | 仅 `recovering`，拒绝 outcome patch |
| end room | 只能写 `room_runtime_status=ended` + `ending_status=aborted`（`termination_reason=owner_terminated`） | 不得生成作者结局或改写 action outcome |

管理员审计、发布、隔离和服务恢复不属于游戏内裁决，但必须保留 actor、原因和影响范围。

## 3. 纯 AI 自主决策矩阵

| 情况 | 纯 AI 处理 | 可接受终态 |
| --- | --- | --- |
| 低风险轻微歧义 | 采用最可逆、最保守的解释，并在理解摘要中说明 | `queued` → `completed`，`resolution_outcome=success|failure|no_check` |
| 会改变结果的歧义 | 返回 2–3 个 Engine 过滤后的候选，等待玩家选择或修改 | `awaiting_player_choice` |
| 超出 RiskContract 的伤害、资源消耗、PvP、共享资源或不可逆状态 | 展示影响与确认项，等待受影响玩家确认 | `awaiting_player_consent` |
| 没有风险/压力/失败代价 | 不强行投骰，直接叙事或执行可逆动作 | `completed`，`resolution_outcome=no_check` |
| 规则缺失但有安全默认 | 使用绑定规则版本内的保守默认，并记录原因 | `completed`，`resolution_outcome=partial_success|no_check` |
| 规则缺失且无安全默认 | 拒绝行动并给出可行动替代，不能编造 | `rejected` |
| Provider 超时/无效响应 | 先用已登记、已测试的确定性降级；无安全降级则拒绝或暂停只读恢复 | `completed` 或 `rejected`；房间另记 `room_runtime_status=paused_system` |
| 玩家质疑结果 | 重新解释意图、复核规则和审计；只在边界内补偿 | 新 action 或 `rejected`，不得 Host 裁决 |
| 系统不可恢复错误 | 保留已提交状态，暂停房间并提供恢复/结束入口 | action 不写终态；房间记 `room_runtime_status=paused_system` 或 `ended` |
| Host 离线 | 不影响上述自主路径 | 不得因此进入 Host 等待 |

### 3.1 P0-1 状态机调整

现有数据库状态继续兼容历史和非纯 AI 房间；纯 AI 房间必须把动作生命周期、房间运行状态和结算结果分成三层。历史字段可映射，但不得混用：

```text
action_status: queued | resolving | awaiting_player_choice |
               awaiting_player_consent | completed | rejected |
               canceled | retrying_provider | ...
room_runtime_status: lobby | running | paused_by_owner | paused_system |
                     recovering | ended
resolution_outcome: success | failure | partial_success | no_check |
                     blocked | not_applicable
```

`action_status=completed` 只表示动作生命周期完成；`room_runtime_status=paused_system`/`ended` 是房间级状态，不是动作终态；安全中止不得把动作伪装成 `resolved` 或 `completed`。每次状态转换同时记录三层快照和 `resolution_id`。纯 AI 房间采用以下动作语义：

```text
analyzing
├─ player_clarification_required  (草稿阶段，等待玩家补充)
awaiting_confirmation
├─ awaiting_player_choice         (选择解释/路线)
├─ awaiting_player_consent        (受影响玩家同意)
queued / resolving
├─ retrying_provider               (阶段事件，不写成 Host 队列)
├─ completed                        (并由 resolution_outcome 区分结果)
├─ rejected
└─ canceled                        (仅显式安全撤销，不替代房间 ended)
```

房间运行状态的 `paused_by_owner`、`paused_system`、`recovering`、`ended` 必须由房间运行状态 API/审计写入，不能伪装成 action 状态。

`awaiting_host_exception` 只对非 `ai_only` 运行路径保留。历史记录和管理员审计可以读取它，但任何 `ai_only` action 在草稿确认、Engine 路由、后台结算和协作批次中都必须在写入前被拒绝或转成玩家路径。

## 4. KP 行为内核（必须可测试）

### 4.1 意图解释

- 尊重玩家字面声明，不替玩家增加未声明动作；
- 不把愿望、猜测或角色背景写成世界事实；
- 复合动作拆成有序步骤，任何一步失败都明确后果；
- 只在不同解释会导致不同结果时追问；
- 解释摘要必须可被玩家纠正，并保留原始声明。

### 4.2 检定触发

- 同时存在不确定性、风险/时间压力和失败代价时才要求检定；
- 规则源、技能、难度和奖励/惩罚骰必须来自运行包或已资格化规则版本；
- 隐藏检定必须有编译规则声明；不能为了增加戏剧性临时投骰；
- 信息获取失败不能永久锁死唯一主线入口。

### 4.3 失败推进

失败应选择至少一种可验证后果：付出代价、得到不完整信息、引发危险、消耗时间/资源、改变 NPC 态度、暴露行动或推进压力。禁止无后果失败和无意义死局。

### 4.4 线索调度

- 核心线索至少有 2 种获取路径或一个已编译恢复节点；
- 区分玩家已知、角色认知、未证实猜测和剧本真相；
- 提示分层，不能直接揭底；
- 已揭示线索不重复刷屏，所有新揭示绑定稳定 clue ID 和 citation。

### 4.5 NPC 自主

重要 NPC 至少具备目标、已知、秘密、恐惧、可交换资源、对角色态度、压力行为和临场创造边界。NPC 的行动依据自身动机和已授权事实，不因玩家点击而无条件吐露信息。

### 4.6 节奏

运行时要能识别建立、探索、停滞、升压、危机和收束。停滞时只能引入已编译的压力事件、环境变化、NPC 行动或分层提示；不能重复询问“接下来做什么”。

### 4.7 多人聚光灯

记录每位玩家最近一次有效行动，避免连续只回应同一人；区分公共、私密和同时行动；必要时点名尚未行动玩家；玩家讨论不得自动视为角色动作。

### 4.8 叙事表达

每次结果按以下顺序投影：理解了什么 → 是否检定 → 检定/状态变化 → 场景叙事 → 当前可行动空间。公共信息、角色私密信息、OOC 和系统提示必须按受众和视觉层级区分；不得替玩家描述心理活动。

## 5. 剧本运行时最小合同

结构化运行包至少要能表达以下字段；字段缺失时质量门禁必须拒绝发布，不能由模型临时补全：

```yaml
scene:
  purpose: string
  entry_conditions: []
  exit_conditions: []
  available_actions: []
  core_clues: []
  optional_clues: []
  fallback_clues: []
  pressure_clock: {}
  escalation_events: []
  improv_boundaries: []
npc:
  importance: major | supporting | flavor
  goals: []
  knowledge: []
  knowledge_fact_refs: []
  secrets: []
  secret_fact_refs: []
  fears: []
  attitude: {}
  leverage: []
  lie_policy: {}
  reaction_rules: []
  improv_boundaries: []
  exit_conditions: []
clue:
  importance: core | supporting | flavor
  reveal_conditions: []
  alternative_sources: []
  failure_outcome: {}
  dependencies: []
  public_version: string
  secret_fact_refs: []
ending:
  ending_id: string
  priority: integer
  mutual_exclusion_group: string | null
  progress_requirements: []
  required_facts: []
  optional_modifiers: []
  trigger_policy: automatic | player_initiated
```

字段按对象类型设置条件门禁，不要求 flavor NPC 或无调查场景强行填写全部字段：major NPC 必须有目标、反应规则和临场边界；核心线索必须有替代来源或恢复节点；调查场景必须有进展定义或明确豁免；无压力时钟必须声明豁免；自动结局必须有可确定计算的触发条件。质量门禁还必须拒绝同一 `mutual_exclusion_group` 中同时命中的相同优先级结局。

当前 `data/golden_modules/02-short-team-glass-rain/module.json` 已有场景、NPC、线索、真相、结局、替代路径、恢复节点、风险契约和 `session_mode=ai_only`；但本文件不把 Glass Rain 的字段现状视为已验证。发布前必须对目标模块逐字段检查，缺失项是阻断，不得只依赖 `raw_text` 或模型常识。

规则书正文不是 Prompt 速查表。`kp_mcp_server/prompts/rules.md` 只能作为接口提示，运行时检定必须引用已登记、已审计、`runtime_eligible=true` 且 gate 为 `ready` 的 CoC7 规则版本；`soul.md` 与 `contract.md` 同样不能越过 Engine 权威链路。

## 6. AI-Only Golden Run v1

唯一首个完整验收模组：`02-short-team-glass-rain`（2–4 人，2–3 小时）。验收必须从新房间开始，不复用旧房间状态。

### 6.1 Session Zero 完成定义

Session Zero 只有在以下条件全部满足后才算完成：所有玩家和角色均 ready；风险契约和必要的 `ActionConsent` 规则已展示并确认；私密投影/秘密边界检查通过；断线重连与待确认 action 恢复检查通过；运行包、规则版本和提示版本 hash 已冻结并写入 Trace。任一条件失败只能停在 `session_zero_incomplete`，不能进入正常回合。

### 6.2 必须覆盖的主链路

1. 玩家无需创建人类 Host 角色；
2. 创建房间后绑定合格的 CoC7 规则版本和 ready runtime package；
3. 2–4 名玩家完成角色选择、Session Zero 和连接恢复确认；
4. AI 自动建立入口场景、目标、压力时钟和第一批公开线索；
5. 至少完成调查、对话、技能检定、冲突/风险确认和线索分享；
6. 至少一次歧义走玩家澄清/候选选择，不得走 Host；
7. 至少一次普通失败产生可继续的代价或替代路径；
8. 模拟一次 Provider 降级，确认状态不回退、不重复投骰；
9. 至少一名玩家断线后重连，状态、私密信息和待确认 action 正确恢复；
10. 进入一个有效结局（victory 或 mixed），并生成档案、时间线、关键选择、角色结局；
11. 回放能还原每次 AI 决策、规则回执、状态变更和受众投影；
12. 全程 `awaiting_host_exception` action 数量为 0，后台不需要人工改 HP、SAN、物品或线索。

除基础主链路外，Golden Run 必须增加以下故障/对抗场景：

13. Host 全程离线；
14. 并发/重复提交只产生一个 `roll_receipt`、状态变更和事件，重试复用 `action_id`、`resolution_id`、`idempotency_key`；
15. 自动申诉循环覆盖“原始意图 → 重新解释 → 原 `RollReceipt` 复核 → 规则重算 → upheld/corrected/compensated”；
16. 恶意秘密泄露、Prompt 注入和越权字段写入尝试均被拒绝并审计；
17. 运行包、规则、Prompt、场景 hash 在运行中被冻结，变更只能进入新房间。

### 6.3 每场必须记录的 Trace

```text
input → director → intent_contract → mechanic_plan → authoritative_mechanic_plan
→ roll_receipt → state_delta → reveal_ledger → spoiler_guard → narrator
→ projection_dispatch
```

每个节点至少记录 `room_id`、`action_id`、`resolution_id`、`state_version`、`rule_version_id`、runtime/scenario/prompt hash、时间戳、结果状态和错误代码；日志和导出必须脱敏，不包含 token、原始安全边界或未揭示秘密。

### 6.4 ProviderFailure 与失败闭环

| ID | 门禁 |
| --- | --- |
| `AIO-PROVIDER-001` | 所有 Provider 和本地 fallback 都失败时，禁止以空对象、默认 DTO 或“无规则候选”继续；只能返回结构化失败、拒绝动作或暂停房间 |
| `AIO-PROVIDER-002` | `AiGateway` 必须返回结构化 `ProviderFailure(task_type, attempts, last_error_code, fallback_available)`，并保留可审计的 provider/fallback 尝试摘要 |
| `AIO-PROVIDER-003` | 只有已登记且通过测试的确定性 fallback 才能完成；否则 action 为 `rejected` 或房间为 `paused_system`，不能编造规则、事实、线索或状态 |

Provider 故障注入必须进入 Golden Run，覆盖首选 Provider 超时、无效 JSON、fallback 失败和恢复重试；断言不重掷、不重复提交，并按 `AIO-RETRY-*` 记录。

### 6.5 重试不变量与阶段恢复

| ID | 不变量 |
| --- | --- |
| `AIO-RETRY-001` | 基础设施重试复用同一 `action_id`、`resolution_id`、`idempotency_key`，不得新建动作 |
| `AIO-RETRY-002` | 已产生 `RollReceipt` 后不得重掷；只可复核同一回执 |
| `AIO-RETRY-003` | 已提交权威状态后不得重复 mutation、事件或库存扣减 |
| `AIO-RETRY-004` | 状态已提交后只允许重跑叙事/投影，不重跑机制结算 |
| `AIO-RETRY-005` | 玩家主动重试是新 action，由规则决定是否 push、补偿或拒绝 |

阶段恢复矩阵：Director/Provider 失败可在同一 resolution 上重试或走已登记降级；Mechanic Compile 失败必须拒绝或系统暂停；收到 Receipt 后只复核；State Commit/Projection 失败分别按幂等提交/只重放投影；未知提交状态必须查询 `resolution_id` 和状态版本，确认前不得再次写入。

## 7. 第一阶段指标与发布门槛

以下分为发布硬阻断和观察指标。所有比例必须同时报告分子、分母、样本范围和排除项。

### 7.1 发布硬阻断

| 指标 | 目标 |
| --- | ---: |
| 人类 Host 裁决次数 | 0 |
| AI-only `awaiting_host_exception` | 0 |
| 权威状态非法写入 | 0 |
| 严重剧透 | 0 |
| 静默机械解释错误 | 0 |
| 严重意图扭曲 | 0 |
| 检定回执验证失败、重复投掷、重复提交 | 0 |
| 不可恢复卡死/未恢复死锁 | 0 |
| Trace 完整率 | 100% |

### 7.2 观察指标（不替代硬阻断）

| 指标 | 目标与口径 |
| --- | --- |
| 动作澄清比例 | ≤15%；分母排除系统按钮、同意/拒绝响应、重连、OOC 和显式技能动作 |
| 玩家主动纠正比例 | ≤5%；分母为已接受的可执行玩家动作 |
| 到达有效结局 | ≥80%；有效结局必须是作者结局被确定性触发并提交 |
| 普通文本动作 P95 | ≤15 秒；与降级、玩家等待、typewriter 展示分别报告，不混为一个 P95 |
| 玩家清晰度/主动权/氛围评分 | 平均 ≥4/5，单独报告每项和样本量 |

### 7.3 Benchmark 样本设计

至少 30 场固定种子 benchmark：15 场双人、15 场四人；覆盖不同玩家意图分布、每场最大 action/turn、Provider 故障注入、失败推进、暂停/恢复和 Owner 终止（`ending_status=aborted`）。手工正向 Golden Run 必须到达 victory 或 mixed；仿真必须同时包含 failure、rejected、paused_system 和 Owner 终止场次。

自动化测试通过不是完整跑团通过的替代品。发布前必须同时拥有：定向回归、整场仿真 Trace、至少一场真实浏览器/多玩家证据和指标汇总。

### 7.4 验收条目映射

| 条目 | 要求 | 代码/测试证据 | 指标/阻断 |
| --- | --- | --- | --- |
| `AIO-INV-001` | AI 不直接写权威状态；所有 patch 经 Engine/StateService | `src/server/engine/resolution_pipeline.py`、`test_ai_decision_audit.py` | 非法状态写入必须为 0，阻断 |
| `AIO-BOUND-001` | 房间绑定合格 rule/runtime package，运行中 hash 冻结 | `src/server/rule_source_lifecycle.py`、runtime package tests | 绑定漂移 0，阻断 |
| `AIO-AUTH-001` | Director 计划必须经 Engine 生成 authoritative mechanic plan | `src/server/engine/`、trace tests | 未验证 plan 驱动写入 0，阻断 |
| `AIO-STATE-001` | action、room runtime、resolution outcome 三层状态不混用 | `src/server/engine/action_state.py`、lifecycle tests | 非法状态转换 0，阻断 |
| `AIO-INTENT-001` | 原始意图、解释摘要和玩家纠正可追溯 | `src/server/player/action_service.py`、intent tests | 静默机械解释错误 0，阻断 |
| `AIO-RULE-001` | `ai_only` 仅使用资格化规则；无规则安全拒绝/暂停 | `src/server/ai/rag.py`、`resolution_pipeline.py`、rule tests | 规则越权 0，阻断 |
| `AIO-HOST-001` | `ai_only` 普通 action 不得进入 `awaiting_host_exception` | `src/server/engine/host_autonomy.py`、`test_host_autonomy.py`、`test_action_drafts_v2.py` | Host 裁决必须为 0，阻断 |
| `AIO-HOST-002` | action review/recalculate/exception/turn skip 等 Host 裁决 API 在 `ai_only` 统一拒绝 | `src/server/host/router_action_reviews.py`、`src/server/router_rooms.py`、API gate tests | `AI_ONLY_HOST_ADJUDICATION_DISABLED` 为 0 次越权，阻断 |
| `AIO-CLR-001` | 会改变结果的歧义必须进入玩家澄清/选择 | `src/server/player/action_service.py`、`test_action_drafts_v2.py` | 不必要澄清 ≤15% |
| `AIO-CONSENT-001` | 只有超出 RiskContract/PvP/共享资源/他人限制/放弃队友/结局才等待 ActionConsent | `src/server/engine/action_policy.py`、consent tests | 未授权风险写入 0，阻断 |
| `AIO-RULE-002` | 无风险、无压力、无失败代价的动作不得强制检定 | `src/server/engine/action_policy.py`、`test_action_policy.py` | 无意义检定 ≤10% |
| `AIO-FAIL-001` | 核心线索不得因单次普通失败永久丢失 | `src/server/scenario/module_compiler.py`、`test_progression_recovery.py` | 核心线索永久丢失 0，阻断 |
| `AIO-REV-001` | 玩家申诉由自动复核或安全重提承接，不进入 Host review；使用原始意图与 RollReceipt | `src/server/player/router_action_reviews.py`、appeal tests | Host 申诉裁决 0，阻断 |
| `AIO-RETRY-001` | 重试/恢复不重掷、不重复 mutation，未知提交先查询 resolution | action lifecycle/retry tests | 重掷和重复提交 0，阻断 |
| `AIO-RETRY-002` | Receipt、state commit、projection 各阶段按恢复矩阵幂等重试 | retry/recovery tests | 重掷/重复提交 0，阻断 |
| `AIO-PROVIDER-001` | 全 Provider/fallback 失败返回结构化失败，不以空 DTO 继续 | `src/server/ai/gateway.py`、`test_ai_gateway.py` | 空对象继续执行 0，阻断 |
| `AIO-PROVIDER-002` | `ProviderFailure` 含 task_type、attempts、last_error_code、fallback_available | `src/server/ai/gateway.py`、gateway tests | 失败字段完整率 100%，阻断 |
| `AIO-PROVIDER-003` | 只有已登记且测试过的确定性 fallback 可完成 | provider fault-injection tests | 未登记降级完成 0，阻断 |
| `AIO-TRACE-001` | 每次结算覆盖完整 Decision Trace、SpoilerGuard 和 ProjectionDispatcher | Trace schema 与 Golden Run 检查 | Trace 完整率 100%，阻断 |
| `AIO-SCEN-001` | 运行包条件门禁、结局互斥和 Session Zero 完成 | module compiler/Glass Rain tests | 质量门禁失败不得发布，阻断 |
| `AIO-METRIC-001` | Benchmark 分层、分母、样本和硬/观察指标齐全 | benchmark report | 缺分母或样本不足，不得宣称通过 |
| `AIO-SEC-001` | Prompt 注入、秘密泄露和敏感字段写入被拒绝并审计 | security/Golden tests | 严重剧透/越权写入 0，阻断 |
| `AIO-GRN-001` | Glass Rain 完整团无需人类 KP 且能到达有效结局 | `tests/server/test_glass_rain_four_player_flow.py` + 浏览器证据 | 有效结局 ≥80%，Host 裁决 0 |

当前实现对 `AIO-REV-001` 先采取 fail-closed：纯 AI 申诉返回稳定的 `AI_ONLY_HOST_ADJUDICATION_DISABLED`，不创建 Host 队列；自动重新解释/使用原始 `RollReceipt` 的复核流程仍是 P0-1 后续工程项，在它完成前不能宣称纯 AI Golden Run 已通过。

## 8. 当前执行顺序

1. 将本文件升级为 v1.1 唯一验收口径，并建立条目追踪矩阵；
2. 对 `session_mode=ai_only` 补齐统一策略、Host API gates 和状态语义；
3. 落地 action/room/outcome 状态机、自动申诉、`ProviderFailure` 和阶段恢复不变量；
4. 对齐 `kp_mcp_server/prompts/soul.md`、`rules.md`、`contract.md` 与运行时 DTO/schema；
5. 建立统一 Resolution Trace，接入 SpoilerGuard 和 ProjectionDispatcher；
6. 对 Glass Rain 做字段核验、条件质量门禁和确定性结局门禁；
7. 建立至少 30 场双人/四人 benchmark；
8. 完成真实浏览器、多玩家、Host 离线、并发重试和对抗 Golden Run；
9. 生成可审计的条目、指标、Trace 和阻断项报告；
10. 仅在以上完成后恢复 P1/P2 的 UI、图片、地图和平台扩展。

任何新增功能都必须回答：它是否直接提高上述 Golden Run 的通过率、公平性、可恢复性或可观测性？不能回答的功能暂缓。
