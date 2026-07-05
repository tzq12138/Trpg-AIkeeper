# Player Client 玩家私人端 PRD V2.0

## 背景

AI-Keeper 的玩家端不是普通聊天窗口，而是玩家在网团中的私人调查终端。它要把玩家自由行动、角色卡、私密线索、队内公开信息、地图探索、日志复盘和断线恢复组织在同一个受限界面里。

当前代码已经具备玩家入房、角色绑定、等待室、ready、行动提交、队内消息、WS、角色卡、背包、线索、地图、日志和语音输入的雏形。但玩家端仍有三类关键缺口：前端文案乱码导致不可用，状态版本屏障和重连恢复未闭合，角色/线索/日志/地图的可见性需要与 Projection、State、Clue 模块统一。

## 目标

1. 让玩家可以从加入房间到完成一轮行动闭环，不依赖 Host 手动补救。
2. 让玩家端始终以 `player_token` 和服务端反查身份为准，不信任前端传来的角色身份。
3. 让玩家端只展示 party 公共内容和本人 player-only 内容。
4. 让行动提交、等待、完成、失败、重连恢复都有清晰状态。
5. 让角色当前状态、背包、线索、地图、日志与服务端权威数据一致。
6. 让玩家端成为核心链路的入口：`Player Intent -> Transaction -> State -> Projection -> Journal`。

## 非目标

- 不在玩家端实现规则裁决。
- 不在玩家端直接修改 HP、SAN、背包、地图位置或线索归属。
- 不在玩家端实现 Host 舞台、KP 全图、隐藏真相或剧本编辑。
- 不在本轮实现完整移动 App、社区主页、付费、观众直播、完整语音频道。
- 不把前端本地过滤当成安全方案。
- 不把玩家私人笔记升级为世界事实。

## 用户角色

| 角色 | 需要什么 | 不能做什么 |
| --- | --- | --- |
| Player | 加入房间、绑定角色、ready、提交行动、查看本人资源、接收私密结果、复盘日志 | 直接写状态、伪造角色、看他人私密结果、看 Host-only 真相 |
| Host | 看到玩家是否加入、ready、公开行动和公共结果 | 通过玩家端处理规则或读取玩家本地 token |
| AI-Keeper | 接收玩家意图并生成建议或叙事 | 直接信任玩家端状态或把未发现真相发给玩家 |
| Admin/Ops | 排查玩家端链路问题 | 无审计查看玩家私密 token 或隐藏真相 |
| Future Observer | 只读观看公开内容 | 加入行动、读取玩家私密资源 |

## 产品范围

### 本轮进入

- 房间码加入。
- 登录后角色归属绑定。
- 预设卡、xlsx 上传、现场建卡、剧本模板入房。
- 等待室成员列表、ready、队内消息。
- 开局后进入行动终端。
- 自由行动、战术快捷动作、技能检定、地图移动、道具主张。
- 角色卡、背包、线索、日志、地图 tab。
- Player WS 实时事件。
- `/api/player/reconnect` 和 `/api/player/sync` 的前端接入方向。
- 中文文案修复和基础移动端可用性。

### 本轮不做

- 原生移动端 App。
- 直播观众端。
- 完整语音视频房间。
- 玩家社区、匹配、招募、付费。
- 复杂离线同步。
- 玩家自定义插件面板。

## 核心流程

### 入房与角色绑定

1. Player 打开 `/player/join`。
2. 如果未登录，跳转 `/login`，登录后回到 join。
3. Player 输入 room code 和玩家昵称。
4. Player 选择一种角色来源：预设卡、xlsx 上传、builder、scenario template。
5. 前端提交 `POST /api/player/rooms/{room_id}/join-with-character`。
6. 服务端创建角色、绑定 account、返回 `player_token` 和角色摘要。
7. 前端保存当前身份槽的 `player_token`，进入 `/player/{room_id}/lobby`。

### 等待室

1. Player 进入等待室后调用 `/api/player/character` 和 `/api/player/rooms/{room_id}/join-info`。
2. PlayerWS 订阅 `s2c_room_lobby_snapshot` 和 `s2c_team_message`。
3. Player 点击 ready，前端提交 `ready_toggle` intent。
4. 后端广播新的 lobby snapshot。
5. 房间变为 active 后，玩家自动进入行动页。

### 行动终端

1. Player 进入 `/player/{room_id}`。
2. 如果房间未 active，前端回到 lobby。
3. Player 在 action tab 输入自由行动，或点击快捷战术动作。
4. 前端生成 `action_id`，提交 `POST /api/player/intent`。
5. UI 进入等待状态，禁止重复提交同一行动。
6. Transaction 返回 queued/batched/resolving/completed/rejected 状态。
7. Projection 发送 party 公共叙事和本人私密结果。
8. Player 解锁输入并显示结果。

### 私人资源查看

1. 角色 tab 调用 `/api/player/character`，当前数值应来自 runtime state。
2. 背包 tab 调用 `/api/player/inventory`。
3. 线索区调用 `/api/player/clues`，只返回本人私密线索和他人已分享公共版本。
4. 日志 tab 调用 `/api/player/archive`，只返回本人可见事件。
5. 地图 tab 调用 `/api/map/{room_id}`，只展示当前可探索范围。

### 断线恢复

1. PlayerWS 断开后自动重连，并携带 lastSequence。
2. 页面刷新或长断线时调用 `/api/player/reconnect`。
3. 服务端返回 character、recent_events、pending_actions、last_sequence、stateVersion。
4. 客户端按可见事件恢复消息和 UI 状态。
5. 收到 `s2c_state_patch` 时按 `baseStateVersion/stateVersion` 应用、丢弃或触发 `/api/player/sync`。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| PC-FR-1 | 玩家端必须提供房间码加入入口，并支持登录后回跳。 | P0 |
| PC-FR-2 | 入房必须选择且只能选择一种角色来源。 | P0 |
| PC-FR-3 | 入房成功后保存服务端返回的 `player_token`，不得由前端自造正式 token。 | P0 |
| PC-FR-4 | 玩家 API 请求必须携带 `X-Room-Token`，账号级接口额外携带 Authorization。 | P0 |
| PC-FR-5 | 等待室必须展示房间状态、剧本标题、成员、调查员名和 ready 状态。 | P0 |
| PC-FR-6 | ready 切换必须走 intent 或 Room 认可接口，并广播 lobby snapshot。 | P0 |
| PC-FR-7 | active 后玩家必须进入行动终端，非 active 时行动页必须回到 lobby。 | P0 |
| PC-FR-8 | 自由行动、战术动作、技能检定、移动、道具主张都必须走服务端 intent。 | P0 |
| PC-FR-9 | 玩家端必须以 `action_id` 做幂等显示，避免弱网重复提交。 | P0 |
| PC-FR-10 | action UI 必须展示 submitting、queued、resolving、completed、rejected、timeout。 | P0 |
| PC-FR-11 | PlayerWS 只能接收 party 事件和本人 player 事件。 | P0 |
| PC-FR-12 | 玩家端必须实现 stateVersion barrier，不能盲目应用乱序 patch。 | P0 |
| PC-FR-13 | `/api/player/reconnect` 返回内容必须在前端恢复为当前 UI 状态。 | P0 |
| PC-FR-14 | 角色当前 HP/SAN/MP/Luck 必须优先读 runtime state。 | P0 |
| PC-FR-15 | 背包、线索、日志、地图必须只展示服务端过滤后的内容。 | P0 |
| PC-FR-16 | 线索分享必须调用服务端 share 接口，不能前端直接改公开状态。 | P0 |
| PC-FR-17 | 地图移动必须提交 move intent，不能直接修改位置。 | P0 |
| PC-FR-18 | 玩家端中文文案、错误提示、按钮、tab 必须可读。 | P0 |
| PC-FR-19 | 无效 token、过期登录、房间不存在、角色不属于本人时必须有明确恢复路径。 | P1 |
| PC-FR-20 | 语音输入必须提供文本降级，不得阻断核心行动提交。 | P1 |
| PC-FR-21 | 玩家端应支持移动端基本布局和键盘可访问性。 | P1 |
| PC-FR-22 | 玩家私人笔记、行动模板、多设备同步放入长期增强。 | P2 |

## 接口方向

| 接口或事件 | 当前状态 | 用途 | 备注 |
| --- | --- | --- | --- |
| `POST /api/player/rooms/{room_id}/join-with-character` | 已有 | 入房并绑定角色 | 支持 preset、file、builder、template、copy |
| `GET /api/player/rooms/{room_id}/join-info` | 已有 | 等待室快照和加入信息 | 前端用于 lobby 和角色来源补充 |
| `GET /api/player/me/characters` | 已有 | 查询账号角色 | 需要前端恢复入口 |
| `POST /api/player/characters/{character_id}/restore-session` | 已有 | 恢复 player token | 必须校验 account owner |
| `GET /api/player/character` | 已有，需增强 | 角色当前状态和技能 | 当前数值应接 runtime |
| `POST /api/player/intent` | 已有 | 所有玩家行动入口 | active 房间走回合收集 |
| `POST /api/player/team-message` | 已有 | 队内消息 | 不触发 AI 裁决 |
| `GET /api/player/sync` | 已有，需增强 | snapshot 和 stateVersion | 给版本屏障重拉 |
| `GET /api/player/reconnect` | 已有，需增强 | 断线恢复 | 需统一可见性过滤 |
| `GET /api/player/actions/{action_id}` | 已有 | 查询本人 action | 不能泄露他人 action 存在 |
| `GET /api/player/inventory` | 已有 | 背包 | 只返回本人 |
| `GET /api/player/clues` | 已有 | 线索 | 返回本人私密和已分享公共版本 |
| `POST /api/player/clues/{clue_id}/share` | 已有 | 分享线索 | 只允许线索 owner |
| `GET /api/player/archive` | 已有 | 玩家日志 | 需复用 Projection 可见性 |
| `GET /api/map/{room_id}` | 已有 | 玩家地图 | token 视角要安全 |
| `POST /api/map/{room_id}/move` | 已有 | 地图移动 intent | 先校验邻接和隐藏节点 |
| `Player WS /ws?role=player` | 已有 | 实时事件和 catch-up | token 查询参数后续需安全收敛 |
| `s2c_room_lobby_snapshot` | 已有 | 等待室同步 | party |
| `s2c_team_message` | 已有 | 队内消息 | party |
| `s2c_tactical_prompt` | 已有 | 战术提示 | player 或 party，按上游定义 |
| `s2c_action_completed` | 已有 | 行动完成 | 目标玩家或 party 摘要 |
| `s2c_state_patch` | 已有，需增强 | 状态变化 | 必须带版本和受众 |
| `s2c_public_observation` | 已有 | 公共叙事 | party |
| `s2c_map_updated/s2c_player_moved/s2c_map_revealed` | 已有 | 地图刷新 | party 或 player，按可见范围 |

## 数据边界

- `player_token` 是玩家角色会话凭证，前端只能保存和发送，不能解释为永久账号权限。
- `account_token` 是账号凭证，用于登录和恢复角色，不直接代表房间身份。
- `characters.xlsx_data` 是角色卡基线，当前 HP/SAN/MP/Luck 应由 runtime state 覆盖。
- `PlayerIntent.params` 是玩家声明参数，不是服务端事实。
- `events` 是投影日志，玩家端只能读取可见子集。
- `stateVersion` 是状态同步版本，不是 UI 本地自增值。
- 玩家本地 messages 是显示缓存，不是可审计日志来源。

## 权限边界

1. 玩家不能通过请求体声明 `character_id` 来操作角色，服务端必须由 token 反查。
2. 玩家不能读取、保存、展示 `owner_token`。
3. 玩家不能调用 Host API、Admin API 或 Host WS。
4. 玩家不能查看其他玩家的 player-only patch、private notice、action completed。
5. 玩家不能查看 Host-only reveal、KP note、隐藏真相、未发现线索。
6. 玩家不能在前端直接把线索、地图节点、道具标为已发现。
7. 玩家端的本地过滤只提升体验，不承担安全责任。

## 客户端状态模型

| 状态 | 含义 | 进入条件 | 退出条件 |
| --- | --- | --- | --- |
| `not_authenticated` | 未登录或账号 token 缺失 | 打开 join 且无 account token | 登录成功 |
| `joining` | 正在入房和绑定角色 | 提交 join 表单 | 成功进入 lobby 或失败回表单 |
| `lobby` | 等待室 | 房间 draft/lobby，角色 joined | 房间 active 或玩家离开 |
| `pending_approval` | 进行中加入等待 Host 批准 | active 房间加入 | Host 批准或拒绝 |
| `active_idle` | 可提交行动 | 房间 active 且无未完成行动 | 提交 action |
| `submitting` | 前端发送中 | 点击提交 | 服务端 202/错误 |
| `queued` | 行动已进入事务 | 后端接受 | 进入 resolving 或 rejected |
| `resolving` | AI/规则/状态结算中 | 回合结算或后台 pipeline | completed、rejected、timeout |
| `syncing` | 正在重拉 snapshot | 发现版本缺口或 reconnect | sync 成功或失败 |
| `offline` | WS 断开 | WS close | 重连成功或用户刷新 |

## 验收标准

1. 玩家可以完成 `登录 -> 加入房间 -> 绑定角色 -> ready -> 开局 -> 提交行动 -> 收到结果`。
2. 两名玩家同时在线时，ready、队内消息、开局跳转在双方和 Host 侧同步。
3. Player A 不会在 WS、reconnect、archive、map、clues、sync 中看到 Player B 私密内容。
4. 玩家端不会看到 Host-only reveal、隐藏真相、KP prompt 或未发现线索。
5. 刷新行动页后，pending action、日志、stateVersion 和角色当前状态能恢复。
6. 乱序或旧 `s2c_state_patch` 不会覆盖当前状态。
7. 角色 HP/SAN 在 Host HUD 和 Player 角色页显示一致。
8. 地图移动只通过 intent，非法移动或隐藏节点访问被拒绝。
9. 中文界面无历史乱码，主要错误提示可读。
10. 前端改动通过 `npm run build`，相关后端改动通过对应 pytest。
