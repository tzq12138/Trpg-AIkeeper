# User 用户与权限系统 PRD v1

## 目标

User 模块建立 AI-Keeper 的身份和权限边界，确保平台账号、房间房主、玩家角色三类身份可以被稳定区分、校验和追踪。

本模块第一轮目标是保护核心跑团链路：

`账号登录 -> 角色授权 -> 房主创建房间 -> 玩家绑定角色 -> token 鉴权 -> 权限失败拦截 -> 可见范围不越界`

User 不负责完整社交系统，也不负责 AI 裁决和投影内容裁剪。它给其它模块提供“请求者是谁、属于哪个房间、能不能执行这个操作”的基础判断。

## 范围

包含：

- 用户注册、登录、当前账号查询。
- 平台账号角色：`admin`、`host`、`player`。
- Admin 后台基础鉴权和账号角色调整。
- Host 房主账号与房间 owner 关系。
- `owner_token` 对 Host 兼容链路的管理权限。
- `player_token` 与 `character_id` 的绑定关系。
- 玩家通过 token 提交 intent、查询个人状态、私密线索、目标、action 和重连数据。
- Host WS、Player WS、RAG 读写、Room 公开 DTO 的权限边界。
- 前端开发态多身份 slot 的使用口径。

不包含：

- 好友、关注、组织、社区声誉。
- 商业会员、付费权限、创作者收益。
- 正式多端 session 撤销体系。
- 完整账号找回、邮箱验证、二次认证。
- 旁观者权限模型完整实现。
- 投影分层、私密线索裁剪、AI 上下文反剧透的细节实现。

## 身份模型

### 平台账号

平台账号由 `accounts` 表维护，字段包含：

- `account_id`
- `username`
- `password_hash`
- `display_name`
- `role`
- `last_seen_at`
- `created_at`

登录后返回 account token。当前实现为 HMAC 签名 token，服务端通过 `Authorization: Bearer <token>` 或 `X-Account-Token` 识别账号。

账号角色：

| 角色 | 权限 |
|---|---|
| `admin` | 管理后台、管理账号角色、管理房间、导入/管理剧本、全局 RAG/AI 配置等运维能力 |
| `host` | 创建自己的房间、查询可用剧本、管理自己拥有的房间 |
| `player` | 加入房间、绑定角色、参与跑团，不具备开房和后台权限 |

### 房主身份

房主身份有两种校验路径：

- `owner_account_id`：房间归属到平台账号，适合正式账号体系。
- `owner_token`：房间创建时生成的兼容令牌，适合当前 Host 前端和旧链路。

owner/admin 可执行房间管理动作，例如开局、暂停、重试回合、checkpoint、Host WS 连接、房间导出 full scope。

房主不是全知 KP。User 模块只授予“管理房间流程”的权限，不授予“读取完整剧本真相和未发现线索”的权限。

### 玩家角色身份

玩家身份由 `characters.player_token` 绑定到一个 `character_id`。所有 Player 接口必须以 token 反查角色，不信任前端传入的 `characterId`。

玩家 token 可用于：

- 提交 intent。
- 查询当前角色信息。
- 查询背包、线索、个人目标、个人 archive。
- 查询自己的 action 状态。
- Player WS 连接。
- 断线重连和全量同步。

玩家 token 不可用于：

- 创建房间。
- 管理房间状态。
- 查看他人私密线索。
- 查询他人 action。
- 执行 RAG 写入或 Admin 操作。

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| USER-1 | 作为用户，我可以注册和登录，获得稳定账号身份。 | P0 |
| USER-2 | 作为管理员，我可以把账号提升为 host，使其能创建房间。 | P0 |
| USER-3 | 作为 host，我可以创建和管理自己拥有的房间。 | P0 |
| USER-4 | 作为玩家，我加入房间后只能操作自己绑定的角色。 | P0 |
| USER-5 | 作为玩家，我刷新或换设备后，可以通过账号恢复自己名下角色 session。 | P0 |
| USER-6 | 作为系统，我能拒绝无效 token、错误房间、非成员 RAG 查询和他人 action 查询。 | P0 |
| USER-7 | 作为安全维护者，我能确认公开房间信息不泄露 owner/player token。 | P0 |
| USER-8 | 作为管理员，我希望后续能审计高风险权限操作。 | P1 |

## 功能需求

| 编号 | 功能 | 需求 |
|---|---|---|
| FR-USER-01 | 注册 | `POST /api/auth/register` 创建账号；第一个账号为 admin，其后默认为 player |
| FR-USER-02 | 登录 | `POST /api/auth/login` 校验用户名密码，成功返回 account token 和账号摘要 |
| FR-USER-03 | 密码存储 | 密码必须以加盐 PBKDF2 或更强方案存储，不允许明文或普通 hash |
| FR-USER-04 | 当前账号 | `GET /api/auth/me` 通过 account token 返回账号摘要 |
| FR-USER-05 | 平台角色 | 系统只接受 `admin/host/player` 三类平台角色 |
| FR-USER-06 | Admin 鉴权 | `/api/admin/*` 只允许 admin 账号访问 |
| FR-USER-07 | 账号角色调整 | admin 可调整账号 `role/display_name`，role 必须在允许枚举内 |
| FR-USER-08 | Host 开房 | `POST /api/rooms` 只允许 host/admin 创建房间 |
| FR-USER-09 | Owner 鉴权 | 房间管理接口同时支持 owner token、owner account、admin account |
| FR-USER-10 | Host WS | Host WS 必须校验 owner token 或等价 owner/admin 身份 |
| FR-USER-11 | 玩家入房绑定 | 玩家入房生成 `character_id` 和 `player_token`，登录用户同时写入 `account_id` |
| FR-USER-12 | 玩家 token 鉴权 | Player 接口必须通过 `X-Room-Token` 反查角色 |
| FR-USER-13 | Player WS | Player WS 必须校验 token 与 room 匹配 |
| FR-USER-14 | session 恢复 | 登录账号只能恢复自己名下角色的 player token |
| FR-USER-15 | 角色复制授权 | 复制角色时必须持有同账号身份或源角色 player token |
| FR-USER-16 | 资源隔离 | action、clue、objective、archive 查询必须按角色或房间身份过滤 |
| FR-USER-17 | RAG 权限 | admin 可全局读写；room owner 可房间级写；房间玩家只可房间级读 |
| FR-USER-18 | DTO 脱敏 | 公开接口不得返回 owner token、player token、owner account 等敏感字段 |
| FR-USER-19 | 前端身份 slot | 前端可支持开发态多身份切换，但不得把 slot 当作后端授权依据 |

## 权限矩阵

| 操作 | admin | host account | room owner account | owner token | player account | player token |
|---|---:|---:|---:|---:|---:|---:|
| 注册/登录 | 是 | 是 | 是 | 否 | 是 | 否 |
| 进入 Admin 后台 | 是 | 否 | 否 | 否 | 否 | 否 |
| 创建房间 | 是 | 是 | 是 | 否 | 否 | 否 |
| 管理任意房间 | 是 | 否 | 否 | 否 | 否 | 否 |
| 管理自己房间 | 是 | 否 | 是 | 是 | 否 | 否 |
| Host WS | 是 | 否 | 是 | 是 | 否 | 否 |
| 玩家加入房间 | 可选 | 可选 | 可选 | 否 | 可选 | 否 |
| 提交玩家行动 | 否 | 否 | 否 | 否 | 否 | 是 |
| 查询自己 action | 否 | 否 | 否 | 否 | 否 | 是 |
| 查询他人私密线索 | 否 | 否 | 否 | 否 | 否 | 否 |
| RAG 房间读 | 是 | 若为 owner 或成员 | 是 | 否 | 若为成员 | 否 |
| RAG 房间写 | 是 | 若为 owner | 是 | 否 | 否 | 否 |

说明：`host account` 只是平台角色；只有成为某个 room 的 `owner_account_id` 后，才拥有该房间的 owner 权限。

## 数据边界

User 模块直接维护或使用：

- `accounts`
- account token
- `owner_account_id`
- `owner_token`
- `player_token`
- `characters.account_id`
- `characters.character_id`
- `characters.status`

User 模块不直接维护：

- 角色卡完整规则数据，归 Character 模块。
- 私密线索内容和分享版本，归 Clue 模块。
- 世界状态真相，归 State/Engine。
- 投影受众和投放时序，归 Projection。
- AI 上下文裁剪和反剧透校验，归 AI-Keeper/Safety。
- 长期审计报表和运维策略，归 Admin/Ops。

## 接口与事件方向

### REST

| 接口 | 权限 | 用途 |
|---|---|---|
| `POST /api/auth/register` | public | 注册账号 |
| `POST /api/auth/login` | public | 登录并签发 account token |
| `GET /api/auth/me` | account token | 当前账号摘要 |
| `GET /api/auth/me/characters` | account token | 查询账号名下角色摘要 |
| `GET /api/player/me/characters` | account token | 查询账号名下角色和房间摘要 |
| `POST /api/player/characters/{character_id}/restore-session` | account token | 恢复自己角色的 player token |
| `GET /api/admin/accounts` | admin | 查看账号列表 |
| `PATCH /api/admin/accounts/{account_id}` | admin | 修改账号角色或显示名 |
| `POST /api/rooms` | host/admin | 创建房间 |
| `POST /api/player/intent` | player token | 提交 ready 或行动 intent |
| `GET /api/player/reconnect` | player token | 断线恢复 |
| `GET /api/player/actions/{action_id}` | player token | 查询自己的 action 状态 |
| `POST /api/rag/search` | account token | 按 admin/owner/member 权限检索 |

### WebSocket

| 连接 | 权限 | 用途 |
|---|---|---|
| `/ws?role=host&room=...&ownerToken=...` | owner token 或等价 owner/admin | Host 舞台和大厅事件 |
| `/ws?role=player&room=...&token=...` | player token 且 room 匹配 | Player 私人端事件 |

### 事件和审计方向

第一轮不新增完整审计系统，但后续应将这些动作结构化记录：

- 账号角色变更。
- 房间 owner token 轮换。
- 房主强制开局、暂停、retry、skip。
- checkpoint restore。
- Admin 修改角色状态或生命值。
- 权限失败高频触发。
- RAG 写入和全局 AI 配置修改。

## 安全规则

- `JWT_SECRET` 生产环境必须使用强随机值，不得沿用默认值。
- account token 用于平台身份，不能替代 player token 操作角色。
- player token 用于角色身份，不能替代 account token 进入后台。
- owner token 用于房间管理，不能进入公开 DTO、公共导出或前端可分享链接。
- 登录用户恢复 session 时，必须校验 `characters.account_id`。
- 其他玩家查询某个 action 时应返回 404，以隐藏资源是否存在。
- 公开房间查询只返回脱敏玩家摘要。
- RAG search 即使允许玩家读，也必须限制在玩家所属房间。
- 前端隐藏按钮不是权限控制，后端每个入口都必须校验。

## 验收标准

- 第一个注册账号成为 admin，后续注册账号默认为 player。
- 登录成功返回 account token，错误密码返回 401。
- player 账号不能创建房间，host/admin 可以创建房间。
- admin 可以把 player 提升为 host。
- 公开房间 DTO 不包含 `owner_token`、`owner_account_id`、`player_token`。
- Host WS 缺失或错误 owner token 时连接被拒绝。
- Player WS 的 token 必须与 room 匹配。
- 玩家缺少 `X-Room-Token` 时提交 intent 返回 401，无效 token 返回 403。
- 玩家只能查询自己的 action，不能用自己的 token 读取他人 action。
- 登录账号只能恢复自己名下角色 session。
- player 不能执行 RAG index，非房间成员不能 RAG search 指定房间。
- 文档和 DeepSeek 任务不把社区、付费、多端会话和完整旁观者模型混入 P0。
