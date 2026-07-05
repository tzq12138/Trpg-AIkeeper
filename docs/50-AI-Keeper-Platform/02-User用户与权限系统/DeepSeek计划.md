# User 用户与权限系统 DeepSeek 计划

## 执行定位

User 模块的 DeepSeek 执行目标是稳定身份与权限边界：

`account token -> 平台角色 -> owner 权限 -> player token -> character 绑定 -> 接口鉴权 -> 可见范围隔离`

本计划只允许 DeepSeek 修补登录、注册、角色、token、房主/玩家/Admin 鉴权、RAG 权限和 WS 权限。社区账号、好友、会员、多端 session、正式邀请体系、完整旁观者模型不进入本轮。

## 全局执行规则

- 每个 Batch 开始前先运行 `git status --short`，确认已有改动，禁止覆盖无关文件。
- 当前代码优先于旧 PRD；旧 PRD 只用于补产品语义。
- 前端隐藏按钮不能替代后端鉴权。
- 后端不能信任前端传入的 `characterId`、`role` 或本地 slot。
- account token、owner token、player token 三者不得混用。
- 权限失败要可诊断，但错误信息不能泄露敏感资源是否存在。
- 涉及 token、账号角色、admin、RAG、WS 的改动必须补测试。
- 不重写整套认证框架；先收敛当前散落鉴权和乱码问题。

## Batch User-0：现状核对与文案乱码风险

| 项 | 内容 |
|---|---|
| 目标 | 核对 auth/admin/player/host/rag/ws 的真实权限实现，修正文案乱码，建立三层身份口径 |
| 允许文件方向 | `src/server/router_auth.py`、`router_admin.py`、`router_rooms.py`、`host/router_host.py`、`player/router_player.py`、`main.py`、`rag_router.py`、`src/client/src/pages/LoginPage.tsx`、`shared/identity.ts`、User 文档 |
| 主要任务 | 修正用户可见中文乱码；列清 account token、owner token、player token 的边界；确认默认 `JWT_SECRET` 部署风险被记录 |
| 测试命令 | `pytest tests/server/test_room_security.py tests/server/test_ws_auth.py -q` |
| 预期结果 | 现有安全测试通过；错误文案可读；文档与代码口径一致 |
| 禁止事项 | 不迁移到大型认证框架，不新增邮箱、短信、OAuth、二次认证 |

## Batch User-1：账号注册、登录、角色与 Admin 后台

| 项 | 内容 |
|---|---|
| 目标 | 稳定平台账号体系和 `admin/host/player` 角色权限 |
| 允许文件方向 | `src/server/router_auth.py`、`src/server/router_admin.py`、`src/client/src/pages/LoginPage.tsx`、`src/client/src/pages/AdminDashboard.tsx`、相关测试 |
| 主要任务 | 确认首账号 admin 策略；确认 PBKDF2 密码校验；确认 `/api/auth/me`；确认 admin 可修改账号 role；修正 Admin 相关乱码 |
| 测试命令 | `pytest tests/server/test_room_security.py tests/server/test_rag_security.py -q` |
| 预期结果 | 未登录 admin 返回 401；非 admin 返回 403；admin 可列账号和改 role；player 不能创建房间 |
| 禁止事项 | 不把 host 权限提升为 admin，不让前端 account.role 成为授权依据 |

## Batch User-2：房主 owner 权限与 Host 鉴权

| 项 | 内容 |
|---|---|
| 目标 | 统一 owner token、owner account、admin account 三条房间管理鉴权路径 |
| 允许文件方向 | `src/server/router_rooms.py`、`src/server/router_archive.py`、`src/server/host/router_host.py`、`src/server/scenario/router_scenarios.py`、`src/client/src/pages/HostCreate.tsx`、`HostLobby.tsx`、`HostStage.tsx`、`tests/server/test_rooms.py`、`test_host_room_lifecycle.py`、`test_host.py`、`test_ws_auth.py` |
| 主要任务 | 校验房间管理接口只允许 owner/admin；Host WS 错误 token 拒绝；公开 DTO 不泄露 owner token；Host 不能获得完整 KP 真相 |
| 测试命令 | `pytest tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py tests/server/test_host.py tests/server/test_ws_auth.py -q` |
| 预期结果 | owner token、owner account、admin 均可管理合法房间；其他账号和错误 token 被拒绝；Host WS 连接安全 |
| 禁止事项 | 不把任意 host 账号当作任意房间 owner，不把 owner token 放入公开响应 |

## Batch User-3：玩家 token、角色绑定与个人资源隔离

| 项 | 内容 |
|---|---|
| 目标 | 稳定 `player_token -> character_id -> room_id` 的角色身份链路 |
| 允许文件方向 | `src/server/player/router_player.py`、`router_reconnect.py`、`router_clues.py`、`router_objectives.py`、`router_player_archive.py`、`src/server/main.py`、`src/client/src/pages/PlayerJoinPage.tsx`、`PlayerLobby.tsx`、`PlayerActionPage.tsx`、相关测试 |
| 主要任务 | 所有 Player 接口用 token 反查角色；session 恢复校验 account_id；复制角色校验同账号或源 token；action 查询隔离；私密线索和个人目标隔离 |
| 测试命令 | `pytest tests/server/test_player_intent.py tests/server/test_character_join_import.py tests/server/test_reconnect.py tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_archive.py -q` |
| 预期结果 | 缺 token 401，无效 token 403；玩家不能查他人 action；玩家不能复制他人账号角色；个人资源不越权 |
| 禁止事项 | 不信任前端传入 characterId，不把 account token 当作角色操作凭证 |

## Batch User-4：RAG、AI 入口与知识权限

| 项 | 内容 |
|---|---|
| 目标 | 确保知识检索和索引操作符合 admin/owner/member 权限 |
| 允许文件方向 | `src/server/rag_router.py`、`src/server/router_admin.py`、`src/server/ai/rag.py`、`tests/server/test_rag_security.py`、`tests/server/test_rag_router.py`、`tests/server/test_rag.py` |
| 主要任务 | RAG index 只允许 admin 或 room owner；search 允许 admin、room owner、房间成员；非成员拒绝；规则文档接口至少要求登录 |
| 测试命令 | `pytest tests/server/test_rag_security.py tests/server/test_rag_router.py tests/server/test_rag.py -q` |
| 预期结果 | player 不能写 index；非房间成员不能 search；admin 可全局管理；RAG 不绕过 User 权限 |
| 禁止事项 | 不在 RAG 层直接暴露完整剧本真相给普通玩家；反剧透裁剪细节归 AI-Keeper/Safety |

## Batch User-5：回归验收与权限矩阵补齐

| 项 | 内容 |
|---|---|
| 目标 | 对 User 权限边界做集中回归，形成可交给后续模块复用的验收口径 |
| 允许文件方向 | 测试和小范围修复文件；发现跨模块缺陷时记录到对应模块文档或 `docs/30-DeepSeek任务包/` |
| 后端测试 | `pytest tests/server/test_room_security.py tests/server/test_rag_security.py tests/server/test_ws_auth.py tests/server/test_player_intent.py tests/server/test_reconnect.py tests/server/test_character_join_import.py -q` |
| 前端测试 | 涉及登录页、Admin 面板、身份 slot、Host/Player 页面时运行 `npm run build` |
| 手动验收 | admin 注册/登录；admin 提升 host；host 创建房间；player 加入并 ready；错误 token 被拒绝；player 不能访问他人 action；非成员不能 RAG search |
| 预期结果 | account/owner/player 三层身份边界清晰，主链路无越权，公开 DTO 脱敏 |
| 禁止事项 | 不为了通过测试删除安全校验，不把权限判断只放在前端 |

## 工程验收命令

User 相关后端回归：

```powershell
pytest tests/server/test_room_security.py tests/server/test_rag_security.py tests/server/test_ws_auth.py tests/server/test_player_intent.py tests/server/test_reconnect.py tests/server/test_character_join_import.py -q
```

涉及前端 User/权限页面时：

```powershell
npm run build
```

文档验收：

```powershell
$badWords = 'TO' + 'DO|TB' + 'D|待' + '补|待' + '定|<{7}|={7}|>{7}'
rg -n $badWords docs/50-AI-Keeper-Platform/02-User用户与权限系统
rg -n "^#+\s*$" docs/50-AI-Keeper-Platform/02-User用户与权限系统
```

## 最终交付标准

- User 三份文档和当前代码口径一致。
- 平台账号、owner token、player token 三层身份被明确区分。
- P0/P1/P2/P3 能力边界清晰，未实现能力不会被误塞进本轮。
- DeepSeek 每个 Batch 都有目标、允许文件方向、测试命令、预期结果和禁止事项。
- 安全验收覆盖账号角色、房主权限、玩家角色隔离、RAG 权限、WS 鉴权和公开 DTO 脱敏。
