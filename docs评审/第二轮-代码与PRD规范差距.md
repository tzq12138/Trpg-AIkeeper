# 代码 ↔ PRDs/产品规范 双向差距分析

- 评审轮次：第二轮（代码实现 ↔ PRD/产品规范 双向差距）
- 评审日期：2026-07-22
- 代码侧证据基线：`G:\hermes-agent-workplace\D&D\CodeX-aikeeper\README.md`（下称 README，引用格式 README §章节/行号）
- 文档侧证据基线：`docs/00-产品规范/`（00 宪法、01 角色、03 权威矩阵、04 M0 范围、05 安全基线、ADR-001~008、裁决映射、验收记录-2026-07-15）与 `docs/PRDs/PRD-00~30`（共 31 份）

---

## 1. 概述

本轮评审以"挑剔的资深评审"立场做双向差距分析：**专门找漏掉的工作**——规范/PRD 要求了但代码无证据的（漏实现），以及代码已建但规范/PRD 未授权或明确排除的（漏需求/越界建设）。

三条总体判断：

1. **主链路骨架完整，M0 安全底座缺失。** README 显示 Engine/ResolutionPipeline/规则 Handler/投影/事件日志/检查点等权威链路均有对应模块（README §1 目录树、§3.2 PlayerIntent 生命周期），但 04-M0 范围中"安全与结束"一整行（内容提醒、边界确认、X-card、淡出、私密反馈、安全结束）在 README 中**零模块、零路由、零页面**，Gate G5 直接红灯。
2. **代码规模明显超出 M0 授权边界。** 04-M0 明文"可保留但不阻塞 M0"的能力（PDF 自动导入、语音、地图、复杂战棋、完整战役归档、多 Provider/MCP、自主 Agent）在 README 中全部已建成完整子系统（`scenario/pdf_parser.py`、`stt.py`、`router_map.py`、`encounter_persistence.py`、`campaign_archive.py`、`agent/game_agent.py`、`kp_mcp_server/`），且部分（语音）被 PRD-08/PRD-14 直接定为 P0 主入口——与 ADR-003"Later"定位正面冲突。
3. **角色模型两代并存且未映射。** ADR-005 与 01 角色总表废止单一 `Host` 概念，规范角色为 ScenarioPreparer/RoomOwner/TableSteward/Player/SharedStage/AIKeeper/Engine；README 代码结构仍以 `host/` 目录、HostStage/HostConsole/HostLobby/HostCreate 四个页面、`host_autonomy.py` 为一等公民，规范角色名在代码中**无一出现**，权限审计无从对表。

---

## 2. M0 必验项实现状态表（逐条：必验项、代码证据、状态判定）

### 2.1 「M0 必须进入验收」8 项（来源：04-M0范围、里程碑与指标.md §M0 必须进入验收）

| # | 必验项（规范原文摘要） | 代码证据（README） | 状态判定 |
|---|---|---|---|
| M0-1 | **内容**：一份原创/获授权固定参考短模组；验收证据=发布版本、来源与质量检查记录 | `data/golden_modules/` 三套原创黄金样本剧本（README §1 目录树 L216）；`scenario/golden_suite.py` 黄金套件、`scripts/run_golden_module_suite.py` E2E 验证（README §1）；`scenario/quality.py` 质量报告 | **疑似有**。黄金样本与质量报告存在；但 ADR-002 要求的"`ScenarioVersion` 发布门禁（未通过发布门禁不可成为黄金路径）"在 README 无对应模块，`content_package.py`/`module_compiler.py` 是否带版本固定与发布门禁不可判定 |
| M0-2 | **房间与身份**：创建、邀请、加入、角色绑定、开始、暂停、结束；角色和设备凭证分离 | `router_rooms.py` 房间路由、`HostCreate.tsx`/`PlayerJoinPage.tsx`/`PlayerLobby.tsx`/`HostLobby.tsx`（README §1）；`X-Room-Token` 鉴权（README §3.2） | **疑似有**。房间生命周期页面与路由齐全；但 01 角色总表要求的"人角色凭证与设备凭证分离"在 README 只有单一 `X-Room-Token`，无设备凭证/角色凭证双轨证据；"权限与伪造身份测试"无对应测试文件名证据 |
| M0-3 | **输入与理解**：文字输入；模糊或高影响行动的 Intent Contract 和确认 | 文字主链：`POST /api/player/intent`（README §3.2）；模糊意图：Director 低置信度（<0.6）→ `player_clarification_required`（README §3.2 L305-306）、`router_clarification.py` | **疑似有**。文字输入与低置信度澄清链完整；但"**高影响行动**的 Intent Contract 和确认"（02 生命周期/裁决 142-150：重大不可逆风险需确认）在 README 无任何"高影响确认/二次确认/联合确认"模块证据 |
| M0-4 | **规则**：CoC 7e 核心技能、SAN 与 M0 所需状态后果；RuleResult、骰点和状态回执 | `rules/coc_handlers.py`（CocSkillCheckHandler/CocSanityHandler/CocCombatHandler/CocLuckHandler，README §5.3）；`engine/skill_check.py` D100 检定；`engine/roll_receipt.py` 骰点回执；`engine/state_service.py` 状态变更 | **有** |
| M0-5 | **权威**：Engine 唯一提交，规则结果先于叙事；direct-mutation 与先叙事拦截测试 | `engine/engine.py`"唯一权威状态写入者"（README §5.2）；ResolutionPipeline 链路 RuleExecutor→StateService→Narrator（README §3.2）；`tests/server/` 约 100 个测试文件含 `test_engine.py`/`test_resolution_pipeline.py`（README §1 L199-209） | **疑似有**。架构与测试目录符合；但"direct-mutation 拦截测试""先叙事拦截测试"两个具体测试名在 README 未列出，无法确认专项覆盖 |
| M0-6 | **信息**：player-private、party、stage-safe、internal 四层；主动分享 | ProjectionDispatcher 按 audience 投影、推送 host+player+party 事件（README §3.2 L314、§5.2）；`player/private_data.py` 私密数据；`router_clues.py` 线索路由 | **疑似有**。投影分层存在（README 自述 audience 为 host/player/party，03 权威矩阵要求 player_private/party/stage_safe/internal 四层且含 internal 层，**internal 层无对应**）；`share_clue` 主动分享意图在 README 无明确证据 |
| M0-7 | **恢复与纠错**：幂等、状态版本屏障、重连、追加式申诉/补偿 | action_id 幂等检查、`state_version` 冲突检测（README §3.2）；`router_reconnect.py` 断线重连；`engine/compensation_service.py` 补偿服务；`router_action_reviews.py` 行动审查；EventLog 检查点（README §1 events/） | **有**（模块级）。专项"重试、乱序、断线和申诉轨迹"验收证据未在 README 列出 |
| M0-8 | **安全与结束**：内容提醒、边界确认、X-card、淡出、私密反馈、安全结束 | **无任何对应模块**。README §5.5"安全模块"仅含 SpoilerGuard/ProviderConfig/SecureRandom/Admin Auth/Asset Security——全部是技术安全，无一项桌面安全（table safety）；`engine/ending_conditions.py` 是剧情结局判定，非安全结束；全目录树无 x-card/safety/consent/内容标签相关文件 | **无 → 漏实现（P0）**。05 安全基线 §内容与桌面安全 5 条要求（开场内容标签与边界确认、任一玩家可触发 X-card 不暴露触发者、暂停立即停止 AI 推进、受限内容淡出/替代、Owner/Steward 最小信号）均无代码证据 |

### 2.2 Gate G0–G6（来源：04-M0范围 §Gate）

| Gate | 目标（规范原文摘要） | 代码证据（README） | 状态判定 |
|---|---|---|---|
| G0 | 产品和规范收敛：角色、权威、生命周期和范围均以 00-产品规范为唯一入口 | 文档侧已收敛（验收记录-2026-07-15）；代码侧角色体系仍是 Host 中心（README §1 `host/` 目录、4 个 Host 页面、`host_autonomy.py`），规范角色名 RoomOwner/TableSteward/SharedStage 在 README 零出现 | **无 → 漏实现（P0）**：代码未按规范角色重构或建立映射 |
| G1 | 权威裁决链：AI/Player/Stage 无越权写入；规则结果先于叙事 | `engine/engine.py` 唯一写入者（README §5.2）；pipeline 先 RuleExecutor 后 Narrator（README §3.2）；Narrator fact-ref 校验+本地回退（README §3.5） | **有**（架构级）；拦截测试专项证据待补 |
| G2 | 状态与投影时序：断线、重连和 Stage 中断不产生状态分叉 | `router_reconnect.py`、EventLog 检查点（README §1）；但 PRD-04 §11 要求的私密 patch 延迟投递（`delayedDelivery`/`executeAfterStep`）在 README 无证据；Stage 中断不阻塞主链的测试证据无 | **疑似有**：重连/检查点有，**时序穿透防御无 → 漏实现（P1）** |
| G3 | Intent 与回执：高影响意图可确认；每次提交有可解释 Receipt | `engine/roll_receipt.py` 骰点回执；行动状态机（README §3.3）；高影响意图确认机制无证据（同 M0-3） | **疑似有**：Receipt 有，**高影响确认无 → 漏实现（P1）** |
| G4 | 事实、认知与线索：私密/公开边界和来源引用可验证，无剧透泄漏 | `engine/spoiler_guard.py` 输出侧确定性匹配+重试+模板回退（README §3.5）；`ai/spoiler_control.py`；Director citations（README §5.1）；`RedactedCitationDisclosure.tsx` | **疑似有**：机制存在；03 权威矩阵的"认知版本/Knowledge 服务"四层可见性完整性、红队检查证据无 |
| G5 | 安全与 Session 闭环：暂停、淡出、私密反馈与安全结束不依赖 Owner 或 Stage | 同 M0-8：**零证据** | **无 → 漏实现（P0）** |
| G6 | 黄金路径：两玩家无 Stage、四玩家有 Stage 两条路径均有完整证据 | `scripts/run_multiplayer_loop.py` 多人循环测试、`scripts/run_golden_module_suite.py`（README §1 scripts/） | **疑似有**：E2E 脚本存在；但"**无 Stage** 路径完整结束"的专项证据无（README 全部房间 UI 均绑定 Host 视角），验收记录-2026-07-15 亦明示"不证明 G1–G6 代码实现已完成" |

### 2.3 M0 必验项小结

- 8 项必验项：**有 1 项（M0-4）、疑似有 5 项、无 1 项（M0-8，P0）、部分缺失 1 项（M0-1 门禁）**。
- 7 个 Gate：**有 1（G1）、疑似有 4（G2/G3/G4/G6）、无 2（G0、G5，均 P0）**。
- 最严重缺口：**桌面安全体系（X-card/边界确认/安全暂停/淡出）整体未开工**；其次为**规范角色模型未落地**。

---

## 3. PRD-00~30 映射表与双向缺口（漏实现/漏需求，P0/P1/P2 分级）

### 3.1 PRD → 代码模块映射总表

| PRD | 名称 | README 对应模块 | 覆盖判定 |
|---|---|---|---|
| PRD-00 | 全局协议与投影契约 | `engine/projection.py`（ProjectionDispatcher 按 audience 投影，README §5.2）；`client/src/types.ts`、`client/src/ws.ts` | **疑似有**。投影机制在；但 18 个 `EngineEventType` 事件全集（s2c_reveal_transaction 等命名）、camelCase 强约束、host/player/system 四类 audience、序列号去重协议在 README 均无证据（README 自述 audience 仅 host/player/party 三类，缺 system） |
| PRD-01 | Engine 意图生命周期与状态写入边界 | `engine/engine.py`、`engine/resolution_pipeline.py`；README §3.2 完整生命周期（actionId 幂等、state_version 409） | **有** |
| PRD-02 | Host 通信总线与路由分发 | `host/router_host.py`（WS endpoint）、`host/ws_manager.py`（ConnectionManager）、`client/src/ws.ts` | **疑似有**。WS 通道在；hostSequence 序列去重、Player 私密事件白名单丢弃+告警、指数退避（max 30s）无证据 |
| PRD-03 | Host 全局 HUD 与状态聚合 | `host/hud_builder.py`、`HostStage.tsx`、`HostSkeletonPanels.tsx` | **疑似有**。HUD 构建在；`displayMode=vague` 模糊显示、chatMessages 200 条上限、resetRoomStore 无证据 |
| PRD-04 | Host 事务播放器与多级队列 | `host/public_stage.py` 公共舞台 | **疑似有（关键子项缺失）**。舞台在；normal/urgent 双队列、15s Watchdog、Urgent 抢占恢复点、§11 **私密 patch 延迟投递（delayedDelivery）防御**在 README 均无证据 → **漏实现（P1）** |
| PRD-05 | Host 氛围引擎 | **无对应模块**。README 目录树无 atmosphere/AudioMixer/BGM/SFX 任何文件（仅 `data/scenario_assets/` 提及音频素材存储） | **无 → 漏实现（P1）**。s2c_atmosphere 事件、视觉覆盖层、AudioMixer、音频解锁全缺 |
| PRD-06 | Host 舞台演出与剧情渲染 | `HostStage.tsx` | **疑似有**。页面在；SceneBackground 双图层、rAF 打字机、Dice3DNode、紧急重置入口无证据 |
| PRD-07 | Player 通信网关与单播路由 | `client/src/ws.ts`（PlayerWS）、`engine/projection.py` | **疑似有**。WS 在；playerSequence 去重、"服务端物理单播隔离为安全主机制"的架构声明无 README 证据 |
| PRD-08 | Player 对讲机与语音意图 | `server/stt.py`（语音转文本集成）、`STT_PROVIDER` 环境变量（README §2）、`VoiceInput.tsx` | **有（实现超前）**。STT 集成与组件均在——但注意 ADR-003 将语音定为 Later，详见 §4 |
| PRD-09 | Player 活体角色卡与触控检定 | `PlayerCharacter.tsx`；README §3.3 行动状态机（idle→submitting→queued→resolving→resolved） | **有** |
| PRD-10 | Player 背包与线索软木板 | `PlayerInventory.tsx`、`router_clues.py` | **疑似有**。背包与线索路由在；CorkboardView 软木板（确定性散列定位、缩放平移）、`show_item` 意图无证据 |
| PRD-11 | Player 战术聊天与结构化行动按钮 | `TacticalButtons.tsx` 战术行动按钮组 | **疑似有**。组件在；`s2c_tactical_prompt {text, actions[]}` 结构化协议、50 条裁剪无证据 |
| PRD-12 | 玩家加入房间与手机准备流程 | `PlayerJoinPage.tsx`、`PlayerLobby.tsx`、`HostLobby.tsx`、`router_reconnect.py` | **疑似有**。页面在；`ready_toggle` 意图、一次性邀请码签名、IP 速率限制（5 次/分）无证据 |
| PRD-13 | 玩家角色卡导入与剧本适配反馈 | `scenario/xlsx_parser.py`（openpyxl）、`CharacterBuilderPage.tsx`、`scenario/character_presets.py` | **疑似有**。xlsx 解析在；`CharacterCompatibilityReport`（matched/warning/missing 三档适配报告）、`character_import_confirm` 意图无证据 |
| PRD-14 | 玩家行动面板与语音优先输入 | `PlayerActionPage.tsx`（5 标签统一面板）、`PlayerActionComposer.tsx`、`VoiceInput.tsx` | **有**（但"语音优先"定位与 ADR-003 冲突，见 §4） |
| PRD-15 | 玩家行动回执与 AI 归并反馈 | 行动状态机（README §3.3）；`engine/batch.py` BatchCollector | **疑似有**。服务端状态链在；前端 `ActionReceipt` 本地回执链、`s2c_action_queued/batched` 两事件无 README 证据 |
| PRD-16 | 玩家私密线索与主动分享 | `player/private_data.py`、`router_clues.py` | **疑似有**。私密数据层在；`share_clue` 意图、Engine 生成 `publicSummary` 公开摘要、分享事件入档无证据 |
| PRD-17 | 玩家个人目标与当前任务 | `router_objectives.py` 目标路由 | **疑似有**。路由在；PersonalObjective 个人目标仅本人可见的权限隔离证据无 |
| PRD-18 | 玩家澄清请求与误判纠正 | `router_clarification.py`；Director 低置信度→`player_clarification_required`（README §3.2） | **疑似有**。澄清链在；澄清窗口（5 分钟/3 回合）、频率限制冷却、Engine 修正事务无证据 |
| PRD-19 | 玩家断线重连与状态恢复 | `router_reconnect.py`；EventLog 检查点 | **疑似有**。路由在；`GET /api/player/sync`、pending action 恢复查询、eventId 幂等丢弃无 README 证据 |
| PRD-20 | 玩家个人档案与自由复盘查询 | `router_player_archive.py` 玩家档案路由 | **疑似有**。路由在；分类筛选/关键词搜索/时间线排序/回放跳转无证据 |
| PRD-21 | 房主开房与有限急救权限 | `router_rooms.py`、`HostCreate.tsx`；`engine/host_autonomy.py` Host 自主决策 | **疑似有（方向存疑）**。开房在；`owner_pause`/`owner_retry_turn` 有限急救意图无证据；且 `host_autonomy.py` 是"Host 自主决策"——与 PRD-21"房主薄权限、不看真相"的对应关系不明，与 01 角色总表存在张力（见 §4 ADR-005） |
| PRD-22 | PDF 剧本导入与自动结构化 | `scenario/pdf_parser.py`（pdfplumber）、`import_service.py`、`content_package.py`、`module_compiler.py`、`router_scenarios.py` | **有（实现超前）**。完整导入链在——但 ADR-002 定位其为"可保留的降级/实验能力、不作验收前提"，见 §4 |
| PRD-23 | 剧本质量报告与一键开局 | `scenario/quality.py`、`review_service.py`、`ScenarioReviewWorkbench.tsx` | **疑似有**。质量报告与审查工作台在；`ready/warning/highRisk/blocked` 四档、一键开局 `create-room` 端点无 README 证据 |
| PRD-24 | AI 自动 KP 主持循环 | `game_loop.py`（GameAgent 自动回合循环）、`agent/game_agent.py`（DeepSeek KP 代理）、`ai/ai_kp.py`（AIKP 高层入口）、`AGENT_ENABLED`（README §2） | **有** |
| PRD-25 | 自由行动收集与批次结算 | `engine/batch.py` BatchCollector、`turn_manager.py`、`turn_timeout_worker.py` | **有（主）疑似（细节）**。批次收集在；`s2c_action_batched` 事件、冲突行动交 AI 判断顺序无证据 |
| PRD-26 | 防剧透策略与暴露度控制 | `engine/spoiler_guard.py`、`ai/spoiler_control.py` | **疑似有**。防剧透双件套在；但 PRD-26 核心类型 `SpoilerProfile` 三档（strict/standard/cinematic，默认 standard 偏严）、`ExposureState` 暴露度模型、释放审计日志在 README 均无证据 → **三档配置漏实现（P1）** |
| PRD-27 | 事件日志存档回放与检查点 | `events/event_log.py`（持久化+检查点+可见性过滤）；"回合结算后自动创建检查点"（README §3.2）；`router_archive.py` | **疑似有**。日志+检查点在；`GET /api/rooms/:roomId/replay` 公共回放、`POST .../restore/:checkpointId` 恢复端点无 README 证据 |
| PRD-28 | 自动结局与可查询战役档案 | `engine/ending_conditions.py`、`campaign_archive.py` | **疑似有**。结局判定+归档在；`s2c_campaign_ended` 事件、结局后房间只读态无证据 |
| PRD-29 | Engine 四阶段意图裁决管线与后验物品主张 | `engine/resolution_pipeline.py`（README §3.2 四段链路）；`engine/retro_items.py` RetroactiveItemService | **有** |
| PRD-30 | 双层规则引擎架构 | `rules/base.py` BaseRuleHandler、`rules/registry.py`、`rules/triggers.py`、`rules/coc_handlers.py` | **疑似有**。Handler+Registry+触发器在；JSON5/受限 DSL 剧本级触发器配置格式（triggers[].condition+mechanics[]）是否落地不可判定 |

### 3.2 漏实现清单（PRD 有要求、README 无对应模块/证据），按优先级

| 优先级 | 缺口 | 来源 | 说明 |
|---|---|---|---|
| **P0** | 桌面安全体系：内容标签+边界确认、X-card/安全暂停、受限内容淡出、私密安全反馈、安全结束 | 04-M0 §必验项第 8 行；05 §内容与桌面安全；Gate G5；01 §权限原则 5 | README 零模块。注意：31 份 PRD **也没有任何一份**承接桌面安全需求——这是"规范有、PRD 漏、代码无"的三层断链，详见 §3.4 |
| **P0** | 规范角色模型（RoomOwner/TableSteward/SharedStage）落地或映射 | ADR-005、01 角色总表、Gate G0 | 代码只有 Host 一族命名（README §1 `host/`、`Host*.tsx`、`host_autonomy.py`） |
| **P1** | PRD-05 Host 氛围引擎整体（s2c_atmosphere、AudioMixer、视觉覆盖层、音频解锁） | PRD-05 §5 | README 无任何氛围/音频模块 |
| **P1** | PRD-04 §11 私密 patch 延迟投递防御（delayedDelivery/executeAfterStep，防"骰子未停、手机已弹"时序剧透） | PRD-04 §11 已知架构 Bug | README §3.2 投影推送无延迟投递环节 |
| **P1** | PRD-26 防剧透三档 SpoilerProfile + ExposureState 暴露度模型 | PRD-26 §5.1-5.3 | README 只有 SpoilerGuard 输出拦截，无配置档与暴露度状态 |
| **P1** | 高影响行动 Intent Contract 与确认（重大不可逆风险二次确认） | 04-M0 §必验项第 3 行；Gate G3；裁决 142-150 | README 仅低置信度澄清，无高影响确认链 |
| **P1** | PRD-00 事件协议细节：18 事件全集、`system` audience 第四类、camelCase 约束、host/player 序列号体系 | PRD-00 §5 | README 自述 audience 三类（§3.2 L314），无事件枚举证据 |
| **P2** | PRD-23 风险四档+一键开局端点；PRD-27 回放/恢复两端点；PRD-28 s2c_campaign_ended+只读态；PRD-12 邀请码签名+速率限制；PRD-13 适配报告；PRD-16 share_clue+publicSummary；PRD-20 自由查询/搜索 | 各 PRD §5/§6 | 对应路由/页面骨架在 README 存在，功能级证据缺失，需代码级核查确认 |

### 3.3 漏需求/越界建设清单（README 有模块、PRD-00~30 无覆盖或明确排除）

| 优先级 | 代码模块（README 证据） | 问题定性 |
|---|---|---|
| **P0** | `player/team_messages.py` 队伍消息（README §1 player/ 目录） | PRD-11 §3 范围边界明文"**不包含玩家之间自由群聊**"——代码做了 PRD 明确排除的功能，且队伍自由聊天是新的剧透/私密泄漏面，未经 05 安全基线评估 |
| **P0** | `engine/host_autonomy.py` Host 自主决策（README §5.2） | 04-M0 §Later 明文"Host 缺席自治"为 Later 项；01 角色总表无"Host 自主决策"权限主体。该模块权限来源无规范授权 |
| **P1** | `router_map.py`+`map_persistence.py`+`map_store.py`+`ai/map_generator.py`+`HostMapPanel.tsx` 地图子系统（README §1） | 04-M0 §可保留但不阻塞："地图与 Token"为可保留实验能力；31 份 PRD 无地图需求。且 `ai/map_generator.py` 运行时 AI 生成地图与 ADR-007"禁止运行时新 Canon"存在张力 |
| **P1** | 遭遇战/战斗轮子系统：`encounter_persistence.py`、`rules/encounter_handlers.py`、`EncounterPanel.tsx`、`combat_round_planner.py`、`solo_combat_reactions.py`（README §1） | PRD-01 §3 明文"不包含复杂战斗/追逐二期规则"；裁决 151-187 战斗切片均为 later。建设超前但未阻塞主链 |
| **P1** | `scenario/solo_adventure.py`+`solo_runtime.py` 单人冒险（README §1） | 31 份 PRD 无单人模式需求（产品宪法主命题为 2-4 名玩家） |
| **P1** | 管理后台族：`router_admin.py`、`AdminDashboard.tsx`、`AdminAcceptancePage.tsx`、`ai/provider_config.py`（Fernet+HKDF 加密配置）、`router_ai.py`（README §1） | 无 PRD 覆盖。属平台运营能力（对应 50-AI-Keeper-Platform 文档族），但未在 PRD-00~30 登记 |
| **P1** | `AbsentPolicyControl.tsx` 缺席策略控制（README §1 components/） | 04-M0 §Later："缺席/替补"为 Later；裁决 96-105 later |
| **P2** | 迁移/运维族：`router_migration.py`、`room_migration.py`、`v2_cutover.py`、`global_reset.py`、`export.py`、`redis_cache.py`、`RagTestPage.tsx`、`kp_mcp_server/` 独立服务（README §1） | 无 PRD 覆盖；多数属工程基建，可接受但应在架构决策中登记（kp_mcp_server 对应"多 Provider/MCP"可保留项，README §2 `AI_PROVIDER_ORDER=mcp,deepseek,local` 显示其已进入默认 provider 链首） |
| **P2** | `LoginPage.tsx`+`router_auth.py` 账号体系（README §1） | PRD-12 §3 明文"不包含账号系统"；README §6.3 显示 JWT_SECRET 生产强校验——轻量鉴权已建，与 PRD"roomToken 轻量凭证"定位的关系需说明 |

### 3.4 重点核查项复核（任务指定四项）

| 项 | 结论 |
|---|---|
| **PRD-08 语音** | 代码已建（`stt.py`/`STT_PROVIDER`/`VoiceInput.tsx`，README §1/§2）。**真正的问题不是漏实现，而是三方口径冲突**：ADR-003+裁决 130-136 定语音为 Later，PRD-08/PRD-14 定为 P0 主入口（"语音是主入口，文字和按钮是补充"），代码已落地。且 PRD-08 US-08-1"松开后系统自动提交给 KP"与 ADR-003"语音只能转换为用户**可编辑、可确认**的文字"存在张力——PRD-15 §5.2 虽有"展示转写文本、允许取消或确认"环节，但 PRD-08 §5.5 是"STT 返回后直接 submitIntent"，两份 PRD 之间亦不一致 |
| **PRD-22 PDF 导入** | 代码已建完整链（`pdf_parser.py`/`import_service.py`/`content_package.py`/`module_compiler.py`，README §1）。问题同样是**定位冲突**：ADR-002 将其定为"可保留演进、必须先生成草稿和异常报告、未过发布门禁不得成为黄金路径"；README 未显示"草稿态/异常报告态/发布门禁"的状态机证据，`review_service.py`+`ScenarioReviewWorkbench.tsx` 是否即发布门禁需代码核查 |
| **PRD-24 AI KP 循环** | 代码已建（`game_loop.py`/`agent/game_agent.py`/`ai/ai_kp.py`）且 PRD-24 有覆盖，双向匹配。**残留问题**：PRD-24 §5.2"AI 输出不能直接写状态"依赖 Engine 校验——README §3.2 链路符合；但 `AGENT_ENABLED=false` 默认关闭（README §2），GameAgent 路径与 ResolutionPipeline 主路径的关系（谁调用谁）在 README 不清晰 |
| **PRD-26 防剧透** | 代码已建 `spoiler_guard.py`+`spoiler_control.py`（README §1/§5.5），**但只覆盖了 PRD-26 的"输出拦截"一半**；`SpoilerProfile` 三档、`ExposureState` 暴露度、释放审计（PRD-26 §5.1-5.3、§5.7）无 README 证据 → 判定**半实现（P1）** |

---

## 4. ADR vs 代码现实冲突表（每条 ADR：规范立场、代码立场、风险）

| ADR | 规范立场（原文摘要） | 代码立场（README 证据） | 判定与风险 |
|---|---|---|---|
| **ADR-001** AI-only | M0 只有 AI-only；不建真人 KP 工作台或**运行期剧情复核队列**；RoomOwner 不是剧情裁判 | 基本合规：`ai/ai_kp.py`、`agent/game_agent.py` 为 AI KP 核心（README §1）。疑点：`player/router_action_reviews.py` 与 `host/router_action_reviews.py" 行动审查`（README §1）——host 侧"行动审查"是否构成剧情复核队列，README 无法判定 | **代码基本站 ADR 一边**。风险：host 侧 action_reviews 语义未审计，若含人工改判即越界 |
| **ADR-002** 人工验证参考短模组 | 自动导入可演进，但必须先草稿+异常报告；**未通过发布门禁不得成为 M0 黄金路径**；PDF 不作验收前提 | 完整 PDF→结构化→编译→审查链已建成（`pdf_parser.py`/`import_service.py`/`module_compiler.py`/`review_service.py`/`ScenarioReviewWorkbench.tsx`，README §1）；黄金路径走 `golden_modules`（README §1 data/）——黄金路径本身合规 | **代码站在"黄金路径"一边，但导入链完整度超出"降级/实验能力"定位**。风险：自动导入链既成事实后，发布门禁若缺位，任意 PDF 会实质进入开团路径，架空 ADR-002 |
| **ADR-003** 文字唯一验收基线 | 文字是唯一 M0 验收基线；语音若存在只能是**可编辑、可确认**的文字前置；裁决 130-136 定语音为 later | `stt.py`、`STT_PROVIDER` 环境变量、`VoiceInput.tsx` 已建成（README §1/§2）；PRD-08/PRD-14 更将语音定为 P0 主入口（"语音优先输入"） | **代码站在 PRD-08/14 一边，与 ADR 正面冲突**。风险：①三方口径（ADR/PRD/代码）不一致，验收时无法判定语音算不算 M0 范围；②"松开即提交"（PRD-08 US-08-1）若先于"可编辑确认"（PRD-15 §5.2）落地，直接违反 ADR-003 后果条款 |
| **ADR-004** Shared Stage 永远可选 | Stage 只读、无业务写权限、断线不阻塞主链；**无 Stage 两玩家路径必须可完整结束** | 架构上 Stage 是投影消费者（README §5.2 ProjectionDispatcher），方向合规；但全部房间 UI 以 Host 视角组织（`HostStage.tsx` 等 4 页面，README §1），README 无"无 Stage 路径完整结束"的验证证据 | **架构站 ADR 一边，证据缺失**。风险：G6 黄金路径验收时，"无 Stage 完成短团"可能从未被真实跑通——README §6.6 测试清单中无对应用例 |
| **ADR-005** 拆分人、设备和服务角色 | `Host` 不是规范概念，仅作兼容别名；任何 API/UI 必须说明对应规范角色；**不能从名称推导真相或写入权限** | `host/` 目录 6 模块、`HostStage/HostConsole/HostLobby/HostCreate` 4 页面、`HostCampaignControls/HostLogsPanel/HostMapPanel/HostSkeletonPanels` 组件、`host_autonomy.py`（README §1/§5.2）——Host 是代码一等公民；RoomOwner/TableSteward/SharedStage 命名零出现 | **代码直接站 ADR 反面（P0）**。风险：①"房主有限急救"（PRD-21）与"Host 控制台"（HostConsole.tsx）的权限边界无法按规范审计；②`host_autonomy.py` 的决策权来源无规范授权；③后续每次安全评审都要先做"Host=哪个规范角色"的翻译，翻译错误即权限事故 |
| **ADR-006** Engine 唯一权威写入 | 只有 Engine 验证前置、提交状态、写事件、生成投影；规则结果先于叙事 | `engine/engine.py` 自述"唯一权威状态写入者"（README §5.2）；pipeline 先 RuleExecutor/StateService 后 Narrator（README §3.2）；Narrator fact-ref 校验+回退（README §3.5） | **代码站 ADR 一边（方向最正的一条）**。风险：边缘路径待核——`compensation_service.py`、`host_autonomy.py`、`global_reset.py`、`v2_cutover.py` 是否全部经由 Engine 提交，README 不证明 |
| **ADR-007** 禁止运行时新 Canon | AI 只能从已发布 ScenarioVersion 选取演绎；重大揭示/NPC 身份/结局必须版本化证据+Engine 提交 | Narrator 只能引用 `allowed_facts` 否则本地回退（README §3.5）；`ending_conditions.py` 结局判定在 Engine 侧（README §5.2）——主链合规。疑点：`ai/map_generator.py` 运行时 AI 生成地图（README §1）是否算运行时新 Canon | **主链站 ADR 一边，地图生成器在灰色地带**。风险：AI 生成地图若进入权威状态，即构成运行时新 Canon；若不进入，则属纯表现层——README 未说明其状态路径 |
| **ADR-008** 可信短团而非长期战役 | Campaign Governor、缺席/替补、跨部署迁移、运行期内容维护均 Later，需独立 ADR | `campaign_archive.py` 战役归档（PRD-28 覆盖，合规）；但 `AbsentPolicyControl.tsx` 缺席策略、`room_migration.py`+`router_migration.py` 迁移（README §1）属 Later 项已建 | **部分站 ADR 反面**。风险：缺席策略/迁移提前建设，扩大状态与隐私边界（ADR-008 背景原话），却无对应 ADR 与隐私评估 |

### 4.1 既成事实风险总评

代码在六个方向上跑在规范前面：语音（ADR-003）、PDF 导入链（ADR-002 定位外）、地图（Later 项）、遭遇战/战斗轮（Later 项）、缺席/迁移（ADR-008 Later 项）、Host 角色实体（ADR-005 明文废止项）。共同风险模式是：**代码先行 → PRD 追认（部分 PRD 如 PRD-08/14 已经把 Later 写成 P0）→ ADR 被倒逼修订或架空**。其中 ADR-005 是唯一直接被代码违反的 ADR（不是"超前"，是"相反"），且它是 G0 Gate 的验收对象——这意味着按现行代码结构，G0 无法通过。

---

## 5. 结论与行动建议

### 5.1 结论

1. **代码主链与 PRD 骨架高度重合，但 M0 验收关键项存在两个 P0 空洞**：桌面安全体系（M0-8/G5，README 零模块）与规范角色模型（G0，代码全员 Host 命名）。前者是"规范有、PRD 漏、代码无"的三层断链——31 份 PRD 无一份承接 05 §内容与桌面安全的 5 条要求，需求在第一棒就掉了。
2. **双向缺口呈不对称分布**：漏实现侧集中在"协议细节层"（事件枚举、三档防剧透、延迟投递、高影响确认，P1 级）和"安全层"（P0 级）；漏需求侧集中在"Later 项提前建设"（地图/遭遇战/单人/缺席/迁移）与"PRD 明文排除项"（team_messages 队伍群聊、账号体系）。
3. **ADR 冲突的本质是治理问题而非技术问题**：8 条 ADR 中 5 条代码方向正确（001/004/006/007 主链、002 黄金路径），1 条被直接违反（005），2 条被"超前实现"架空（003/008）。当前最危险的不是代码多写了，而是**多写的部分没有对应的 ADR/安全评估/验收口径**，形成审计盲区。

### 5.2 行动建议（按优先级）

**P0（阻塞 M0 验收，必须先补）**

1. **补桌面安全需求与实现**：新增 PRD（建议编号 PRD-31 桌面安全与 X-card）承接 05 §内容与桌面安全 5 条：开场内容标签+边界确认门禁、任一玩家 X-card（匿名、无需理由、立即停 AI）、受限内容淡出/替代、私密安全反馈通道、安全结束路径。代码侧至少需要 safety 服务模块 + 玩家端触发入口 + Owner/Steward 最小信号投影。
2. **裁决 Host 角色映射**：二选一——(a) 代码重构：`host/` 拆分为 RoomOwner 操作面 + SharedStage 播放面，权限按 01 总表分离；(b) 新增 ADR-009 追认"Host 为兼容聚合名"，并逐模块声明其对应规范角色与权限边界（ADR-005 后果条款要求的"说明对应规范角色"）。推荐 (b) 为 M0 过渡、(a) 为 M1 目标。同时澄清 `host_autonomy.py` 的授权来源。
3. **裁决语音口径**：ADR-003 与 PRD-08/14 必须统一——要么修订 ADR-003 承认"语音转写+可编辑确认"为 M0 验收项（并把 PRD-08"松开即提交"改为强制确认环节），要么 PRD-08/14 降级为实验能力、退出 M0 验收范围。二者择一，不能继续三方各说各话。

**P1（M0 验收前应关闭）**

4. 补 PRD-05 氛围引擎或将其显式移出 M0 范围（改 PRD 状态+标注，不要留着"待开发"却无人认领）。
5. 补 PRD-04 §11 延迟投递防御（delayedDelivery），这是已被 PRD 自己识别的剧透 bug，防御方案 B（Engine 在 status_delta step 广播后再发 Player Patch）实现成本低。
6. 补 PRD-26 `SpoilerProfile` 三档 + `ExposureState` 暴露度模型，接通现有 `spoiler_control.py`。
7. 补高影响行动确认链（Intent Contract），打通 G3。
8. 处置 `team_messages.py`：PRD-11 明文排除玩家群聊，应下线该模块或走新增 PRD+安全评估流程补票。
9. 对地图、遭遇战、单人冒险、缺席策略、迁移五个超前模块补登记：逐一标注"实验/降级能力，非 M0 验收面"（04-M0 §可保留但不阻塞的原文地位），其中 `ai/map_generator.py` 需补 ADR-007 符合性说明。

**P2（M0 后清理）**

10. 补 PRD-00 事件全集枚举与第四类 `system` audience 的代码对齐，冻结 camelCase 校验。
11. 补 PRD-23 四档风险+一键开局、PRD-27 回放/恢复端点、PRD-28 ended 只读态等端点级缺口。
12. 将 `router_admin.py`/`provider_config.py` 等平台模块与 50-AI-Keeper-Platform 文档族正式挂接登记。
13. 为 G6 补"两玩家无 Stage 完整结束"的可重复验证用例并纳入 §6.6 测试清单。

---

*报告完。所有"疑似有"项的最终确认需进入代码级核查（README 为结构总结，非逐行证据）；本报告已按任务要求仅以 README 与规范/PRD 文档为证据基础。*
