# Clue 线索与道具系统 PRD V2.0

## 背景

跑团里“线索”和“道具”不是普通列表，它们是玩家推理、行动宣告、AI 上下文和战役复盘的证据。AI-Keeper 必须保证：玩家已经发现的内容能被可靠追踪，队友只能看到被分享的公共版本，AI 只能读取当前权限允许的证据，道具获得和消耗必须进入状态与日志。

当前代码已有线索列表、线索分享、背包列表、目标列表、追溯道具主张和玩家归档雏形，但还没有形成完整证据链：分享默认公开原文，发现/分享未稳定写事件，AI 工具可直接插入线索，StateService 的分享路径缺少 `public_version`，追溯道具绕过统一状态写入。

## 产品目标

1. 玩家能安全查看自己的线索、背包和目标。
2. 玩家能主动分享线索，但队友只看到公共版本。
3. 每条线索和道具变化都能追溯来源：哪个行动、哪个角色、哪个时间、哪次分享。
4. AI 只能读取已发现或已分享的证据，不读取 WorldBook 未公开真相。
5. DeepSeek 后续能按证据链逐段修复，不把 Clue 写成简单 CRUD。

## 非目标

- 本轮不做完整线索墙 UI。
- 本轮不做复杂道具交易市场。
- 本轮不让玩家自由创造规则效果。
- 本轮不让 AI 自动公开线索。
- 本轮不把 WorldBook 的未发现线索复制到玩家线索表。

## 用户角色

| 角色 | 可做 | 不可做 |
| --- | --- | --- |
| Player | 查看自己线索/背包/目标，分享自己线索，提交道具使用或追溯主张 | 查看别人私密线索，伪造线索来源，直接写背包 |
| Host | 通过日志和公共线索了解队伍进度，必要时发放线索或目标 | 在玩家视角看到所有私密线索 |
| AI-Keeper | 在权限范围内读取线索、背包和近期证据 | 读取未发现线索、直接公开真相、直接落库 |
| Admin | 排查线索、道具、目标和事件一致性 | 将敏感线索导出到 public scope |

## 主流程

### Flow A：玩家获得私密线索

1. 玩家提交调查行动。
2. Rule/AI/Engine 判定应释放线索。
3. State/Clue 写入 `clues`：`room_id`、`character_id`、`text`、`source`、`is_private=true`。
4. Journal 写入“线索发现”事件。
5. Projection 向该玩家发送私密通知或状态补丁。
6. AI 后续可在该角色上下文读取这条线索。

当前代码缺口：AI tool 直接写 `clues`，未统一 State/Journaling。

### Flow B：玩家分享线索

1. 拥有者调用 `POST /api/player/clues/{clue_id}/share`。
2. 后端验证该 clue 属于当前角色。
3. 玩家提交或确认 `public_version`。
4. 后端插入 `clue_shares`，更新 `clues.is_private=false`。
5. Journal 写入分享事件。
6. 队友在 `/api/player/clues` 中看到 `public_version`。

当前代码缺口：`public_version` 默认包含完整原文，缺少防剧透摘要流程。

### Flow C：玩家获得或主张道具

1. 玩家提交使用/获得道具 intent。
2. 普通道具由规则裁决或 StateChangeSet 写入。
3. 追溯主张走 `retroactive_item_claim`，根据职业、素材矩阵和 Luck 判断。
4. 成功后写入 `inventory`，必要时扣 Luck。
5. Journal 写入道具获得事件。
6. Projection 给玩家发送背包 patch。

当前代码缺口：追溯道具直接插入 inventory，直接修改 `xlsx_data.luck`。

### Flow D：目标提示

1. 玩家请求 `/api/player/objectives`。
2. 返回团队目标和当前角色个人目标。
3. 目标变更应写入 Journal，并可被 AI 作为允许上下文读取。

当前代码缺口：只有读取，没有创建、完成、撤销接口。

## 功能需求

### FR-1 私密线索读取

- 玩家只能通过 `X-Room-Token` 读取自己角色线索。
- 返回字段包括 `clue_id`、`text`、`source`、`discovered_at`、`is_owner`、`is_private`。
- 对拥有者，`text` 可以是原文。
- 对非拥有者，只能返回 `public_version`。

验收：玩家 B 不能读取玩家 A 未分享线索。

### FR-2 线索分享公共版本

- 只有拥有者能分享。
- 同一 clue 默认只允许分享一次，后续版本化另行设计。
- 分享必须产生 `public_version`。
- `public_version` 不应默认等于完整原文；如果沿用原文，必须是玩家显式确认。
- 分享后队友可见，原始 `text` 仍只归拥有者和授权审计使用。

验收：分享后队友列表出现公共版本，但接口不返回原始私密字段。

### FR-3 线索证据链

每条线索应能追踪：

- 发现者。
- 来源 action 或系统来源。
- 发现时间。
- 分享者。
- 分享时间。
- 公共版本。
- 相关 Journal sequence。

验收：归档接口能按 clue_id 找到发现和分享事件。

### FR-4 背包与道具状态

- 玩家只能查看自己的 inventory。
- 道具添加、移除、消耗必须有来源和事件。
- `is_secret=true` 道具只对持有人和授权 Host/Admin 可见。
- 追溯道具不能授予 unique/剧情关键物品，除非世界书或 Host 明确允许。

验收：追溯道具成功后背包增加，失败不会写入 inventory。

### FR-5 目标列表

- team 目标对同房间玩家可见。
- personal 目标只对对应角色可见。
- 目标状态至少支持 `active`、`completed`、`failed`、`hidden`。
- 目标变更要可归档。

验收：玩家不能读取其他玩家 personal objective。

### FR-6 AI 上下文过滤

- AI 查询线索时只读取当前角色拥有线索和队伍已分享公共版本。
- RAG clue chunk 必须按 room 和 visibility 过滤。
- 未发现 WorldBook clue 不进入玩家行动 prompt。
- `truth` 永远不因 clue share 直接解锁完整内容。

验收：AI 上下文预览不含未拥有、未分享、未解锁线索。

## 接口

| 接口 | 权限 | 说明 |
| --- | --- | --- |
| `GET /api/player/clues` | Player token | 获取自己线索和队友分享公共版本 |
| `POST /api/player/clues/{clue_id}/share` | Clue owner | 分享线索 |
| `GET /api/player/inventory` | Player token | 获取自己背包 |
| `GET /api/player/objectives` | Player token | 获取团队和个人目标 |
| `GET /api/player/sync` | Player token | 获取玩家同步包，后续需与 clues 口径一致 |
| `POST /api/player/intent` | Player token | 使用道具、追溯主张、调查行动 |
| `GET /api/player/archive/clues` | Player token | 获取可见线索事件归档 |

## 数据安全

- `clues.text` 是敏感字段，默认只给拥有者。
- `clue_shares.public_version` 是队伍可见字段。
- `inventory.is_secret` 不能被公共队伍接口泄露。
- `objectives.type=personal` 只能给对应角色。
- public export 只能包含 public_version 和公开道具摘要。

## 异常处理

- 缺少 `X-Room-Token`：401。
- token 无效：403。
- 分享非自己线索：404 或 403，避免泄露 clue 是否存在。
- 重复分享：409。
- 追溯道具频率过高：429。
- 追溯道具不符合职业/剧情权限：403 或 409。
- State/Journaling 写入失败：不能只改一半数据，应回滚或返回明确失败。

## 验收标准

1. 玩家 A 私密线索不会出现在玩家 B `/clues`。
2. 玩家 A 分享后，玩家 B 只能看到 `public_version`。
3. 分享路径和 StateService 分享路径都能写入 `public_version`。
4. 追溯道具成功后 inventory 增加，并产生 action/result/state patch。
5. 追溯道具失败不会写 inventory。
6. AI 查询线索不包含未发现世界书线索。
7. 玩家归档能查到线索发现和分享记录。
8. 相关测试命令通过：

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_retroactive_items.py tests/server/test_archive.py -q
```
