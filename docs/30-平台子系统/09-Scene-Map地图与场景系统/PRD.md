# Scene / Map 地图与场景系统 PRD V2.1

## 背景

AI-Keeper 的地图不是传统 VTT 的自由画布，而是跑团主链路里的空间投影层。它把剧本场景、地图模板、房间探索状态、角色当前位置和当前叙事场景组合成不同视角：

- Host 看全图和运行态
- Player 只看安全投影
- AI 只能建议，不直接落库
- Engine/StateService 才能推进真实状态

当前仓库已经具备地图生成、房间地图初始化、玩家移动入口、Host 全图和基础事件，但文档和实现边界仍需加固，尤其是鉴权、读接口副作用、DTO 脱敏、版本契约和审计链路。

## 当前阶段说明

本 PRD 对应 `P0 主链路 + 地图投影安全风险识别版`。

本轮目标是把地图系统收束成可以交给工程执行的主链路版本，不追求多楼层编辑器、动态光照、战棋网格等外围能力。

## 产品目标

1. 让 confirmed 地图模板可以稳定支撑房间开局。
2. 让玩家地图只返回安全投影，不出现剧透和越权。
3. 让玩家移动进入 `意图 -> 裁决 -> 状态变更 -> 投影 -> 日志` 主链路。
4. 让 Host 拥有可监管、可审计的显隐与急救式强制移动能力。
5. 让地图状态与当前场景状态衔接清晰，但不彼此越权。
6. 让地图事件具备稳定的版本和载荷契约，支持重连与回放。

## 非目标

- 不做动态光照、视野遮挡、3D 地图
- 不做完整战棋网格和精确距离规则
- 不让玩家编辑地图结构
- 不让 Host 直接承担规则裁决
- 不让 AI 直接写 `room_map_state`、`character_map_positions`、`room_scene_state`
- 不把线索正文、隐藏 NPC、世界真相字段放进玩家地图响应

## 角色与权限

| 角色 | 能力 | 限制 |
| --- | --- | --- |
| Admin | 生成、编辑、确认剧本地图模板 | 不参与房间内实时裁决 |
| Host | 查看全图、显隐节点、急救式强制移动 | 操作必须可审计；不能把全图直接投给玩家 |
| Player | 查看私人安全地图、提交移动请求 | 不能直接写位置、探索、显隐状态 |
| AI-Keeper | 给出地图/场景建议、叙事建议 | 不能直接改真实状态 |
| Engine | 接收移动 intent 并裁决 | 只在裁决结果成立后推进地图状态 |
| StateService | 管理 `room_scene_state` | 不负责生成地图模板 |

## 模块边界

| 边界 | Scene / Map 负责 | 不负责 |
| --- | --- | --- |
| Room | 房间开局时挂接 confirmed map | 房间成员、ready、start 规则 |
| User | 消费 token、角色身份 | 账号体系本身 |
| Transaction | 移动后发布安全事件、推进版本 | 统一事务引擎的定义 |
| Projection | 产出 Player/Host 地图视图 | 其他模块的投影定义 |
| State | 地图运行态、位置与场景衔接 | 角色数值、道具、线索正文 |
| Journal | 输出地图事件与审计字段 | 回放 UI 编排 |

## 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 | `knowledge_graph.scenes` | 剧本语义源，是地图生成首选输入 |
| L1 | `scenario_maps` | 剧本级地图模板，状态为 `draft/confirmed` |
| L2 | `room_map_state` | 房间级地图运行态，保存 `explored_nodes`、`hidden_nodes`、`state_version` |
| L3 | `character_map_positions` | 角色当前位置，仅受控链路可写 |
| L4 | `room_scene_state` | 当前叙事场景、已访问场景、公开事实 |
| L5 | `PlayerMapView` | 给玩家的安全投影 |
| L6 | `HostMapView` | 给 Host 的监管视图 |
| L7 | 地图事件 | 只传递安全摘要和版本，不传完整剧透数据 |
| L8 | 地图生成草稿 | AI 或 fallback 产出的中间层，只能落到 draft |

## DTO 契约

### `MapNodePublicDTO`

最小公开摘要，用于公共列表或安全占位：

- `nodeId`
- `label`
- `position`
- `isStart`

### `MapNodePlayerDTO`

玩家视图节点，允许字段：

- `nodeId`
- `label`
- `position`
- `explored`
- `isCurrent`
- `isAdjacent`
- `safeHint`
- `movementState`

禁止字段：

- 原始 `npcsPresent`
- 原始 `cluesAvailable`
- 隐藏描述
- Host 注释
- AI 草稿字段

### `MapNodeHostDTO`

Host 全图节点，可含：

- 节点基础信息
- 边关系
- 当前显隐状态
- 已探索状态
- 角色占位信息
- 场景/线索/NPC 的内部引用

### `MapNodeInternalDTO`

仅服务端内部使用，可含调试或原始引用字段，不得直接下发前端。

## 状态语义

| 状态 | 取值 | 说明 |
| --- | --- | --- |
| `template_status` | `draft` / `confirmed` | 剧本地图模板是否可用于开局 |
| `node_visibility` | `normal` / `hidden` | 玩家地图是否允许展示该节点 |
| `player_node_state` | `current` / `explored` / `adjacent` / `unknown` | 玩家对节点的认识层级 |
| `movement_state` | `allowed` / `blocked` / `locked` / `requires_check` | 当前可否发起移动以及原因 |

补充规则：

- `hidden` 只控制地图可见性，不等于线索或 NPC 被删除。
- `adjacent` 只表示允许尝试到达，不自动等于场景切换。
- `requires_check` 代表动作可提交，但需 Rule/Engine 二次判定。

## 初始位置责任

玩家初始地图位置由显式链路负责，优先级如下：

1. 房间开局时根据 start node 初始化
2. 玩家入房并绑定角色时按规则补齐
3. Host 急救恢复或系统补偿链路写入

`GET /api/map/{room_id}` 不是初始化入口。若当前角色没有位置，接口应返回 `no_current_position` 或安全空态，不得在读取时偷偷写库。

## 地图移动与场景切换边界

- 地图移动成功，表示角色空间位置变化成立。
- `current_scene` 是否切换，要交给 `StateService` 或事务链路判断。
- Scene/Map 不直接写 `room_scene_state.current_scene`。
- 某些节点可以映射到场景，但“进入节点”与“叙事切场景”不是同一个动作。

## Host 显隐与强制移动语义

### reveal / hide

- 只改变玩家地图里该节点是否可见。
- 不直接释放 NPC、线索正文或真相字段。
- 操作后必须推进 `mapVersion` 并记录审计。

### force move

- 仅作为急救式调度能力。
- 必须校验目标角色属于房间、目标节点属于房间地图。
- 必须记录 `reason`，前端建议加显式确认。
- 失败不应写位置，也不应发成功事件。

## 关键用户故事

### 1. Admin 生成并确认地图

Admin 从已导入剧本中生成 draft map，必要时修正节点和边，再确认成 confirmed。

验收标准：

- `knowledge_graph.scenes` 可直接出图
- 无场景数据时返回可理解错误
- confirmed 后可供房间开局使用

### 2. Host 开局并挂接地图

Host 创建房间并开局，系统用 confirmed map 初始化 `room_map_state`。

验收标准：

- 无 confirmed map 时返回稳定空态或明确提示
- 重复开局/重入不重置已探索状态

### 3. Player 查看安全地图

Player 打开地图，只能看到当前位置、已探索节点、公开相邻节点和安全提示。

验收标准：

- 无 token、无效 token、跨房间 token 不能读地图
- 玩家响应不包含隐藏 NPC、未发现线索正文、真相字段
- 地图 GET 不写库

### 4. Player 提交移动

Player 点击相邻节点提交移动，动作进入 Engine intent，裁决成功后再更新位置与探索状态。

验收标准：

- 非相邻、隐藏、锁定节点移动被拒
- 裁决失败不改位置
- 成功后发出带 `mapVersion` 的安全事件

### 5. Host 显隐和强制移动

Host 可以调舞台，但所有操作都要可校验、可追踪、可回放。

验收标准：

- reveal/hide 只能操作本房间地图节点
- force move 只能作用于本房间角色
- 操作日志可查操作者、对象、原因、版本、时间

## 接口方向

| 接口 | 调用方 | 作用 | 权限 |
| --- | --- | --- | --- |
| `POST /api/admin/scenarios/{scenario_id}/map/generate` | Admin | 生成 draft map | admin |
| `GET /api/admin/scenarios/{scenario_id}/map` | Admin | 查看地图草稿/确认图 | admin |
| `PATCH /api/admin/scenarios/{scenario_id}/map` | Admin | 编辑 draft map | admin |
| `POST /api/admin/scenarios/{scenario_id}/map/confirm` | Admin | 确认地图 | admin |
| `GET /api/map/{room_id}` | Player | 读取安全地图投影 | player token |
| `POST /api/map/{room_id}/move` | Player | 提交移动 intent | player token |
| `GET /api/host/{room_id}/map/full` | Host | 读取全图和运行态 | owner/admin |
| `POST /api/host/{room_id}/map/reveal` | Host | 切换节点显隐 | owner/admin |
| `POST /api/host/{room_id}/map/move-character` | Host | 急救式强制移动 | owner/admin |

## 事件契约

### `s2c_map_updated`

用途：通知地图投影应刷新。

建议载荷：

```json
{
  "type": "s2c_map_updated",
  "roomId": "room_xxx",
  "mapVersion": 12,
  "reason": "move_resolved",
  "actorCharacterId": "char_xxx"
}
```

约束：

- 面向 `party`
- 不携带完整节点详情
- 前端收到后应重新拉取对应安全视图

### `s2c_player_moved`

用途：通知某角色位置变化。

建议载荷：

```json
{
  "type": "s2c_player_moved",
  "roomId": "room_xxx",
  "mapVersion": 12,
  "characterId": "char_xxx",
  "fromNodeId": "node_a",
  "toNodeId": "node_b",
  "forced": false
}
```

约束：

- 不附带目标节点完整信息
- `forced=true` 时仍需安全载荷

### `s2c_map_revealed`

用途：通知节点显隐变化。

建议载荷：

```json
{
  "type": "s2c_map_revealed",
  "roomId": "room_xxx",
  "mapVersion": 13,
  "nodeId": "node_secret_door",
  "visible": true
}
```

约束：

- 只表达显隐结果
- 不在事件里塞节点描述、NPC、线索正文

## Host 审计字段契约

Host 地图操作至少应记录：

- `operation`：`reveal` / `hide` / `force_move`
- `roomId`
- `actorAccountId`
- `actorRole`
- `targetNodeId`
- `targetCharacterId`
- `fromNodeId`
- `toNodeId`
- `reason`
- `mapVersion`
- `createdAt`

其中：

- `force_move.reason` 必填
- `force_move` 建议前端提供 `confirm=true` 风险确认位

## 异常与安全行为

| 场景 | 期望行为 |
| --- | --- |
| 房间无 confirmed map | 返回 `no_map` 空态或稳定错误，不报 500 |
| 无 token 请求玩家地图 | 返回 401/403 或安全空态，但绝不返回完整节点列表 |
| 无效 token 请求玩家地图 | 返回 401/403，不退化成匿名全图 |
| 玩家无当前位置 | 返回 `no_current_position`，不在 GET 中自动写入 |
| 非相邻节点移动 | 返回 400/409，不改位置 |
| 隐藏节点移动 | 返回 400/409，不改位置 |
| Host 操作非法角色/节点 | 返回 400/404/403，不写状态，不发成功事件 |

## 验收标准

1. `GET /api/map/{room_id}` 为纯读接口，不产生位置、探索或版本写入。
2. 玩家地图接口不会因 token 异常而退化成匿名全图读取。
3. `PlayerMapView` 不返回原始 `npcsPresent`、原始 `cluesAvailable`、真相字段。
4. 地图生成优先消费 `knowledge_graph.scenes`，兼容旧字段但不再绑定旧字段为主源。
5. 玩家移动必须进入 Engine/Transaction 链路，不能由路由直接改位置。
6. 移动成功后只推进地图位置与探索状态；`current_scene` 的变化由 StateService/事务链路决定。
7. Host reveal/hide/force move 具备鉴权、目标归属校验、版本推进和审计记录。
8. 地图事件带稳定 `mapVersion`，前端可据此避免乱序覆盖。
9. Host 与 Player 获取的是不同 DTO 视图，不能复用全图接口充当玩家接口。
10. 端到端可跑通：生成地图 -> 开房 -> 入房 -> 开局 -> 看图 -> 移动 -> 双端刷新 -> 日志可查。
