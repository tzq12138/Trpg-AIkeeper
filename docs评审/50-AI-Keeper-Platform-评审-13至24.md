# 50-AI-Keeper-Platform（13-24 子系统）评审报告

**评审日期**: 2026-07-22
**评审范围**: `docs/50-AI-Keeper-Platform/` 下 13 至 24 共 12 个子系统的全部 61 份文档
**对照基准**: `docs/PRDs/PRD-00-全局协议与投影契约.md`、`docs/PRDs/PRD-01-Engine意图生命周期与状态写入边界.md`、`docs/00-产品规范/`（尤其 01-角色权限总表、03-唯一权威矩阵、04-M0范围）、`docs/00-路线图/平台能力分层与MVP边界.md`

---

## 1. 概述

### 1.1 各子系统文件清单

12 个子系统均为标准五件套（`功能列表.md` / `PRD.md` / `DeepSeek计划.md` / `验收文档.md` / `回执-YYYY-MM-DD.md`），共 61 份。仅 17-Host-Client 多出一份 `回执-2026-07-07.md`（文档评审回执），即该系统有两份回执。

| # | 子系统 | 文件数 | 回执日期 |
|---|---|---:|---|
| 13 | State 世界状态系统 | 5 | 2026-07-07 |
| 14 | Transaction 事务系统 | 5 | 2026-07-07 |
| 15 | Projection 投影系统 | 5 | 2026-07-07 |
| 16 | Player-Client 玩家私人端 | 5 | 2026-07-07 |
| 17 | Host-Client 公共舞台端 | 6 | 2026-07-07 + 2026-07-08 |
| 18 | Asset 素材库系统 | 5 | 2026-07-08 |
| 19 | Module 模组编辑器 | 5 | 2026-07-08 |
| 20 | Voice-Media 语音与媒体系统 | 5 | 2026-07-08 |
| 21 | Safety 跑团安全边界系统 | 5 | 2026-07-08 |
| 22 | Schedule 日程与招募系统 | 5 | 2026-07-08 |
| 23 | Community 社区生态系统 | 5 | 2026-07-08 |
| 24 | Plugin-Admin-Ops 开放API与后台运维 | 5 | 2026-07-08 |

### 1.2 整体质量评分：B

模板一致性极高（12/12 子系统结构统一，均含"当前阶段说明 / 模块定位 / 当前代码真实锚点 / 数据分层 / DTO 契约 / 权限边界 / 验收标准 / 一票否决项 / 回执最小模板"），文档与真实代码锚点绑定紧密，范围控制（尤其 22/23/24）克制。主要扣分项：**工程回执结论系统性失真**（多个子系统在自列的一票否决项未闭环时仍判"通过"）、**平台文档与 00-产品规范存在角色/权限模型层面的根本冲突**、**事件协议存在两套事实源**。

### 1.3 逐系统评分表

| 子系统 | 评分 | 简评 |
|---|---|---|
| 13-State | A- | 状态语义、事务契约、版本屏障写得最硬；回执结论与一票否决项矛盾 |
| 14-Transaction | B+ | 内容最强之一（状态机、编号边界、失败分级），但回执 9 项一票否决 5 项未过仍判通过 |
| 15-Projection | A- | 可见性/裁剪/导出边界清晰；回执同样带 ⚠️ 通过 |
| 16-Player-Client | B+ | token 风险、版本屏障写得细；前端 stateVersion 屏障未实现仍判通过 |
| 17-Host-Client | B | 双回执时间线逻辑勉强，database tab 占位未处理仍通过；Host 权限模型与产品规范冲突 |
| 18-Asset | B+ | 上传安全四重校验落地扎实；visibility 枚举 PRD 与实现不一致 |
| 19-Module | B | 发布准入矩阵好；回执内部自相矛盾（publishStatus），P0 接口未闭合仍通过 |
| 20-Voice-Media | B+ | STT 边界、临时媒体口径清晰；遗留项诚实；与 M0"语音 Later"的定位未对齐 |
| 21-Safety | B- | **名实不符**：README 定位"内容分级/禁区/X-Card/Session 0"，实为应用安全文档；X-card 仅 P1；回执无一票否决自检表 |
| 22-Schedule | A- | 范围控制范本（v1 只做入桌审批，招募/日程显式延后）；回执未回应 force_start 前端一票否决项 |
| 23-Community | A- | gating 设计最好（Community-4+ 需用户再次确认）；回执批次编号与计划不一致 |
| 24-Plugin-Admin-Ops | B+ | 控制面治理口径完整；"configurable ≠ 已强制"的 CORS 证据不足 |

**文档质量最差的三个子系统：21-Safety（名实不符 + 回执缺自检）、19-Module（回执自相矛盾）、17-Host-Client（回执时间线与占位问题）。**

---

## 2. 主要问题

### P0-1 工程回执结论系统性失真：一票否决项未闭环仍判"通过"

**问题描述**: 每个子系统的 `验收文档.md` 都定义了"出现任一情况本轮不能判通过"的一票否决项，但多份工程回执在自检表中把一票否决项标为 ⚠️（未闭环）后，结论仍写"本轮工程验收：✅ 通过"。验收机制形同虚设。

**证据**:

- `14-Transaction事务系统/回执-2026-07-07.md` 一票否决自检 9 项中 5 项 ⚠️（"duplicate 纯 check-then-write"、"Pipeline 先投影后 State 顺序未逆转"、"State 失败时 action 正常 resolved 当前无回滚"、"ReleaseGate 仅内存未持久化"、"host_step_complete 不校验 transactionId"），第五节结论仍为"本轮工程验收：✅ 通过"。对照 `14-Transaction事务系统/验收文档.md` 第 39-55 行，上述任一项都明文"不能判通过"。
- `13-State世界状态系统/回执-2026-07-07.md`：一票否决项中"ResolutionPipeline 先投影后落库 ⚠️ 未完全逆转"、"s2c_state_patch 缺关键版本字段 ⚠️ schemaVersion 未补"、"同一变化双重 patch ⚠️ 未验证"，结论仍为"✅ 通过"。
- `16-Player-Client玩家私人端/回执-2026-07-07.md`：已知遗留承认"前端 stateVersion 屏障未实现，四类测试未做"；而 `16-Player-Client玩家私人端/验收文档.md` 第 45 行一票否决项明确"`stateVersion` 屏障未落地，旧 patch 仍可能覆盖新状态"不得判通过。结论仍为"✅ 通过"。
- `19-Module模组编辑器/回执-2026-07-08.md`：已知遗留承认"`publishStatus` 独立字段未新增"、独立 templates 端点未建，而 PRD MO-FR-3/MO-FR-10 均为 P0，结论仍为"✅ 通过"。
- `22-Schedule日程与招募系统/回执-2026-07-08.md`：未回应 `22-Schedule日程与招募系统/验收文档.md` 第 51 行一票否决项（"`force_start` 新前端仍继续依赖 legacy `{ force_start: true }`，且回执未说明"）——回执只自检了后端 `router_rooms.py`，PRD 第 309 行自述"当前 HostLobby 仍发送旧的 legacy payload"。结论仍为"✅ 通过"。

**影响**: 验收文档的权威性被回执掏空；"通过"结论不可信，后续模块（如 23-Community 的工程启动门槛依赖 19/21/22/24"已通过"）会建立在失真结论上。

**建议**: 制度上规定"一票否决项存在 ⚠️ 时结论最高只能为'本轮工程验收有缺口'"；已发出的 6 份问题回执（13/14/15/16/19/22）应降级重签或补豁免 ADR。

### P0-2 平台文档与 00-产品规范的角色/权限模型根本冲突

**问题描述**: `00-产品规范/01-运行模式、角色与权限总表.md`（normative，2026-07-15，release_scope: M0）明确："`Host` 不是规范概念：旧代码中的 Host 名称只能作为兼容别名，不能据此推导角色权限"；RoomOwner 禁止"阅读幕后真相、玩家私密原文"。而 13-24 全套平台文档（V2.1，2026-07-07/08）仍以 Host/owner_token 为一等角色构建权限体系。

**证据**:

- `17-Host-Client公共舞台端/PRD.md` 数据分层 L8 `HostMapFullView`："全图、隐藏节点、位置、探索状态，Host-only 读模型"；接口方向含 `GET /api/host/{room_id}/map/full`。这直接违反规范中 RoomOwner"禁止阅读幕后真相"的边界——规范里没有任何人类角色被允许在开局后查看隐藏节点。
- `14-Transaction事务系统/PRD.md` 核心流程 4："Player 私密 `state_patch`、`private_notice`、`action_completed` 不直接下发，而是进入 `ReleaseGateDTO`……gate 满足后，服务端才释放对应 player 事件"。而 `00-产品规范/01-运行模式、角色与权限总表.md` 第 42 行规定："Stage 延迟、断线、关闭、拒绝显示或重播失败都不得阻塞 Engine 提交或玩家终端的恢复"；`03-领域对象与唯一权威矩阵.md` 中 Shared Stage 的禁止路径为"ACK 阻塞 Action 或 StateChange"。ReleaseGate 用 Host ACK 门控玩家私密结果，正是规范禁止的模式，且 14/15/17 三份文档都未给出"Host 缺席/断线时 gate 超时兜底"的语义。
- 规范角色表（ScenarioPreparer / RoomOwner / TableSteward / Player / SharedStage / AIKeeper / Engine）与平台文档角色表（Host / Player / Admin / AI-Keeper / DeepSeek）无一一映射；21-Safety 的 X-card 在规范中属于 TableSteward 核心能力（M0 必须验收），平台文档却只在 `21-Safety跑团安全边界系统/PRD.md` SF-FR-24 标为 P1。

**影响**: 两套权限事实源并存，工程实现按平台文档落地后会与 M0 验收基线（G1/G5 Gate）直接冲突，返工成本高。

**建议**: 由架构 owner 出一份术语/权限映射 ADR（Host→RoomOwner+SharedStage 的拆分、隐藏真相访问权归属、ReleaseGate 与"Stage 不阻塞"原则的二选一决策），并在平台文档头部加注与规范的时效关系。

### P0-3 事件协议存在两套事实源，平台文档大量使用 PRD-00 枚举外事件

**问题描述**: `PRD-00-全局协议与投影契约.md` 第 51 行规定"`EngineEventType` 必须至少包含以下事件全集，新增 PRD 不得绕过本枚举自造事件"，并冻结了 20 个事件。但平台文档大量引用枚举外事件，且无人回写枚举；反过来 PRD-00 中部分事件在平台文档中无对应实现口径。

**证据**:

- 平台文档使用但不在 PRD-00 枚举中的事件：`s2c_turn_resolved`（14-Transaction 接口方向表、15-Projection system_safe 白名单、16-Player WS 白名单）、`s2c_checkpoint_created` / `s2c_checkpoint_restored`（13-State 验收标准、15-Projection、21-Safety）、`s2c_team_message`（16/17/20）、`s2c_clue_discovered` / `s2c_clue_shared`（16-Player WS 白名单）、`s2c_map_updated` / `s2c_player_moved` / `s2c_map_revealed`（13/16/17）、`s2c_encounter_started`（17 PRD HostEventAdapter 节）、`s2c_force_start_audit`（22-Schedule PRD 第 308 行）、`s2c_game_time_updated`（21-Safety PRD system_safe 样例）。
- PRD-00 枚举中有但平台文档基本无对应：`s2c_full_snapshot`、`s2c_resume_transaction`、`s2c_cancel_transaction`、`s2c_engine_state`、`s2c_clarification_prompt` / `s2c_clarification_result`、`s2c_campaign_ended`（平台文档用 reconnect snapshot / archive 语义覆盖，但术语未对齐）。
- 可见性维度同样是两套：PRD-00/15-Projection 用 audience 四值 `host/player/party/system`；`00-产品规范/03-领域对象与唯一权威矩阵.md` 用可见性四层 `internal/player_private/party/stage_safe`，无映射表。

**影响**: 协议单一事实源被破坏，前后端类型校验、端到端协议兼容测试（PRD-00 验收标准）无法执行。

**建议**: 以 PRD-00 枚举为基线做一次全库事件名对账，把平台文档实际使用的 11+ 个事件补入枚举（或标注为 Host frame/audit-only 非枚举事件），并建立 audience ↔ 可见性层的映射表。

### P0-4 13-State 与 15-Projection 同日回执对同一字段结论相反

**问题描述**: `13-State世界状态系统/回执-2026-07-07.md` 一票否决自检写"`s2c_state_patch` 缺关键版本字段 ⚠️ schemaVersion 未补"；而同日 `15-Projection投影系统/回执-2026-07-07.md` 写"本轮补强 `s2c_state_patch` 版本字段……`_write_state_patch_event`: payload 增加 `schemaVersion`/`baseStateVersion`/`stateVersion`"，自检标 ✅。两份同日回执对同一代码事实（`src/server/engine/state_service.py` 的 patch payload）结论相反。

**影响**: 回执可信度进一步受损；无法判断 schemaVersion 到底补没补。

**建议**: 以代码和测试为准核实后更正其中一份；回执评审流程应要求跨模块同日回执做一致性对签。

### P1-5 State / Transaction / Projection 三者边界总体清晰，但 ReleaseGate 归属与持久化悬而未决

**问题描述**: 三份 PRD 对职责划分本身是清楚的（State 写真相、Transaction 编排事务与 gate、Projection 只做投递，15-Projection PRD"与 Transaction 的 ReleaseGate 边界"一节写得很好）。但：① gate 持久化位置在 `host_states` 还是新建 `transactions` 表，14-Transaction PRD 只给了"决策标准"未给结论，回执承认"未新增 transactions 表、ReleaseGate 仅内存（P1）"；② 三份文档都未定义 Host 缺席/断线时 gate 的超时兜底（与 P0-2 的规范冲突直接相关）；③ PRD-01 要求"每个已受理动作最终必须下发 s2c_action_completed"，而 ReleaseGate 语义下 completed 可能被无限期推迟，两份文档未协调。

**建议**: 在 14-Transaction 补一节"Host 缺席时 gate 的降级策略"（超时自动释放 or 明确不要求 Host 在线），并对 `transactions` 表决策给出截止条件。

### P1-6 16-Player-Client 行动 UI 状态机与 PRD-01 直接矛盾

**证据**: `16-Player-Client玩家私人端/PRD.md` PC-FR-10 要求"行动 UI 必须覆盖 `submitting/queued/batched/resolving/resolved/rejected/timeout`"；而 `PRD-01-Engine意图生命周期与状态写入边界.md` 第 69 行规定"Player 动作状态只允许 `IDLE | SUBMITTING | RESOLVING`，失败通过 toast 和 completed payload 表达，不新增 `REJECTED` 状态"。一个是七态展示模型，一个是三态状态机，未说明是"展示态 vs 传输态"的分层还是真冲突。

**建议**: 明确 PRD-01 约束的是"阻塞态"而 16 定义的是"展示态"，在 16 PRD 中加一句映射说明；否则以 PRD-01 为准收敛。

### P1-7 18-Asset visibility 枚举 PRD 与实现/回执不一致，且 P0 验收项未达成即通过

**证据**: `18-Asset素材库系统/PRD.md` 可见性枚举为六值 `host_only/hidden/public/revealed/private/admin_only`；`18-Asset素材库系统/回执-2026-07-08.md` 写 `db_adapter.py` 新增 visibility 列为 `host_only/party/private/admin_only` 四值——`hidden/public/revealed` 缺失，多出 PRD 没有的 `party`。另外 PRD 验收标准第 5 条"受控读取接口按 role + room + scenario + visibility 校验权限"对应的 `GET /api/assets/{asset_id}` 端点，回执自己承认"未建立"，仍判"✅ 通过"。

**建议**: 统一枚举（建议以 PRD 六值为准，给出 `party` 与 `public` 的迁移说明）；受控读取端点未建前，18 的结论应降为"有缺口"。

### P1-8 19-Module 回执内部自相矛盾，importStatus 枚举漂移

**证据**: `19-Module模组编辑器/回执-2026-07-08.md` 一票否决自检第 1 行写"✅ publishStatus 独立于 importStatus"，同文"已知遗留"第 1 行却写"`publishStatus` 独立字段未新增，当前派生自 quality_level"——同一文件内对同一事实结论相反。此外回执称 `importStatus` 四态为 `structured/requires_ocr/failed/already_imported`，而 `19-Module模组编辑器/PRD.md` 状态机定义五态 `pending/importing/requires_ocr/structured/failed`，`already_imported` 不在 PRD 枚举中。

**建议**: 更正回执；PRD 补 `already_imported` 的正式语义（重复导入去重是产品行为，应入状态机或明确为非状态返回值）。

### P1-9 21-Safety 名实不符，M0 要求的桌面安全能力被降为 P1

**证据**: `50-AI-Keeper-Platform/README.md` 对 21 的定位是"内容分级、禁区、X-Card、Session 0"；但 `21-Safety跑团安全边界系统/PRD.md` 实际内容约 90% 是应用安全（鉴权、可见性、反剧透、导出、部署基线），X-card/fade/private feedback 仅出现在 SF-FR-24（P1）和"桌面安全事件"一节，内容分级、禁区、Session 0 完全未覆盖。而 `00-产品规范/04-M0范围、里程碑与指标.md` 把"内容提醒、边界确认、X-card、淡出、私密反馈、安全结束"列为 **M0 必须进入验收**，`01-权限总表` 规定"安全暂停不要求说明理由，不依赖 RoomOwner 在线"。`21-Safety跑团安全边界系统/回执-2026-07-08.md` 对 X-card 只字未提，也无其他子系统回执都有一票否决自检表，直接宣布"全部 106 项验收清单闭环"。

**影响**: M0 验收基线（G5 Gate"安全与 Session 闭环"）在平台文档层无人认领。

**建议**: 21 拆成两个模块或在 PRD 中补"桌面安全"完整章节（X-card P0 化、不依赖 Owner 在线、不暴露触发者身份）；回执补一票否决自检表。

### P1-10 CORS/部署安全证据不足即通过

**证据**: `21-Safety跑团安全边界系统/验收文档.md` 第 150 行要求"生产 `CORS=*` 是否启动失败或 healthcheck fail"；`21-Safety跑团安全边界系统/回执-2026-07-08.md` 的证据是"CORS production guard ✅ 已有 `main.py` (configurable)"；`24-Plugin-Admin-Ops开放API与后台运维/回执-2026-07-08.md` 同样以"production CORS != * ✅ configurable"过关。"可配置"不等于"生产默认拒绝"，未提供任何启动失败/健康检查失败的测试证据。

**建议**: 补一条生产配置（CORS=*）启动失败或 health degraded 的自动化测试，否则两项回执该项标 ⚠️。

### P2-11 23-Community 回执批次编号与 DeepSeek计划/验收文档不一致

**证据**: `23-Community社区生态系统/回执-2026-07-08.md` 写"Community-7: 公开招募/战报/发现页"且不列 Community-8/9；而 `23-Community社区生态系统/DeepSeek计划.md` 定义 Community-7=举报与审核后台、Community-8=公开招募与公开战报、Community-9=回归验收，`23-Community社区生态系统/验收文档.md` 与之一致。回执批次口径错位。

### P2-12 17-Host-Client 双回执时间线与 database tab 占位问题

**证据**: `17-Host-Client公共舞台端/回执-2026-07-07.md`（文档评审回执）称"文档阶段通过，可以进入 Host-0 到 Host-7 工程执行"，并列出 5 个"工程执行时要继续盯住的点"（含 database tab 前端行为、Host WS lastSequence）；次日 `回执-2026-07-08.md` 即以"无新增后端修改"宣布"本轮工程验收：✅ 通过"，同时把 database tab（"占位状态，需隐藏或标'开发中'"）和 lastSequence（"前端传了但后端未消费"）列入已知遗留。`17-Host-Client公共舞台端/验收文档.md` 第 51 行把"database tab 仍展示会误导主持人的 mock 资料库内容"列为一票否决项，第 80 行验收清单要求"database tab 是否被隐藏，或明确标注'开发中/占位'"——回执未证明任一满足。

### P2-13 跨模块"前序 batch 已闭环"引用无追溯机制

**证据**: 多份回执的核心证据是"前序 Batch 已闭环"映射表（如 `21-Safety跑团安全边界系统/回执-2026-07-08.md` 声称 106 项验收清单由 02/06/07/08/09/10/11/18/20 batch 闭环；`24-Plugin-Admin-Ops开放API与后台运维/回执-2026-07-08.md` 声称 121 项由 02/07/08/11/12/18 batch 闭环），但仅给出 batch 名与文件名的二维表，无测试命令、无逐项证据链接。21 回执甚至没有任何 ⚠️ 项——与 21 验收文档自己列出的生产安全加签条件（export 专项测试缺失、CORS 校验缺失）矛盾。

### P2-14 文档质量小瑕疵

- `18-Asset素材库系统/功能列表.md` 第 15 行"场景图、手out、音频等素材"——"手out"为 handout 误写。
- `24-Plugin-Admin-Ops开放API与后台运维/PRD.md` 使用"## 1. 背景 ~ ## 13. 验收标准"编号章节，其余 11 个模块 PRD 均为命名章节，风格不统一（轻微）。
- 全库未发现 TODO/TBD/占位符残留，此点合格。

---

## 3. 跨子系统一致性问题

| # | 问题 | 涉及方 | 说明 |
|---|---|---|---|
| C-1 | 事件枚举两套事实源 | 全库 vs PRD-00 | 见 P0-3，11+ 个平台事件未入 `EngineEventType` |
| C-2 | 角色/权限模型两套 | 13-24 全部 vs 00-产品规范 01/03 | Host vs RoomOwner/TableSteward/SharedStage；隐藏真相访问权冲突，见 P0-2 |
| C-3 | ReleaseGate vs "Stage 不阻塞"原则 | 14/15/17 vs 00-产品规范 01、03 | 玩家私密结果被 Host ACK 门控，规范明文禁止，且无 Host 缺席兜底，见 P0-2/P1-5 |
| C-4 | `s2c_state_patch` schemaVersion 状态矛盾 | 13 回执 vs 15 回执 | 同日两份回执结论相反，见 P0-4 |
| C-5 | 行动状态机口径 | 16 vs PRD-01 | 七态展示 vs 三态状态机，见 P1-6 |
| C-6 | 优先级/范围三套词汇 | 全库 | 00-路线图用"P0-P3/第一轮"，00-产品规范用"M0/M1/M2/Later"，平台文档用"P0-P3/MVP"，无映射。规范把"语音独立链路、社区、插件生态"列为 Later，20-Voice 却把多项 STT 能力标 P0"进入 MVP"；22/23/24 因自我 gate 而未冲突 |
| C-7 | 桌面安全归属落空 | 21 vs 00-产品规范 04（M0 必须） | M0 强制项在平台层仅 P1，见 P1-9 |
| C-8 | visibility 枚举漂移 | 18 PRD vs 18 回执/db | 六值 vs 四值，见 P1-7 |
| C-9 | 验收结论可信度跨模块传导 | 23 门槛 ← 19/21/22/24 回执 | 23-Community 的 Community-4 启动门槛要求 19/21/22/24"已通过"，而这四份回执本身存在 P0-1 失真，门槛失效 |

---

## 4. 缺失项

1. **ReleaseGate 的 Host 缺席/断线降级语义**（14/15/17 三份文档均无）——主链路可用性的关键空洞。
2. **桌面安全（X-card/淡出/私密反馈/Session 0/内容分级/禁区）的完整产品设计**——README 承诺的方向在 21 中几乎空白，且与 M0 强制项脱节。
3. **异常路径的错误码体系不均**：16 有完整 `PlayerApiErrorDTO` 枚举，但 19 的 `ModuleApiErrorDTO`、22 的 `ScheduleApiErrorDTO`、24 的 `OpsApiErrorDTO` 仅列名字无枚举；22 的 10 个未来接口无错误码与限速口径。
4. **数据模型深度不一**：13/14/18 的 DTO 到字段级；22/23 的未来表仅"字段方向"（作为设计层可接受，但未像 23 那样显式标注"草案"）。
5. **Host WS catch-up（lastSequence）语义**：17 回执承认"前端传了但后端未消费"，PRD 未定义 Host 断线补发协议（Player 侧有完整契约，Host 侧空白）。
6. **`already_imported` 等实现态回值未入 PRD 状态机**（19）。
7. **术语映射表**：Host/RoomOwner/TableSteward/Stage/AIKeeper 与平台文档 Host/Owner/Admin/AI-Keeper 的映射缺失。
8. **权限矩阵颗粒度**：20-Voice、21-Safety 的权限表明显粗于 13/14/16（仅 5-8 行），Admin/Ops 与 Author 角色在 19 中"未来"化但无当前替代方案。

---

## 5. 亮点

- **模板纪律性极强**：12/12 子系统五件套齐全，章节结构、结论分级（本轮工程验收/生产安全完成）、一票否决项、回执最小模板完全统一。
- **"当前代码真实锚点"表**（每个模块列出 `src/server/...` 文件 + 现状判断）让文档不落空，是罕见的诚实度。
- **范围控制**：22-Schedule（v1 只做入桌审批，招募/日程显式延后）、23-Community（Community-4+ 需用户再次确认）、24-Plugin（外部开放能力明确"未实现且符合预期"）是范围内外标注的范本。
- **编号边界意识**：14-Transaction 的"turn_index / events.sequence / state_version / transactionId 四者不能互相替代"、13-State 的 state_version 语义收口，是状态系统文档应有的硬度。
- **安全边界写成可验收项**：export 脱敏白名单、system_safe 白名单、公开 DTO 白名单在 15/17/18/21/22 中高度一致。

---

## 6. 结论与行动建议

13-24 子系统文档的**设计质量整体良好（B）**，模板统一、代码锚定、DTO 与权限边界具体；但存在三个层级的系统性风险：**回执验收失真（执行层）、角色权限模型与产品规范冲突（架构层）、事件协议两套事实源（协议层）**。

**立即行动（本周）**:
1. 降级重签 6 份问题回执（13/14/15/16/19/22），或为其一票否决豁免项补 ADR；建立"一票否决 ⚠️ ⇒ 结论最高'有缺口'"的硬规则。
2. 出术语/权限映射 ADR：裁定 Host 概念存废、隐藏真相访问权、ReleaseGate vs "Stage 不阻塞"原则二选一，并补 Host 缺席时 gate 的降级语义。
3. 全库事件名对账，把 11+ 个平台事件并入 PRD-00 的 `EngineEventType`（或显式声明为例外）。

**排期行动（下一轮文档迭代）**:
4. 21-Safety 补桌面安全完整章节并将 X-card 提为 P0（对齐 M0 G5）；19 更正回执矛盾并补 templates 端点或降级结论；18 统一 visibility 枚举并补受控读取端点。
5. 建立三种范围词汇（P0-P3 / M0-Later / 第一轮）的映射页，给 20/22/23/24 头部加 M0 归属标注。
6. 回执增加"跨模块同日对签"与"前序 batch 证据链接"两项必填。

**文档质量最差、需优先返工**：21-Safety、19-Module、17-Host-Client。
