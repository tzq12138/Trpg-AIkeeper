# Clue 线索与道具系统 DeepSeek 计划 V2.0

## 执行目标

把 Clue 模块从“能查看和分享线索的接口”修成“可追溯、可防剧透、可进入 AI 上下文过滤的证据链系统”。本计划只覆盖线索、道具、目标和相关归档，不做完整线索墙 UI。

## 总体禁止事项

- 不让玩家读取别人未分享的 `clues.text`。
- 不把 WorldBook 未发现线索或 `truth` 塞进玩家上下文。
- 不让 AI 工具直接绕过 State/Journaling 写线索。
- 不让追溯道具授予 unique/剧情关键物品。
- 不把 Host 全量视角复用给 Player。

## Batch Clue-0：现状基线和测试补齐

### 为什么做

当前已有 `test_clues.py`、`test_objectives.py`、`test_retroactive_items.py`，但覆盖不到 StateService 分享路径、AI 工具保存线索、玩家 sync 口径和归档事件。

### 允许修改

- 测试文件优先。
- `src/server/player/router_clues.py`
- `src/server/player/router_objectives.py`
- `src/server/player/router_player.py`

### 具体任务

1. 增加测试：非拥有者不能分享 clue。
2. 增加测试：队友只能看到 `public_version`。
3. 增加测试：`/api/player/sync` 与 `/api/player/clues` 口径差异。
4. 增加测试：personal objective 不泄露给其他玩家。
5. 增加测试：重复分享返回 409。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_objectives.py -q
```

### 验收结果

- 当前安全边界被测试固定。
- 后续修改有红绿反馈。

## Batch Clue-1：分享 public_version 安全化

### 为什么做

现在分享接口默认把原始线索全文放入 `public_version`，再追加备注。对于含剧透或私人细节的线索，这会绕过“公共摘要”概念。

### 允许修改

- `src/server/player/router_clues.py`
- `src/server/engine/spoiler_guard.py`
- `tests/server/test_clues.py`

### 具体任务

1. 分享接口支持请求体传入 `public_version`。
2. 如果没有传入，则使用安全默认摘要，不直接拼完整原文。
3. 如果玩家显式选择原文公开，需要字段表达确认，例如 `share_full_text=true`。
4. `public_version` 进入 SpoilerGuard 审查，命中未解锁 truth 时拒绝或替换。
5. 返回体只返回 `share_id` 和最终 `public_version`。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_spoiler*.py -q
```

### 验收结果

- 默认分享不暴露完整私密文本。
- 显式全文分享有测试覆盖。
- 含未解锁真相的 public_version 被阻止。

## Batch Clue-2：StateService 线索路径修复

### 为什么做

`StateService._apply_clue_changes` 插入 `clue_shares` 时缺少 `public_version`，而表定义要求 `public_version TEXT NOT NULL`。这条路径一旦被执行会失败或产生不一致。

### 允许修改

- `src/server/engine/state_service.py`
- `src/server/models.py`
- `tests/server/test_state_service*.py`
- `tests/server/test_clues.py`

### 具体任务

1. 为 clue change schema 增加或确认 `publicVersion` 字段。
2. `_apply_clue_changes` 插入 `share_id`、`clue_id`、`shared_by`、`public_version`。
3. 如果没有 public version，生成安全摘要或拒绝。
4. 更新 `clues.is_private=false` 时必须限定 `room_id`。
5. 返回 applied diff，便于状态版本和日志追踪。

### 验收命令

```powershell
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_clues.py -q
```

### 验收结果

- StateService 分享路径不再违反 DB 约束。
- 分享结果与 player share API 一致。

## Batch Clue-3：线索发现和分享写入 Journal

### 为什么做

玩家归档目前主要从 `events` 读取线索类事件，但线索发现和分享不一定写入事件。结果是表里有 clue，归档里未必有证据链。

### 允许修改

- `src/server/player/router_clues.py`
- `src/server/engine/state_service.py`
- `src/server/agent/tools.py`
- `src/server/player/router_player_archive.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`

### 具体任务

1. 线索发现写入 `s2c_private_notice` 或专用 `s2c_clue_discovered` 事件。
2. 线索分享写入 `s2c_clue_shared` party 事件，payload 只含 public_version。
3. 事件 payload 包含 `clueId`、`source`、`characterId`、`shareId`、`publicVersion`。
4. 玩家 archive 按 clue_id 聚合发现和分享事件。
5. public export 只能导出 public_version。

### 验收命令

```powershell
python -m pytest tests/server/test_event_log.py tests/server/test_archive.py tests/server/test_clues.py -q
```

### 验收结果

- 发现、分享、查看都能追溯到事件 sequence。
- 其他玩家不能从 archive 读到私密 clue 原文。

## Batch Clue-4：追溯道具写入收口

### 为什么做

`_submit_retroactive_claim` 当前直接插入 `inventory`，直接递增 `rooms.state_version`，并直接修改 `characters.xlsx_data.luck`。这绕过了 StateService 的统一状态口径。

### 允许修改

- `src/server/player/router_player.py`
- `src/server/engine/retro_items.py`
- `src/server/engine/state_service.py`
- `tests/server/test_retroactive_items.py`
- `tests/server/test_state_service*.py`

### 具体任务

1. 保留 `RetroactiveItemService.evaluate_claim` 的判断逻辑。
2. 成功道具加入改走 StateService inventory change。
3. Luck 消耗改走角色运行态 mutation，或明确同步 `character_runtime_state`。
4. 失败分支只写 action rejected，不写 inventory。
5. 成功分支写 action resolved、state patch、Journal 事件。
6. 频率限制 2/min 保留。

### 验收命令

```powershell
python -m pytest tests/server/test_retroactive_items.py tests/server/test_state_service.py tests/server/test_player_intent.py -q
```

### 验收结果

- auto_pass 成功加入背包。
- roll_required 成功扣 Luck 并加入背包。
- roll failed 或 forbidden 不写背包。
- 状态版本和 patch 一致。

## Batch Clue-5：AI 上下文和 RAG clue 过滤

### 为什么做

AI 工具和 RAGContextBuilder 都可能把 clue 放进 AI 上下文。这里必须严格区分当前角色拥有线索、队伍分享公共版本和未发现世界书线索。

### 允许修改

- `src/server/agent/tools.py`
- `src/server/ai/rag_context.py`
- `src/server/ai/rag.py`
- `tests/server/test_rag_security.py`
- `tests/server/test_spoiler*.py`

### 具体任务

1. `_tool_query_clues` 返回当前角色拥有线索和 shared public version。
2. `_tool_engine_save_clue` 不再直接插库，改走受控服务或 Engine/State。
3. RAG `source_type=clue` 查询必须限定 room 和 visibility。
4. Admin context preview 标明每条 clue 的来源和可见级别。
5. 未发现 WorldBook clue 不进入玩家 prompt。

### 验收命令

```powershell
python -m pytest tests/server/test_rag_security.py tests/server/test_spoiler*.py tests/server/test_clues.py -q
```

### 验收结果

- AI 上下文只包含允许线索。
- shared clue 使用 public version。
- 未发现 clue 和 truth 不出现在玩家 prompt。

## Batch Clue-6：目标和玩家同步口径统一

### 为什么做

`/api/player/objectives` 只读目标，`/api/player/sync` 返回线索和背包但线索口径与 `/clues` 不一致。玩家端长期会出现“线索页和同步状态不同”的问题。

### 允许修改

- `src/server/player/router_player.py`
- `src/server/player/router_objectives.py`
- `src/server/player/router_clues.py`
- `tests/server/test_objectives.py`
- `tests/server/test_player_features.py`

### 具体任务

1. 抽出共享的 clue view builder，供 `/clues` 和 `/sync` 使用。
2. `/sync` 返回 owned clues 和 shared public clues。
3. objectives 增加状态过滤，默认返回 active。
4. 设计 Host/Admin 创建和完成目标的后续接口，但本批可只补后端测试和文档口径。
5. 个人目标不泄露给其他玩家。

### 验收命令

```powershell
python -m pytest tests/server/test_objectives.py tests/server/test_player_features.py tests/server/test_clues.py -q
```

### 验收结果

- 玩家同步包与线索页面一致。
- 团队目标和个人目标权限正确。

## Batch Clue-7：端到端回归

### 验收流程

1. 玩家 A 调查获得私密线索。
2. 玩家 B 看不到该线索。
3. 玩家 A 分享公共版本。
4. 玩家 B 看到 public version，但看不到原文。
5. 玩家 A 追溯道具成功，背包增加，Luck 状态一致。
6. 玩家归档能查到线索发现、分享、道具获得。
7. AI 上下文只含允许证据。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_retroactive_items.py tests/server/test_archive.py tests/server/test_rag_security.py tests/server/test_spoiler*.py -q
```

### 完成定义

- Clue 模块形成“发现 -> 私密保存 -> 分享公共版本 -> 事件沉淀 -> AI 可见过滤 -> 归档可查”的闭环。
- 道具形成“主张/获得 -> 状态写入 -> patch -> 事件 -> 背包展示”的闭环。
- DeepSeek 可以按 Batch Clue-0 到 Clue-7 逐步执行，不需要重新理解模块边界。
