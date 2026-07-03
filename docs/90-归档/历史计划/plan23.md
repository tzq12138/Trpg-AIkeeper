# 房间等待室、Ready 同步与 Host Lobby 修复计划

## Summary
- 把“加入房间后直接进游戏页”改成“先进入玩家等待室”，玩家可看到其他人、聊天、切换准备状态。
- 修复 ready 状态显示不准：以数据库 `characters.is_ready/status` 为唯一来源，API、WebSocket、页面初始化都读取同一份状态。
- 重做 Host 房主大厅 UI，使其和当前 Bauhaus 风格一致，并让开始游戏按钮只在剧本已选、玩家存在、所有玩家已准备时可用。
- 房主点击开始后进入 Host 舞台；玩家等待室检测到房间进入游戏状态后进入自己的 Player 端。

## API / Interfaces
- 扩展 `GET /api/player/character`：返回 `is_ready/isReady`、`status`、`room_status/roomStatus`，避免玩家刷新后准备态丢失。
- 固化 `GET /api/player/rooms/{room_id}/join-info` 为玩家等待室数据源：返回房间状态、剧本标题、玩家列表、每个玩家的昵称、调查员名、状态、ready。
- Host 侧使用已有 Host 房间/HUD 数据或新增轻量 lobby 查询，必须包含玩家 ready 状态和当前剧本信息。
- 修复 `POST /api/player/team-message`：导入路径正确，只写一次事件日志，同时实时广播给房间内 host/player。
- `ready_toggle` 成功后广播一次统一房间快照事件，例如复用 `s2c_room_lobby_snapshot`，HostLobby 和 PlayerLobby 都订阅它。

## Key Changes
- 新增玩家等待室页面：路由建议为 `/player/:roomId/lobby`。玩家加入成功后从 `/player/join` 跳到等待室，而不是直接进 `/player/:roomId`。
- 玩家等待室包含：房间码、剧本名、玩家列表、自己的准备/取消准备按钮、房间聊天框、进入游戏状态提示。
- 玩家等待室启动逻辑：若房间状态变为 `active/running`，显示“进入游戏”按钮，并可自动跳转到 `/player/:roomId`。
- HostLobby 重构：使用统一 Bauhaus 样式层，不再用旧的居中窄卡片内联样式；显示剧本选择、玩家状态、等待室聊天摘要、开始游戏按钮。
- HostLobby 初始化时必须主动拉取当前房间数据，不能只等 WebSocket；WebSocket 作为实时更新，失败时用 3-5 秒轮询兜底。
- 开始游戏按钮规则：无剧本、无玩家、存在未准备玩家时禁用，并显示明确原因；全部满足后可点击。
- PlayerActionPage 保留 ready 显示但不再承担等待室职责；游戏开始前的社交、准备、玩家列表都迁移到 PlayerLobby。
- 地图/日志 UI 混用问题另开检查项：确认 HostStage tab 内容按 tab key 渲染，不允许 `map` 复用 `log` 组件。

## Test Plan
- 后端测试：ready toggle 后数据库 `is_ready` 更新，`GET /api/player/character` 和 `join-info` 都返回正确 ready。
- 后端测试：玩家发送 team message 后事件日志只新增一次，WebSocket payload 包含玩家昵称、调查员名、文本、时间。
- 后端测试：房主开始游戏在无剧本、无玩家、未全员准备时返回拒绝；全员准备后成功切到 active/running。
- 前端构建：`src/client` 下跑 TypeScript/Vite build。
- 手动验收：玩家加入后进入等待室，两个浏览器账号互相可见，聊天可见，ready 状态双端同步。
- 手动验收：HostLobby 刷新后仍显示真实玩家 ready；全员 ready 后按钮可用；开始后 Host 进舞台，玩家从等待室进入 play 端。
- 回归验收：玩家直接访问 `/player/:roomId` 时，如果房间未开始，应引导回等待室；如果已开始，正常进入游戏页。

## Assumptions
- ready 状态继续存在 `characters.is_ready/status`，不新增独立 ready 表。
- 等待室聊天先走事件日志，不新增专门聊天表。
- 本轮只做房间等待室、ready 同步、HostLobby 风格和开始流程，不处理完整账号体系、断线在线状态、地图真实交互。
- 房主身份暂时沿用当前 host/admin 入口，不在本轮新增复杂登录鉴权。
