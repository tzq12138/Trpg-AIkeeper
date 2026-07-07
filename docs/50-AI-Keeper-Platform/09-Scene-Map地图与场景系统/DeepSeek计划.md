# Scene / Map 地图与场景系统 DeepSeek 计划 V2.1

## 执行定位

本计划服务于 `P0 主链路 + 地图投影安全风险识别版`。

目标不是一次做完完整地图平台，而是先把当前仓库里已经存在的地图链路加固成工程可执行版本：鉴权正确、读接口无副作用、DTO 不剧透、移动经 Engine、Host 操作可审计、事件有版本。

## 当前仓库已确认事实

基于当前代码可确认：

- 玩家地图入口在 `src/server/router_map.py`
- 玩家地图投影构建在 `src/server/map_persistence.py`
- Host 全图、显隐、强制移动在 `src/server/host/router_host.py`
- 地图生成在 `src/server/router_admin.py` 和 `src/server/ai/map_generator.py`
- 地图移动成功后的运行态推进已接入 `src/server/engine/resolution_pipeline.py`
- 当前场景状态由 `src/server/engine/state_service.py` 管理

已识别的核心风险：

- 玩家地图 GET 仍可能退化成匿名读取
- 玩家地图 GET 仍带写库副作用
- 玩家视图仍可能暴露原始 NPC/线索字段
- 地图生成源与 `knowledge_graph.scenes` 脱节
- Host 显隐和强制移动的校验、审计、版本契约仍不完整

## 全局禁止事项

- 禁止让 Player 端复用 Host 全图接口
- 禁止 `GET /api/map/{room_id}` 调用任何 `set_`、`mark_`、`bump_` 类写入 helper
- 禁止无效 token 或跨房间 token 退化成匿名安全图或匿名全图
- 禁止把原始 `npcsPresent`、原始 `cluesAvailable`、隐藏描述直接返回给 Player
- 禁止绕过 Engine 直接完成玩家移动
- 禁止 Scene/Map 直接写 `room_scene_state.current_scene`
- 禁止在 WS 事件里塞完整节点详情代替安全拉取
- 禁止顺手重构无关模块、清理全仓格式或修改测试产物

## Batch Map-0：现状固化与测试基线

### 目标

先用测试锁住当前风险和目标行为，避免后续修复回退。

### 允许改动文件方向

- `tests/server/test_map.py`
- 必要时新增：
  - `tests/server/test_map_visibility.py`
  - `tests/server/test_map_generation.py`
  - `tests/server/test_map_movement.py`
  - `tests/server/test_map_host_ops.py`
- `tests/server/test_room_security.py`
- `tests/server/conftest.py` 仅在补测试夹具时小范围调整

### 任务

1. 构造包含 confirmed map、room、character、player token 的最小测试场景。
2. 覆盖无 token、无效 token、跨房间 token 读取玩家地图。
3. 覆盖“连续两次 GET 不应改库”的断言。
4. 覆盖玩家移动到相邻、非相邻、隐藏节点三类行为。
5. 覆盖 Host full map、reveal/hide、force move 的基本鉴权。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_room_security.py -q
```

### 验收

- 测试能稳定暴露匿名读取、GET 副作用、越权操作等问题。
- 新增测试不污染其他房间/角色用例。

## Batch Map-1：玩家地图鉴权与纯读化

### 目标

修掉最危险的两件事：地图 GET 越权、地图 GET 写库。

### 允许改动文件方向

- `src/server/router_map.py`
- `src/server/map_persistence.py`
- `tests/server/test_map.py`
- `tests/server/test_room_security.py`

### 任务

1. `GET /api/map/{room_id}` 必须要求有效玩家身份。
2. `_get_character` 出错时返回鉴权失败，不退化成匿名读取。
3. 移除 GET 路径中的自动 `set_character_position`、`mark_node_explored`。
4. `build_player_map_view` 改为纯投影函数，不做落库。
5. 无当前位置时返回 `no_current_position` 或安全空态。
6. 修正 `hiddenCount` 只统计真实不可见节点。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_room_security.py -q
```

### 验收

- 无 token、无效 token、跨房间 token 都拿不到节点列表。
- 连续 GET 不修改 `character_map_positions`、`room_map_state.explored_nodes`、`state_version`。
- 有效玩家只能拿到安全投影。

## Batch Map-2：DTO 脱敏与防剧透投影

### 目标

把玩家地图从“有迷雾的原始节点”改成“真正的安全 DTO”。

### 允许改动文件方向

- `src/server/map_persistence.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/player/router_clues.py`
- `tests/server/test_map.py`
- `tests/server/test_spoiler_guard.py`

### 任务

1. 固化 `MapNodePlayerDTO` 字段边界。
2. explored 节点也不默认返回原始 `cluesAvailable`、`npcsPresent`。
3. 玩家地图只展示已发现或已公开的 clue/NPC 摘要。
4. 相邻未探索节点只显示安全 label 和方向提示，不显示完整描述。
5. 如内部仍保留原始 clue/NPC 引用，必须在投影层过滤。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_spoiler_guard.py -q
```

### 验收

- 未发现线索不出现在玩家地图 JSON。
- 隐藏 NPC 不出现在玩家地图 JSON。
- Host 全图仍能看到完整内部节点信息。

## Batch Map-3：地图生成源对齐与草稿质量

### 目标

把地图生成接回当前剧本导入产物，并清理生成文案/字段口径。

### 允许改动文件方向

- `src/server/router_admin.py`
- `src/server/ai/map_generator.py`
- `tests/server/test_map_generation.py`
- 必要时补到 `tests/server/test_scenario_import.py`

### 任务

1. 地图生成优先读取 `knowledge_graph.scenes`。
2. 如旧数据仍在 `scenario_assets.scenes`，提供兼容适配层。
3. 清理地图生成 prompt/返回结构中的乱码和字段漂移。
4. 统一输出 snake_case 字段。
5. fallback 生成器在无 AI key 时仍可工作。

### 测试命令

```bash
python -m pytest tests/server/test_map_generation.py -q
python -m pytest tests/server/test_scenario_import.py -q
```

### 验收

- 只有 `knowledge_graph.scenes` 的剧本也能生成地图。
- 无 DeepSeek key 时仍可输出可确认的 draft map。
- 中文文案与字段结构稳定。

## Batch Map-4：移动事务、版本屏障与场景边界

### 目标

把地图版本推进、移动结果写入和场景切换边界彻底说清并落到代码。

### 允许改动文件方向

- `src/server/map_persistence.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/events/events_registry.py`
- `tests/server/test_map_movement.py`
- `tests/server/test_projection.py`
- `tests/server/test_host_room_lifecycle.py`

### 任务

1. 修正 `init_room_map_state` 的幂等返回值。
2. 移动成功后统一推进位置、explored 和 `mapVersion`。
3. 明确 move success 不自动等于 `current_scene` 改写。
4. 让地图事件稳定携带 `mapVersion`。
5. 重连补丁按版本应用，旧事件不能覆盖新状态。

### 测试命令

```bash
python -m pytest tests/server/test_map_movement.py tests/server/test_projection.py -q
python -m pytest tests/server/test_host_room_lifecycle.py -q
```

### 验收

- 裁决失败不移动角色。
- 重复开局/恢复不会清空探索状态。
- 事件顺序可按 `mapVersion` 验证。
- `current_scene` 只由 State/事务链路推进。

## Batch Map-5：Host 操作校验与审计

### 目标

把 Host 的地图操作从“能用”加固到“可控、可追踪、可回放”。

### 允许改动文件方向

- `src/server/host/router_host.py`
- `src/server/map_persistence.py`
- `src/server/events/event_log.py`
- `tests/server/test_map_host_ops.py`
- `tests/server/test_event_log.py`

### 任务

1. reveal/hide 前校验节点属于房间地图。
2. force move 前校验角色属于房间、目标节点属于地图。
3. `force_move` 要求 `reason`，建议接入 `confirm` 位。
4. 记录统一审计字段：操作者、对象、原因、版本、时间。
5. `s2c_map_revealed`、`s2c_player_moved` 只发送安全事件摘要。

### 测试命令

```bash
python -m pytest tests/server/test_map_host_ops.py tests/server/test_event_log.py -q
```

### 验收

- 非 Host/Admin 不能执行地图舞台操作。
- 非本房间角色不能被强制移动。
- 非本地图节点不能被 reveal/hide 或作为强制移动目标。
- 日志中可追踪每次 Host 操作。

## Batch Map-6：前端地图状态与事件消费对齐

### 目标

在不做大改版 UI 的前提下，让前端严格对齐安全 DTO 和版本事件。

### 允许改动文件方向

- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/shared/types.ts`
- `src/client/src/api.ts`

### 任务

1. Player 地图处理 `401`、`403`、`no_map`、`no_current_position`、`moving` 状态。
2. 前端类型不再依赖原始 `npcsPresent`、`cluesAvailable`。
3. Host 操作失败时给出明确反馈，不显示假成功。
4. 收到 WS 事件后按安全接口重新拉取，不信任事件中的潜在敏感细节。

### 测试命令

```bash
cd src/client
npm run build
npm run test
```

### 验收

- 前端类型检查通过。
- Player 地图不会因字段收紧而崩溃。
- Host 地图操作失败时页面状态正确。

## Batch Map-7：端到端主链路验收

### 目标

验证地图链路已能稳定融入主跑团流程。

### 手动验收流程

1. Admin 导入带 scenes 的剧本。
2. Admin 生成并确认地图。
3. Host 创建房间并选剧本。
4. Player 加入并绑定角色。
5. Host 开局，初始化房间地图状态。
6. Player 打开地图，只看到安全投影。
7. Player 提交一次合法移动。
8. Engine 裁决成功后，Host/Player 都收到对应刷新。
9. Host 执行一次 reveal/hide。
10. Host 执行一次有 reason 的 force move，并在日志中可查。

### 回归命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_room_security.py tests/server/test_projection.py -q
python -m pytest tests/server -q
cd src/client
npm run build
```

### 最终验收

- 地图主链路完成：生成 -> 确认 -> 开房 -> 入房 -> 开局 -> 看图 -> 移动 -> 双端刷新 -> 日志可查
- 安全链路完成：玩家不能通过地图 GET 拿全图，不能提前看到未发现线索或隐藏 NPC
- 工程链路完成：地图相关测试、前端构建、关键回归命令可稳定通过
