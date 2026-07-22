# PRDs（PRD-00 ~ PRD-30 + README）评审报告

## 1. 概述

**文件清单**：`docs/PRDs/` 共 32 份文件——README（索引，v2.0）+ PRD-00 至 PRD-30 连续编号 31 份。编号无断层、无重叠。分层为：模块 PRD（00–11）、工作流 PRD（12–28）、裁决与规则 PRD（29–30）。

**评审范围**：PRD-00/01/24/25/29/30 全文精读；其余 25 份通读 2/3 以上正文；并与 `00-产品规范`（产品宪法、01 角色权限、03 唯一权威矩阵、04-M0 范围、06 ADR）、`50-AI-Keeper-Platform` README、`90-归档/host|player模块设计` 交叉核对。

**整体质量评分：B-**

模板骨架统一度高（31 份均含背景/目标/范围边界/用户故事/功能需求/接口依赖/状态与错误处理/验收标准/测试场景/风险依赖十节），协议治理意识（PRD-00 事件全集、README 已修正口径表）高于一般水平。但存在三个层级的硬伤：① 与 2026-07-15 生效的 normative 产品规范方向性冲突且全库无一处引用或声明替代关系；② 若干跨 PRD 直接矛盾（动作状态机、语音提交时序、HTTP 状态码语义）；③ 最核心的 PRD-24（AI KP 主循环）恰是全书最薄、最不可测的一份。

### 逐份评分表

| PRD | 评分 | 简评 |
|---|---|---|
| PRD-00 全局协议 | B+ | 事件全集冻结有价值；但信封完整 TS 定义缺席、REST 表不全、`visibility` 未枚举 |
| PRD-01 Engine 边界 | B | 权限边界清晰；202→RESOLVING 与 PRD-25 矛盾；409 语义被 PRD-29 撞车 |
| PRD-02 Host 路由 | A- | 白名单/序列/重连具体可测；漏 `s2c_campaign_ended`/`s2c_chat_stream` 处理 |
| PRD-03 Host HUD | B+ | Store 字段明确；残留归档"模块 3/4/5"称谓 |
| PRD-04 事务播放器 | A- | Watchdog/Urgent 恢复设计扎实；§11 与 PRD-29 Bug2 重复且已漂移 |
| PRD-05 氛围引擎 | B+ | AudioMixer 单一入口明确；§11 与 PRD-29 Bug4 重复且已漂移（duckBGM 仅此处有） |
| PRD-06 舞台渲染 | B+ | 常驻组件/打字机口径清楚 |
| PRD-07 Player 网关 | B | 单播隔离原则正确；FR 白名单未覆盖自身验收标准要求的全部 Player 事件；token 走 URL query |
| PRD-08 语音意图 | B+ | MIME 降级/上滑取消具体；与 PRD-15 确认窗口矛盾 |
| PRD-09 角色卡检定 | B+ | 状态机/幂等/Watchdog 可测；202→RESOLVING 与 PRD-25 矛盾 |
| PRD-10 背包线索板 | B+ | "通知不改状态"原则落实好 |
| PRD-11 战术聊天 | B+ | 结构化 actions 取代正则解析，边界清楚 |
| PRD-12 入房准备 | B | 有量化（5 次/分钟限流）；中途加入"旁观/补位"未定义 |
| PRD-13 xlsx 导入 | B | 流程完整；文件大小上限无数值；`character_import_confirm` 意图未注册 |
| PRD-14 行动面板 | B- | 薄；语音优先与 ADR-003 冲突；依赖的 PRD-08 被排到最后一批 |
| PRD-15 行动回执 | B | 回执链完整；与 PRD-08 自动提交矛盾 |
| PRD-16 私密线索分享 | B+ | 权限边界好；"进入其他玩家 clues 或 party clues"语义未决 |
| PRD-17 个人目标 | B | 薄但自洽 |
| PRD-18 澄清纠错 | B+ | 有量化窗口（5 分钟/3 回合），边界清楚 |
| PRD-19 断线重连 | A- | State Version Barrier 设计好；但附录伪代码有死循环缺陷 |
| PRD-20 个人档案 | B | 薄；`/api/player/archive` 鉴权在 PRD-00 表中查无此项 |
| PRD-21 房主开房 | B | 薄权限定位准；`owner_pause`/`owner_retry_turn` 意图未注册、入口不明 |
| PRD-22 PDF 导入 | B | 原文引用/本地优先好；不产出 PRD-29/30 依赖的物品标签/职业矩阵/触发器 |
| PRD-23 质量报告 | B+ | 风险分级与二次确认可操作 |
| PRD-24 AI KP 循环 | **D+** | 产品核心却最薄：无回合状态机、无结束条件、无量化验收、无成本/时延约束；与 PRD-29 管线关系未定义 |
| PRD-25 批次结算 | **C+** | 状态映射表与 PRD-01/09 直接矛盾；收集窗口无参数 |
| PRD-26 防剧透 | **C+** | 三档有名无实：ExposureState 无等级/阈值/更新规则，验收不可测 |
| PRD-27 日志回放 | B | 边界（不做任意回滚）明确；无保留/膨胀量化策略 |
| PRD-28 自动结局 | B- | 薄；结局触发条件 Schema 未定义 |
| PRD-29 四阶段裁决 | B+ | 全书最充实；但 202 之后再返回 HTTP 4xx/5xx 的时序错误、409 语义撞车、错误章节引用 |
| PRD-30 双层规则 | B | Handler/DSL 方向好；示例代码与自身 Schema 矛盾；`auto_success` 降级危险 |
| README 索引 | B+ | 矩阵/依赖图/已修正口径表优秀；实施批次自相矛盾（PRD-14 先于其依赖 PRD-08） |

**质量最差的三份**：PRD-24（D+）、PRD-25（C+）、PRD-26（C+）——不幸的是它们恰好构成 AI 自动 KP 的心脏。

## 2. 主要问题

### P0-1 PRDs 与 normative 产品规范方向性冲突，且无任何替代/引用声明

- **证据**：`00-产品规范/06-决策记录 ADR.md`（status: normative，effective 2026-07-15）规定：ADR-002"PDF 自动导入不作为验收前提"、ADR-003"文字是唯一验收基线，语音只能是输入适配器"、ADR-004"Shared Stage 永远可选"；`00-产品宪法` M0 非目标含"语音、视频、音效"，M0 首要体验 #4"没有 Shared Stage 时，文字主链仍能完成一场短团"；`04-M0` 内容项要求"一份固定参考短模组"。而 PRD README §1 核心假设写明"玩家输入语音优先""剧本准备以文字 PDF 导入为起点"；§8 实施建议第一批就是"PRD-00、01、22、23，先让 PDF 到可开房成立"；PRD-14 US-14-2 语音按住说话为 P0；PRD-14 §10"远程跑团若无大屏，后续需补公共叙事模式"——无 Stage 路径被明示后置。31 份 PRD 全文无一处引用 `00-产品规范` 或任何 ADR。
- **影响**：规范自称"M0 唯一现行入口"，PRDs 自称"最终版本 v2.0"，两套文档对 M0 验收什么给出相反答案。开发按 PRDs 做将直接无法通过 G4/G6 Gate；按规范做则 PRD-08/14/22/23 大面积返工。
- **建议**：立即开一份 ADR 裁决：要么修订 ADR-002/003/004 接纳 PRDs 的产品形态（语音主输入、PDF 起点、Stage 依赖），要么把 PRD-08/14/22/23 降级为 M1+。在 PRD README 增加 front matter 声明与 `00-产品规范` 的 supersedes/depends_on 关系。

### P0-2 动作状态机跨文档直接矛盾（202 之后是 SUBMITTING 还是 RESOLVING）

- **证据**：PRD-01 §7"REST 返回 202 后，Player 状态进入 `RESOLVING`"；PRD-09 §5.5"REST 返回 202/200 后进入 `RESOLVING`"。PRD-25 §5.1 映射表却规定：HTTP 202→`SUBMITTING`；`s2c_action_queued`→`SUBMITTING`；`s2c_action_batched`→`RESOLVING`。开发文档 §7.4 站在 PRD-25 一边（"Engine 返回 202，Player 显示 queued"）。
- **影响**：前端动作锁是全书被引用最多的机制（PRD-07/08/09/10/11/14 全部依赖），两套真值表会让 Player Store 实现者无所适从，验收用例互相打架。
- **建议**：以 PRD-25 的细粒度映射为准（它能表达 queued/batched 差异），修订 PRD-01 §7 与 PRD-09 §5.5，并在 PRD-00 增加动作状态机权威定义节。

### P0-3 安全边界能力（X-card / 安全暂停 / TableSteward）全库缺失

- **证据**：`01-运行模式、角色与权限总表`定义 TableSteward"暂停、恢复、X-card、故障恢复"，并规定"安全暂停不要求说明理由，不依赖 RoomOwner 在线，也不暴露触发者身份"；`04-M0` 验收行含"内容提醒、边界确认、X-card、淡出、私密反馈、安全结束"，G5 Gate 专测此项；`50-AI-Keeper-Platform/21-Safety跑团安全边界系统`存在对应模块。31 份 PRD 中 grep 不到 X-card/安全暂停/内容提醒；PRD-21 房主暂停是"含剧透风险的行政暂停"，不等价于规范的安全暂停。
- **影响**：M0 验收硬性缺项；跑团产品的内容安全风险（AI 生成不适内容）无产品级出口。
- **建议**：新增 PRD-31"安全边界与 X-card"，或将其并入 PRD-21 并按规范补齐三原则（无理由、不依赖 Owner、不暴露触发者）。

### P0-4 AI KP 主持循环（PRD-24）与四阶段裁决管线（PRD-29）的架构关系未定义，且 PRD-24 违反"规则先于叙事"

- **证据**：PRD-24 §5.3"AI 输出结构化为叙事、检定建议、状态变更建议、线索释放建议"后由"Engine 校验"——叙事与结算建议由同一个 AI 调用同时产出。PRD-29 §5.1 则是严格的四阶段：LLM 阶段二只编译机制 JSON"严禁生成叙事文本"，Python 阶段三绝对裁决后，阶段四才把数学事实包装成叙事。`03-唯一权威矩阵`的权威提交顺序明确"Rule Executor → Engine State commit → … → AI narration from committed result"（规则结果先于叙事，宪法 M0#2、G1 同）。批次（PRD-24/25 的 ActionBatch）与逐意图管线（PRD-29）如何嵌套——批次内每条意图各跑一遍四阶段？还是批次整体过一次 LLM？——无任何文档说明。
- **影响**：这是 Engine 的核心数据流，两种结算哲学并存，开发无法同时满足。
- **建议**：在 PRD-24 增加"与 PRD-29 的关系"节：明确批次→拆分逐意图→四阶段管线→批次级叙事的调用拓扑；按 PRD-29 修正 PRD-24 §5.3 的 AI 输出结构。

### P1-5 PRD-29 在已返回 202 之后再规定返回 HTTP 4xx/5xx，时序不成立

- **证据**：PRD-29 附录 A 序列图：网关先 `HTTP 202 Accepted`，之后才进入"阶段一 校验资产持有权"。但 §5.1 阶段一要求"校验失败立即返回 HTTP 400/403"；§7 规定阶段三不可恢复错误"返回 HTTP 500"、后验主张违和/争议暗骰失败"返回 HTTP 409"、unique 物品"返回 HTTP 403"。202 发出后 HTTP 事务已结束，这些状态码无处投递。
- **影响**：阶段一之后的所有失败路径在协议上无法实现；客户端收不到错误会等到 Watchdog 超时。
- **建议**：明确"202 前同步校验（参数/持有权/频率）可返回 4xx；202 后一切失败经 `s2c_action_completed(status: rejected, reason)` 投递"，重写 §5.1/§7 对应条目。

### P1-6 HTTP 409 语义撞车

- **证据**：PRD-01 §5.4 与 PRD-09 §7：409 = `baseStateVersion` 过期 → 前端 toast 并触发快照重拉。PRD-29 §5.2/§7：后验物品主张违和、争议暗骰失败也返回 409（业务规则驳回）。
- **影响**：玩家主张物品被拒时，前端会误触发全量同步；反之状态过期时被当成业务驳回。同一客户端对 409 无法二义处理。
- **建议**：业务驳回改用 422（或走 rejected 事件），409 保留给版本冲突单一语义，写进 PRD-00。

### P1-7 语音行动提交时序矛盾：自动提交 vs 确认窗口

- **证据**：PRD-08 §5.5"STT 返回 `transcribedText` 后调用 `submitIntent('voice_command', transcribedText)`"——自动提交。PRD-15 §5.2"STT 返回后展示转写文本，允许玩家在短时间内取消提交或确认提交"——人工确认。
- **影响**：同一条语音链路两种交互，PRD-14 同时引用两者。
- **建议**：二选一。若保留确认窗口，修改 PRD-08 §5.5 并给出窗口时长（建议 ≤3s 可取消、超时自动提交）；在 PRD-15 写明与 ADR-003"文字基线"的关系。

### P1-8 PRD-00 作为协议单一事实源不完整

- **证据**：① PRD-00 §5.1 只列信封 8 个字段名，完整 TS 接口（含 `transactionId`、`sourceActionId`、`visibility` 四值枚举 `public|private|party|hostOnly`）只存在于开发文档 §4.1，PRD-00 反而没有；PRD-29 §13 引用"完整定义见 PRD-00 §2"，而 PRD-00 §2 是"目标"——错误引用。② PRD-00 §6 REST 表仅 7 个端点，缺 PRD-08 `/api/player/speech-to-text`、PRD-13 `/api/player/character/import-xlsx`、PRD-20 `/api/player/archive`、PRD-22/23 `/api/scenarios/*`（3 个）、PRD-27 `/api/rooms/:roomId/replay` 与 `/restore/:checkpointId`。README §7 自称已修正"工作流 PRD 新增接口未标注鉴权方式"，但修正只落在 PRD-00 表内已列端点，新增端点依旧全库无 Auth 标注（仅开发文档 §5 有）。③ `visibility` 取值全库无枚举；与 `03-唯一权威矩阵`可见性四层（internal/player_private/party/stage_safe）无映射表。
- **影响**：协议 SSOT 名不副实，前端/后端/测试三方各拿一份不全的表。
- **建议**：把信封 TS 定义、完整事件表、完整 REST+Auth 表、visibility 枚举及与权威矩阵四层映射全部回收进 PRD-00；修正 PRD-29 §13 引用。

### P1-9 意图类型注册表无家可归

- **证据**：PRD-29 附录 B 枚举 `intentType` 9 值（skill_check/use_item/show_item/dialogue/voice_command/retroactive_item_claim/ready_toggle/share_clue/clarification_request）。但 PRD-13 定义 `character_import_confirm`、PRD-21 定义 `owner_pause`/`owner_retry_turn`、PRD-30 触发器用 `$action: "read_item"`，均不在任何枚举中；PRD-00 未定义意图枚举。
- **影响**：Engine 路由层无法封闭校验，新 PRD 随时私造意图类型（与 PRD-00 §5.9"不得绕过枚举自造事件"同性质的问题在上行侧重演）。
- **建议**：PRD-00 或 PRD-01 增加 `IntentType` 权威枚举并回收集散各处的 13+ 种意图。

### P1-10 事件全集存在孤儿与漏处理：`s2c_chat_stream` 无人消费，多个 Player/Host 事件无路由归属

- **证据**：PRD-00 §5.9 事件全集含 `s2c_chat_stream`，但 PRD-02 瞬时白名单（§5.7）、开发文档 §6.1、全部 31 份 PRD 无任何消费方——孤儿事件。反向地，PRD-00 全集的 `s2c_room_lobby_snapshot`、`s2c_action_queued/batched`、`s2c_clarification_prompt/result`、`s2c_campaign_ended` 在 PRD-07 §5 的 Player 路由 FR 中均未出现，而 PRD-07 §8 验收标准却要求"Player Router 覆盖所有 PRD-00 中的 Player 相关事件"——自相矛盾；`s2c_campaign_ended` 在 PRD-02 Host 处理清单中同样缺席。
- **影响**：验收标准不可能通过；结局、大厅、批次反馈事件在前端路由层悬空。
- **建议**：删除或指派 `s2c_chat_stream` 的消费方；补全 PRD-02/07 的事件处理 FR 与全集一一对应。

### P1-11 资产链断裂：PRD-29/30 依赖的 `scenario_assets.json` 不由任何 PRD 产出

- **证据**：PRD-29 §5.3 需要 `items[].narrative.tags/baselineAccess` 与 `professionsMatrix`；PRD-30 §5.2 需要 `scene.triggers`。PRD-22 §5.5 结构化产出清单仅"场景、NPC、线索、真相、结局、危险点、推荐标签"——无物品标签、无职业矩阵、无触发器。PRD-29 §10 称"若剧本包缺失此文件，所有后验主张走争议分支"，则 §8 验收标准"流浪汉主张注射器→违和分支→HTTP 409"在缺文件时不可达。
- **影响**：PRD-29/30 的核心卖点（后验主张三分支、剧本触发器）在 PDF 导入主路径上没有数据源。
- **建议**：PRD-22 §5.5 产出清单补物品/职业矩阵/触发器抽取；PRD-23 质量报告增加"资产完整度"维度；修订 PRD-29 验收标准的可达性。

### P1-12 PRD-26 防剧透三档有名无实，验收不可测

- **证据**：PRD-26 §5.3"暴露度根据已发现线索、场景进度、玩家推理更新"无更新规则；§5.6"真相和结局只在高暴露度或结局阶段释放"——"高暴露度"无定义；三档 strict/standard/cinematic 无任何参数差异表；§8 验收"AI 越界输出会被拦截"无拦截率/测试集口径。
- **影响**：防剧透是产品差异化的核心宣称（README 验收矩阵、宪法 M0#3），却无法写测试。
- **建议**：定义 ExposureState（等级或 0–100 数值）、三档的释放阈值表、每档的上下文过滤规则；验收改为"固定剧本+固定线索集下，越权信息拦截率 100%（红队用例集 N 条）"。

### P1-13 PRD-25 收集窗口无任何参数

- **证据**：PRD-25 §5.3"到达时间、人数或 AI 判断条件后生成 ActionBatch"——三个条件均无默认值；§10 风险自述"窗口过短会打碎叙事，过长会让玩家等待"却不给窗口。
- **影响**：批次行为不可验收、不可调参。
- **建议**：给出默认窗口（如 20s / 全员已提交 / AI 显式收口三者先到为准）及房间级可配范围。

### P1-14 用户故事角色称谓遗留人类 KP

- **证据**：PRD-01 US-01-3"作为 KP，我需要公共演出和私密状态来自同一结算"；PRD-02 US-02-1、PRD-03 US-03-3、PRD-04 US-04-2、PRD-05 US-05-2、PRD-06 US-06-2 均以"作为 KP/作为房主"混用人类主持人视角。README §1 明确"AI 是 KP，人类房主只负责开房…"；ADR-005 后 `Host`/人类 KP 均非规范角色。
- **影响**：从归档 host/player 模块设计拷贝时未做角色清洗，权限语义错位（人类 KP 视角=全知，与本产品房主薄权限矛盾）。
- **建议**：统一改为"作为房主/作为观众/作为开发者"。

### P2-15 "已知架构 Bug"段落跨 PRD 复制且已漂移

- **证据**：PRD-29 §11 Bug2 与 PRD-04 §11 是同一 Spoiler Leak，但 PRD-04 版多出 `delayedDelivery: true` 实现要求与 2 条新增测试场景；PRD-29 Bug4 与 PRD-05 §11 同一 BGM 幽灵音，但 `duckBGM`（10% 音量）方案只在 PRD-05 有；PRD-29 Bug3 与 PRD-19 §11 重复。
- **影响**：违反自身"单一事实源"原则，后续修订必然继续分叉。
- **建议**：Bug 防御只留一份（建议归 PRD-29 §11），其余 PRD 改为引用链接。

### P2-16 PRD-19 §11 伪代码存在死循环与缓冲区泄漏

- **证据**：`onFullSnapshot` 中 `for (const p of pendingPatches) applyStatePatch(p)`，而 `applyStatePatch` 在 `base > current` 分支会再次 `pendingPatches.push(patch)`——JS 的 for...of 会遍历到循环内新 push 的元素，版本不齐时构成死循环；且成功应用的 patch 从未从缓冲区移除。
- **影响**：防御方案的示例代码本身有缺陷，照抄即事故。
- **建议**：改为先 `const queue = pendingPatches; pendingPatches = [];` 再逐个应用，并补充 `nextStateVersion` 连续性断言。

### P2-17 PRD-30 示例代码与自身 Schema 矛盾，降级策略危险

- **证据**：§5.4 `RuleResult` 声明 5 个字段（is_success/metadata/mutations/reveal_steps/cascading_state_changes）无默认值，§5.1 `CocSkillCheckHandler` 却只传 2 个——按定义运行即 TypeError；正文 §5.4 下方写"关键字段 `cascading_stateChanges`"（camelCase）与代码 snake_case 不一致，PRD-29 附录 B 又用 camelCase；标题宣称"JSON5 DSL"，示例却是严格 JSON，未展示任何 JSON5 特性；§7"Handler 不存在降级为 `auto_success`"——未知机制静默成功是规则引擎最危险的默认。
- **建议**：示例代码补全字段；统一命名；或展示 JSON5 注释/尾逗号或改称 JSON Schema；`auto_success` 降级改为 rejected + 告警。

### P2-18 其余零散问题

- PRD-29 Bug2 方案 A 要求 Player 监听 Host 事务 step 索引，与 PRD-07 §5.10"`s2c_reveal_transaction` 默认不进入 Player UI"冲突（方案 B 为 MVP 推荐，建议直接删方案 A）。
- PRD-00 §6 与 PRD-07 §5.1：room token 走 WebSocket URL query，易被代理日志记录；建议改 Sec-WebSocket-Protocol 或首条认证帧。
- README §8 实施批次：PRD-14（第二批）的主入口语音依赖 PRD-08，而 PRD-08 被排入"后续批"，批次图自相矛盾。
- PRD-16 §5.8"进入其他玩家 clues 或 party clues"二选一未决。
- PRD-13/22 文件大小上限、PRD-27 日志保留/膨胀策略均无数值。
- 多份 PRD 用户故事以"作为系统"开头（PRD-18 US-18-3、PRD-24 US-24-2、PRD-26 US-26-3、PRD-29 US-29-3、PRD-30 US-30-3），非用户角色。
- 模板元数据三种变体：PRD-00~11（来源+适用范围）、PRD-12~28（仅定位）、PRD-29/30（来源+定位）；且全部缺少 `00-产品规范` 已建立的 front matter 标准（status/version/doc_owner/effective_date/release_scope）。

## 3. 一致性问题汇总

| # | 双方 | 冲突点 |
|---|---|---|
| C1 | PRDs vs 00-产品规范/ADR-002/003/004 | PDF 起点、语音优先、Stage 依赖（见 P0-1） |
| C2 | PRD-01/09 vs PRD-25/15/开发文档 | 202 后动作状态（见 P0-2） |
| C3 | PRD-24/开发文档 vs PRD-29/权威矩阵 | AI 同步产出叙事+结算 vs 规则先于叙事（见 P0-4） |
| C4 | PRD-29 内部 | 202 之后再返 4xx/5xx（见 P1-5） |
| C5 | PRD-01/09 vs PRD-29 | 409 语义（见 P1-6） |
| C6 | PRD-08 vs PRD-15 | 语音自动提交 vs 确认窗口（见 P1-7） |
| C7 | PRD-00 vs PRD-07/02 | 事件全集与两端路由清单互不覆盖（见 P1-10） |
| C8 | PRD-22 vs PRD-29/30 | 结构化产出不包含规则资产（见 P1-11） |
| C9 | PRD-29 vs PRD-04/05/19 | Bug 防御复制漂移（见 P2-15） |
| C10 | PRD-29 方案A vs PRD-07 | Player 是否可见 Host 事务（见 P2-18） |
| C11 | README 内部 | 批次排序 vs 依赖关系（见 P2-18） |
| C12 | PRDs vs 90-归档 host/player 模块设计 | 仅各 PRD 头部"来源：Host 模块 N"暗示派生，无任何"本 PRD 取代归档模块设计"的正式声明；PRD-03 验收标准仍用"模块 3/4/5"旧称谓 |

## 4. 缺失项

1. **安全边界 PRD**：X-card、安全暂停、内容提醒、淡出（规范 M0 验收硬要求，见 P0-3）。
2. **无 Stage 纯文字路径**：宪法 M0#4 要求，全库仅 PRD-14 §10 一句"后续补"。
3. **意图类型权威枚举**（见 P1-9）。
4. **非功能需求**：无性能（回合端到端时延）、并发房间数、可用性、AI 单场成本上限——规范要求"指标先记录基线"，PRDs 连基线采集需求都未提。
5. **AI 质量指标**：PRD-24 无叙事质量、幻觉拦截率、重试成功率的度量口径。
6. **多设备同角色冲突策略**：PRD-07/19 均自述"后续定义"，但手机+平板是大概率场景。
7. **中途加入/旁观者**：PRD-12 §7 一句话带过，无事件、无权限模型。
8. **结局条件 Schema**：PRD-28"Engine 校验结局触发条件"无数据结构。
9. **STT 供应商与限额**：PRD-08 §10 自述"需后端确认"，无下文。
10. **PRDs 对归档模块设计的替代声明**（见 C12）。

## 5. 亮点

- PRD-00 事件全集 + README §7"已修正口径"表，体现了真实的协议治理与评审闭环。
- PRD-04（Watchdog/Urgent 恢复点）、PRD-19（State Version Barrier）、PRD-29（Fact Lag/Spoiler Leak 压力推演）的分布式时序防御设计，深度远超一般 PRD。
- 编号 00–30 连续无断层；README 的依赖图、角色旅程矩阵、模块覆盖矩阵、验收矩阵四张表使全库可导航。
- PRD-12（限流 5 次/分钟）、PRD-18（5 分钟/3 回合窗口）是量化验收的正面样例。

## 6. 结论与行动建议

全库骨架专业、协议意识强，但"最终版本"之名不副实：与 normative 规范的三向冲突（PDF/语音/Stage）不裁决，M0 验收必然翻车；动作状态机、语音提交、HTTP 语义三处内部矛盾不统一，前端无法动工；AI KP 三件套（24/25/26）恰是质量洼地。

**建议行动（按序）**：
1. （P0）召开一次 ADR 评审，裁决 PRDs 与 00-产品规范的冲突项，输出 ADR-009+ 并给 PRDs 补 front matter 与替代声明。
2. （P0）补齐安全边界 PRD；统一动作状态机真值表。
3. （P1）重写 PRD-24 并明确其与 PRD-29 管线的调用拓扑；修复 PRD-29 的 HTTP 时序与 409 语义；收编信封/REST/意图枚举/可见性映射进 PRD-00。
4. （P1）给 PRD-25 窗口参数、PRD-26 暴露度模型、PRD-22 规则资产产出。
5. （P2）去重 Bug 防御段落、清洗"作为 KP"称谓、修复 PRD-19 伪代码与 PRD-30 示例。
