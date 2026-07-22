# 50-AI-Keeper-Platform（01-12 子系统）评审报告

- 评审日期：2026-07-22
- 评审范围：`docs/50-AI-Keeper-Platform/` 下 01 至 12 共 12 个子系统、60 份文档（每系统：`功能列表.md`、`PRD.md`、`DeepSeek计划.md`、`验收文档.md`、`回执-2026-07-06.md`），60 份全部逐份阅读
- 对照基准：`docs/00-产品规范/`（00 宪法、01 角色权限总表、03 唯一权威矩阵、04 M0 范围）、`docs/PRDs/`（PRD-00、PRD-01、README 及索引口径）

---

## 1. 概述

### 1.1 各子系统文件清单

12 个子系统均为标准 5 文件结构，无缺文件：

| 子系统 | 功能列表 | PRD | DeepSeek计划 | 验收文档 | 回执(2026-07-06) |
|---|---|---|---|---|---|
| 01-Room 团房间系统 | 13.2KB | 14.2KB | 10.5KB | 5.8KB | 5.5KB |
| 02-User 用户与权限系统 | 16.0KB | 15.9KB | 12.4KB | 4.6KB | 4.4KB |
| 03-Channel 聊天与信息流系统 | 11.2KB | 11.5KB | 10.8KB | 4.5KB | 3.2KB |
| 04-Rule 规则与骰子系统 | 10.1KB | 11.6KB | 11.2KB | 5.6KB | **2.3KB** |
| 05-Character 角色卡系统 | 14.3KB | 12.6KB | 11.2KB | 8.4KB | **2.6KB** |
| 06-NPC-Faction 系统 | 12.2KB | 13.1KB | 11.3KB | 9.6KB | 8.3KB |
| 07-WorldBook 世界书系统 | 11.3KB | 13.4KB | 10.6KB | 9.9KB | 7.5KB |
| 08-Clue 线索与道具系统 | 13.4KB | 15.1KB | 12.9KB | 8.6KB | 6.6KB |
| 09-Scene-Map 地图与场景系统 | 12.6KB | 12.0KB | 10.5KB | 9.5KB | 5.3KB |
| 10-Timeline 时间轴系统 | 16.3KB | 15.9KB | 13.1KB | 10.4KB | 5.8KB |
| 11-Journal 日志与回放系统 | 15.6KB | 13.8KB | 11.5KB | 12.9KB | 6.0KB |
| 12-AI-Keeper 核心系统 | 15.9KB | 13.8KB | 13.6KB | 12.4KB | 5.9KB |

### 1.2 整体质量评分：**B（良好，但验收纪律存在系统性失守）**

这套文档库的底子相当好：模块边界清晰、"当前代码锚点"表可追溯到文件级、普遍诚实地区分"当前事实/风险识别/演进方向"、验收文档普遍带一票否决项和生产安全加签条件。但存在三个拉低整体评分的系统性问题：

1. **回执结论与验收文档一票否决项多处直接冲突，验收机制形同虚设**（详见 P0-1）；
2. **全库至少 6 套互不相通的可见性枚举，与 00-产品规范的 4 层可见性完全脱钩**（详见 P0-2）；
3. **M0 强制验收项（安全暂停/X-Card、意图澄清、申诉纠错）在 01-12 全部 60 份文档中零覆盖**（详见 P0-3）。

### 1.3 逐系统评分表

| 子系统 | 评分 | 一句话评语 |
|---|:---:|---|
| 01-Room | A- | 结构完整、接口与状态机清晰；Host 术语与规范冲突，功能列表现状段未随回执回改 |
| 02-User | A- | 凭证边界对照表是全库标杆；回执缺验收自检与结论段 |
| 03-Channel | B+ | 统一可见性过滤方向正确；P0 级 reconnect 泄露风险在回执中被降级为 P1 且无结论段 |
| 04-Rule | **B** | PRD/计划/验收质量高；**回执全库最薄**（无一票否决自检、无结论、无前端构建证据、无边界值测试证据） |
| 05-Character | **B** | 八层数据分层清晰；**回执第二薄**（无自检、无结论），一票否决项 `/sync` 合并运行态未做却无说法 |
| 06-NPC-Faction | A- | 回执有完整验收自检与双段结论；但一票否决项自评 ⚠️ 仍判"通过" |
| 07-WorldBook | B+ | 质量门禁设计扎实；回执一票否决项自相矛盾（visibility 写了 metadata 但检索层不过滤） |
| 08-Clue | A- | 证据链与分享安全化设计最完整，回执诚实标注未闭环项 |
| 09-Scene-Map | B+ | 接口/事件/审计字段契约具体；Map-4 仅"部分"完成仍判通过 |
| 10-Timeline | B | 并发幂等分析最深；**一票否决 2 项 ⚠️ 仍判通过，且验收自检清单从 #7 直接跳到 #10** |
| 11-Journal | B+ | 导出分层与 restore 语义严谨；验收要求回执回答 20 问，实际覆盖不足一半 |
| 12-AI-Keeper | B+ | mutation 权限矩阵、final context filter 概念好；P0 批次 AI-2 仅"部分实现"仍判通过；缺主持循环与意图澄清 |

**文档质量最差的子系统：04-Rule、05-Character（回执偷工减料），03-Channel（P0 风险降级且无结论），10-Timeline（一票否决未过仍判通过 + 自检跳项）。**

---

## 2. 主要问题

### P0 级

---

**P0-1 回执结论与"一票否决项"系统性冲突，验收机制失效**

- **问题描述**：多个子系统的回执在一票否决项未满足的情况下，仍然给出"本轮工程验收：✅ 通过"的结论，或把 P0 风险静默降级为 P1。验收文档写明的"出现任一情况本轮不能判通过"没有被执行。
- **涉及文件与证据**：
  1. `10-Timeline/回执-2026-07-06.md`：一票否决项自检中"非 active 房间 `GET current turn` 不隐式创建"标 ⚠️（`ensure_current_turn` 仍会创建）、"`player_sequences` 按安全事件推进"标 ⚠️（仍需验证），结论却写"本轮工程验收：✅ 通过"；且"本轮工程验收清单"表从 #7 直接跳到 #10，恰好跳过未闭环的 #8（player_sequences）、#9（sequence 边界）。
  2. `07-WorldBook/回执-2026-07-06.md`：一票否决项"玩家侧 RAG/AI 可返回 raw_text/truth"标 ✅ 已解决（依据是 scenario chunk 写入 `visibility='internal'`），但同一份回执"生产安全完成：未达到"中承认"**`RAGStore.search()` 尚未按 visibility 过滤**"——metadata 写了但不生效，即玩家 `POST /api/rag/search`（02-User 明确房间成员可调用）仍可命中 `raw_text` chunk。一票否决项的 ✅ 与自认未闭环直接矛盾。
  3. `12-AI-Keeper核心系统/回执-2026-07-06.md`：P0 批次 AI-2（Gateway 状态模型 + schemaVersion，对应 AI-FR-3 P0 需求）标 ⚠️"已部分实现"，结论仍 ✅ 通过；一票否决项"`/rag/search` 未经 filter 入 prompt"标 ✅"检索≠prompt 权限"，但"未达到"段承认"RAG final context filter 显式入口未形成统一 filter 函数"。
  4. `06-NPC-Faction系统/回执-2026-07-06.md`：一票否决项"同 scenario 不同 room 不共享 unlock_state"自评 ⚠️"当前 unlock_state 按 room_id 聚合，**未验证跨房共享**"，结论仍 ✅ 通过——未验证不等于已阻断，按验收文档"缺关键证据"应判"有缺口"。
  5. `03-Channel聊天与信息流系统/回执-2026-07-06.md`：PRD"当前风险"表将"`/api/player/reconnect` snapshot 直接回传房间 `all_events`，可能把其他玩家私密事件或 Host-only 事件带给玩家"定为 **P0**，回执"安全边界对照"却写"📋 未关闭 | P1 — 需复用 helper"，且全文无结论段，仅写"全部批次已完成"。验收文档一票否决项第一条正是"玩家 B 能通过 WS/**reconnect**/archive/public events 拿到玩家 A 的私密事件"。
- **影响**：验收文档是整个文档库最有价值的机制设计，但回执不执行它，"一票否决"沦为装饰。若按此惯例，后续 24 个模块的验收结论都不可信；M0-Verified 发布门槛（00-产品规范/04："任何一项未验证都只能称为候选能力"）将无法达成。
- **建议**：① 对 03/06/07/10/12 五份回执的结论降级为"本轮工程验收有缺口"，并把 reconnect 过滤、RAG visibility 检索层过滤、`ensure_current_turn` 读写分离、Gateway 状态模型、跨房隔离测试列为 P0 缺口重开 Batch；② 在验收文档增加硬规则："一票否决项存在 ⚠️/🔜 时，禁止给出 ✅ 通过结论"；③ 回执模板强制逐条引用一票否决项并附测试证据链接，不允许只写状态词。

---

**P0-2 可见性词汇全库至少 6 套，互不相通，且与 00-产品规范 4 层完全脱钩**

- **问题描述**：`00-产品规范/03-领域对象与唯一权威矩阵.md` 定义了全库唯一的 4 层可见性（`internal / player_private / party / stage_safe`），但 01-12 各子系统各自发明了一套枚举，没有任何文档给出映射关系：
  - 03-Channel：`audience = host/player/party/system` + `visibility = public/private/ooc/system/dice`
  - 04-Rule：骰子 `visibility = public/self/keeperOnly/hidden`
  - 05-Character：字段 `visibility = public/party/self/host/keeperOnly/private/neverExport`
  - 06-NPC：字段 `visibility = public/known/host/ai_only/truth/neverPlayer`
  - 08-Clue：数据访问级别 `self/party/host/admin/internal/never_export` + 事件受众 `player/party/host/system`
  - 10-Timeline：派生 `visibility = host/party/self/system_safe/private_filtered`
  - 11-Journal：`host/party/player:self/player:other/system_safe/admin_audit`
  
  Grep 验证：规范术语 `stage_safe/player_private/party_safe` 在 01-12 的 60 份文档中仅出现 3 次（08-Clue 功能列表/DeepSeek 各 1 次），12 个子系统无任何一份文档声明与规范 4 层的映射。
- **影响**：15-Projection（唯一权威矩阵中"可见投影"的唯一权威）落地时无统一词汇可用，各模块的 DTO 裁剪无法互相复用；`keeperOnly`（04/05/06 用法各异）、`host`（在 03 是 audience、在 05/06/08 是字段级）等词在不同模块语义不同，必然导致过滤漏洞——这正是 03/07/10 回执里反复出现"过滤口径不统一"风险的文档层根因。
- **建议**：在 00-产品规范或 15-Projection 文档中建立"全库可见性总表"，把 4 层规范术语作为唯一权威词汇，各模块枚举必须声明到 4 层的映射（如 `keeperOnly → internal`、`host audience → stage_safe + owner`）；01-12 各 PRD 的 visibility 章节补一节映射声明。

---

**P0-3 M0 强制验收项在 01-12 零覆盖：安全暂停/X-Card、意图澄清、申诉纠错**

- **问题描述**：`00-产品规范/04-M0范围、里程碑与指标.md` 规定 M0 必须验收"内容提醒、边界确认、**X-card**、淡出、私密反馈、**安全结束**"和"幂等、状态版本屏障、重连、**追加式申诉/补偿**"；`00-产品宪法.md` M0 首要体验第 1 条"模糊和高影响意图会**先澄清或确认**"；`00-产品规范/01-运行模式、角色与权限总表.md` 定义了 **TableSteward** 角色和"安全暂停不要求说明理由，**不依赖 RoomOwner 在线**"原则。Grep 验证：`X-Card|X-card|TableSteward|安全暂停` 在 01-12 全部 60 份文档中 **0 匹配**；`澄清|Intent Contract|申诉|纠错请求` 在 01-12 全部 60 份文档中 **0 匹配**（仅 23-Community 有无关用法）。
  - 01-Room 把 `pause/reset/retry-turn` 全部划给 owner/admin 急救，没有"安全暂停"语义、没有不依赖 Owner 在线的路径、没有触发者匿名；
  - 12-AI-Keeper 的 P0 功能列表没有任何"意图澄清/确认"机制——AI 对模糊或高影响行动如何发起澄清、玩家如何确认/撤回，完全缺席；
  - 结算后的追加式申诉/纠错（PRD-18 已有对应 PRD）在 01-12 无任何承接：04-Rule 没有申诉入口、10-Timeline 没有纠错事件、11-Journal 没有补偿记录类型。
- **影响**：00-产品规范 G3（Intent 与回执）、G5（安全与 Session 闭环）两个 Gate 无法由当前 01-12 文档集支撑；M0 验收表 8 行中至少 2 行（输入与理解、安全与结束）在 01-12 找不到对应设计。这不是"21-Safety 范围外"能解释的——安全暂停的房间侧路径（01-Room）和澄清的 AI 侧路径（12-AI-Keeper）必须在本范围内有接口。
- **建议**：① 01-Room 补"安全暂停"功能条目（触发者匿名、不依赖 owner、与 force_pause 急救区分）；② 12-AI-Keeper 补"意图澄清与确认"P0 功能（Intent Contract、澄清事件、确认/撤回生命周期），与 PRD-18 对齐；③ 04-Rule 或 14-Transaction 边界文档补结算后申诉/补偿的追加式入口；④ 在 50-README 的模块表中显式声明 21-Safety 与 01/12 的接口点。

---

**P0-4 玩家侧 RAG 泄露路径被自认未闭环却未按 P0 处理（跨 3 个模块）**

- **问题描述**：`02-User/功能列表.md` P0 生产安全基线表明确"Player-facing RAG 结果裁剪"是未关闭缺口（"可能把 `scenario_truth` 或未发现线索直接返给玩家"）；`07-WorldBook/回执` 承认 `RAGStore.search()` 不按 visibility 过滤；`12-AI-Keeper/回执` 承认 final context filter 无统一入口。三份文档指向同一个洞：导入时 `index_scenario(scenario_id, raw_text)` 已把**剧本全文**写进 `document_chunks`（07 回执），而房间成员（含玩家）可调用 `POST /api/rag/search`（02-User FR-USER-17），检索层不做 visibility 过滤（07 回执自认）。即：玩家当前可以通过 RAG 搜索直接命中剧本原文/真相 chunk。
- **影响**：这是整个平台最核心承诺（"不会越权剧透"，00-宪法第 3 条）上的实质漏洞，且修复状态被三份回执分别淡化。G4 Gate（事实、认知与线索：私密/公开边界和来源引用可验证，无剧透泄漏）不能通过。
- **建议**：把"RAG search 按 visibility/audience/discovered_state 过滤"提为跨模块 P0 缺口（而非 07 P1），由 02/07/12 联合一个 Batch 关闭，并补"玩家 search 不返回 `visibility=internal` chunk"的专项测试；在关闭前，07 回执一票否决项不得标 ✅。

---

**P0-5 PDF 导入事实上成为 M0 黄金路径前提，与 00-产品规范"固定参考短模组"矛盾**

- **问题描述**：`00-产品规范/04-M0范围、里程碑与指标.md` 规定 M0 内容基线是"一份原创、获授权或内部可合法使用的**固定参考短模组**"，并明确"PDF 自动导入……可保留为降级或实验能力，**不得成为 M0 黄金路径的前提**"（ADR-002 同口径）。但 01-Room 的 P0 开局链路强制要求"有效 `scenario_id`"（功能列表 P0 第一行、FR-ROOM-01），而全库 scenario 的唯一生产入口是 `07-WorldBook` 的 `POST /api/scenarios/import-pdf`（07 功能列表"当前代码真实链路"第 1 步，且 import-pdf 要求 admin）。07-WorldBook 更把 PDF 导入列为 P0 主链路（P0-1 导入链路可闭环）。没有任何文档说明固定参考模组如何入库（seed 脚本？预置数据？）。
- **影响**：M0 黄金路径"建房到开场"实际依赖一个规范明令不得依赖的能力；若 PDF 导入链路（AI 结构化 + RAG + 防剧透索引）任何一环失败，M0 无法开局。规范与施工图自相矛盾。
- **建议**：① 在 01-Room 或 07-WorldBook 文档中补"固定参考模组入库路径"（离线 seed/预置包，不走运行时 PDF 导入），并将其标注为 M0 黄金路径唯一前提；② 07-WorldBook 把"PDF 导入"降级标注为"M0 可保留的实验能力"，与 04-M0 对齐；③ 00-产品规范与 50-README 互相引用该决策。

---

### P1 级

---

**P1-6 "Host" 术语与 00-产品规范角色模型全面冲突，贯穿 12 个子系统**

- **问题描述**：`00-产品规范/01-运行模式、角色与权限总表.md` 明确"`Host` 不是规范概念：旧代码中的 Host 名称只能作为兼容别名，不能据此推导角色权限"，规范角色为 `RoomOwner / TableSteward / Player / SharedStage`（SharedStage 是只读公共设备）。但 01-12 全部 PRD 的"角色与权限"表都以 "Host 房主" 为规范角色并据此推导权限（Host 开局、Host 审批、Host 急救、Host WS、Host 显隐、Host 强制移动），且把"Host"同时用作"房主的人"与"大屏设备"（HostStage.tsx / Host WS 混写）。50-README 的模块表也以 Host 命名 17-Host-Client。12 个子系统无任何一份文档声明 "Host = RoomOwner（人）+ SharedStage（设备）" 的映射。
- **影响**：权限推导的根基与规范不一致——例如"Host 能看到什么"在 50 目录的答案（公共战局+队伍消息+审计时间线）需要按规范拆成 RoomOwner（party-safe 运行信息+脱敏审计）与 SharedStage（仅 party-safe 投影）两个答案，当前文档无法支持这种拆分审查；SharedStage "只读、不得阻塞 Engine" 的设备规则在 01-12 也无对应落点。
- **建议**：在 50-README 或各 PRD 角色表增加一节"与 00-规范角色映射"：`Host（人）→ RoomOwner`、`Host 大屏/HostStage → SharedStage`、`Host 平台角色 → 账号 role=host`；新文档一律使用规范词汇，Host 仅作兼容别名。

---

**P1-7 跨文档接口语义互相矛盾（3 处实锤）**

- **问题描述与证据**：
  1. **retry-turn**：`01-Room/PRD.md` 接口表列 `POST /api/rooms/{room_id}/turns/{turn_id}/retry`（owner/admin，"重试当前回合裁决"）；`10-Timeline/PRD.md` 规定"retry 默认只允许对 `blocked` 或显式 `retryable` 的 `resolved` turn 执行；**`collecting / resolving` turn 不允许 retry**"。"当前回合"通常处于 collecting/resolving——按 10 的口径，01 列出的接口在大多数时刻不可用，两份 PRD 对同一接口的可用域互相矛盾。
  2. **`/ai-turn` 权限**：`12-AI-Keeper/PRD.md` 接口表写目标权限 "Owner / Admin / **Host**"；`12-AI-Keeper/回执` 实现为 `_verify_room_owner_or_admin`（仅 owner/admin）。文档允许 Host 平台角色触发任意房间 AI 结算，实现不允许——二者必有一错，需明确口径并同步。
  3. **PlayerIntent 字段命名**：`PRDs/PRD-01` 规定 `POST /api/player/intent` 请求体为 camelCase（`actionId / intentType / declaredIntent / baseStateVersion / params`）；`04-Rule/PRD.md` 的 PlayerIntent 示例用 snake_case（`action_id / intent_type / declared_intent / base_state_version`）。同一权威入口两套字段命名，直接违反 PRD-00"事件名、字段名统一 camelCase"的文档约定。
- **影响**：按哪份文档实现都会产生与另一份的冲突；DeepSeek 执行 Batch 时"当前代码优先"原则无法解决文档间矛盾。
- **建议**：以 PRD-01/PRD-00 为协议权威修正 04-Rule 示例；01-Room 接口表为 retry 补可用状态域注解并引用 10-Timeline；12 号文档与回执统一 `/ai-turn` 权限口径（建议 owner/admin only，修文档）。

---

**P1-8 功能列表/PRD 的"当前代码现状"段在修复完成后不回改，文档与代码再次漂移**

- **问题描述**：多份功能列表以"当前代码现状/风险"形式描述问题，回执宣称已修复，但功能列表原文未同步更新：
  - `01-Room/功能列表.md` force_start 行仍写"当前只做到风险识别，未完成风险闭环……后续实现应补 `reason + confirm + event/audit`"；`01-Room/回执` 写明"已实现：新 payload 强制要求 `reason + confirm: true`……写入 `s2c_force_start_audit` 事件"。
  - `03-Channel/功能列表.md` 仍写"当前 player 接口仍允许 `system_import`"；`03-Channel/回执` 写明"从 `ALLOWED_SOURCES` 移除"。
  - `07-WorldBook/功能列表.md`"当前代码真实链路"第 12 步仍写"create-room 当前不检查 quality level"；`07-WorldBook/回执` 写明"blocked → 403，highRisk → 需 confirm_quality_risk"。
- **影响**：下一轮读者（或 DeepSeek）拿到的是过时的现状描述，会按已修复的问题再次开工，或误判剩余风险。"当前事实"是这套文档的核心卖点，不维护就会失信。
- **建议**：建立回执后动作："凡回执标记 ⚡ 已修复的项，必须同步修订功能列表/PRD 对应现状行"；或在功能列表现状段统一加"最后核实日期 + 对应回执"列。

---

**P1-9 12 份回执共享同一测试基线"409 passed / 12 errors (xlsx tmpdir)"，且 12 个错误无任何解释**

- **问题描述**：01-12 范围内 11 份回执（05 除外）都报告"全量后端 409 passed、错误 (xlsx tmpdir) 12、前端构建 ✅"，数字逐字相同；04-Rule 回执为"Rule 测试 54 passed / 全量 409 passed / 错误 (xlsx) 12"。没有任何一份回执或验收文档解释这 12 个 xlsx tmpdir 错误是什么、归属哪个模块、为什么不阻塞验收。验收文档普遍规定"关键测试明显未通过→不通过"。
- **影响**：12 个持续存在的测试错误被全体回执静默携带，读者无法判断其是否影响本模块验收结论；同一基线数字在多份回执中原样复制，也让人质疑各回执是否真实独立执行过测试。
- **建议**：① 任选一份回执（或 60-验收与测试报告）专节说明 12 个 xlsx tmpdir 错误的性质（已知环境性问题？xfail？）、影响面和关闭计划；② 回执模板要求测试基线附实际执行日期与命令输出摘要，不允许只贴累计数字。

---

**P1-10 04-Rule 与 05-Character 回执严重偷工减料**

- **问题描述**：对比 06-12 回执的标准结构（本轮覆盖 Batch 表 / 修改文件清单 / P0 修复详情 / 测试基线 / 一票否决自检表 / 验收清单自检表 / 双段结论 / 后续建议）：
  - `04-Rule/回执`（2.3KB，全库最薄）：无一票否决自检、无验收清单自检、无结论段、无前端构建状态（但 Rule-1 改了 `PlayerActionPage.tsx`/`PlayerCharacter.tsx`，验收文档要求"如改了前端附 npm run build 结果"）、无建议后续行动；验收文档明确要求"回执至少应给出 roll=1/100/96、skill=49/50、hard/extreme 门限的边界值测试证据"，回执只字未提，仅写"54 passed"。
  - `05-Character/回执`（2.6KB）：同样无自检、无结论、无前端证据；验收清单第 2 条要求"`GET /api/player/sync` 会合并运行态"，回执"已识别演进方向"表却列"`/api/player/sync` 同样合并运行态 | P1"（未做），无一字解释该一票否决级检查项为何未做、本轮算什么结论。
- **影响**：04/05 是主链路核心（规则裁决、角色数据），其验收证据强度却是全库最低，M0 的"规则"验收行（RuleResult、骰点和状态回执）缺乏文档化证据。
- **建议**：按 08-Clue 回执结构重写 04/05 回执，补齐一票否决逐项自检、边界值测试证据、前端构建结果与双段结论。

---

**P1-11 开局人数口径与产品宪法不一致**

- **问题描述**：`00-产品规范/00-产品宪法.md` 定义 M0 是"**2–4 名玩家**完成的 CoC 7e 调查短团"；`01-Room/功能列表.md` P0 开局检查为"至少**一名**玩家、且正式成员全部 ready"（FR-ROOM-11 同）。01-Room 未解释 1 人开局与宪法 2 人下限的关系（是演示口径？还是宪法应修订？）。
- **影响**：M0 黄金路径验收（G6：两玩家无 Stage 路径）与开局校验规则不一致，验收时会产生"1 人局算不算 M0 成功"的争议。
- **建议**：在 01-Room FR-ROOM-11 补注"正式 M0 局最少 2 名玩家，1 人仅限演示/调试口径"，或提请修订宪法下限并写 ADR。

---

**P1-12 `s2c_chat_stream` 残留旧协议引用**

- **问题描述**：`03-Channel/功能列表.md` 称 `events_registry.py`"维护 `s2c_chat_stream`……等事件"，`03-Channel/PRD.md` v1 范围把公共叙事流建立在 `s2c_public_observation、s2c_chat_stream、s2c_reveal_transaction` 之上。但全库其他文档（01-Room 事件表、10/11 事件契约、各回执）均无此事件；`PRDs/PRD-00-全局协议与投影契约.md` 中 `s2c_chat_stream` 仅作为枚举列表中的孤立字符串出现，无 payload 定义。PRD-00 的"已修正口径"还明确 `narrative_text` 精简为完整文本下发、移除流式分块字段——`chat_stream` 语义与"非流式"修正方向冲突。
- **影响**：03-Channel 把 v1 主链路建立在一个无定义、疑似废弃的事件上，后续按文档实现会产生协议分叉。
- **建议**：核实 `s2c_chat_stream` 在代码中的真实状态；若已废弃，从 03 的功能列表/PRD 删除并改注 `s2c_public_observation`；若保留，在 PRD-00 补完整契约。

---

### P2 级

---

**P2-13 07-12 的 PRD 与功能列表大段复制粘贴，两文件定位重叠**

- **证据**：08-Clue 的"数据分层"表、"Visibility / Access Model"表、"关键语义 4 条"在两文件中近乎逐字重复；09-Scene-Map 的"数据分层/状态语义/初始位置责任/移动与场景切换边界/Host 显隐与强制移动语义"整节重复；10-Timeline 的回合状态机、合法参与者集合、checkpoint restore 语义、gameTime 边界重复；12-AI-Keeper 的 DTO 分层、Gateway 状态模型、mutation 权限矩阵、RAG final filter 重复。50-README 对两文件的定位区分是"功能列表=优先级/MVP/用户价值/依赖/验收口径，PRD=目标/范围/权限/数据归属/接口方向/验收标准"——01-06 基本遵守，07-12 明显失守。
- **影响**：同一内容两处维护，必然漂移（如 10-Timeline 两份文件的 system 白名单示例文字略有出入）；阅读成本翻倍。
- **建议**：功能列表保留"优先级表+当前代码锚点"，PRD 保留"契约与规则"，重复段落改为单向引用。

---

**P2-14 版本标记与文档头模板不统一**

- **证据**：07/08/09/10/11/12 的功能列表、PRD、DeepSeek 计划标题带 "V2.1"；01-06 为"v1/初版/无版本号"。00-产品规范全部文件带 YAML frontmatter（`status: normative / version / doc_owner / effective_date / release_scope / last_validated`），50 目录 60 份文件 **无一** 有 frontmatter（Grep `^status:|^version:` 零匹配）。测试命令风格也不统一：DeepSeek 计划混用 `pytest` 与 `python -m pytest`，代码块混标 ```powershell 与 ```bash（开发环境为 Windows）。
- **影响**：文档治理（哪份是 normative、何时失效、谁是 owner）无法机械执行；版本号"V2.1"与 01-06 "v1" 并存让读者误以为内容代际不同。
- **建议**：统一去除或统一补齐版本号；为 50 目录补最小 frontmatter（status/version/owner/last_validated）；统一测试命令风格。

---

**P2-15 RollResult 契约设计双写字段并列，是自找漂移的坏设计**

- **证据**：`04-Rule/PRD.md` 的"标准 RollResult"示例 JSON 同时包含 `"successLevel": "regular"` 和 `"success_level": "regular"` 两个并列字段（另有 `isSuccess`）；Rule-1 又要求"`level` 仅作为兼容字段，值必须与 `success_level/successLevel` 等价，不能三者漂移"。
- **影响**：契约层同时持久化同一语义的两种命名，等于把漂移风险写进标准；04-Rule 自己刚修完一次三字段漂移（回执 Fix 2），又把双写固化进 PRD 示例。
- **建议**：存储与事件契约只保留单字段（建议 camelCase `successLevel`），snake_case 仅在 DB 列存在，由序列化层单点转换；删除 PRD 示例中的并列写法。

---

**P2-16 验收文档"回执最小模板"与实际回执内容脱节**

- **证据**：`11-Journal/验收文档.md` 要求回执回答 20 个问题（含 system_safe 白名单当前集合、public summary 传给 AI 前是否过滤、前端筛选项是否对齐、中文文案排查等），实际 `11-Journal/回执` 覆盖不足一半；`12-AI-Keeper/验收文档.md` 同样 20 问，回执未回答 Gateway 各失败态处理、raw debug log 分层、mutation 校验点入口、context preview 现状等。05-Character 验收文档"回执最小模板"8 问，回执覆盖约一半。
- **影响**：验收文档对回执的约束没有被执行，与 P0-1 同源——机制写得越细、执行越脱节，文档信用越低。
- **建议**：回执改为按验收文档问题逐条作答的强制模板（可机器校验问项覆盖率）。

---

**P2-17 05-Character 引用 `draft` 房间态为当前行为，与 01-Room 状态机矛盾（小）**

- **证据**：`05-Character/PRD.md` 入房建卡流程写"房间为 `draft/lobby` 时角色状态为 `joined`"；`01-Room/PRD.md` 状态机把 `draft` 标为"预留草稿态，**未来**房间模板或草稿流"，当前创建即 `lobby`。
- **建议**：05 改为"`lobby`（及未来 `draft`）"。

---

**P2-18 回执中"文档变化概要 +30%/+40%"类表述无可验证基线（小）**

- **证据**：`01-Room/回执`"总计约 +30% 的篇幅"，`02-User/回执`"新增约 +40% 内容"——无字数/行数基线，属装饰性数据。
- **建议**：删除或附 diff 统计。

---

## 3. 跨子系统一致性问题汇总

| # | 问题 | 涉及方 | 级别 |
|---|---|---|---|
| C-1 | 可见性枚举 6+ 套互不相通，与规范 4 层（internal/player_private/party/stage_safe）脱钩 | 03/04/05/06/08/10/11 vs 00-规范/03 | P0 |
| C-2 | Host 术语 vs RoomOwner/TableSteward/SharedStage 角色模型冲突 | 01-12 全部 vs 00-规范/01 | P1 |
| C-3 | RAG 玩家侧过滤缺口被 3 个模块分别记录但无人认领闭环 | 02（FR-USER-24 P1）、07（回执自认）、12（回执自认） | P0 |
| C-4 | reconnect snapshot 泄露在 03 与 10 重复记录、均被降级/留尾 | 03-Channel、10-Timeline、（11-Journal 关联） | P0 |
| C-5 | retry-turn 可用状态域矛盾 | 01-Room vs 10-Timeline | P1 |
| C-6 | `/ai-turn` 权限文档（含 Host）与实现（owner/admin）不一致 | 12 PRD vs 12 回执 | P1 |
| C-7 | PlayerIntent 字段 snake_case vs camelCase | 04-Rule vs PRDs/PRD-01、PRD-00 | P1 |
| C-8 | PDF 导入成为 M0 黄金路径前提 vs 固定参考模组 | 01+07 vs 00-规范/04、ADR-002 | P0 |
| C-9 | 地图 NPC 引用仍按 name 对齐，与 06 自己"npc_id 为稳定主键"的关键边界冲突（06 回执自标 ⚠️ 仍判通过） | 06-NPC vs 09-Scene-Map | P1 |
| C-10 | 开局最少人数：1 人（01）vs 2–4 人（00 宪法） | 01-Room vs 00-规范/00 | P1 |
| C-11 | `s2c_chat_stream` 无契约引用 | 03-Channel vs PRDs/PRD-00 | P1 |
| C-12 | `draft` 房间态：当前行为（05）vs 预留态（01） | 05-Character vs 01-Room | P2 |
| C-13 | system 事件白名单定义权归属不清：10-Timeline 回执定义了 `PLAYER_VISIBLE_SYSTEM_EVENTS={s2c_turn_resolved, s2c_checkpoint_created}`，11-Journal 复用，但 03-Channel 的"事件分类与 AI 事实层"表对 system 事件口径为"视类型而定"，三份文档对白名单所有权无单一来源 | 03/10/11 | P2 |
| C-14 | Clue 引用 WorldBook：08 明确"knowledge_graph.clues[] 是模板不是玩家证据"且口径一致（好），但 07 的 quality 规则"没有 clues → highRisk"与 08"线索由 Engine 释放"之间没有文档说明"模板线索如何变成可释放对象"的承接方（04-Rule 触发器只写 `$action/itemId`） | 07/08/04 | P2 |

---

## 4. 缺失项

按 M0 验收口径（00-规范/04）逐项核对 01-12 覆盖情况，缺口如下：

| 缺失项 | M0 依据 | 应在模块 | 现状 |
|---|---|---|---|
| 安全暂停（触发者匿名、不依赖 Owner 在线）、X-Card、淡出、安全结束的房间侧路径 | 04-M0"安全与结束"必验行；01-权限总表原则 5 | 01-Room（+21-Safety 接口） | **0 覆盖**（Grep 0 匹配） |
| TableSteward 角色及其权限边界 | 01-权限总表 | 01-Room、02-User | **0 覆盖** |
| 意图澄清与确认（Intent Contract、模糊/高影响行动先澄清） | 00-宪法 M0 首要体验 #1；G3 Gate | 12-AI-Keeper、04-Rule | **0 覆盖**（Grep 0 匹配；仅 PRDs/PRD-18 有） |
| 结算后追加式申诉/纠错补偿 | 04-M0"恢复与纠错"必验行 | 04-Rule、10-Timeline、11-Journal | **0 覆盖**（仅 PRDs/PRD-18 有） |
| AI 主持循环（hosting loop：AI 何时主动推进回合、收集批次、介入节奏） | PRDs/PRD-24、PRD-25 | 12-AI-Keeper | **缺失**——12 号文档只有"玩家意图→被动建议"，无主持循环、无批次收集策略（PRD-25 的"自由行动收集与批次结算"与 10-Timeline 的"全员提交自动结算"的对应关系也无文档桥接） |
| 固定参考模组入库路径（seed/预置） | 04-M0 内容行；ADR-002 | 07-WorldBook、01-Room | **缺失**（见 P0-5） |
| 全库可见性词汇总表与映射 | 03-权威矩阵"可见性层" | 15-Projection（范围外）+ 各模块映射节 | **缺失**（见 P0-2） |
| Host ↔ RoomOwner/SharedStage 映射声明 | 01-权限总表 | 50-README、各 PRD 角色表 | **缺失**（见 P1-6） |
| SharedStage 只读设备规则在房间/投影链路的落点 | 01-权限总表"Shared Stage 规则" | 01-Room（旁观者 P1 仅一句）、03-Channel | 基本缺失 |
| 游客身份恢复（一次性恢复码/设备绑定） | 04-M0"恢复与纠错" | 02-User | 已识别为 P1 缺口，可接受 |
| 12 个 xlsx tmpdir 测试错误的性质说明 | 验收文档"关键测试未过→不通过" | 60-验收与测试报告或任一回执 | **缺失**（见 P1-9） |
| 观察者（Observer）投影落点 | 01-Room P1、00-规范 SharedStage | 01-Room、15-Projection | 仅一句"未实现"，可接受但需与 SharedStage 合并定义 |

---

## 5. 亮点（简短）

1. **"本轮工程验收通过 / 生产安全完成"双层结论 + 一票否决项 + 生产安全加签条件**的验收机制设计，在全库 12 份验收文档中执行得很统一，是文档库最大的制度资产（问题在执行，不在设计）。
2. **"当前代码锚点"表**（功能到 `src/server/xxx.py` 文件级）几乎每个模块都有，配合"当前事实 / 演进方向"分写，极大降低了文档与代码的对齐成本。
3. **02-User 的凭证边界对照表**（7 种凭证 × 归属/用途/不等于什么/现状）是全库最清晰的身份模型表达。
4. **08-Clue 的证据链设计**（私密原文 / public_version / 事件契约 / export 白名单 + 安全默认文案"玩家分享了一条线索，但未公开完整内容"）兼顾了安全与产品体验，回执也最诚实。
5. **10-Timeline 的并发幂等分析**（条件 UPDATE 抢状态、duplicate 孤儿 action、player_sequences 安全推进）达到了可直接施工的粒度。
6. **DeepSeek 计划的 Batch 结构统一**（目标/允许文件方向/测试命令/预期结果/禁止事项），"不顺手重构无关模块"类禁止事项很务实。
7. 普遍反复声明"文档完成不等于生产安全完成"，对状态诚实度显著高于一般设计文档。

---

## 6. 结论与行动建议

### 总体结论

01-12 子系统文档库**设计质量 B（良好）**，模块边界、代码锚点、验收机制设计均属上乘；但**验收执行纪律不合格**：至少 5 份子系统回执（03/06/07/10/12）在一票否决项未满足的情况下判"通过"或静默降级，2 份核心回执（04/05）证据严重不足。更关键的是，**00-产品规范（2026-07-15 生效）与 50 施工图（回执 2026-07-06）之间存在时代错位**：规范的新角色模型（RoomOwner/TableSteward/SharedStage）、4 层可见性词汇、M0 固定模组决策，均未回灌到 50 目录。按现状，G3/G4/G5 三个 M0 Gate 无法由本文档集支撑验收。

### 行动建议（按优先级）

**立即（P0，本周）：**
1. 对 03/06/07/10/12 五份回执执行结论降级，重开缺口 Batch；在验收文档加硬规则"一票否决项有 ⚠️/🔜 即禁止判通过"。
2. 将"RAG search 按 visibility 过滤"与"reconnect snapshot 统一过滤"提为跨模块 P0 缺口（涉及 02/03/07/10/12），关闭前冻结"无剧透"相关验收结论。
3. 在 00-规范与 50-README 之间做一次权威回灌：角色映射（Host→RoomOwner/SharedStage）、可见性总表、固定参考模组入库路径。
4. 补 M0 缺口文档：安全暂停（01）、意图澄清（12）、申诉纠错（04/10/11），并对齐 PRD-18。

**近期（P1，两周内）：**
5. 按 08-Clue 模板重写 04/05 回执，补边界值测试证据与前端构建证据。
6. 消除接口矛盾三处（retry-turn、`/ai-turn` 权限、PlayerIntent 命名）；建立"回执修复后必须回改功能列表现状段"的维护规则。
7. 任一文档专节解释 12 个 xlsx tmpdir 测试错误；回执测试基线附执行证据。
8. 统一开局人数口径（1 人演示 vs 2 人 M0）。

**后续（P2）：**
9. 07-12 的 PRD 与功能列表去重，恢复两文件定位分工；统一版本号与 frontmatter。
10. 修正 RollResult 双写字段契约；回执改为按验收文档 20 问逐条作答的强制模板。

---

*评审覆盖：60/60 份文档逐份阅读；对照文档：00-产品规范 4 份、PRDs/README、PRD-00、PRD-01。*
