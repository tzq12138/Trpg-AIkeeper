# Scene / Map 地图与场景系统 PRD V2.0

## 背景

AI-Keeper 的地图不是传统 VTT 的单纯画布，而是核心跑团链路中的空间投影层。它把剧本场景、探索进度、角色位置和当前场景状态组合成不同视角：Host 需要全局监督，Player 只能看到安全投影，AI 只能提出建议，Engine 和 StateService 才能推动真实状态变化。

当前仓库已有地图生成、Host 全图、玩家迷雾、移动 intent 和场景状态表，但还存在安全边界不稳的问题。本 PRD 的第一目标是先堵住剧透和越权，再提升地图体验。

## 产品目标

1. 让 Host 能用 confirmed 剧本地图支撑开局和跑团监督。
2. 让 Player 能在不剧透的前提下理解当前位置、可探索方向和移动结果。
3. 让移动行为进入 `意图 -> 裁决 -> 状态变更 -> 投影 -> 日志` 主链路。
4. 让当前场景、已访问场景和公开事实通过 StateService 管理。
5. 让地图事件具备版本和审计基础，支持后续断线重连和回放。

## 非目标

- 不做动态光照、3D 地图、完整战棋网格。
- 不让玩家编辑地图结构。
- 不让 Host 端承载规则裁决。
- 不把线索正文、NPC 秘密或世界真相存进玩家地图响应。
- 不绕过 Clue、NPC、State、Transaction 模块做状态结算。

## 角色与权限

| 角色 | 能力 | 限制 |
| --- | --- | --- |
| Admin | 生成、编辑、确认剧本地图模板 | 不参与房间内规则裁决 |
| Host | 查看全图、控制节点显隐、必要时强制移动角色 | 操作必须可审计，不能把全图投影给玩家 |
| Player | 查看自己的安全地图投影，提交移动 | 不能直接写位置、探索节点、隐藏节点 |
| AI-Keeper | 建议场景变化、移动叙事、探索后果 | 不能直接落库，不能绕过 SpoilerGuard |
| Engine | 接收移动 intent，校验并裁决 | 只在成功后推动地图状态变化 |
| StateService | 管理当前场景和公开状态 | 不负责生成地图模板 |

## 范围

### 本轮进入

- 剧本地图模板生成、编辑、确认。
- 房间开局初始化 `room_map_state`。
- 玩家安全地图投影。
- 玩家移动 intent 和相邻校验。
- Host 全图监督、节点显隐、强制移动。
- 当前场景状态：`current_scene`、visited、public facts、scene variables。
- 地图事件和场景事件的日志沉淀。

### 本轮暂不进入

- 多楼层地图编辑器。
- 真实光照、遮挡、视野锥。
- 地图素材市场。
- 玩家协作白板。
- 完整战斗网格和精确距离测量。

## 关键用户故事

### Admin 生成地图

Admin 在后台选择一个已导入剧本，点击生成地图。系统从结构化场景数据中生成节点和边，保存为 draft。Admin 可以查看、修正并确认地图。只有 confirmed 地图能进入房间开局。

验收：PDF 导入产出的结构化场景可以生成地图；无场景数据时返回可理解错误；生成结果字段稳定。

### Host 开局并监督地图

Host 创建房间并选择剧本。开局时，如果剧本有 confirmed 地图，系统初始化房间地图状态。Host 进入舞台后可以看到完整节点、边、角色位置、已探索节点和隐藏节点。

验收：非房主不能访问 Host 全图；重复开局或重入不会重置已探索状态。

### Player 查看安全地图

Player 打开地图 tab，系统使用玩家 token 和角色身份构建地图投影。玩家只看到已探索节点和安全的相邻节点提示，不看到非相邻隐藏区域，不看到未发现线索正文或 NPC 秘密。

验收：无 token、无效 token、跨房间 token 都不能拿到完整地图。

### Player 移动

Player 在地图上点击相邻可移动节点，前端提交 `POST /api/map/{room_id}/move`。后端先做轻量校验，再提交 move intent。Engine 裁决成功后更新角色位置和 explored，并通过 WS 通知 Host 与 Player。

验收：非相邻移动、隐藏节点移动、无当前位置移动都被拒绝；失败裁决不改变位置。

### Host 显隐和强制移动

Host 可以隐藏或显示节点，也可以在救场时强制移动角色。操作必须校验目标合法性，记录事件，并只向玩家发送安全投影变化。

验收：强制移动只能作用于本房间角色和已有节点；日志能查到操作者、目标和结果。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| MAP-FR-1 | 系统能从结构化场景生成 `scenario_maps` draft，并支持确认 | P0 |
| MAP-FR-2 | 房间开局时能从 confirmed map 初始化 `room_map_state` | P0 |
| MAP-FR-3 | 玩家地图接口必须要求有效玩家身份 | P0 |
| MAP-FR-4 | 玩家地图响应必须经过迷雾和防剧透过滤 | P0 |
| MAP-FR-5 | 地图查询接口不得改变数据库状态 | P0 |
| MAP-FR-6 | 玩家移动必须进入 Engine intent，不允许直接写位置 | P0 |
| MAP-FR-7 | 移动成功后才更新位置、探索节点和地图事件 | P0 |
| MAP-FR-8 | Host 全图、显隐、强制移动必须做 owner/admin 鉴权 | P0 |
| MAP-FR-9 | Host 操作必须校验节点和角色归属 | P1 |
| MAP-FR-10 | 地图和场景事件必须进入日志或审计链路 | P1 |
| MAP-FR-11 | 地图事件必须具备稳定 schema 和版本信息 | P1 |
| MAP-FR-12 | 前端地图需要显示 no map、鉴权失败、移动中和移动失败状态 | P1 |

## 接口方向

| 接口 | 使用方 | 响应/效果 | 权限 |
| --- | --- | --- | --- |
| `POST /api/admin/scenarios/{scenario_id}/map/generate` | Admin | 生成 draft map | admin |
| `GET /api/admin/scenarios/{scenario_id}/map` | Admin | 查看当前地图草稿或确认图 | admin |
| `PATCH /api/admin/scenarios/{scenario_id}/map` | Admin | 修改 draft nodes/edges | admin |
| `POST /api/admin/scenarios/{scenario_id}/map/confirm` | Admin | 确认地图 | admin |
| `GET /api/map/{room_id}` | Player | 返回安全地图投影 | player token |
| `POST /api/map/{room_id}/move` | Player | 提交 move intent | player token |
| `GET /api/host/{room_id}/map/full` | Host | 返回完整地图和运行态 | owner/admin |
| `POST /api/host/{room_id}/map/reveal` | Host | 设置节点显隐 | owner/admin |
| `POST /api/host/{room_id}/map/move-character` | Host | 救场强制移动 | owner/admin |

## 事件方向

| 事件 | Audience | 用途 | 约束 |
| --- | --- | --- | --- |
| `s2c_player_moved` | party | 通知角色位置变化 | 不包含隐藏节点详情 |
| `s2c_map_updated` | party | 通知地图状态刷新 | 应带版本和安全摘要 |
| `s2c_map_revealed` | party | 通知节点显隐变化 | 不应暴露完整节点内容 |
| `s2c_scene_sync` | party | 同步当前场景 | 只包含公开场景信息 |
| `s2c_reveal_transaction` | host | Host 演出裁决过程 | 玩家私密投影不得早于 Host 演出泄露 |

## 数据边界

| 字段类别 | Host 可见 | Player 可见 | 说明 |
| --- | --- | --- | --- |
| 节点名称 | 是 | 已探索或安全相邻节点可见 | 隐藏节点不返回 |
| 节点描述 | 是 | 仅已探索且经过安全过滤后可见 | 不放未发现真相 |
| NPC 列表 | 是 | 仅公开出现或已遭遇 NPC 可见 | 不暴露隐藏 NPC |
| 线索列表 | 是 | 仅已发现或公开线索摘要可见 | 不暴露未发现线索 |
| 节点坐标 | 是 | 可见节点可见 | 用于绘图 |
| 边关系 | 是 | 可移动方向可见 | 不暴露非可见区域结构 |
| 当前角色位置 | 是 | 本人位置可见，团队共享策略另行限制 | 避免泄露私密分线 |
| 当前场景公开事实 | 是 | 是 | 由 StateService 管理 |

## 异常与安全

| 场景 | 期望行为 |
| --- | --- |
| 无地图房间 | 返回 no map 空态，不报 500 |
| 无 token 请求玩家地图 | 返回 401 或安全空态，不返回完整节点 |
| 无效 token 请求玩家地图 | 返回 401 或 403 |
| 跨房间 token | 返回 403 |
| 目标节点不存在 | 返回 400 |
| 目标节点被 Host 隐藏 | 返回 400 |
| 目标节点非相邻 | 返回 400 |
| 玩家无当前位置 | 不在 GET 中写入；由显式初始化或移动入口处理 |
| Engine 裁决失败 | 不更新位置，不标记 explored |
| Host 强制移动非法角色 | 返回 404 或 403 |

## 验收标准

1. 玩家不能通过无 token 或伪造 token 读取完整地图。
2. 玩家地图响应不包含未发现线索正文、隐藏 NPC、真相字段和非可见节点详情。
3. `GET /api/map/{room_id}` 不产生数据库写入。
4. 玩家移动必须生成 action，并由 Engine 裁决后改变位置。
5. 移动失败、非相邻、隐藏节点不会改变 `character_map_positions`。
6. Host reveal/hide 和 force move 有鉴权、校验、版本推进和日志记录。
7. 地图事件触发后 Host 与 Player 前端能刷新到各自正确视图。
8. 断线重连时，地图状态不会因为旧事件覆盖新状态。
9. 场景状态变化通过 StateService 写入 `room_scene_state`。
10. 端到端链路可完成：生成地图 -> 开房 -> 加入 -> 开局 -> 看图 -> 移动 -> 双端刷新 -> 日志可查。
