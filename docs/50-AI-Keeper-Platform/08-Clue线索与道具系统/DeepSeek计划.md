# Clue 线索与道具系统 DeepSeek 计划 V2.1

## 执行目标

把 Clue 模块从“能查看和分享线索的接口”修成“玩家证据链系统”：玩家私密线索、分享公共版本、背包资源、目标提示、AI 可读上下文、Journal 事件、Archive 复盘都走各自边界，而不是混成普通 CRUD。

## 当前阶段说明

- 当前是 `P0 主链路 + 证据链安全风险识别版`。
- 本计划只覆盖 `08-Clue线索与道具系统`，不把 WorldBook、Projection、Safety、Journal、State、Transaction 的全部细节重写到本模块里。
- 当前代码已经有基础接口，但存在私密线索泄露、分享默认公开原文、StateService 分享路径缺字段、AI 工具直接写 clue、追溯道具直接改 `xlsx_data.luck`、public export 走错字段、Archive 事件契约薄弱等问题。

## 总体禁止事项

- 不让玩家读取别人未分享的 `clues.text`。
- 不把 WorldBook 未发现线索模板或 `truth` 塞进 player-facing AI / RAG。
- 不让 `clues.is_private=false` 被解释成“原文公开”。
- 不让 public export 直接导出 `clues.text`。
- 不让 AI 工具直接绕过 State / Journal / Projection 写线索。
- 不让追溯道具直接只改 `characters.xlsx_data.luck` 而不更新运行态。
- 不让 clue / inventory / event / action 出现半成功。

## 模块级硬约束

1. `knowledge_graph.clues[]` 不是玩家 clue。
2. 玩家证据只有写入 `clues` 表后才成立。
3. shared clue 对队友永远展示 `public_version`，不是 `clues.text`。
4. `/sync` 与 `/clues` 必须复用同一 clue 视图口径。
5. public export 只能导出 `public_version` 与公开事件摘要。
6. Host 默认运营视角不直接混入 `clues.text` 原文；原文读取应走 Host/Admin debug 路径并有审计。

## Batch Clue-0：现状基线、术语锁定与测试补齐

### 为什么做

当前文档已经识别出多数风险，但测试还没把“分享不等于原文公开”“`is_private=false` 不等于原文公开”“`/sync` 与 `/clues` 不一致”等边界彻底钉住。

### 允许修改

- 测试文件优先
- `src/server/player/router_clues.py`
- `src/server/player/router_objectives.py`
- `src/server/player/router_player.py`

### 具体任务

1. 增加测试：玩家 B 看不到玩家 A 未分享的 `clues.text`。
2. 增加测试：分享后玩家 B 只看到 `public_version`。
3. 增加测试：`clues.is_private=false` 不代表原文公开。
4. 增加测试：`/sync` 与 `/clues` 口径差异。
5. 增加测试：personal objective 不泄露给其他玩家。
6. 增加测试：重复分享返回 `409`。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_player_features.py -q
```

### 验收结果

- 当前证据边界被测试固定。
- 后续批次每改一处都有红绿反馈。

## Batch Clue-1：分享 `public_version` 安全化与语义锁定

### 为什么做

当前 `share_clue` 默认把 `clues.text` 原样写进 `public_version`，这会直接绕过“公共摘要”概念；同时 `is_private=false` 容易被误解成“原文已公开”。

### 允许修改

- `src/server/player/router_clues.py`
- `src/server/engine/spoiler_guard.py`
- `tests/server/test_clues.py`
- `tests/server/test_spoiler.py`
- `tests/server/test_spoiler_guard.py`

### 具体任务

1. 分享接口支持请求体传入 `public_version`。
2. 未传 `public_version` 时使用固定安全默认摘要，不直接复制 `clues.text`，例如：`玩家分享了一条线索，但未公开完整内容。`
3. 若要全文分享，要求显式确认字段，例如 `share_full_text=true` 与 `confirm_share_full_text=true`。
4. `public_version` 进入 SpoilerGuard 或等价安全检查。
5. 明确 `clues.is_private=false` 只代表“已有 party-visible share”，不代表原文公开。
6. 返回体只返回 `share_id` 和最终 `public_version`。
7. `share_full_text=true` 不是绕过 SpoilerGuard 的开关。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py -q
```

### 验收结果

- 默认分享不暴露完整私密文本。
- 显式全文分享有服务端硬校验。
- `is_private` 语义不再被误用。

## Batch Clue-2：统一 Clue 写入路径与 StateService 修复

### 为什么做

当前有两条高风险路径：

- `_tool_engine_save_clue()` 直接插 `clues`
- `StateService._apply_clue_changes()` 插 `clue_shares` 时缺 `public_version`

这两条路径都没有形成可靠的证据链入口。

### 允许修改

- `src/server/agent/tools.py`
- `src/server/engine/state_service.py`
- `src/server/models.py`
- `tests/server/test_state_service.py`
- `tests/server/test_state_service_consistency.py`
- `tests/server/test_clues.py`

### 具体任务

1. 为 clue change schema 明确 `publicVersion` 或等价字段。
2. `_apply_clue_changes()` 写入 `share_id`、`clue_id`、`shared_by`、`public_version`。
3. 明确缺少 `public_version` 时是生成安全摘要还是拒绝。
4. AI 保存线索不再直接 insert，改走受控服务或 State / Engine 统一入口。
5. 统一写入入口至少负责：权限校验、房间绑定、`clue_id` 生成、来源记录、事件写入。
6. share API 与 StateService share 复用同一套 share builder / validation。
7. 明确 `clue_shares` 的 room scope 修复方案：要么补 `room_id`，要么所有 room 查询统一 `JOIN clues` 通过 `clues.room_id` 过滤。

### 验收命令

```powershell
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_clues.py -q
```

### 验收结果

- StateService 分享路径不再违反 DB 约束。
- AI 工具不再直接裸写 `clues`。
- share API 与 StateService share 结果一致。

## Batch Clue-3：Journal / Archive 事件契约闭环

### 为什么做

当前 Archive 主要读 `s2c_private_notice` 和 `s2c_public_observation`，但线索发现和分享没有 clue 专属事件契约，证据链不稳定。

### 允许修改

- `src/server/player/router_clues.py`
- `src/server/engine/state_service.py`
- `src/server/agent/tools.py`
- `src/server/player/router_player_archive.py`
- `src/server/events/event_log.py`
- `tests/server/test_archive.py`
- `tests/server/test_event_log.py`
- `tests/server/test_clues.py`

### 具体任务

1. 线索发现写入 `s2c_clue_discovered` 或等价私密事件。
2. 线索分享写入 `s2c_clue_shared`，`audience=party`。
3. 分享事件 payload 只带 `publicVersion`，不能带原始 `text`。
4. 事件 payload 至少包含 `clueId`、`characterId`、`source`、`shareId`、`publicVersion`。
5. Archive 能按 `clue_id` 聚合发现与分享。
6. 玩家 archive 和 public export 不直接回查私密原文。

### 验收命令

```powershell
python -m pytest tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_clues.py -q
```

### 验收结果

- 发现、分享、归档能串成同一条 clue 证据链。
- 队友和 public export 看不到私密原文。

## Batch Clue-4：追溯道具、Luck 与事务一致性

### 为什么做

当前 `_submit_retroactive_claim()` 直接插入 `inventory`、直接改 `xlsx_data.luck`、直接递增房间版本。这和 05-Character、13-State、14-Transaction 的口径不一致。

### 允许修改

- `src/server/player/router_player.py`
- `src/server/engine/retro_items.py`
- `src/server/engine/state_service.py`
- `tests/server/test_retroactive_items.py`
- `tests/server/test_state_service.py`
- `tests/server/test_player_intent.py`

### 具体任务

1. 保留 `RetroactiveItemService.evaluate_claim()` 的判断逻辑。
2. 成功道具加入改走受控 state / transaction 写入。
3. Luck 消耗优先写 `character_runtime_state`；若保留 `xlsx_data`，只能作为派生/同步字段。
4. 成功时一起完成：Luck 变化、inventory 添加、action resolved、state patch、Journal 事件。
5. 失败时只写 rejected/no-op，不写 inventory。
6. 对 `unique / plot_critical / mythos_artifact` 级别道具保持禁止或需要上游明确授权。

### 验收命令

```powershell
python -m pytest tests/server/test_retroactive_items.py tests/server/test_state_service.py tests/server/test_player_intent.py -q
```

### 验收结果

- `auto_pass` 成功时背包增加且状态一致。
- `roll_required` 成功时 Luck 与背包都一致更新。
- `forbidden / roll failed` 不留下半成功 inventory。

## Batch Clue-5：AI / RAG clue 过滤与 WorldBook 边界

### 为什么做

线索一旦进入 AI / RAG，上下文边界比 API 更危险。这里必须把 owned clue、shared clue、WorldBook 模板和 truth 分开。

### 允许修改

- `src/server/agent/tools.py`
- `src/server/ai/rag_context.py`
- `src/server/ai/rag.py`
- `src/server/engine/spoiler_guard.py`
- `tests/server/test_rag_security.py`
- `tests/server/test_spoiler.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_clues.py`

### 具体任务

1. `_tool_query_clues()` 返回 owned private clue 和 shared public clue，不能只看 owned raw clue。
2. `_tool_engine_save_clue()` 改走受控路径。
3. `source_type=clue` 查询必须限定 room 和 visibility。
4. 未发现 WorldBook clue template 不进入玩家 prompt。
5. `truth` 不因 share 直接变成玩家上下文。
6. 如有 Admin context preview，标明过滤原因，例如 `owned / shared_public / hidden_worldbook / truth_blocked / other_player_private`。

### 验收命令

```powershell
python -m pytest tests/server/test_rag_security.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py tests/server/test_clues.py -q
```

### 验收结果

- AI 上下文只包含允许证据。
- shared clue 使用 `public_version`。
- WorldBook 未发现 clue 和 truth 不进 player-facing AI。

## Batch Clue-6：`/sync`、Objective 与 Export 口径统一

### 为什么做

当前 `/sync`、`/clues`、`/archive`、`export` 对 clue 的表达口径并不一致，长远会造成“页面、AI、导出、日志各说各话”。

### 允许修改

- `src/server/player/router_player.py`
- `src/server/player/router_clues.py`
- `src/server/player/router_objectives.py`
- `src/server/player/router_player_archive.py`
- `src/server/export.py`
- `tests/server/test_player_features.py`
- `tests/server/test_objectives.py`
- `tests/server/test_archive.py`
- `tests/server/test_clues.py`

### 具体任务

1. 抽出共享的 ClueViewBuilder 或等价视图构建器。
2. `/sync` 返回 owned clue + shared public clue。
3. Objectives 保持 `team` / `personal` 权限边界清晰。
4. public export 改为导出 `public_version` 和公开事件摘要，而不是 `clues.text`。
5. 如需保留 private export / debug export，明确权限范围。

### 验收命令

```powershell
python -m pytest tests/server/test_player_features.py tests/server/test_objectives.py tests/server/test_archive.py tests/server/test_clues.py -q
```

### 验收结果

- `/sync` 和 `/clues` 对同一 clue 的可见字段一致。
- personal objective 不泄露。
- public export 不再带私密 clue 原文。

## Batch Clue-7：端到端回归

### 验收流程

1. 玩家 A 调查获得私密线索。
2. 玩家 B 看不到该线索。
3. 玩家 A 分享公共版本。
4. 玩家 B 看到 `public_version`，看不到原文。
5. 玩家 A 追溯道具成功，背包增加，Luck 状态一致。
6. 玩家归档能查到线索发现、分享、道具获得。
7. public export 只包含公共版本。
8. AI 上下文只含允许证据。
9. WorldBook 未发现线索不会进入玩家提示。
10. 任一步失败时，不产生半成功数据。

### 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_player_features.py tests/server/test_retroactive_items.py tests/server/test_archive.py tests/server/test_state_service.py tests/server/test_state_service_consistency.py tests/server/test_rag_security.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py tests/server/test_player_intent.py -q
```

### 完成定义

- Clue 主链路形成：
  `发现 -> 私密保存 -> 分享公共版本 -> 事件沉淀 -> AI 可见过滤 -> 归档可查`
- 道具主链路形成：
  `主张/获得 -> 统一状态写入 -> patch -> 事件 -> 背包展示`
- DeepSeek 可以按 `Clue-0` 到 `Clue-7` 顺序执行，不需要重新理解模块边界。
