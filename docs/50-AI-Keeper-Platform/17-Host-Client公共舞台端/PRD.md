# Host Client 公共舞台端 PRD V2.0

## 背景

Host Client 是 AI-Keeper 跑团体验的公共舞台。它既是房主控制台，也是玩家共同观看的主持端：房主在这里看队伍状态、接收 AI/规则裁决后的公共演出、监管地图、处理遭遇、查看日志和管理检查点。

当前代码已经有 `HostCreate`、`HostLobby`、`HostStage`、HUD、Host WS、HostStore、地图面板、遭遇面板、日志面板和相关后端接口。但现状仍有明显缺口：前端中文乱码和 TSX 字符串风险会阻断可用性，Host 事件协议混合标准 `s2c_*` 与内部 frame，Host 操作审计与 State/Projection 口径还没有完全收口。

## 目标

1. 让 Host 可以完成 `创建房间 -> 等待室 -> 开局 -> 公共舞台 -> 日志/地图/遭遇` 主流程。
2. 让 Host 端只负责演出、监管和授权操作，不承担规则裁决和世界状态真相写入。
3. 让 Host WS、Host REST、日志、导出都经过 owner/admin 鉴权。
4. 让 Host 舞台可以稳定展示 reveal transaction、公共观察、地图变化、遭遇变化和玩家 HUD。
5. 让 Host-only、Player-only、Party 事件边界清晰，避免私密内容被错误投影。
6. 让 Host 操作具备审计路径，方便长团恢复和排障。

## 非目标

- 不在 Host 前端实现规则判定、骰子结算或伤害计算。
- 不在 Host 前端直接修改角色运行时数值。
- 不把 Host 舞台做成完整导演软件或直播系统。
- 不在本轮实现多 Host 协作。
- 不把 Database tab 扩展成完整世界书编辑器。
- 不让 Host 端绕过 Projection 直接把内容发给 Player。
- 不用前端隐藏字段保护私密信息。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Host | 创建房间、管理等待室、开局、看 HUD、播放公共叙事、监管地图和遭遇、查日志 | 直接改规则结果、读取玩家端 token、把 Host-only 真相公开给玩家 |
| Admin | 以管理身份进入 Host 能力排障和维护 | 无审计篡改日志或隐藏权限来源 |
| Player | 间接受益于 Host 舞台输出的公共叙事和地图揭示 | 访问 Host Client、Host WS、Host API |
| AI-Keeper | 向 Host 投递已安全处理的 reveal 和建议 | 直接绕过 Host 把隐藏真相投给 Player |
| Future Observer | 延迟观看公共舞台 | 控制房间或读取 Host-only 内容 |

## 产品范围

### 本轮进入

- Host 创建房间和保存 `owner_token`。
- Host 等待室：玩家列表、ready、剧本选择、开局、force_start。
- Host Stage：叙事投影、骰子/步骤展示、玩家 HUD、队列状态。
- Host WS 鉴权和初始 HUD。
- 暂停/恢复、紧急重置、retry-turn 的基础反馈。
- 地图全图、揭示/隐藏、强制移动。
- 遭遇建议确认、下一轮、结束、临时 NPC。
- 日志时间线、事件详情、检查点、恢复、导出。
- 中文文案修复和前端 build 恢复。

### 本轮不做

- 多 Host 协同权限。
- 直播观众端。
- 大屏独立投影模式。
- 完整音效/灯光/镜头导演台。
- 完整世界书和资料库编辑。
- Host 插件系统。

## 核心流程

### 创建房间

1. Host 打开 `/host/create`。
2. 未登录时跳转登录。
3. 后端校验账号角色为 host 或 admin。
4. Host 选择一个可用剧本。
5. 前端提交 `POST /api/rooms`。
6. 后端创建 room、owner token、owner account 关系。
7. 前端保存 `owner_token` 并进入 `/host/{roomId}`。

### 等待室与开局

1. HostLobby 调用 `GET /api/rooms/{room_id}` 获取房间和玩家摘要。
2. Host WS 订阅 lobby snapshot，轮询 HUD 作为降级。
3. Host 可在 lobby 状态切换剧本。
4. 玩家加入和 ready 后，Host 看到成员状态变化。
5. 普通 start 要求至少一名玩家且已 ready。
6. 显式 force_start 作为急救能力。
7. start 成功后房间 active，首回合创建，Host 进入 Stage。

### 公共舞台

1. HostStage 建立 Host WS，并先拉取 `/api/host/{room_id}/hud`。
2. Host WS 推送 `host_state_update` 作为 UI frame，源头仍应可追到标准事件或 DB 状态。
3. `s2c_reveal_transaction` 被转换为舞台演出步骤：骰子、叙事、状态摘要。
4. `s2c_public_observation` 和 `s2c_team_message` 进入公共叙事流。
5. `s2c_map_*` 触发地图面板刷新。
6. `s2c_encounter_*` 触发遭遇面板状态变化。
7. Host 暂停只影响舞台播放，不修改权威裁决结果。

### 地图与遭遇

1. HostMapPanel 调用 `/api/host/{room_id}/map/full` 查看全图。
2. Host 可揭示/隐藏节点，后端写入地图状态并发 map 事件。
3. Host 可强制移动角色，用于纠错或主持干预。
4. EncounterPanel 接收 AI/规则建议，Host 确认后创建 active encounter。
5. Host 可新增 NPC、进入下一轮或结束遭遇。
6. 每个 Host 操作都应进入事件或审计链路。

### 日志与恢复

1. HostLogsPanel 调用 `/api/rooms/{room_id}/timeline` 查看完整房间时间线。
2. Host 可筛选事件类型和关键词。
3. Host 可查看单条事件 payload。
4. Host 可创建手动检查点。
5. Host 可恢复检查点，恢复操作必须确认并记录事件。
6. Host 可导出 public markdown 或 full json；public 版本必须脱敏。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| HC-FR-1 | Host 创建房间必须要求 host/admin 账号。 | P0 |
| HC-FR-2 | Host 创建房间必须选择有效剧本。 | P0 |
| HC-FR-3 | 创建房间成功后前端保存 `owner_token` 到当前身份槽。 | P0 |
| HC-FR-4 | Host Lobby 必须展示 room code、剧本、玩家、调查员、ready 状态。 | P0 |
| HC-FR-5 | Host 正常开局必须受玩家人数、剧本和 ready 限制。 | P0 |
| HC-FR-6 | Host force_start 必须是显式操作，并在 UI 上标明风险。 | P0 |
| HC-FR-7 | Host REST 和 WS 必须支持 owner token、owner account、admin 鉴权。 | P0 |
| HC-FR-8 | Host Stage 必须能在无 WS 首帧时通过 HUD API 初始化。 | P0 |
| HC-FR-9 | Host HUD 必须优先展示 runtime state 中的玩家当前状态。 | P0 |
| HC-FR-10 | Host Stage 必须展示 reveal transaction，但不得改写 transaction 结果。 | P0 |
| HC-FR-11 | Host 不得接收或显示 Player-only 私密事件。 | P0 |
| HC-FR-12 | Host 暂停、重置、重试必须有可读反馈和后端鉴权。 | P0 |
| HC-FR-13 | Host 地图全图只对 Host 可见，Player 不得复用该接口。 | P0 |
| HC-FR-14 | Host 地图揭示、隐藏、强制移动必须产生投影或审计记录。 | P0 |
| HC-FR-15 | Host 遭遇确认、下一轮、结束、NPC 创建必须可追踪。 | P0 |
| HC-FR-16 | Host 日志可查完整主持时间线，Player 日志仍按可见性过滤。 | P0 |
| HC-FR-17 | 检查点恢复必须二次确认，并记录恢复事件。 | P0 |
| HC-FR-18 | public 导出不得包含 owner token、player token、Host-only 真相和玩家私密 payload。 | P0 |
| HC-FR-19 | Host 前端中文文案和 TSX 字符串必须恢复到可构建状态。 | P0 |
| HC-FR-20 | Host 事件 adapter 必须把标准事件和 UI frame 边界固定下来。 | P1 |
| HC-FR-21 | Host WS 重连必须有 catch-up 或 HUD 重拉策略。 | P1 |
| HC-FR-22 | Database tab 在接入真实资料库前必须标明为占位或隐藏。 | P1 |

## 接口方向

| 接口或事件 | 当前状态 | 用途 | 备注 |
| --- | --- | --- | --- |
| `POST /api/rooms` | 已有 | 创建房间 | host/admin 账号 |
| `GET /api/rooms/{room_id}` | 已有 | HostLobby 房间摘要 | 不返回 owner token |
| `GET /api/rooms/{room_id}/scenario-options` | 已有 | lobby 选择剧本 | owner/admin |
| `PATCH /api/rooms/{room_id}/scenario` | 已有 | lobby 切换剧本 | active 后禁止 |
| `POST /api/rooms/{room_id}/start` | 已有 | 开局/force_start | owner/admin |
| `GET /api/host/{room_id}/hud` | 已有 | Host HUD | 从 DB/runtime 构建 |
| `POST /api/host/{room_id}/pause` | 已有 | 暂停/恢复舞台 | HostStore 状态 |
| `POST /api/host/{room_id}/reset` | 已有 | 紧急重置舞台 | 不回滚世界状态 |
| `POST /api/host/{room_id}/retry-turn` | 已有 | 重试当前 HostStore transaction | 与 Room turn retry 需区分 |
| `GET /api/host/{room_id}/map/full` | 已有 | Host 全图 | Host-only |
| `POST /api/host/{room_id}/map/reveal` | 已有 | 揭示或隐藏地图节点 | 发 `s2c_map_revealed` |
| `POST /api/host/{room_id}/map/move-character` | 已有 | 强制移动角色 | 发 `s2c_player_moved` |
| `GET /api/host/{room_id}/encounter` | 已有 | 当前遭遇 | Host-only |
| `POST /api/host/{room_id}/encounter/confirm` | 已有 | 确认遭遇 | 发 `s2c_encounter_started` |
| `POST /api/host/{room_id}/encounter/reject` | 已有 | 拒绝建议 | 审计需补强 |
| `POST /api/host/{room_id}/encounter/next-round` | 已有 | 下一轮 | 发 `s2c_encounter_updated` |
| `POST /api/host/{room_id}/encounter/resolve` | 已有 | 结束遭遇 | 发 `s2c_encounter_resolved` |
| `POST /api/host/{room_id}/encounter/npc` | 已有 | 临时 NPC | 事件需补强 |
| `GET /api/rooms/{room_id}/timeline` | 已有 | Host 时间线 | owner/admin |
| `POST /api/rooms/{room_id}/checkpoint` | 已有 | 创建检查点 | owner/admin |
| `POST /api/rooms/{room_id}/restore/{checkpoint_id}` | 已有 | 恢复检查点 | owner/admin |
| `GET /api/rooms/{room_id}/export` | 已有 | 导出 | scope 需安全过滤 |
| `Host WS /ws?role=host` | 已有 | 实时舞台 | ownerToken query 当前可用 |
| `s2c_reveal_transaction` | 已有 | Host 演出事务 | host |
| `s2c_host_snapshot` | 已有 | Host HUD/状态快照 | host |
| `s2c_public_observation` | 已有 | 公共叙事 | party |
| `s2c_team_message` | 已有 | 队内消息 | party |
| `s2c_map_updated/s2c_player_moved/s2c_map_revealed` | 已有 | 地图变化 | party |
| `s2c_encounter_suggested/started/updated/resolved` | 已有 | 遭遇变化 | party 或 host 展示 |

## 数据边界

- `owner_token` 是房主房间凭证，不能写入日志、导出或 Player 响应。
- Host HUD 是展示模型，不是世界状态表。
- HostStore 是舞台播放状态，不是规则事实来源。
- `events` 是可审计投影日志，Host 日志从这里读。
- Host map full view 是 Host-only 读模型。
- Host 操作请求里的 node、character、encounter 参数都需要服务端校验归属。
- public export 是脱敏战报，full export 是管理调试包。

## 权限边界

1. 非 owner/admin 不能访问 Host REST。
2. 非 owner/admin 不能连接 Host WS。
3. Player 不能通过 `owner_token` 为空、错误或 player token 访问 Host 接口。
4. Host 不能直接读取玩家本地 `player_token`。
5. Host 不接收 Player-only 私密状态 patch。
6. Host 可看全图和主持日志，但 public projection/export 不能包含 Host-only 真相。
7. Host 的强制操作必须有事件或审计痕迹。

## 客户端状态模型

| 状态 | 含义 | 进入条件 | 退出条件 |
| --- | --- | --- | --- |
| `not_authenticated` | 未登录或无 Host 权限 | 进入 `/host/create` 无有效账号 | 登录 host/admin |
| `creating` | 正在创建房间 | 提交创建请求 | 创建成功或失败 |
| `lobby_loading` | 等待室加载中 | 进入 `/host/{roomId}` | room 数据返回 |
| `lobby_ready_check` | 等待玩家 ready | room 为 lobby | 所有玩家 ready 或 force_start |
| `starting` | 正在开局 | 点击开始 | active 或错误 |
| `stage_connecting` | 舞台连接中 | 进入 Stage | HUD/WS 成功或失败 |
| `stage_live` | 公共舞台在线 | Host WS 打开 | WS 断开、暂停、离开 |
| `stage_paused` | 舞台暂停 | 点击 pause | 再次 pause 或 reset |
| `stage_error` | 舞台错误 | 鉴权失败、HUD 失败、WS 失败 | 重试、刷新、返回 lobby |
| `map_operating` | 地图操作中 | reveal/hide/move | 操作成功或失败 |
| `encounter_operating` | 遭遇操作中 | confirm/next/resolve/npc | 操作成功或失败 |
| `restoring` | 检查点恢复中 | 确认 restore | 恢复完成或失败 |

## 验收标准

1. host/admin 可以创建房间，player 创建房间返回 403。
2. HostLobby 能显示剧本、玩家、ready 状态和开局限制。
3. 正常 start 创建 active 房间和首回合，force_start 只在显式点击时发生。
4. HostStage 打开后通过 HUD API 或 WS 首帧显示玩家状态。
5. Host WS 无 token、错 token 被拒绝，owner token 连接成功。
6. Host 收到 `s2c_reveal_transaction` 时显示公共演出内容。
7. Host 不显示 `s2c_state_patch`、`s2c_private_notice`、`s2c_action_completed` 等 Player-only 私密 payload。
8. Host map full 接口只允许 owner/admin，Player 不可访问。
9. Host map reveal/move 和 encounter 操作可在事件或日志中追踪。
10. Host timeline/checkpoint/export 均需 owner/admin 鉴权。
11. public export 不含敏感 token、Host-only 真相和玩家私密内容。
12. Host 前端通过 `npm run build`，主要页面中文可读。
