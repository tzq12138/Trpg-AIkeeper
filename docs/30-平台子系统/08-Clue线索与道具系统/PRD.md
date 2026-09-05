# Clue 线索与道具系统 PRD V2.1

## 背景

在 AI-Keeper 里，线索和道具不是普通列表，而是玩家推理、行动声明、AI 上下文和战役复盘的证据。系统必须区分：

- 剧本里可能存在的线索模板
- 玩家已经发现的私密证据
- 玩家主动分享给队伍的公共版本
- 道具和 Luck 等运行态资源变化
- 事件日志、Archive、Export、AI 上下文中的可见边界

当前代码已经有线索列表、线索分享、背包列表、目标列表、追溯道具主张和玩家归档雏形，但证据链还没有闭环：分享默认公开原文，`clues.is_private` 语义过重，StateService 分享路径缺 `public_version`，AI 工具可直接插入线索，追溯道具直接修改 `xlsx_data.luck`，public export 仍按 `clues.text` 导出，Archive 没有 clue 专属事件契约。

## 当前阶段说明

- 当前是 `P0 主链路 + 证据链安全风险识别版`。
- 文档完成不等于代码风险关闭。
- 本轮目标是把 `发现 -> 私密保存 -> 分享公共版本 -> 事件沉淀 -> AI 可见过滤 -> 归档可查` 这条主链路定义清楚，并把 Inventory / Objective 与 Character / State / Transaction 的边界收紧。

## 产品目标

1. 玩家能安全查看自己的线索、背包和目标。
2. 玩家可以分享线索，但队友只看到公共版本。
3. 线索和道具变化能追溯来源、时间、分享动作和事件序列。
4. AI 只能读取允许的玩家证据，不能直接读取 WorldBook 未发现线索或真相。
5. 工程实现后，Clue 可以作为 Journal、Archive、Projection、Safety、RAG 的稳定上游。

## 非目标

- 本轮不做完整线索墙 UI。
- 本轮不做复杂交易系统、队伍公共仓库、背包拖拽 UI。
- 本轮不做完整复盘展示页，只定义证据链数据契约。
- 本轮不让玩家自由创造具有效果的世界状态。
- 本轮不把 WorldBook 未发现线索直接复制到玩家线索表。

## 用户角色

| 角色 | 可做 | 不可做 |
|---|---|---|
| Player | 查看自己线索/背包/目标，分享自己线索，发起道具使用或追溯主张 | 查看别人私密线索，伪造线索来源，直接写背包或 Luck |
| Host | 通过公共版本、日志和回放了解队伍进度，必要时发放线索或目标 | 在玩家视角下直接看到所有私密线索原文 |
| AI-Keeper | 在权限范围内读取线索、背包、目标和近期事件 | 读取未发现线索、直接公开 truth、直接裸写 clue/inventory |
| Admin | 排查线索、道具、目标、事件一致性 | 把私密 clue 或本地调试信息混进 public scope |

## 数据分层

| 层 | 来源 | 用途 | 边界 |
|---|---|---|---|
| WorldBook 线索模板 | `knowledge_graph.clues[]` | 剧本潜在线索定义 | 不是玩家证据 |
| 玩家私密线索 | `clues.text` | 已发现证据原文 | 只给拥有者 |
| 分享公共版本 | `clue_shares.public_version` | 队伍共享摘要 | 不等于原始 clue |
| 线索发现事件 | `s2c_clue_discovered` 或等价私密事件 | 归档、审计、补发 | 不是队伍公开原文 |
| 线索分享事件 | `s2c_clue_shared` | 队伍证据链 | 只带 `publicVersion` |
| AI clue context | 裁剪后的 clue view / clue chunk | AI 推理上下文 | 不含未发现模板和 truth |
| 玩家同步 DTO | `/api/player/sync` | 玩家当前可见状态 | 和 `/clues` 口径一致 |
| Archive DTO | `/api/player/archive*` | 复盘 | 非拥有者不看原始私密 clue |
| Inventory runtime state | `inventory` + 受控状态写入 | 当前角色资源 | 不由玩家或 AI 直接裸写 |
| Objective runtime state | `objectives` | 团队/个人任务 | `personal` 不泄露 |

## Visibility / Access Model

本模块采用“数据访问级别”和“事件投影受众”分离的口径。

### 数据访问级别

- `self`：仅拥有者当前角色可见
- `party`：同房间队伍可见
- `host`：Host 舞台视角可见
- `admin`：后台审计可见
- `internal`：Engine / AI / Safety / Debug 内部使用，不直接对玩家输出
- `never_export`：不进入 public export

### 事件投影受众

- `player`
- `party`
- `host`
- `system`

### 默认映射

| 对象 | 默认访问级别 |
|---|---|
| `clues.text` | `self` |
| `clue_shares.public_version` | `party` |
| `clues.source` | `self + host/admin` |
| `inventory.is_secret=true` 条目 | `self + host/admin` |
| 普通背包条目 | `self`，共享由显式分享机制决定 |
| `objectives.type=team` | `party` |
| `objectives.type=personal` | `self` |
| WorldBook 未发现线索模板 | `host / internal` |
| public export 线索内容 | 仅 `party` 级公共版本 |

## 领域定义

### 1. WorldBook clue template 不等于玩家 clue

- `knowledge_graph.clues[]` 是剧本定义。
- 只有在 Rule / Engine / State / ClueService 释放后，写入 `clues` 表的内容才算玩家证据。

### 2. 分享不等于原文公开

- `clues.is_private=false` 不得被解释为 `clues.text` 对队友公开。
- 队友只能通过 `clue_shares.public_version` 读取共享内容。

### 3. 本轮 share scope 固定为 `party`

- 当前一条 clue 默认整房间共享一次。
- `target_scope / target_character_id` 作为后续扩展，不在本轮落地。

### 4. Clue Source Type 需要分层

为了统一 AI / RAG / Archive 口径，文档定义以下来源类型方向：

- `worldbook_clue_template`
- `player_clue`
- `shared_clue`
- `inventory_event`
- `objective_event`

player-facing AI / RAG 只能消费：

- 当前角色 owned `player_clue`
- 同房间 `shared_clue.public_version`
- 已公开事件

## 主流程

### Flow A：玩家获得私密线索

1. 玩家提交调查行动。
2. Rule / AI / Engine 判定应释放线索。
3. 统一受控路径写入 `clues`：`room_id`、`character_id`、`text`、`source`、`is_private=true`。
4. 写入 `player` 受众的 clue 发现事件。
5. Projection 向拥有者发送私密通知或状态补丁。
6. 可选写入 clue 索引，但索引视图必须保留 visibility。

### Flow B：玩家分享线索

1. 拥有者请求 `POST /api/player/clues/{clue_id}/share`。
2. 服务端验证 clue 属于当前角色。
3. 玩家提交 `public_version`，或服务端生成安全默认摘要。
4. 若请求全文公开，必须显式传入 `share_full_text=true` 与确认字段。
5. 插入 `clue_shares`。
6. 写入 `party` 受众的分享事件，事件只带 `publicVersion`。
7. 队友在 `/clues`、`/sync`、Archive、AI 公共上下文中看到的都是 `public_version`。

安全默认摘要建议固定文案为：

- `玩家分享了一条线索，但未公开完整内容。`
- 或 `分享者公开了一条线索摘要，完整内容仍由分享者掌握。`

要求：

- 默认摘要不能直接从 `clues.text` 自动摘要。
- `share_full_text=true` 也不能绕过 SpoilerGuard。

### Flow C：玩家追溯获得道具

1. 玩家提交 `retroactive_item_claim`。
2. `RetroactiveItemService.evaluate_claim()` 判断 `auto_pass / roll_required / forbidden`。
3. 若需要 Luck 检定，则在统一状态路径内完成 Luck 读取、掷骰、Luck 扣减。
4. 成功时统一写入 `inventory`、状态补丁、Action 结果、Journal 事件。
5. 失败时不得留下半成功 inventory 数据。

### Flow D：目标读取与变更

1. 玩家读取 `/api/player/objectives`。
2. 返回团队目标和当前角色个人目标。
3. 后续目标变更同样应写入事件链和归档。

### Flow E：AI 读取线索证据

1. AI 或 RAG 构建上下文时，先按角色、房间、visibility 裁剪 clue。
2. owned clue 使用原始 `text`。
3. shared clue 使用 `public_version`。
4. WorldBook 未发现 clue 模板、truth、隐藏 clue 原文不进入 player-facing AI prompt。

## 功能需求

### FR-1 私密线索读取

- Player 只能通过当前 `X-Room-Token` 读取自己的私密 clue。
- 队友不能从 `/clues`、`/sync`、Archive、Export、AI 上下文读到未分享原文。

### FR-2 分享公共版本安全化

- 分享必须产生 `public_version`。
- 默认不得直接把 `clues.text` 原样复制到 `public_version`。
- 若要全文公开，必须有服务端可验证的显式确认字段，例如 `share_full_text=true` 与 `confirm_share_full_text=true`。
- `public_version` 必须经过 SpoilerGuard 或等价安全检查。
- 未传 `public_version` 时，应使用固定安全摘要，而不是自动摘要原文。
- `share_full_text=true` 不是安全绕过开关。

### FR-3 `clues.is_private` 语义收口

- `is_private=true` 表示当前仅自有原文可见。
- `is_private=false` 只表示该 clue 已存在或曾存在 party-visible share，不代表 `clues.text` 可被队友直接读取。

### FR-4 线索发现与分享事件契约

- 发现线索写 `s2c_clue_discovered` 或等价私密事件。
- 分享线索写 `s2c_clue_shared`。
- `party` 事件禁止携带 `clues.text` 原文。
- Archive 能按 `clue_id` 聚合发现、分享、后续引用。

### FR-5 统一受控写入路径

- `_tool_engine_save_clue` 不得直接插库。
- StateService / ClueService / Engine 中必须存在唯一受控写入入口或等价入口。
- 该入口至少负责：权限校验、房间绑定、来源记录、事件记录、必要 patch、可选索引。
- `clue_shares` 的 room scope 必须有明确方案：要么补 `room_id`，要么所有 room-scope 查询一律 `JOIN clues` 通过 `clues.room_id` 过滤。

### FR-6 背包与 Luck 统一状态口径

- 追溯道具成功必须通过受控状态路径写 `inventory`。
- Luck 当前值应优先以 `character_runtime_state` 为权威，不能只落在 `characters.xlsx_data`。
- 若仍保留 `xlsx_data` 同步，它只能作为派生/兼容字段，不能成为唯一真实来源。
- 成功分支与失败分支都要保证 Action、Inventory、Luck、State patch、Journal 的一致性。

### FR-7 `/sync` 与 `/clues` 口径一致

- `/sync` 和 `/clues` 应复用同一 ClueViewBuilder 或等价视图构建器。
- owned clue 返回原始 `text`。
- shared clue 返回 `public_version`。
- 同一 clue 不能在两个接口里表现出冲突的可见性。

### FR-8 Objectives 权限边界

- `team` 目标对同房间玩家可见。
- `personal` 目标只对目标拥有者可见。
- 目标状态至少覆盖当前代码已有的 `active / completed / failed / expired`。

### FR-9 AI / RAG clue 过滤

- player-facing AI 只能读取 owned private clue、shared public clue、公开事件。
- WorldBook clue template 不进入玩家 prompt。
- `truth` 不因 clue share、Archive、Export 而直接变成玩家可读对象。

### FR-10 Public export 只导出公共版本

- public export 不再按 `clues.is_private` 直接导出 `clues.text`。
- public export 只能导出 `public_version` 和公开事件摘要。
- private/export/debug 才允许更高权限读原始数据。

## 事件契约

### 线索发现事件

```json
{
  "type": "s2c_clue_discovered",
  "audience": "player",
  "payload": {
    "clueId": "clue_xxx",
    "characterId": "char_xxx",
    "source": "action:act_xxx",
    "sourceActionId": "act_xxx",
    "visibility": "self",
    "publicVersion": null,
    "discoveredAt": "2026-07-06T12:00:00Z"
  }
}
```

### 线索分享事件

```json
{
  "type": "s2c_clue_shared",
  "audience": "party",
  "payload": {
    "clueId": "clue_xxx",
    "shareId": "share_xxx",
    "sharedBy": "char_xxx",
    "publicVersion": "公开摘要",
    "visibility": "party",
    "sharedAt": "2026-07-06T12:05:00Z"
  }
}
```

要求：

- `party` 事件不能包含 `clues.text`
- Archive 聚合必须能回指 `clueId`

## 接口方向

| 接口 | 权限 | 现状 | 本轮方向 |
|---|---|---|---|
| `GET /api/player/clues` | Player token | 已有 | 继续作为主读取接口 |
| `POST /api/player/clues/{clue_id}/share` | Clue owner | 已有 | 支持 `public_version` 与显式全文分享确认 |
| `GET /api/player/inventory` | Player token | 已有 | 保持自有读取 |
| `GET /api/player/objectives` | Player token | 已有 | 保持只读，先锁权限边界 |
| `GET /api/player/sync` | Player token | 已有 | 与 `/clues` 统一视图口径 |
| `POST /api/player/intent` | Player token | 已有 | 追溯道具改走受控事务写入 |
| `GET /api/player/archive/clues` | Player token | 已有 | 逐步切到 clue 专属事件契约 |

## 数据安全

- `clues.text` 默认是敏感字段。
- `clue_shares.public_version` 是公共版本字段。
- `inventory.is_secret=true` 不被公共玩家接口泄露。
- `objectives.type=personal` 不给其他玩家。
- WorldBook clue template、truth、隐藏 clue 原文不进入 player-facing AI。
- public export 只导出 `public_version`，不导出原始 `clues.text`。
- Host 默认运营视角读取 `public_version`、事件摘要和进度；如需查看 `clues.text` 原文，应走 Host/Admin debug 或 Keeper 特权接口，并记录审计，不得混入普通 player-facing / party-facing DTO。

## 事务与异常处理

- 缺少 `X-Room-Token`：401。
- token 无效：403。
- 分享非自己线索：404 或 403，避免泄露 clue 是否存在。
- 重复分享：409。
- `public_version` 非法或命中 SpoilerGuard：400 / 409。
- 追溯道具频率过高：429。
- 追溯道具不符合职业/剧情权限：403 / 409。
- 发现 clue、分享 clue、追溯道具、Luck 扣减、Journal 事件、Action 状态更新必须在同一事务或有等价补偿策略里完成。
- 不允许出现“inventory 写了、Luck 没扣、Action 已 resolved、事件没写”的半成功。

## 验收标准

1. 玩家 B 看不到玩家 A 未分享的 `clues.text`
2. 玩家 A 分享后，玩家 B 只能看到 `public_version`
3. `clues.is_private=false` 不会被接口误解为“原文全队公开”
4. StateService 分享路径与 player share API 都能正确写 `public_version`
5. `_tool_engine_save_clue` 不再直接 `INSERT clues`
6. 追溯道具成功时 inventory、Luck、state patch、action 结果一致
7. 追溯道具失败时不写 inventory，不留下半成功状态
8. `/sync` 与 `/clues` 对同一 clue 的返回口径一致
9. Archive 能聚合 clue 发现和分享
10. public export 不再导出私密 `clues.text`
11. player-facing AI / RAG 不包含未发现 WorldBook clue 和完整 truth
12. 相关测试命令通过：

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_player_features.py tests/server/test_retroactive_items.py tests/server/test_archive.py tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_rag_security.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py -q
```
