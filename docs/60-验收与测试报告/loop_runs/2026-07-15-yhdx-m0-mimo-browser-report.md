# 《向火独行》M0 MIMO 浏览器验收报告

日期：2026-07-15  
工作树：`C:\Users\tzq12138\.codex\worktrees\7a43\CodeX-aikeeper`  
验收房间：`9054c9aa`（本地开发数据）

## 范围

本轮验证 AI KP 的最小单人主链路：邀请入房、预设角色、Session Zero、自然语言行动、MIMO 叙事、玩家地图、角色技能与装备投影。未执行战斗、结局、四人并发、弱网或完整六类黄金样本回归。

## 浏览器结果

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 进行中房间加入 | 通过，但状态文案待优化 | 新账号经过 REST/WS 预检、选择剧本预设后进入等待页，随后进入房间；顶栏仍短暂显示“等待批准”。 |
| 角色卡 | 通过 | 预设记者显示技能、SAN、MP、幸运；隔离验证角色为 HP `9/9`。 |
| 装备 | 内容缺口 | 当前记者预设的背包为空，无法完成“初始物品”验收。 |
| 自然语言行动 | 通过 | “登上长途车并观察乘客”先生成中风险移动预览，再确认入队、规则校验并完成。 |
| MIMO 运行时 | 通过 | `narrate_action` 成功调用活动动态配置 `mimo` / `mimo-v2.5` / `chat_completions`，耗时 11078ms。未记录或展示 Key、请求体或上游原始响应。 |
| 叙事结构 | 后端通过，前端已补显示 | 已完成行动的安全结构含 1 条环境变化、1 个交互对象和开放问题；玩家端此前仅展示正文，本轮已补为叙事卡片映射。 |
| 地图素材 | 通过 | 玩家地图实际渲染底图 `1452×1816`，含当前位置与迷雾；移动仍提示使用自然语言行动。 |
| 地图保密 | 通过 | 玩家地图不再返回独行原始条目全文、条目号或目标节点；仅显示公开地点名和安全行动引导。 |

## 本轮修复

1. MIMO 缺少字段级 citation 时，叙事网关从已验证上下文补齐安全字段，避免行动在状态已变更后转入 Host 异常队列。
2. 发布 CoC7 基础规则时回填已发布剧本的规则绑定，避免“暂无可用剧本”的发布顺序问题。
3. 文字地图不再将独行原始节点全文作为地图描述返回。
4. 地图底图只有在资产显式公开或已确认绑定到 `map/map` 时才投影和下载；已确认底图可在玩家端真实渲染。
5. `s2c_narration_completed` 现在把环境变化、可交互对象和开放问题追加为玩家可见叙事卡片。

## 未通过 / 待决定

1. **进行中加入的地图位置**：新加入角色尚未获得当前位置时会看到“已知区域”的空地图。应在 Host 放行时继承队伍当前位置，或投影队伍当前已知地图。
2. **入房状态文案**：玩家已进入房间后顶栏可能仍显示“等待批准”，需要统一审批/已入房状态。
3. **记者初始物品**：当前《向火独行》预设没有可验证的起始背包内容；应由剧本编译包补齐并绑定到角色模板。
4. **主持质感**：功能链路和证据边界已成立，但仍需以多轮调查、战斗和结局的真实回合评估 MIMO 的叙事质量，不能仅凭一次行动判定“像人类 KP”。
5. **后端全量**：`python -m pytest tests/server -q` 收集 849 项，但在 244 秒和 604 秒两次超时，未产生失败栈；本报告不将其记为通过。

## 自动化验证

```text
python -m pytest tests/server/test_ai_gateway.py tests/server/test_rag_router.py \
  tests/server/test_solo_adventure_runtime.py tests/server/test_configured_openai_provider.py -q
# 47 passed

cd src/client && npm run test -- --run
# 16 files, 55 passed

cd src/client && npm run build
# passed

git diff --check
# passed
```

## 本地数据说明

为了在本地开发环境验证已发布剧本门禁，本轮使用了一份受限 CoC7 测试规则资料作为 `host_only` 本地 fixture，并绑定到《向火独行》发布版本。该 fixture 仅用于本地测试，不构成生产授权或规则内容发布。

## 追加验收：自然语言规则链

验收房间：`c978e2f8`（本地专用浏览器验收房间；曾回到理智检定 checkpoint 重跑，不改剧本原件）。活动生成供应商为已测试通过的 `mimo` 配置；本节不记录 URL、Key 或请求正文。

| 场景 | 浏览器结果 | 结算证据 |
| --- | --- | --- |
| 夜间追踪黑影 | 通过 | 玩家用“沿脚印和泥迹追踪”描述行动，预览识别为 `追踪` 检定；实际卡片显示目标值 `36`、`d100 31`、常规成功，并进入成功场景。 |
| 悬崖异象理智 | 通过 | 玩家用自然语言压下恐惧并返回，预览识别为 `理智` 检定；实际卡片显示目标值 `50`、`d100 18`、常规成功，并进入返回场景。失败路径由自动化验证为扣 `1d2` SAN、回执记录状态前后值、仍推进唯一后续节点。 |
| NPC 交涉与休息 | 通过 | 向露丝致意并回房的自然语言行动，按确认链进入梦境与晨间场景；未展示条目号或隐藏出口。 |
| 条件分支 | 通过 | 玩家表达“利用昨夜线索继续勘查”，Director 选择已通过检定允许的调查分支，玩家界面仅显示自然语言理解。 |
| 悬崖侦查 | 通过 | 原文中的“转\\n到”和“否则转\\n到”断行已被规则解析器识别；浏览器预览显示 `侦查` 检定，实际失败卡显示目标值 `65`、`d100 93`、失败，并进入失败场景。 |

### 本次修复

1. 单人规则解析支持带引号的命名技能检定，以及“成功了/失败了”和“否则”两种分支句式。
2. 单人规则解析允许原 PDF 将“转到”拆成跨行的“转\\n到”。
3. 单人剧本的理智检定编译为现有 `sanity_check`：成功损失 `0`、失败损失由证据中的骰式确定；状态变更走 `StateService`，回执记录权威前后状态。
4. `CocSanityCheckHandler` 现在输出与技能检定一致的技能、目标值、难度和成功等级，玩家判定卡不再显示“无需技能”。
5. 为导入残留“七宫”补充玩家投影、验证叙事和本地单人转场三条清洗覆盖；最后一条已通过自动化回归，需在下一次新转场浏览器回合复验。

### 验证

```text
python -m pytest tests/server/test_solo_adventure_runtime.py \
  tests/server/test_rules.py tests/server/test_narrator_runtime.py -q
# 74 passed

git diff --check
# passed; only existing working-tree CRLF warnings
```

### 仍未覆盖

- 本轮尚未完成《向火独行》单人结局，也未在浏览器跑到战斗/追逐场景。
- “七宫”本地转场清洗已覆盖自动化测试；因最后一次修复后未继续产生新转场，尚未做最终浏览器复验。

## 追加修复：合法时间推进不再升级 Host

### 复现

在烬头村自由调查结束后，玩家输入“回梅的家、推进时间、等待下午或线索”。活动供应商正确识别出合法的剧情目标，但因没有在响应中附 citation、置信度为 `0.75`，本地验证器将草稿误送为 `awaiting_host_exception`。这属于正常可见移动，不应消耗 Host 的异常处理权。

### 修复与回归

1. 保持本地对“当前节点 -> 已存在目标节点”的边校验与 citation 回填不变。
2. 对供应商未附 citation、但已选择合法边且具备有效解释的多分支行动，将自动接纳阈值从 `0.80` 调整为 `0.70`；玩家看到的仍是本地权威 citation。
3. 新增 `0.75` 置信度的多分支时间推进回归测试。

### 浏览器验证

1. 旧异常行动由 Host 明确拒绝，仅用于清理修复前已创建的记录。
2. 使用相同玩家原文重新生成预览：页面显示“行动确认”和“依据已校验”，没有进入异常队列。
3. 玩家确认后，行动完成并进入“一上午的辛劳让你饥肠辘辘”的后续场景；无 Host 审批、无条目号泄露。

```text
python -m pytest tests/server/test_director_runtime.py \
  tests/server/test_solo_adventure_runtime.py -q
# 50 passed
```

## 追加修复：黑熊敌方回合与玩家反应（2026-07-16）

此前 P0 缺口是：玩家攻击黑熊后，敌方不会继续行动，导致单人战斗不能闭环。本次采用独立的、可恢复的反应记录，而不是让 AI 或前端直接扣血。

### 实现

1. 新增 `encounter_pending_reactions`：记录房间、遭遇、来源行动、轮次、攻击序号、攻击名称、玩家选择和不可篡改的结算结果；同一角色/轮次/攻击序号唯一。
2. 玩家战斗行动无论命中与否均会消耗本轮行动；存活黑熊会依序创建本轮的爪击/啃咬反应，刷新后可从 `GET /api/player/encounter-reactions/pending` 恢复。
3. 玩家通过 `POST /api/player/encounter-reactions/{reaction_id}/resolve` 选择“闪避”或“反击”；双方判定、伤害骰和 HMAC 校验回执均在服务器生成。
4. 玩家 HP 同时更新 encounter 参与者和 `StateService` 权威角色状态；重复提交已结算 reaction 不会再次扣血。
5. 剧本证据中的黑熊使用爪击 `35%` / `2D6`、啃咬 `25%` / `1D8`，厚皮每轮吸收前 `3` 点伤害；第一、三轮各两次爪击，第二轮为爪击加啃咬。三轮结束、任一方倒下均会结束 encounter，后续剧本分支仍由已发布剧本的自然语言行动链推进。
6. 玩家页收到 WebSocket 事件或刷新后会展示“黑熊第 N 轮·攻击名”卡片；在选择闪避/反击前，普通行动输入被阻止。

### 验证

```text
python -m pytest tests/server/test_kp_mcp_config.py \
  tests/server/test_kp_mcp_brain.py tests/server/test_ai_providers.py \
  tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py \
  tests/server/test_solo_adventure_runtime.py -q
# 109 passed, 4 个既有 Pydantic citation 序列化 warning

cd src/client && npm run test -- tests/player-api.test.ts
# 6 passed

cd src/client && npm run build
# passed

git diff --check
# passed；仅既有工作树 CRLF warning
```

### 真实浏览器验收（2026-07-16）

使用隔离房间 `m0-bear-browser-20260716` 和独立前端端口完成，不修改用户正在体验的房间或身份。活动生成供应商为已测试通过的 `mimo` 配置；本节不记录 URL、Key 或上游请求正文。

| 场景 | 结果 | 浏览器证据 |
| --- | --- | --- |
| 自然语言攻击 | 通过 | 输入“我拔出小刀，正面攻击黑熊。”后出现高风险确认卡，显示 `格斗（斗殴）`、常规难度、95% 置信度与“依据已校验”，不再进入 Host 异常队列。 |
| 单人回合调度 | 通过 | 进行中房间角色状态为 `ready` 时，唯一玩家确认动作后从 `queued → resolving → completed`，不再永久排队。 |
| MIMO 叙事 | 通过 | 已完成动作记录 `provider_source=configured_provider`；玩家流展示经过事实校验的叙事、环境变化、可交互对象和开放问题。 |
| 判定卡 | 通过 | 角色卡使用 `格斗（斗殴）=75`；浏览器卡片显示目标值 `75`、`d100 88` 与失败等级。 |
| 黑熊反应 | 通过 | 战斗结算后显示“黑熊第 1 轮·爪击”；两次点击“闪避”均由服务器结算，分别记录闪开与伤害，第一轮结束后可再次发起攻击。 |
| 反应投影 | 通过 | WebSocket 与刷新接口统一使用玩家安全的驼峰字段投影，轮次与招式名称不再空白。 |

本轮继续到第二轮攻击时，真实供应商链在叙事阶段超过预期时间并使该隔离动作停留在 `resolving`。已在运行时将整次 Narrator 调用限制为 `30` 秒；超时后会转为 `narrator_timeout`、进入可恢复异常状态并向玩家发送恢复事件。该保护已由自动化回归验证。完整三轮结局（节点 `201` 或 `193`）仍需在供应商稳定窗口内单独验收，不能在本报告中标记为已完成。

```text
python -m pytest tests/server/test_kp_mcp_config.py \
  tests/server/test_kp_mcp_brain.py tests/server/test_ai_providers.py \
  tests/server/test_director_runtime.py tests/server/test_narrator_runtime.py \
  tests/server/test_solo_adventure_runtime.py tests/server/test_turn_manager.py -q
# 115 passed, 4 个既有 Pydantic citation 序列化 warning

cd src/client && npm run test -- tests/player-api.test.ts
# 6 passed

cd src/client && npm run build
# passed
```

## 追加：MIMO 配置加密恢复（2026-07-16）

### 根因与处理

1. 数据库中的 `mimo` 配置始终存在且为活动项；此前“看似没有保存”的判断来自一次错误的只读查询列名，不能作为配置丢失的证据。
2. 该配置创建时没有 `AI_CONFIG_MASTER_KEY` 或 `JWT_SECRET`，旧代码会退回到公开的开发默认字符串派生密钥。Windows 用户级 `MIMO_API_KEY` 与 `MIMO_MODEL` 也不会自动注入已运行的后端进程。
3. 本轮仅在缺失时生成用户级 `AI_CONFIG_MASTER_KEY`，并将 `secret_cipher_from_env` 改为没有主密钥时明确拒绝配置读写；保留 `AI_CONFIG_MASTER_KEY → JWT_SECRET` 的既定优先级。
4. 使用用户级 MIMO Key 重新加密原活动配置，保持既有专用端点、`chat_completions` 协议和 `mimo-v2.5` 模型不变。真实连接测试通过后重新激活；审计链只有 `update → test → activate`，不含 Key、密文、请求正文或上游原始响应。
5. 后端已重启并显式继承用户级主密钥、MIMO 和 DeepSeek 环境变量。运行时选择顺序已验证为 `configured:MIMO → MCP → DeepSeek → local`，活动配置声明文本和图片能力。

### 安全与自动化证据

| 项目 | 结果 | 证据类型 |
| --- | --- | --- |
| 无主密钥时拒绝加密配置 | 通过 | 新增单元回归；不再使用公开默认主密钥。 |
| API Key 重加密 | 通过 | 数据库仅保存密文，查询未发现明文标记。 |
| MIMO 文本/图片连接测试 | 通过 | 配置测试状态为 `passed`，活动状态保持为真。 |
| 运行时主提供方选择 | 通过 | 隔离进程中 `AiGateway` 解析为 `configured → mcp → deepseek → local`。 |
| 浏览器完整单人通关 | 待验收 | 仍需在新的隔离房中以真实浏览器完成自然语言主链。 |

```text
python -m pytest tests/server/test_ai_provider_config.py \
  tests/server/test_admin_ai_provider_routes.py -q
# 27 passed

python -m pytest tests/server/test_solo_adventure_runtime.py \
  tests/server/test_narrator_runtime.py tests/server/test_turn_manager.py -q
# 76 passed
```

本节的数据库与提供方验证不替代浏览器证据；下一轮浏览器验收需重新覆盖开局、调查、理智、黑熊三轮、固定恢复/伤害、结局和刷新恢复。

## 追加：正式剧本模板与隔离单人房准备（2026-07-16）

为避免此前浏览器验收房和用户正在使用的房间互相影响，本轮通过正式 API 创建了新的隔离单人房 `5d8bd952`，绑定已发布的《向火独行》快照，而非测试替身剧本。

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 剧本推荐角色 | 通过 | 发布版本具有 `yhdx-reporter-v1`（查尔斯·钱伯斯 / 记者）模板；玩家加入页支持“剧本预设”来源。 |
| 初始物品 | 通过 | 模板背包实际写入 5 件：旅行箱、宽檐帽、录用通知、记者证、笔记本与铅笔。 |
| 房间开局 | 通过 | 隔离角色已准备并启动为 `active`，首回合为 1，当前公开开局场景为汽车站与长途车。 |
| 全局 XLSX 预设目录 | 未配置但非阻断 | 当前全局预设目录为空；玩家页面同时渲染剧本模板，因此《向火独行》可直接从“剧本预设”开局。 |
| 浏览器提交 | 待确认 | 浏览器已在该房间的加入页且已登录隔离测试玩家；尚未点击“确认并进入”，不会把未授权的加入操作写成完成。 |

后续浏览器验收会从该页选择记者模板，再依次记录自然语言调查、判定、理智、黑熊三轮、固定恢复/伤害、结局与刷新恢复；每项都将附浏览器或事件证据。

## 追加：正式单人完整通关（2026-07-16）

验收房间：`solo-e2e-mimo-8da9594a`（全新隔离房；未改写用户房间、既有行动或骰点）。玩家通过正常浏览器登录、选择《向火独行》记者预设、准备和入场；Host 仅对该隔离房执行开局操作。

### 结论

**通过。** 玩家从长途车开局以自然语言完成调查、移动、物品获取、技能检定、被捕、灯塔仪式、火焰伤害和逃生；最终到达剧本终局 `solo:185`。数据库权威状态为：房间 `completed`、状态版本 `66`、场景版本 `63`、已访问场景 `61`、完成行动 `63`。其中一条修复前已产生的错误异常行动被明确拒绝，未影响最终状态。

### 浏览器主链证据

| 环节 | 结果 | 玩家自然语言与运行时结果 |
| --- | --- | --- |
| 开局与角色 | 通过 | 记者预设以 `HP 9/9`、`SAN 50/50` 开局；长途车、车票、行李等开局行动均经“预览 → 确认 → 结算”进入下一场景。 |
| 自然语义移动 | 通过 | “沿着街道和山路寻找失踪的长途车”被本地可见单一目标规则直接映射到合法剧情边，无需 Host 澄清。 |
| 物品与调查 | 通过 | 玩家购买狩猎小刀、调查杂货店、灯塔、工坊和卧室；卧室侦查成功后可见地窖线索，玩家选择不越权进入并安全回到自由调查。 |
| 条件门槛 | 通过 | 在工坊、灯塔与卧室三处调查后，玩家说“已经试过三个调查地点”，运行时正确进入监视/追捕剧情，而非泄露条目或要求 Host 解释。 |
| 技能与规则 | 通过 | 行程中实际结算敏捷、汽车驾驶、侦查和外貌检定；灯塔火场依次结算火焰伤害、力量检定、再次火焰伤害，未预设或篡改骰点。 |
| 异常分支恢复 | 通过 | “告别梅，出门寻找长途车”此前因可选的“昨夜勘查”条件被误送 Host；修复后同一自然语言行为稳定选择“否则”分支并继续。 |
| 终局与逃生 | 通过 | 玩家在烟雾中挣断锁链、跃下灯塔、骑自行车出村；最终动作“立即骑上自行车沿南边道路离开烬头村”完成后，权威场景为 `solo:185`，房间变为 `completed`。 |

### 本轮运行时修复

1. 对当前场景只有一个安全可见目标的低风险行动，优先使用本地语义映射，避免供应商兜底返回无意义的澄清。
2. 对“若昨夜检定成功则可勘查，否则前往下一处”的可选回溯条件，玩家明确离开时稳定选择“否则”分支，不进入 Host 异常队列。
3. 终局本地叙事不再显示“当前场景仍可互动”或继续追问；改为“本次冒险已结束”，并将侧栏提示为只读的“本次冒险记录”。

### 限制与后续

- 这次完整通关的独行剧情采用证据约束的本地叙事兜底；运行记录中该链路的 `provider_source` 为 `local_fallback`，因此本节不能作为 MIMO 叙事质量验收。MIMO 配置连通与其他隔离浏览器回合已在前文记录。
- 终局动作发生在终局投影修复前，浏览器留存画面仍显示旧的通用“开放问题”；新终局文本由新增回归测试验证，下一次新房完整通关时应补一张真实终局截图。
- 本次路线未经过黑熊战斗节点；黑熊三轮反应的独立浏览器验收见上文，仍需在供应商稳定窗口内补一条“战斗节点 → 剧情后续 → 结局”的连贯通关路线。

### 本节验证

```text
python -m pytest tests/server/test_narrator_runtime.py::test_verified_solo_ending_narration_marks_adventure_complete \
  tests/server/test_narrator_runtime.py::test_solo_transition_exposes_a_safe_visible_change_without_node_number \
  tests/server/test_narrator_runtime.py::test_verified_solo_transition_narration_uses_visible_scene_question -q
# 3 passed
```

### 最终回归（本节）

```text
python -m pytest tests/server/test_solo_adventure_runtime.py tests/server/test_narrator_runtime.py -q
# 98 passed

python -m pytest tests/server/test_director_runtime.py -q
# 26 passed, 4 个既有 Pydantic citation 序列化 warning

python -m pytest tests/server/test_action_drafts_v2.py -q
# 30 passed

cd src/client && npm run build
# passed

git diff --check
# passed
```

前端全量 Vitest 本次为 `61 passed, 1 failed`：`tests/campaign-home-panel.test.tsx` 仍断言“1 个可选方向”，但当前 `CampaignHomePanel` 实际只显示场景、citation 和“继续当前场景”。该组件不属于本轮终局/单人行动改动，未擅自修改；应在独立回流界面任务中决定恢复方向计数或更新断言。一次合并的后端四文件回归在 124 秒内没有返回结果，已改用上述模块化命令完成验证；未将该合并命令标记为通过。

## 追加：MIMO 主叙事与最小 MCP 闭环（2026-07-16）

### 修复

此前独行剧本的每次场景跳转都会直接使用 `build_verified_narration`，即使活动 AI 配置已经是 `mimo`，也不会调用动态提供方。因此“完整通关”只能验证规则与剧情状态，不能验证真实 MIMO 叙事。

现在独行跳转与普通行动一样先调用 `AiGateway.narrate_action`：通过事实与 citation 校验时采用提供方叙事；超时、异常、非对象响应或事实校验失败时，才退回可验证的本地叙事，并记录拒绝原因。规则和房间状态仍只由确定性执行器写入。

同时修复 `KpMcpClient.close()` 未关闭 `AsyncExitStack` 的资源泄漏；真实 MCP 健康检查进程退出时不再出现 AnyIO cancel-scope 异常。

### 隔离浏览器验收

验收房间：`dd94b98e`；独立前后端端口：`5188 → 3002`。通过浏览器创建临时 Host 与 Player、选择已发布《向火独行》、选择记者预设、准备、开局，并提交自然语言行动：

> 我提着行李箱登上灰色长途车，继续前往阿卡姆。

浏览器先显示 `awaiting_confirmation` 预览（中风险、无需技能、公开、90% 置信度、依据已校验），确认后依次经历 `queued → narrating → completed`，并进入长途车后的下一场景。该行动的权威结果元数据为：

```text
metadata.narration.provider_source = configured_provider
metadata.solo_adventure_transition = 1 → 263
```

活动配置元数据为 `mimo / chat_completions / mimo-v2.5 / supports_image=true / test_status=passed / is_active=true`。报告不记录 Base URL、API Key、密文或上游完整请求；`configured_provider` 与活动配置共同证明本动作使用的是 MIMO 动态配置，而非本地兜底。

### 最小 MCP 验收

本地 MCP 进程健康返回 `status=ok`、`provider=deepseek`、`model=deepseek-v4-pro`。服务仅公开以下四个工具：

```text
kp_structure_scenario
kp_analyze_director_action
kp_narrate_action
kp_health_check
```

运行时生成顺序为 `configured(MIMO) → MCP(DeepSeek) → DeepSeek 环境配置 → local`。MIMO 为活动主链；MCP 保持可用的兼容/故障回退，不获得房间权威写入权限。

### 本节验证

```text
$env:TEST_DATABASE_URL='postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test_mimo_runtime'
python -m pytest tests/server/test_narrator_runtime.py -q
# 23 passed

python -m pytest tests/server/test_kp_mcp_client.py \
  tests/server/test_kp_mcp_config.py tests/server/test_kp_mcp_brain.py \
  tests/server/test_ai_providers.py tests/server/test_solo_adventure_runtime.py \
  tests/server/test_director_runtime.py tests/server/test_action_drafts_v2.py -q
# 156 passed, 4 个既有 Pydantic citation 序列化 warning

cd src/client && npm run build
# passed
```

前端全量 Vitest 仍为 `61 passed, 1 failed`，失败项仍是上一节记录的 `campaign-home-panel` 旧方向计数断言；不影响本节真实浏览器的预览、确认、MIMO 叙事与场景推进。
