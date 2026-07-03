# 地图探索系统计划

## Summary
- 第一版做“剧本空间地图”：AI 根据剧本结构生成地图草稿，Host 确认后保存，玩家在跑团中以迷雾方式探索。
- 地图移动纳入场景回合制：玩家点击移动不是立即改位置，而是提交 `intent_type=move`，由 AI/规则统一结算并叙事。
- 玩家视野采用队伍共享迷雾：任一玩家探索过的区域，全队可见；相邻区域可见但隐藏细节。
- Host 地图页是全局监督视角：看到全图、玩家位置、探索状态，并能手动公开/隐藏区域。
- 本轮不做完整拖拽地图编辑器、不做复杂素材挂点、不做个人独立迷雾。

## Key Changes
- 替换当前内存地图：
  - 废弃 `map_store.py` 的会话内存状态，改为 PostgreSQL 持久化。
  - 新增地图表：`scenario_maps`、`map_nodes`、`map_edges`、`room_map_state`、`character_map_positions`。
  - 房间开始时从已确认的剧本地图初始化房间地图状态；所有玩家默认在起点区域。
  - 队伍共享探索状态记录在 `room_map_state`，角色当前位置记录在 `character_map_positions`。

- 剧本地图生成与确认：
  - 新增 Admin/Host 入口：从 `knowledge_graph.scenes`、NPC、线索、素材元数据生成地图草稿。
  - 有 DeepSeek 配置时用 AI 生成节点、连接、起点和区域描述；无 AI 时用 Python 规则按场景顺序生成线性/网状草稿。
  - Host 可编辑节点名称、描述、起点、公开状态、相邻连接，然后点“确认地图”。
  - 未确认地图不能用于正式房间；房间无地图时玩家页显示静态骨架和提示。

- 玩家地图探索：
  - `GET /api/map/{room_id}` 返回玩家视野：已探索节点、当前位置、可移动相邻节点、隐藏节点数量。
  - `POST /api/map/{room_id}/move` 改为兼容包装：校验 token 和目标节点后，提交 `intent_type=move` 行动，不立即移动。
  - 玩家提交移动后显示“移动已提交，等待本轮结算”；结算完成收到地图更新后刷新位置。
  - 可移动节点只显示名称和简短提示；未探索节点不显示完整描述、线索、NPC。

- AI/规则接入：
  - `move` 行动进入当前场景回合，与调查、对话、技能检定一起统一结算。
  - 规则层校验目标节点是否相邻、是否已公开、是否被 Host 锁定；失败则拒绝该行动。
  - 移动成功后更新角色位置，标记目标节点为队伍已探索，并递增房间 `state_version`。
  - 地图节点的线索/NPC 不“进入即公开”；只作为本轮 AI 叙事上下文，由 AI/触发器决定是否发放线索或战术提示。

- Host 地图监督：
  - HostStage 的地图/资料相关面板新增全局地图视图：所有节点、连接、玩家当前位置、探索状态。
  - Host 可手动公开/隐藏节点，修正 AI 生成错误，或把玩家强制移动到某区域。
  - Host 操作写事件日志，并通过 WS 推送 `s2c_map_updated` 给玩家和 Host。
  - 地图页保留 Bauhaus 视觉风格，第一版使用节点图/列表混合，不做复杂拖拽布局。

## API / Interfaces
- 新增：
  - `POST /api/admin/scenarios/{scenario_id}/map/generate`
  - `GET /api/admin/scenarios/{scenario_id}/map`
  - `PATCH /api/admin/scenarios/{scenario_id}/map`
  - `POST /api/admin/scenarios/{scenario_id}/map/confirm`
  - `GET /api/map/{room_id}`
  - `POST /api/map/{room_id}/move`
  - `POST /api/host/{room_id}/map/reveal`
  - `POST /api/host/{room_id}/map/move-character`

- 新增事件：
  - `s2c_map_updated`
  - `s2c_player_moved`
  - `s2c_map_revealed`

- `PlayerIntent.intent_type` 继续使用已有 `move`，`params` 至少包含：
  - `targetNodeId`
  - `fromNodeId`
  - `roomId`

## Test Plan
- 后端：
  - 从剧本 `knowledge_graph.scenes` 生成地图草稿。
  - Host 确认地图后，房间开始时初始化起点、连接和队伍探索状态。
  - 玩家只能移动到相邻且可见节点。
  - 移动提交后行动进入当前回合，不立即改位置。
  - 回合结算成功后更新角色位置、队伍探索状态和事件日志。
  - 非相邻移动、未公开节点移动、无地图房间移动返回明确错误。
  - Host 手动公开/隐藏节点后玩家视野正确变化。

- 前端：
  - `npm run build` 通过。
  - 手动验证：Admin/Host 生成地图、确认地图、开房间、玩家进入地图页。
  - 手动验证：玩家只看到已探索和相邻区域，移动提交后等待结算。
  - 手动验证：结算后玩家位置刷新，Host 全图能看到玩家移动。
  - 手动验证：Host 手动公开区域后，玩家地图实时更新。

## Assumptions
- 地图是“场景节点图”，不是精确战棋网格。
- v1 迷雾按队伍共享，不做个人独立视野。
- v1 地图编辑只做节点、连接、起点、公开状态，不做拖拽坐标编辑和素材挂点。
- 线索/NPC 的真正公开仍由 AI 叙事和规则触发器决定，地图只提供空间上下文。
