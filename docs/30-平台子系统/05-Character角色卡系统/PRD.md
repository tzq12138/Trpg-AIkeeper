# Character 角色卡系统 PRD 初版

## 目标

Character v1 的目标是让玩家能在房间中稳定拥有一个可验证、可恢复、可参与规则检定的调查员，并让角色的公开摘要、技能值、HP/SAN/MP/Luck、ready 状态和运行态变化被 Room、Rule、State、Projection 正确消费。

成功标准是：玩家入房并绑定角色后，Host 能看到公开摘要，玩家能查看自己的完整角色页，ready 后可开局，提交技能检定时后端读取权威角色数据，状态变化后 Host 与玩家视图最终一致。

当前阶段说明：

- 本 PRD 已可进入工程执行，但当前阶段仍是“P0 主链路 + 角色数据权威风险识别版”。
- 文档已经识别 `xlsx_data` 与 `character_runtime_state` 数据源漂移、技能值权威来源、角色状态枚举漂移、私密背景/RAG 裁剪、`restore-session` token 风险、运行态初始化失败、DTO 分层不足等问题，但不代表这些风险已在代码里全部关闭。
- 本文优先锁定 Character 的边界、数据分层、接口方向和验收口径，不把生产硬化写成既成事实。

## 产品边界

包含：

- 玩家在房间中创建或选择角色。
- XLSX 预览、XLSX 导入、预设卡、剧本模板、前端建卡器、复制已有角色。
- 角色与 `player_token`、账号、房间的绑定。
- 大厅公开摘要、ready、进行中加入审批。
- 静态角色卡到运行态的初始化。
- 玩家角色页、Host 公共状态、技能检定所需角色数据。
- 角色数据进入 AI 上下文前的可见范围边界。

不包含：

- 完整多规则角色生态。
- 商业化角色模板市场。
- 角色头像、立绘、素材管理。
- 完整成长、升级、死亡、长期档案玩法。
- Clue/Inventory 的归属细节；Character 只引用摘要。
- AI 直接生成并写入角色状态。

## 数据分层

| 层 | 权威来源 | 作用 |
|---|---|---|
| 身份绑定 | `characters.character_id / room_id / player_token / account_id` | 确定角色归属、恢复和房间内身份 |
| 成员状态 | `characters.status / is_ready` | Room Lobby、审批、ready、开局校验 |
| 静态角色卡 | `characters.xlsx_data` | 初始属性、技能、背景、职业、导入快照 |
| 运行态 | `character_runtime_state` | 当前 HP/SAN/MP/Luck、状态标签、临时修正、版本 |
| 长期档案 | `character_profiles` | 跨房长期角色沉淀与成长，P2 以后再做产品闭环 |
| 公开摘要 | Character DTO 派生 | Lobby、Host HUD、Projection 公共展示 |
| 规则快照 | Character + Runtime 派生 | Rule 读取技能、属性、当前修正 |
| AI 上下文 | 裁剪后的 DTO | AI 只能读取授权字段 |

Character 后续实现必须围绕这八层分工，避免把身份、静态卡、运行态、公开摘要和 AI 上下文揉成一团。

## 角色与权限

| 角色 | 权限 |
|---|---|
| Player | 创建、导入、选择、查看自己的角色；提交 ready 和角色相关意图 |
| Host | 查看公开摘要、审批进行中加入、查看公共战局状态 |
| Admin | 后台修正异常角色、统计与封禁，不参与普通跑团裁决 |
| Engine/StateService | 按规则和事务结果写入角色运行态 |
| AI-Keeper | 读取裁剪后的角色上下文，给出裁决建议或叙事建议 |
| Observer | 未来只读公开摘要和公共演出，不看私密字段 |

## 数据模型

| 表 | 作用 | 当前口径 |
|---|---|---|
| `characters` | 房间内角色身份、玩家名、token、静态角色卡、ready、成员状态 | 主表；`xlsx_data` 是静态快照 |
| `character_runtime_state` | 当前 HP/SAN/MP/Luck、状态标签、临时修正、版本 | 战局可变状态权威来源 |
| `character_templates` | 剧本预设角色模板 | 可被入房流程读取，管理入口另属 Module/Scenario |
| `character_profiles` | 账号长期角色档案 | 已有 schema 和初始化写入，产品闭环还未完整 |

角色成员状态使用 `joined/pending_approval/left`。历史兼容值 `active` 仍可能出现在查询和默认值中，DeepSeek 后续需要收敛，不应继续扩大使用。

`is_ready` 是大厅准备状态，不是角色生命周期状态。

后续状态收敛要求：

- 新写入只允许 `joined / pending_approval / left`
- `active` 仅作为 legacy read compatibility 存在，不应继续扩大使用

## 主要流程

### 入房建卡

1. 玩家输入房间号和玩家名。
2. 玩家选择一种角色来源：预设卡、XLSX 上传、剧本模板、前端建卡器、复制已有角色。
3. 后端校验房间、来源数量、账号所有权或 token 所有权。
4. 后端解析并写入 `characters.xlsx_data`，生成 `character_id` 和 `player_token`。
5. 房间为 `draft/lobby` 时角色状态为 `joined`；房间为 `active` 时状态为 `pending_approval`。
6. 后端尝试初始化 `character_runtime_state`，并广播 `s2c_room_lobby_snapshot`。

### 大厅与开局

1. 大厅只展示玩家名、调查员名、职业、ready、成员状态。
2. 玩家通过 `ready_toggle` 切换准备状态。
3. Room 开局只读取已加入且未离开的角色；force start 是 Room 层急救能力。
4. 开局后角色继续通过 player token 参与回合和意图链路。

### 进行中加入

1. 活跃房间新加入角色进入 `pending_approval`。
2. Host 调用 approve 后角色变 `joined`。
3. Host 调用 reject 后角色变 `left`。
4. 未批准角色不应进入正常回合结算和公共投影。

### 状态变化

1. 导入或创建时的 HP/SAN/MP/Luck 写入静态卡。
2. StateService 初始化运行态。
3. 后续战局变化写入 `character_runtime_state` 并产生状态 patch 事件。
4. Host HUD 已优先读取运行态。
5. 玩家 `/api/player/character` 和 `/api/player/sync` 需要合并运行态，避免玩家页显示旧值。

若运行态初始化失败，后续最小处理要求应为：

1. 入房主链路允许继续
2. 写结构化 warning event 或 error log
3. 玩家 `/character` 或 `/sync` 读取时可懒初始化
4. 懒初始化失败时返回明确 degraded 状态
5. 不得让 Host HUD 与 Player 页长期无提示地读取不同来源

## 接口方向

| 接口 | 作用 | 权限 |
|---|---|---|
| `GET /api/player/rooms/{room_id}/join-info` | 获取入房页所需房间、模板、预设、玩家摘要 | 公开房间信息，不能含私密字段 |
| `GET /api/player/character/presets` | 获取可选预设卡并标记房间占用 | 公开预设摘要 |
| `POST /api/player/character/preview-xlsx` | 预览上传卡，不创建角色 | 无落库 |
| `POST /api/player/rooms/{room_id}/join-with-character` | 创建并绑定角色 | 可带账号 token；复制角色需所有权 |
| `POST /api/player/character/import-xlsx` | 旧流程中为已有 token 导入角色卡 | `X-Room-Token` |
| `GET /api/player/character` | 当前玩家角色页 DTO | `X-Room-Token` |
| `GET /api/player/sync` | 当前玩家同步包 | `X-Room-Token` |
| `GET /api/player/me/characters` | 当前账号拥有的角色列表 | Bearer account token |
| `POST /api/player/characters/{character_id}/restore-session` | 恢复本账号角色的 player token | Bearer account token |
| `POST /api/host/{room_id}/approve/{character_id}` | 批准进行中加入 | Host owner/admin |
| `POST /api/host/{room_id}/reject/{character_id}` | 拒绝进行中加入 | Host owner/admin |
| `POST /api/player/intent` | ready、技能检定和其他行动入口 | `X-Room-Token` |
| `POST /api/player/skill-check` | 技能检定兜底接口 | `X-Room-Token` |
| `GET /api/host/{room_id}/hud` | Host 公共战局状态 | Host owner/admin |

其中 `POST /api/player/skill-check` 口径必须与 04-Rule 对齐：

- 只作为 debug/兼容/降级入口
- 不进入正式 action lifecycle
- 不写状态
- 不触发事务
- 不应被前端静默替代正式 intent
- `skill_value` 不得作为正式权威值

## 权限与隐私边界

- `player_token` 只能定位一个玩家角色，不能被列表接口、日志、导出明文暴露。
- `account_id` 只用于账号恢复、复制和长期档案归属，不能替代房间内 player token。
- 大厅和 Host 公共状态只展示公开摘要与战局状态。
- 背景、信念、恐惧、秘密、欲望等字段进入 AI 上下文前必须按 DTO 和 visibility 裁剪，不能原样喂给 RAG。
- 进行中加入的 `pending_approval` 角色在批准前不能参与行动结算。
- 前端传入的技能值不是权威值；后端必须能从角色卡或运行态读取技能。
- `restore-session` 若直接返回原 `player_token`，当前也只能视为兼容路径，不是最终安全方案；正式方向应是短期恢复票据、rotate 或设备绑定。

## DTO 分层方向

后续至少拆出以下 DTO：

- `PublicCharacterSummaryDTO`
- `LobbyCharacterDTO`
- `SelfCharacterDTO`
- `HostCharacterDTO`
- `RuleCharacterSnapshotDTO`
- `AICharacterContextDTO`
- `AdminCharacterDTO`

最小字段边界建议：

| DTO | 可含字段 | 禁止字段 |
|---|---|---|
| `PublicCharacterSummaryDTO` | 玩家名、调查员名、职业、公开状态 | `player_token`、完整 `xlsx_data`、私密背景 |
| `LobbyCharacterDTO` | 公开摘要 + 状态 + ready | 技能全量、秘密、私密笔记 |
| `SelfCharacterDTO` | 本人完整角色卡 + 本人运行态 | 其他玩家私密字段 |
| `HostCharacterDTO` | 公共战局状态、HP/SAN/MP/Luck、状态标签 | 未授权秘密、私人背景全文 |
| `RuleCharacterSnapshotDTO` | 技能、属性、运行态、临时修正 | `player_token`、`account_id` |
| `AICharacterContextDTO` | 裁剪后的公开/本人/Host 授权字段 | 未授权秘密、未发现线索、其他玩家私密字段 |
| `AdminCharacterDTO` | 排错、归属、审计字段 | 不进入普通跑团接口 |

## 字段可见性方向

最小 visibility 契约建议先锁为：

- `public`
- `party`
- `self`
- `host`
- `keeperOnly`
- `private`
- `neverExport`

建议默认分级：

| 字段 | 默认可见性 |
|---|---|
| 调查员姓名、职业 | `public` |
| 年龄、性别 | `public` 或 `party` |
| 当前 HP/SAN/MP/Luck | `party` 或 `host+self`，后续再交 Room/Rule/Projection 配置 |
| 技能列表 | `self`，Host 仅在授权或规则需要时读取 |
| 背景故事、重要人物 | `self` |
| 恐惧、秘密、欲望、私密笔记 | `self` 或 `keeperOnly` |
| 个人目标 | `self/host` |
| `player_token` | `neverExport` |
| `account_id` | 后台可见，不进入普通 DTO |

## RAG / AI 上下文边界

Character 加入、导入或更新时，不得把完整 `xlsx_data` 原样索引进 player-facing RAG。

后续最小要求：

1. 索引前先构建 `AICharacterContextDTO`
2. 写入索引时附带 `visibility / audience / discovered_state` metadata
3. player-facing search 必须再经过可见性过滤
4. 其他玩家不能通过 AI 检索链路读到本角色的私密背景、秘密、恐惧、欲望、私人目标

## 验收标准

- 上传合法 XLSX 能预览，预览不创建角色。
- 上传损坏 XLSX 返回 400，数据库不产生占位角色。
- 玩家通过 `join-with-character` 入房后能获取自己的 `/api/player/character`。
- 预设卡在同一房间被选择后再次选择返回 409。
- 活跃房间入房角色为 `pending_approval`，Host approve 后才能成为 `joined`。
- StateService 修改 HP/SAN/MP/Luck 后，Host HUD 与玩家角色页最终读取同一运行态。
- 玩家不能通过别人的 `character_id` 恢复 session 或复制角色。
- 技能检定不能信任前端提交的任意 `skill_value` 作为最终权威。
- 大厅快照、公开 DTO、普通日志不包含完整 `xlsx_data`、`player_token`、私密背景。

## 当前风险

- 玩家角色页仍主要读取 `xlsx_data`，而 Host HUD 已读取运行态，双方可能显示不同 HP/SAN/MP。
- `/api/player/skill-check` 兜底接口信任请求中的 `skill_value`，需要限制为兼容路径或改成服务端取值。
- `characters.status` 存在 `active` 与 `joined/pending_approval/left` 的口径漂移。
- 多个前端角色页面存在历史编码乱码，影响真实验收。
- 角色 RAG 索引若原样吞入完整 `xlsx_data`，会把私密背景和未公开信息暴露给 AI 检索链路。
- `character_profiles` 已写入但长期角色产品闭环不足，不能被误认为已完成。
