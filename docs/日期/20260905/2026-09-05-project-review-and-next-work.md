# 项目评审与剩余工作估计（2026-09-05）

当前项目已经有完整的平台骨架和较多业务实现，但仍处于技术闭环收口阶段。主要剩余工作是接通现有实现、修复跨流程断点、补齐自动纠错与恢复，以及取得真实整场证据。当前不能认定为 M0-Verified 或 P0 发布通过。

在保持现有技术栈、固定 CoC 7e 短模组、复用现有页面的前提下，P0 技术闭环及验收暂估 **20–35 人日**；达到陌生玩家可独立完成一场团的 P1 Playable Alpha，再预留 **15–25 人日**。这不是按代码量推算的完成百分比，也不是交付承诺。真人招募、外部服务等待和新增需求不在估计内。

## 1. 评审范围与证据边界

- 工作区：`G:\hermes-agent-workplace\D&D\CodeX-aikeeper`。
- 分支：`codex/20260813-rag-corpus-audit`；HEAD：`38014fd`，最近提交日期 2026-08-30。
- 评审开始时有 **51 个已跟踪文件修改、443 个未跟踪文件**。其中源码 `src/` 有 25 个修改、28 个新增；`tests/` 有 19 个修改、13 个新增。其余包含文档、工具和临时材料，不能全部当作功能开发量。
- 已跟踪差异为 4,163 行新增、132 行删除，不含未跟踪文件。以上是工作树现状，不等于已提交、合并或发布。
- 本轮读取产品规范、8 月冻结任务包、8 月 23/27 验收材料，并交叉检查主流程源码与测试。没有修改业务代码；仅新增本评审报告及忽略目录中的验证日志。
- 本轮没有启动真实 Provider、多浏览器完整跑团或故障断电演练。静态确认问题、自动测试结果、历史实测证据分别报告。

## 2. 应采用的产品范围

现行产品规范定义的是：纯 AI KP、Engine 唯一权威、文字优先、固定参考短模组、可选只读 Stage，以及可确认、可回执、可恢复的行动。M0 是内部验证，不等于公开发布。

来源：[M0 范围与 Gate](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/docs/00-产品规范/04-M0范围、里程碑与指标.md:18)、[规范优先级](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/docs/00-产品规范/README.md:27)。

工程验收还需对齐 D01–D25、123 条 AIO 冻结要求。8 月 27 日的执行包已明确：已有定向实现证据，但尚无完整 RC、30 场 Benchmark 和两场真实浏览器发布证据。[最新核验入口](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/docs/日期/20260823/AI_KEEPER_P0_P1_执行文档包_2026-08-22/00_使用说明与总索引.md:56)

需要统一的文档口径：

- 根 `AI_ONLY_ACCEPTANCE_SPEC.md` 与 `docs/00-产品规范/` 都使用“唯一”表述；新冻结包与旧 ADR 的接纳关系需要写清。
- 根验收规范部分条款写至少一场浏览器，新冻结包与聚合器要求至少两场；计划按后者估计。
- 8 月 23 日“未开始”的多项内容已在工作树中出现，不应照搬为当前剩余项；其汇总数也未完全对齐 25 项决策、123 项要求。
- `plan/plan25.md` 是空文件，不能承担后续执行计划。

不应计入本轮剩余量：完整 VTT/战棋、任意 PDF 可靠自动编译、长期战役、语音视频独立链路、社区市场、付费及插件生态。它们属于后续范围，不应阻塞固定短模组的验收。

## 3. 已有能力及实际边界

| 能力 | 当前工作树已有内容 | 仍需完成的部分 |
|---|---|---|
| 建房、身份、加入与角色 | Host/Player 页面、角色绑定、版本化剧本入口 | 严格开局门禁与玩家准备入口接通 |
| 玩家行动 | 文本输入、草稿、选择/确认/同意、回执、撤回及后续检定 | 新 intake/batcher/后台结算集成，自动申诉 |
| 规则与状态 | Engine、规则结果、骰点、状态服务、版本屏障 | 后台路径依赖一致性与故障后继续执行 |
| 线索、秘密与投影 | 私人/队伍分层、主动分享、证据板、Stage 凭证 | 所有后台路径使用同等保护；实际跨端探测 |
| 暂停、终止与恢复 | pause/resume、Owner 终止、系统 proposal、检查点 | 真实故障入口与恢复状态统一、重启续跑、可达 UI |
| 结局与档案 | 确定性结局、结局卡、归档、版本束、Trace/retention | 完整团产出的固定版本束及可追踪证据 |
| 内容与管理 | 导入、编译、质量门禁、RAG、Provider 与房间管理 | 以冻结发布实物验收，不以编辑器页面存在替代 |
| 测试与指标 | 较多契约/单元/集成测试、Golden 套件、指标聚合器 | 实际仿真采集器、真实场次、可靠发布门禁 |

## 4. 优先处理的发现

本节“阻断”表示会阻断本项目下一阶段目标，不代表所有问题都属于安全漏洞。

### F1：开局确认入口与开局门禁形成循环依赖

**静态路径确认，真实浏览器待复现。** 新玩家加入后进入 Lobby；Session Zero 面板只在 `CampaignHomePanel` 中，该组件挂在玩家运行页面。未开局访问运行页面会重定向回 Lobby；服务端又要求先完成 Session Zero 才能开始。

证据：[加入路由](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/client/src/shared/player-join-flow.ts:16)、[未开局重定向](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/client/src/pages/PlayerActionPage.tsx:613)、[确认面板](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/client/src/components/CampaignHomePanel.tsx:806)、[服务端开始门禁](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/router_rooms.py:710)。确认记录唯一生产 INSERT 由显式 Session Zero POST 执行，Join/Ready 不会自动完成确认。

此外，Host 开局错误把结构化 `detail` 转成字符串，会显示 `[object Object]`，无法说明缺少哪个玩家的哪项确认。[错误呈现](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/client/src/pages/HostLobby.tsx:315)

处理：复用现有面板接入准备流程，并展示服务端缺项；补 Join → Lobby → 确认 → Start 的完整测试。现有面板 SSR 测试和假 fetch 测试不能覆盖路由副作用。

### F2：后台调度、Pipeline 和投影的新实现尚未一起接通

**源码确认；相关定向测试验证结果见第 5 节。** `RoomActionBatcher` 存在，但未找到生产调度接入；调度仍走 `asyncio.create_task`。后台 Pipeline 构造存在差异：单行动路径未传 `spoiler_guard`，协作批次还未传 `gateway`、`state_service`。批次涉及权威状态变化时会撞到状态服务缺失的拒绝分支。

证据：[实际调度](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/player/router_actions_v2.py:1513)、[单行动装配](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/player/router_player.py:1516)、[协作装配](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/player/router_player.py:1619)。

新增测试要求 `_create_background_pipeline`，但源码未定义；回合投影测试引用的 `build_turn_resolved_projection` 也不存在，已经阻断全量测试收集。不能把这些未接通的文件当作已完成功能。

处理：先收口当前工作树的接口与装配，确保实际 PostgreSQL 后台与测试使用一致的权威、AI、防剧透依赖，再验批次结算和投影。冻结要求需要自动、幂等的结算，不限定必须使用某个 batcher；intake、resolution-console 等新接口应先对照要求决定归属，不能仅因已有未完成测试就扩充 M0 范围。

### F3：真实故障暂停与新系统恢复入口不匹配

**静态跨函数路径确认。** `_pause_room_for_integrity` 把行动写成 `rejected`，房间写为 `status='paused'`、`integrity_status='read_only_recovery'`，没有写 `runtime_status='paused_system'`。新恢复 API 却只接受后者，因而该故障路径进入恢复时会被 `room_not_paused_system` 拒绝。

证据：[故障写入](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/engine/resolution_pipeline.py:3707)、[恢复门禁](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/engine/system_recovery.py:105)。已有恢复成功测试直接 SQL 构造 `paused_system`，绕开了实际故障入口。[测试设置](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/tests/server/test_glass_rain_golden_flow.py:914)

另有可靠性边界：领取后已是 `resolving` 的行动，再次进入流水线会直接返回；没有发现持久化领取回收和跨阶段重启续跑的完整接入。进程中断后卡住属于待故障注入验证的风险，不声称本轮已做 kill/restart 实验。

处理：统一房间、行动和结算三层状态；验证 Provider 失败 → 暂停 → 重启/恢复 → 同一行动继续，原骰和已提交事务不得重做。现有恢复方案仅支持严格同版本恢复，不能等同于完整事务重放。

### F4：纯 AI 自动申诉仍没有业务闭环

**确认的功能缺口。** 当前玩家 review 请求在 `ai_only` 下直接返回 409。拒绝进入 Host 人工队列符合权限边界，但没有自动重新解释、复用原 RollReceipt、规则复核和有界补偿承接。前端也未使用回执的 `can_review` 提供完整入口。

证据：[服务端拒绝](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/player/router_action_reviews.py:37)、[玩家回执](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/client/src/components/PlayerDecisionCard.tsx:376)。

处理：提供原始意图 → 异议 → 原骰复核 → upheld/corrected/compensated 的可追踪闭环，并与“重新尝试一次行动”分开。歧义候选已部分实现，应专项核验后补差量，不按从零开发估计。

### F5：Session Zero 缺少真实投影探测和缺勤策略冻结

**源码与最新核验文档一致的缺口。** 目前开始门禁检查五项确认、风险合同 hash 与 ready 状态，并不证明私人消息确实到达本人、公共内容正确投影；玩家缺勤策略仍可直接更新，未形成开团冻结证据。

证据：[开始检查](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/router_rooms.py:48)、[缺勤策略更新](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/player/router_player_settings.py:92)。

处理：服务端保存带身份/版本绑定的实际探测证据，并冻结缺勤策略；刷新、设备更换和配置变更时按协议处理。不能只新增勾选框。

### F6：发布聚合器会把缺失指标视为不阻断

**本轮已用独立合成反例复现。** 向 `aggregate_benchmark` 提供 30 份声明为 victory 的观测，15 双人、15 四人，其中两份自带浏览器计数；但所有观测都没有行动、Trace 行动、耗时或评分。多个指标返回 `not_measurable`，最终仍为 `release_ready=true`、`release_blockers=[]`。

原因是阈值逻辑只在 `value is not None` 时判失败，最终阻断列表未包含“缺少指标/Trace 分母”。[阈值与发布判定](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/src/server/scenario/ai_only_benchmark.py:157)

现有缺分母测试只传一场数据，最终被 `sample_size` 拦住，无法证明样本数量达标时仍会拒绝缺证据。[现有测试](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/tests/server/test_ai_only_benchmark.py:51)

这次合成输入仅用于证明聚合器缺陷，不是真实跑团/浏览器证据。处理时应把不可测指标、Trace 分母、唯一场次和原始证据完整性作为独立门禁。

### F7：真实整场验收工具与证据仍需建设

在 `src/`、`scripts/`、`tests/`、`tools/` 搜索聚合器调用，仅找到定义与单测。现有模块接受外部观测，不负责跑真实场次；Golden 套件使用确定性夹具，不能替代真实 AI 决策质量。

因此剩余不只是“把 30 场脚本跑一遍”，还需要固定种子仿真 runner、Trace 到观测的采集、故障注入、Provider/Prompt/规则/剧本版本固定，以及两玩家无 Stage、四玩家有 Stage 两条浏览器黄金路径；Stage 中断也必须不阻塞行动完成。

## 5. 本轮验证

| 验证 | 当前结果 | 可证明的范围 |
|---|---|---|
| 前端 `npm run test` | 退出 0；55 文件、217 测试通过 | 当前前端自动化；多数为纯函数、SSR、假网络或 WebSocket |
| 前端 `npm run build` | 退出 0；TypeScript 与 Vite 通过 | 类型检查与构建，不代表浏览器闭环 |
| 后端标准全量 | 退出 2；收集阶段 2 个错误 | MCP 环境依赖缺失、回合投影函数不存在 |
| 后端允许收集错误的续跑 | 约四分钟后主动停止，最后完整进度行 4%，无完整结果 | 不计作全量通过，也不把人工停止说成产品测试失败 |
| 后端定向验证 | 退出 1；**16 failed、12 passed，40.99 秒** | 28 项定向样本，特意选择疑似未完成区域，不代表全仓通过率 |
| Benchmark 缺证据反例 | 已复现 `release_ready=true` | 发布门禁存在缺陷；不是合格场次 |
| 真实 Provider/浏览器/弱网/断电 | 本轮未执行 | 不作完成声明 |

后端日志保存在忽略目录 `.runtime/review-20260905/`。测试使用本轮独立库 `aikeeper_review_20260905_test`，没有清理业务库。当前 Python 为 PATH 中的 Hermes 环境，缺少 `mcp.server.fastmcp`；MCP 依赖列在独立 `kp_mcp_server/requirements.txt`，应使用可复现的项目环境完成正式回归。

定向范围：Benchmark、后台 Pipeline、调度器、玩家 intake、结果包投影、房间 batcher、图片配置，以及 Session Zero/版本束、系统恢复、Owner 终止三个已有 Golden 用例。完整回归没有被定向结果替代。

定向失败分组：

| 测试区域 | 失败数 | 实际症状 |
|---|---:|---|
| 后台 Pipeline | 1 | `_create_background_pipeline` 不存在 |
| 行动调度 | 1 | 未使用 batcher，直接创建异步任务；测试环境无运行中事件循环 |
| 玩家行动协议 | 8 | intake 返回 405；分析结果缺少约定的 `player_context` / `director_plan` |
| 结果包投影 | 2 | Stage/Host resolution-console 接口返回 404 |
| 图片配置 | 4 | 缺少 `image_generation_configs` 表，或 image-providers 接口返回 404 |

通过的 12 项包括聚合器现有 6 项、batcher 自身 1 项、图片相关独立测试 2 项和所选 Golden 3 项。batcher 自身通过、接入测试失败，恰好说明“模块已写”与“生产路径可用”之间的差距。所选 Golden 通过证明既有功能在其测试条件下可用，不抵消 F1/F3 的跨流程问题。

图片生成属于可后置能力；上述 4 项需保留为当前工作树未完成证据，但不应自动扩充 M0 产品范围。正式回归时应明确实验能力的归属和测试范围，不能将跳过结果标作全量通过。

复现命令（先配置本轮隔离的 `TEST_DATABASE_URL`，并令 `DATABASE_URL` 指向同一测试库；开启开发测试模式）：

```powershell
python -m pytest tests/server -q --basetemp=.pytest-tmp-review-20260905 --tb=short
python -m pytest -q --basetemp=.pytest-tmp-review-20260905-targeted --tb=short tests/server/test_ai_only_benchmark.py tests/server/test_background_resolution_runtime.py tests/server/test_action_resolution_scheduler.py tests/server/test_player_action_protocol.py tests/server/test_resolution_bundle_projection.py tests/server/test_room_action_batcher.py tests/server/test_image_generation_config.py tests/server/test_glass_rain_golden_flow.py::test_ai_only_session_zero_freezes_mode_and_room_version_bundle tests/server/test_glass_rain_golden_flow.py::test_ai_only_system_recovery_uses_a_generated_verified_proposal tests/server/test_glass_rain_golden_flow.py::test_ai_only_owner_end_is_an_aborted_termination_not_an_authored_ending
```

日志：[全量收集](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/.runtime/review-20260905/backend-tests.log)、[未完成的全量续跑](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/.runtime/review-20260905/backend-tests-continued.log)、[定向结果](G:/hermes-agent-workplace/D&D/CodeX-aikeeper/.runtime/review-20260905/backend-targeted.log)。日志包含测试过程数据，保留本地，不作为公开发布附件。

## 6. 下一步工作包与估计

按一名熟悉当前仓库的开发者、复用已有组件、不重做设计、包含定向测试和必要联调估计。下表有意合并前后端重叠工作，不能再机械加上各领域估计。

| 顺序 | 工作包 | 完成标准 | 估计人日 |
|---|---|---|---:|
| A | 收口工作树、运行环境、后台装配与调度 | 按冻结要求接通必要接口及自动幂等结算；实验/废弃方案明确归属；主链相关红例清零，能完整收集回归 | 3–5 |
| B | 开局与运营入口闭环 | 新玩家正常 UI 完成 Session Zero；实际探测与策略冻结；暂停/终止入口和错误可理解 | 2–4 |
| C | 故障恢复与重启续跑 | 真实故障进入正确状态；同一行动原骰/事务/投影恰好一次；可恢复后继续完成 | 5–8 |
| D | 自动申诉及歧义合同补齐 | 玩家可提交异议；原骰复核；追加式纠错/补偿；有解释和 Trace | 4–7 |
| E | Benchmark 采集、门禁与整场执行 | 缺证据必阻断；15 双人+15 四人观测；两玩家无 Stage、四玩家有 Stage 的真实浏览器及 Stage 中断证据；指标可追溯 | 4–7 |
| F | RC 与完整证据收口 | 固定 commit/版本束；123 条映射；Prompt/权限检查、全量回归及逐项未通过披露 | 2–4 |
| | **P0 合计** | 可信技术闭环并形成可复现验收结论 | **20–35** |

其中 C、D、E 不确定性最高。正式安排后应以 A+B 的实测结果重新估计；真实 AI 或并发故障若暴露结构性问题，需要额外预留，不能靠调整指标分母消除失败。

P0 后的 P1 仍是一个独立阶段，增量暂估 **15–25 人日**：完善第一次行动与结果理解、场景/NPC/线索和多人参与感、恢复与结局体验、Review Workbench 和真人反馈闭环。复用现有页面，不把文档里的 12 个工作包当成 12 个全新系统。至少需要内部试用、受控新玩家、陌生玩家各一轮；真人排期另计。

按单人每周五个有效工作日，P0 约 4–7 周，累计到 P1 约 7–12 周；多人可并行部分前后端和证据工作，但 C/D 的状态与协议依赖不能简单按人数平分。这是现阶段粗估，不是日历承诺。

## 7. 建议下一轮直接执行的范围

先完成 A+B：统一后台装配与调度接口，接通开局前 Session Zero，修复缺项显示，并用两个玩家走通“加入 → 确认 → 开始 → 第一条行动 → 回执”。同时加入缺证据 Benchmark 反例。该阶段先建立可运行基线，再展开恢复和自动申诉。

没有必要现在扩充平台目录或整体重构大文件。Owner 结束、版本冻结、系统恢复等已有实现应补跨链路验证，不能重做一遍；长期战役页面的个别无效按钮和样例面板可后置处理。
