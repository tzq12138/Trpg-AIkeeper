# Scene / Map 地图与场景系统 DeepSeek 计划 V2.0

## 执行目标

先把地图从“可展示”修到“不会剧透、不会越权、不会绕过主链路”，再补生成质量和前端体验。第一轮只围绕现有 FastAPI、React、PostgreSQL 表和 WS 事件施工，不引入大型地图编辑器或 VTT 引擎。

## 全局禁止事项

- 禁止让 Player 端调用 Host 全图接口。
- 禁止在玩家地图响应中返回完整 `scenario_maps.nodes`。
- 禁止让 `GET /api/map/{room_id}` 写入数据库。
- 禁止 AI 直接写 `room_map_state`、`character_map_positions` 或 `room_scene_state`。
- 禁止绕过 Engine 直接完成玩家移动。
- 禁止把线索正文、NPC 秘密、真相字段作为地图节点公共字段返回给玩家。
- 禁止顺手重构无关模块、格式化全仓或修改测试产物。

## Batch Map-0：现状基线与测试骨架

### 目标

建立地图模块的可回归测试入口，先用测试锁住当前风险，再进入修复。

### 允许改动文件方向

- `tests/server/test_map.py`
- `tests/server/test_room_security.py`
- `tests/server/conftest.py`，仅在测试夹具缺少地图表清理时小范围调整
- 必要时读取 `src/server/router_map.py`、`src/server/map_persistence.py`、`src/server/host/router_host.py`

### 任务

1. 构造带 confirmed map 的 scenario、room、character、player token。
2. 覆盖玩家地图无 token、无效 token、有效 token 三种请求。
3. 覆盖玩家移动到相邻节点、非相邻节点、隐藏节点。
4. 覆盖 Host full map、reveal、force move 的鉴权。
5. 标记当前会失败的用例，随后批次逐步修正。

### 测试命令

```bash
python -m pytest tests/server/test_map.py -q
python -m pytest tests/server/test_room_security.py -q
```

### 验收

- 新增测试能稳定复现地图匿名泄露和 GET 副作用风险。
- 测试数据不污染其他 room、character、scenario 用例。

## Batch Map-1：玩家地图鉴权与无副作用查询

### 目标

修复最高优先级安全问题：玩家地图接口必须鉴权，并且查询不能改变真实状态。

### 允许改动文件方向

- `src/server/router_map.py`
- `src/server/map_persistence.py`
- `tests/server/test_map.py`
- `tests/server/test_room_security.py`

### 任务

1. `GET /api/map/{room_id}` 必须要求有效玩家 token。
2. `_get_character` 抛出异常时不能降级为匿名全图。
3. 删除或迁移 GET 中的自动 `set_character_position` 和 `mark_node_explored`。
4. `build_player_map_view` 改成纯投影函数，不写数据库。
5. 没有当前位置时返回安全空态或明确错误，由开局初始化、加入流程或移动入口处理。
6. 修正 `hiddenCount` 统计，只统计实际不可见节点。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_room_security.py -q
```

### 验收

- 无 token 或无效 token 不能获得节点列表。
- 连续调用 GET 不改变 `character_map_positions`、`room_map_state.explored_nodes` 和版本。
- 有效 token 只能看到安全投影。

## Batch Map-2：防剧透投影与线索/NPC 引用

### 目标

让地图节点只展示玩家已获得权限的信息，避免通过地图提前看到线索名、NPC 名或场景秘密。

### 允许改动文件方向

- `src/server/map_persistence.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/player/router_clues.py`
- `tests/server/test_map.py`
- `tests/server/test_spoiler_guard.py` 或现有 spoiler 相关测试

### 任务

1. 定义 PlayerMapNode 安全字段：`nodeId`、name、position、isCurrent、isAdjacent、explored、safeHint。
2. 已探索节点也不默认返回 `cluesAvailable` 和 `npcsPresent` 的原始数组。
3. 线索展示只引用 Clue 模块中已发现或已分享的线索。
4. NPC 展示只引用已公开出现或当前场景公开 NPC。
5. 相邻未探索节点只显示可公开名称或模糊名称，不显示描述。
6. 如地图生成节点中保留 clue/NPC 原始引用，Player 视图必须过滤。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_clues.py -q
python -m pytest tests/server/test_spoiler_guard.py -q
```

### 验收

- 未发现线索不会出现在玩家地图 JSON。
- 隐藏 NPC 不会出现在玩家地图 JSON。
- Host 全图仍可看到完整节点信息。

## Batch Map-3：地图生成数据源与乱码修正

### 目标

让地图生成接上当前剧本导入产物，并修正文案乱码，保证 Admin 从 PDF 导入后能生成可用地图。

### 允许改动文件方向

- `src/server/router_admin.py`
- `src/server/ai/map_generator.py`
- `tests/server/test_admin_map.py` 或 `tests/server/test_map.py`
- 相关前端 Admin 页面仅在接口字段变更时小范围调整

### 任务

1. 地图生成优先读取 `scenarios.knowledge_graph.scenes`。
2. 如旧数据仍在 `scenario_assets.scenes`，提供兼容适配。
3. 清理 `MAP_GEN_SYSTEM_PROMPT` 乱码，统一输出 snake_case 字段。
4. fallback 生成器继续可用，并能处理 scene 缺少 exits、NPC、clue 的情况。
5. 地图节点内部保留引用字段时，区分内部引用和玩家显示字段。

### 测试命令

```bash
python -m pytest tests/server/test_map.py -q
python -m pytest tests/server/test_scenario_import.py -q
```

### 验收

- 只有 `knowledge_graph.scenes` 的剧本也能生成地图。
- 无 DeepSeek key 时 fallback 仍生成节点和边。
- 生成接口返回中文正常，无乱码 prompt 残留。

## Batch Map-4：移动事务、版本屏障与幂等初始化

### 目标

让地图状态变更和核心事务时序对齐，避免移动状态早于裁决或乱序投影。

### 允许改动文件方向

- `src/server/map_persistence.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `src/server/events/events_registry.py`
- `tests/server/test_map.py`
- `tests/server/test_projection.py`
- `tests/server/test_host_room_lifecycle.py`

### 任务

1. 修正 `init_room_map_state` 幂等返回值，重复初始化不清空探索状态。
2. 移动成功后统一更新位置、explored 和地图版本。
3. 地图事件 payload 带 `mapVersion` 或可比较的状态版本。
4. 断线重连时按版本应用地图补丁，旧事件不能覆盖新状态。
5. 如 StateService 负责统一版本，应通过 StateService 包装地图变更。
6. 保留 Engine 是玩家移动唯一落库路径的规则。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_projection.py -q
python -m pytest tests/server/test_host_room_lifecycle.py -q
```

### 验收

- 裁决失败不会移动角色。
- 重复开局不会重置地图状态。
- WS 地图事件顺序可验证，重连后最终状态正确。

## Batch Map-5：Host 操作校验与审计

### 目标

把 Host 的 reveal、hide、force move 从“直接写表”加固为“有鉴权、有校验、有审计、有安全投影”。

### 允许改动文件方向

- `src/server/host/router_host.py`
- `src/server/map_persistence.py`
- `src/server/events/event_log.py`
- `tests/server/test_map.py`
- `tests/server/test_host.py`
- `tests/server/test_event_log.py`

### 任务

1. reveal/hide 前校验 room map 已存在、node_id 属于该地图。
2. force move 前校验 character 属于该 room，target node 属于该地图。
3. Host 操作写入事件日志或审计记录，含操作者、操作类型、目标和时间。
4. `s2c_map_revealed` 不携带完整节点内容，只通知刷新或安全摘要。
5. 操作失败时不发送 WS 事件。

### 测试命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_host.py tests/server/test_event_log.py -q
```

### 验收

- 非房主、非 admin 不能执行 Host 地图操作。
- 非本房间角色不能被强制移动。
- 不存在节点不能被 reveal 或移动。
- 日志可追踪 Host 操作。

## Batch Map-6：前端地图体验对齐

### 目标

在不做大型 UI 改造的前提下，让 Host 和 Player 地图页面准确反映后端安全状态。

### 允许改动文件方向

- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/shared/types.ts`
- `src/client/src/api.ts`
- 必要的 CSS 文件

### 任务

1. PlayerMapPanel 处理 401、403、no map、no current position、moving 五类状态。
2. PlayerMapPanel 不依赖后端返回未过滤 `hasClues`、`hasNpcs`。
3. HostMapPanel 对 reveal、hide、force move 的失败结果给出可见反馈。
4. 地图事件到达后按安全接口重新拉取，不直接信任 WS payload 中的隐藏信息。
5. 修复地图相关中文乱码文案。

### 测试命令

```bash
cd src/client
npm run build
npm run test
```

### 验收

- 前端类型检查通过。
- Player 地图不会因字段收紧而崩溃。
- Host 地图操作失败时页面不显示假成功。

## Batch Map-7：端到端验收

### 目标

验证完整跑团空间链路可以从地图生成走到玩家移动，并且双端投影一致。

### 手动验收流程

1. Admin 导入一个带 scenes 的剧本。
2. Admin 生成地图并确认。
3. Host 创建房间并选择该剧本。
4. Player 加入房间并绑定角色。
5. Host 开局，系统初始化地图状态。
6. Player 打开地图，只看到安全投影。
7. Player 移动到相邻节点。
8. Engine 裁决成功，Host 地图和 Player 地图都刷新。
9. Host 隐藏一个节点，Player 不再看到该节点详情。
10. Host 强制移动角色，日志中能看到该操作。

### 回归命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_room_security.py tests/server/test_projection.py tests/server/test_host.py -q
python -m pytest tests/server -q
cd src/client
npm run build
```

### 最终验收

- 核心链路完成：生成地图 -> 开房 -> 加入 -> 开局 -> 玩家看图 -> 移动 -> Host/Player 投影刷新 -> 日志可查。
- 安全链路完成：玩家不能直接写地图状态，不能通过地图读取全图，不能提前看到未发现线索或隐藏 NPC。
- 工程链路完成：新增测试覆盖地图安全、移动、Host 操作和事件刷新。
