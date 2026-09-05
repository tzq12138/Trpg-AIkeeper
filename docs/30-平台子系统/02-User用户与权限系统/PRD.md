# User 用户与权限系统 PRD v1

## 目标

User 模块为 AI-Keeper 提供稳定的身份与权限边界，确保平台账号、房间房主、玩家角色这三层身份可以被清晰区分、校验和追踪。

第一轮目标是保护核心跑团链路：

`账号登录 -> 平台角色判断 -> Host 创建房间 -> 玩家绑定角色 -> token 鉴权 -> 越权拦截 -> 可见范围不越界`

User 不负责 AI 裁决，也不负责投影内容裁剪；它负责给其他模块提供“请求者是谁、属于哪个房间、有没有资格发起这个操作”的基础判断。

当前阶段说明：

- 本 PRD 已可进入工程执行，但当前阶段仍是“P0 主链路 + 生产风险识别版”。
- 文档已经把 `account_token / owner_token / player_token` 的边界、DTO 脱敏、恢复链路和生产基线缺口标出来，但不代表这些安全问题已经在代码里关闭。
- 正式环境要达标，仍需后续工程批次真正落地 `JWT_SECRET` fail-fast、bootstrap admin 阻断、`ws_ticket`、token 生命周期和 RAG 结果裁剪。

## 范围

包含：

- 用户注册、登录、当前账号查询
- 平台账号角色 `admin/host/player`
- Admin 后台基础鉴权与账号角色调整
- `owner_account_id` 与房间 owner 关系
- `owner_token` 对 Host 兼容链路的房间管理权限
- `player_token` 与 `character_id` 的绑定关系
- 玩家通过 token 提交 intent、查询个人状态、线索、目标、action、archive 和重连数据
- Host WS、Player WS、RAG 入口、Room 公开 DTO 的权限边界
- 前端开发态多身份 slot 的使用口径

不包含：

- 好友、关注、社区声誉
- 商业会员、付费权限、创作者分成
- 完整多设备会话管理
- 邮箱验证、找回密码、二次认证
- 旁观者权限模型完整实现
- Projection/Safety 对玩家内容可见范围的最终裁剪

## 身份模型

### 平台账号

平台账号由 `accounts` 表维护。当前已有字段：

- `account_id`
- `username`
- `password_hash`
- `display_name`
- `role`
- `last_seen_at`
- `created_at`

登录后返回 `account_token`。当前实现为 HMAC 签名 token，带 `iat/exp`，服务端每次请求重新查询数据库中的账号角色。

这带来一个重要现状：

- 账号降权后，旧 token 再请求时会按数据库中的新角色生效
- 但当前仍没有主动撤销、封禁、强制下线和 token version 机制

### 房间房主身份

房主身份有两条路径：

- `owner_account_id`：房间归属到平台账号，适合正式账号体系
- `owner_token`：创建房间时生成的兼容凭证，适合当前 Host 旧链路和单机调试

owner/admin 可以执行房间管理动作，例如开局、暂停、重试回合、查询回合、Host WS 连接、部分导出与急救能力。

注意：房主不是全知 KP。User 模块只授予“管理房间流程”的权限，不授予“读取完整剧本真相和未发现线索”的权限。

### 玩家角色身份

玩家身份由 `characters.player_token` 绑定到一个具体 `character_id`。Player 接口必须通过 token 反查角色，不信任前端传入的 `characterId`。

玩家 token 可用于：

- 提交 `intent`
- 查询当前角色信息
- 查询背包、线索、个人目标、个人 archive
- 查询自己的 action 状态
- Player WS 连接
- 断线重连和全量同步

玩家 token 不可用于：

- 创建房间
- 管理房间状态
- 读取他人的私密线索
- 查询他人 action
- 执行 RAG 写入或 Admin 操作

## 凭证模型

| 凭证/标识 | 归属 | 当前用途 | 不是啥 | 当前状态 |
|---|---|---|---|---|
| `account_token` | User | 平台账号身份、Admin、Host 开房、RAG | 不是玩家角色凭证 | 已实现 |
| `owner_token` | Room / User 边界 | 单房间管理、Host REST/WS 兼容 | 不是平台登录态 | 已实现，明文存储 |
| `player_token` | Character / User 边界 | 单角色控制、私人资源、Player WS | 不是账号登录态 | 已实现，明文存储 |
| `room_id` | Room | 当前公开查房与加入入口 | 不是权限凭证 | 已实现 |
| `room_code` | Room | 未来短码入房 | 不是 owner/player token | 未实现 |
| `invite_token` | Room | 未来邀请链接 | 不能替代玩家 token | 未实现 |
| `ws_ticket` | User / WS 边界 | 未来短期一次性 WS 鉴权票据 | 不是长期会话 | 未实现 |

## 角色与权限

| 身份 | 权限 | 禁止事项 |
|---|---|---|
| `admin` | 后台管理、账号角色调整、任意房间管理、全局 RAG/AI 配置入口 | 不应长期和所有运维/内容/审计能力混为同一粗粒度角色 |
| `host` 平台角色 | 创建自己的房间，查询可用剧本，管理自己拥有的房间 | 不是任意房间 owner，不是全知 KP |
| `room owner account` | 管理自己归属的房间 | 不能管理别人的房间 |
| `owner_token` | 兼容当前单房间 Host 管理路径 | 不能进入公开 DTO、分享链接或长期暴露在日志中 |
| `player` 平台角色 | 入房、绑定角色、作为账号恢复自己的角色会话 | 不能只靠 account token 直接提交玩家行动 |
| `player_token` | 操作单个角色，查询自己的私人资源和 Player WS | 不能替代 account token 进后台或替代 owner_token 管房 |

## User 与 Room 的衔接

01-Room 文档已经区分了：

- `room_id`
- `room_code`
- `invite_token`
- `owner_token`
- `player_token`

02-User 需要把它们和身份体系对应起来：

- `account_token`：平台账号身份
- `owner_token`：单房间管理兼容凭证
- `player_token`：单角色控制凭证
- `room_code`：公开加入标识，不是权限
- `invite_token`：未来加入授权凭证，但不应能直接操作角色
- `ws_ticket`：未来短期连接票据，不应长期替代用户会话

这几层不得混用。

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| USER-1 | 作为用户，我可以注册和登录，获得稳定的平台账号身份。 | P0 |
| USER-2 | 作为管理员，我可以把账号提升为 host，使其具备开房能力。 | P0 |
| USER-3 | 作为 host，我可以创建和管理自己拥有的房间。 | P0 |
| USER-4 | 作为玩家，我加入房间后只能操作自己绑定的角色。 | P0 |
| USER-5 | 作为登录玩家，我可以恢复自己账号名下角色的玩家会话。 | P0 |
| USER-6 | 作为系统，我能拒绝无效 token、错误房间、非成员 RAG 查询和他人 action 查询。 | P0 |
| USER-7 | 作为安全维护者，我需要保证公开 DTO 和 WS 广播都不泄露 owner/player token。 | P0 |
| USER-8 | 作为维护者，我希望高风险权限操作未来可被结构化审计。 | P1 |

## 功能需求

| 编号 | 功能 | 需求 |
|---|---|---|
| FR-USER-01 | 注册 | `POST /api/auth/register` 创建账号；当前代码中第一个账号自动成为 admin |
| FR-USER-02 | 登录 | `POST /api/auth/login` 校验用户名密码，成功返回 `account_token` 和账号摘要 |
| FR-USER-03 | 密码存储 | 密码必须使用加盐 PBKDF2 或更强方案存储，不允许明文或普通 hash |
| FR-USER-04 | 当前账号 | `GET /api/auth/me` 通过 `account_token` 返回账号摘要 |
| FR-USER-05 | 平台角色 | 系统只接受 `admin/host/player` 三类平台角色 |
| FR-USER-06 | Admin 鉴权 | `/api/admin/*` 只允许 admin 账号访问 |
| FR-USER-07 | 账号角色调整 | admin 可修改 `role/display_name`；role 只能在允许枚举内 |
| FR-USER-08 | Host 开房 | `POST /api/rooms` 只允许 host/admin 创建房间 |
| FR-USER-09 | Owner 鉴权 | 房间管理接口同时支持 owner token、owner account、admin account |
| FR-USER-10 | Host WS | 当前 Host WS 必须校验 owner token 或等价 owner/admin 身份 |
| FR-USER-11 | 玩家入房绑定 | 玩家入房生成 `character_id` 和 `player_token`；登录用户同时写入 `account_id` |
| FR-USER-12 | Player 鉴权 | Player 接口必须通过 `X-Room-Token` 反查角色 |
| FR-USER-13 | Player WS | 当前 Player WS 必须校验 `player_token` 与 `room` 匹配 |
| FR-USER-14 | session 恢复 | 登录账号只能恢复自己名下角色的玩家会话 |
| FR-USER-15 | 角色复制授权 | 复制角色时必须持有同账号身份或源角色 `player_token` |
| FR-USER-16 | 私人资源隔离 | action、clue、objective、archive 查询必须按角色或房间身份过滤 |
| FR-USER-17 | RAG 鉴权入口 | admin 可全局读写；room owner 可房间级写；房间玩家只可房间级读 |
| FR-USER-18 | DTO 脱敏 | 公开接口不得返回 owner token、player token、password hash 等敏感字段 |
| FR-USER-19 | 前端多身份 slot | 开发态可支持多身份切换，但不得把 slot 当作后端授权依据 |
| FR-USER-20 | 生产 bootstrap 基线 | 生产环境不应允许无保护的“首账号自动 admin”路径 |
| FR-USER-21 | JWT 生产基线 | 生产环境必须拒绝使用默认 `JWT_SECRET` 启动 |
| FR-USER-22 | token 生命周期 | 未来需要支持 account/owner/player token 的失效、轮换、撤销和脱敏 |
| FR-USER-23 | WS 短期票据 | 正式环境应从 query token 迁移到短期 `ws_ticket` |
| FR-USER-24 | RAG 结果裁剪 | Player-facing RAG 返回内容必须经过 `visibility/audience/discovered_state` 过滤，不能直接返回原始 chunk |

## DTO 分层方向

当前代码已做到基础脱敏，但还没有系统化 DTO 层。后续建议明确：

- `PublicUserDTO`：其他普通用户可见的公开信息，如 `account_id`、`display_name`、`avatar_url`
- `SelfUserDTO`：本人可见的账号信息，如 `username`、`display_name`、`role`
- `AdminUserDTO`：管理员可见的账号信息，如 `created_at`、`last_seen_at`、`disabled_at`
- `RoomMemberDTO`：大厅成员可见摘要，如 `display_name`、`character_name`、`ready`、`status`

下列字段不应出现在公开 DTO 或大厅成员 DTO 中：

- `password_hash`
- `account_token`
- `owner_token`
- `player_token`
- `character_secret`
- `private_clue_ids`
- `scenario_truth`

注意：WS payload 要与 DTO 使用同一套 audience 口径，而不是 REST 脱敏、WS 放任。

## 错误码口径

建议以对外不泄露资源存在性为原则：

| 场景 | HTTP | 口径 |
|---|---:|---|
| 未登录 / 缺 token | 401 | 不暴露资源是否存在 |
| token 格式错误或已过期 | 401 | 不暴露资源是否存在 |
| token 有效但权限不足 | 403 | 仅在后台类接口可明确提示权限不足 |
| 查询他人私密资源 | 404 | 不暴露资源存在 |
| 房间不存在或不可见 | 404 | 不暴露是否存在 |
| 角色不属于当前账号 | 对外优先 404 | 避免提示“这个角色存在但不属于你” |

当前代码已经部分采用这套思路，例如：

- `/api/player/actions/{action_id}` 他人查询返回 404
- `restore-session` 对“不是你的角色”当前返回 403

后续需要统一口径，而不是让各 Player 接口各自发挥。

## 数据边界

User 模块当前直接维护或使用：

- `accounts`
- `account_token`
- `owner_account_id`
- `owner_token`
- `player_token`
- `characters.account_id`
- `characters.character_id`
- `characters.status`

User 模块不直接维护：

- 角色卡完整规则数据，归 Character
- 私密线索内容和分享版本，归 Clue
- 世界状态真相，归 State / Engine
- 投影受众和投放时序，归 Projection
- AI 上下文裁剪和反剧透校验，归 AI-Keeper / Safety

## 数据模型演进方向

当前事实：

- `accounts` 还没有 `token_version`、`disabled_at`
- `rooms.owner_token` 为明文列
- `characters.player_token` 为明文列
- `restore-session` 返回现有 `player_token`，不是轮换后的新 token

后续建议：

- `accounts` 增加 `token_version`、`disabled_at`、`updated_at`
- 如需要多设备管理，引入 `account_sessions`
- `rooms` 增加 `owner_token_hash`、`owner_token_rotated_at`、`owner_token_revoked_at`
- `characters` 增加 `player_token_hash`、`player_token_version`、`joined_at`、`left_at`
- 新增 `auth_audit_events` 记录 actor、target、result、reason、IP/User-Agent 摘要

## 当前接口与事件方向

### REST

| 接口 | 权限 | 用途 |
|---|---|---|
| `POST /api/auth/register` | public | 注册账号 |
| `POST /api/auth/login` | public | 登录并签发 `account_token` |
| `GET /api/auth/me` | account token | 当前账号摘要 |
| `GET /api/auth/me/characters` | account token | 查询自己名下角色摘要 |
| `GET /api/player/me/characters` | account token | 查询自己账号名下角色与房间摘要 |
| `POST /api/player/characters/{character_id}/restore-session` | account token | 恢复角色 `player_token` |
| `GET /api/admin/accounts` | admin | 查询账号列表 |
| `PATCH /api/admin/accounts/{account_id}` | admin | 修改账号角色或显示名 |
| `POST /api/rooms` | host/admin | 创建房间 |
| `POST /api/player/intent` | player token | 提交 ready 或玩家行动 intent |
| `GET /api/player/reconnect` | player token | 断线恢复 |
| `GET /api/player/actions/{action_id}` | player token | 查询自己的 action 状态 |
| `POST /api/rag/search` | account token | 按 admin/owner/member 权限搜索 |

### WebSocket

当前实现：

- `/ws?role=host&room=...&ownerToken=...`
- `/ws?role=player&room=...&token=...`

当前代码事实：

- 业务层 logger 没有直接打印完整 token 值
- 但 URL query 仍可能出现在浏览器历史、代理日志、监控和 trace 中

文档口径：

- 当前 query token 只视为开发兼容路径
- 正式环境目标应迁移为短期一次性 `ws_ticket`

## 安全规则

- `JWT_SECRET` 在生产环境必须使用强随机值，不得沿用默认值。
- 生产环境不能裸暴露“首账号自动 admin”行为。
- `account_token` 用于平台账号身份，不能替代 `player_token` 操作角色。
- `player_token` 用于角色身份，不能替代 `account_token` 进入后台。
- `owner_token` 用于房间管理，不能进入公开 DTO、公开导出或前端可分享链接。
- 登录用户恢复 session 时，必须校验 `characters.account_id`。
- Host 不是全知 KP，User 不授予 Host 读取完整 `scenario_truth` 的能力。
- RAG search 即使允许玩家读，也不能直接向玩家返回未裁剪的原始 chunk。
- 前端隐藏按钮不是权限控制，后端每个入口都必须校验。

以上生产基线在当前代码里仍有未关闭项，只有工程落地并通过测试后，才算从“风险识别”进入“风险闭环”。

## 验收标准

- 注册和登录可以稳定返回账号身份。
- player 账号不能创建房间；host/admin 可以创建房间。
- admin 可以把 player 提升为 host。
- 非房间 owner 的 host 账号不能管理别人的房间。
- account token 不能直接提交玩家 intent。
- 公开 Room DTO 不包含 `owner_token`、`owner_account_id`、`player_token`。
- Host WS 和 Player WS 在错误 token 或 room 不匹配时都会拒绝连接。
- 玩家只能查询自己的 action、线索、目标和 archive。
- 登录账号只能恢复自己名下角色的玩家会话。
- player 不能执行 RAG index；非房间成员不能 search 指定房间。
- Player-facing RAG 若上线，结果必须经过可见性裁剪，不得直出 `scenario_truth` 或未发现线索。
- 文档明确区分了当前代码事实、生产安全缺口和后续演进方向。
- 文档完成不等于生产安全完成；至少需要 `JWT_SECRET`、bootstrap admin、`ws_ticket`、token 生命周期、RAG 结果裁剪几项真正实现并通过验收。
