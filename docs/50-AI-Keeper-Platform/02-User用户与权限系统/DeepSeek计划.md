# User 用户与权限系统 DeepSeek 计划

## 执行定位

User 模块的 DeepSeek 执行目标，是把身份和权限边界收紧到可持续回归：

`account token -> 平台角色 -> owner 权限 -> player token -> character 绑定 -> 接口鉴权 -> 资源隔离`

本计划允许 DeepSeek 修补注册、登录、账号角色、owner/player token、Room/Host/Player/Admin/RAG/WS 鉴权和恢复链路。社区账号、好友、会员、多设备正式会话、完整邀请体系和旁观者系统不进入本轮。

当前阶段说明：

- 本计划对应的是“P0 主链路 + 生产风险识别版”的执行包，不是 User 的最终生产安全完成版。
- `JWT_SECRET`、首账号 admin、query token WS、owner/player token 生命周期、Player-facing RAG 裁剪这些问题，当前都还是已识别未关闭缺口。

## 全局执行规则

- 每个 Batch 开始前先运行 `git status --short`，确认工作区已有改动，禁止覆盖无关文件。
- 当前代码优先于旧 PRD；旧 PRD 只用来补产品语义。
- 前端隐藏按钮不能替代后端鉴权。
- 后端不能信任前端传入的 `characterId`、`role` 或本地 slot。
- `account_token`、`owner_token`、`player_token` 三者不得混用。
- 当前 `room_id`、未来 `room_code`、未来 `invite_token` 都不等于角色控制凭证。
- 每个 Batch 在动接口前，先列出本批涉及的 DTO、WS payload、日志字段和敏感字段清单。
- 默认禁止把以下字段塞进 public DTO、party 广播、普通日志和错误上报：`password_hash`、`account_token`、`owner_token`、`player_token`、`character_secret`、`scenario_truth`、`private_clue_ids`。
- 涉及 token、账号角色、Admin、RAG、WS 的改动必须补测试。
- 不重写整套认证框架；先收敛当前散落鉴权和生产安全缺口。

## Batch User-0：现状核对与文档乱码风险

| 项 | 内容 |
|---|---|
| 目标 | 核对 auth/admin/player/host/rag/ws 的真实鉴权实现，修正文档乱码，建立三层身份口径 |
| 允许文件方向 | `src/server/router_auth.py`、`router_admin.py`、`router_rooms.py`、`host/router_host.py`、`player/router_player.py`、`main.py`、`rag_router.py`、`src/client/src/pages/LoginPage.tsx`、`src/client/src/shared/identity.ts`、User 文档 |
| 主要任务 | 修正文档或用户可见乱码；梳理 `account/owner/player` 三层身份；标出当前代码已实现、未实现和仅开发兼容的路径 |
| 测试命令 | `pytest tests/server/test_room_security.py tests/server/test_ws_auth.py -q` |
| 预期结果 | 现有安全测试通过；文档与代码口径一致；能明确指出生产风险缺口 |
| 禁止事项 | 不迁移到大型认证框架；不顺手新增 OAuth、短信、邮箱、二次认证 |

## Batch User-1：账号注册、登录、角色与 Admin 后台

| 项 | 内容 |
|---|---|
| 目标 | 稳定平台账号体系和 `admin/host/player` 角色边界 |
| 允许文件方向 | `src/server/router_auth.py`、`src/server/router_admin.py`、`src/client/src/pages/LoginPage.tsx`、`src/client/src/pages/AdminDashboard.tsx`、相关测试 |
| 主要任务 | 确认 PBKDF2 密码校验；确认 `/api/auth/me`；确认 admin 可修改账号 `role`；确认 player 不能开房；补首账号 admin 与生产 bootstrap 策略文档；生产环境加入 `JWT_SECRET` fail-fast 方案 |
| 测试命令 | `pytest tests/server/test_room_security.py tests/server/test_rag_security.py -q` |
| 预期结果 | 未登录后台 401；非 admin 403；admin 可列账户与改 role；player 不能创建房间；生产环境默认密钥和无保护 bootstrap 有明确阻断策略，且不能再被文档口径误写成“已天然安全” |
| 禁止事项 | 不把 host 权限提升成 admin；不让前端 `account.role` 成为授权依据；不假装“首账号自动 admin”可以直接带去生产 |

## Batch User-2：房主 owner 权限与 Host 鉴权

| 项 | 内容 |
|---|---|
| 目标 | 统一 `owner_token`、`owner_account_id`、`admin` 三条房间管理鉴权路径 |
| 允许文件方向 | `src/server/router_rooms.py`、`src/server/router_archive.py`、`src/server/host/router_host.py`、`src/server/scenario/router_scenarios.py`、`src/client/src/pages/HostCreate.tsx`、`HostLobby.tsx`、`HostStage.tsx`、`tests/server/test_rooms.py`、`test_host_room_lifecycle.py`、`test_host.py`、`test_ws_auth.py` |
| 主要任务 | 校验房间管理接口只允许 owner/admin；确认 host account 不能管理不是自己 `owner_account_id` 的房间；公开 DTO 不泄露 owner token；Host 不能借 User/Room 口径拿到完整 KP 真相 |
| 测试命令 | `pytest tests/server/test_rooms.py tests/server/test_host_room_lifecycle.py tests/server/test_host.py tests/server/test_ws_auth.py -q` |
| 预期结果 | owner token、owner account、admin 均可管理合法房间；其他 host 账号被拒绝；公开 DTO 安全；Host WS 鉴权稳定 |
| 禁止事项 | 不把任意 host 账号当作任意房间 owner；不把 owner token 放进公开响应 |

## Batch User-2.5：Token 生命周期与脱敏

| 项 | 内容 |
|---|---|
| 目标 | 先补齐 token 生命周期设计和敏感字段脱敏口径，再进入更深的权限施工 |
| 允许文件方向 | `src/server/router_auth.py`、`src/server/router_rooms.py`、`src/server/player/router_player.py`、`src/server/main.py`、`src/server/db_adapter.py`、日志相关文件、相关测试、User/Room 文档 |
| 主要任务 | 为 account/owner/player token 明确 `exp`、撤销、轮换、hash 存储方向；确认 owner/player token 不进入公开 DTO、公共事件和普通日志；若当前做不到 hash，至少预留字段与技术债说明 |
| 测试命令 | `pytest tests/server/test_room_security.py tests/server/test_player_intent.py tests/server/test_ws_auth.py -q` |
| 预期结果 | token 生命周期口径清晰；日志与 DTO 不再扩散高敏字段；账号降权、改密、封禁后的 token 失效策略有明确方案；若本批未实现 rotate/revoke/hash，也必须把未关闭缺口写清楚 |
| 禁止事项 | 不为了快速过关把 token 常驻到更多前端状态；不把“开发兼容凭证”包装成正式长期方案 |

## Batch User-3：玩家 token、角色绑定与个人资源隔离

| 项 | 内容 |
|---|---|
| 目标 | 稳定 `player_token -> character_id -> room_id` 的角色身份链路 |
| 允许文件方向 | `src/server/player/router_player.py`、`router_reconnect.py`、`router_clues.py`、`router_objectives.py`、`router_player_archive.py`、`src/server/main.py`、`src/client/src/pages/PlayerJoinPage.tsx`、`PlayerLobby.tsx`、`PlayerActionPage.tsx`、相关测试 |
| 主要任务 | 所有 Player 接口通过 token 反查角色；`restore-session` 校验 `account_id`；复制角色校验同账号或源 token；action/clue/objective/archive 资源隔离；统一 401/403/404 外部口径 |
| 测试命令 | `pytest tests/server/test_player_intent.py tests/server/test_character_join_import.py tests/server/test_reconnect.py tests/server/test_clues.py tests/server/test_objectives.py tests/server/test_archive.py -q` |
| 预期结果 | 缺 token 401；无效 token 403；玩家不能查他人 action；玩家不能复制他人账号角色；私人资源不越界 |
| 禁止事项 | 不信任前端传入 `characterId`；不让 `account_token` 直接代替 `player_token` 执行玩家动作 |

## Batch User-3.5：WebSocket 鉴权升级

| 项 | 内容 |
|---|---|
| 目标 | 从长期 query token 逐步过渡到短期 `ws_ticket` 方案 |
| 允许文件方向 | `src/server/main.py`、`src/server/host/router_host.py`、`src/server/router_auth.py`、`src/server/player/router_player.py`、`src/client/src/shared/ws.ts`、`src/client/src/pages/HostLobby.tsx`、`PlayerLobby.tsx`、相关测试 |
| 主要任务 | 设计 `POST /api/ws-ticket` 或等价票据接口；Host 使用 owner/account 身份换取 host ticket；Player 使用 player token 换取 player ticket；ticket 应短期有效且一次性使用；连接失败不泄露房间/角色存在性 |
| 测试命令 | `pytest tests/server/test_ws_auth.py tests/server/test_host.py -q` |
| 前端验证 | 涉及 WS 客户端时运行 `npm run build` |
| 预期结果 | 正式环境可以摆脱 query token；日志与浏览器层敏感面收敛；断线重连仍可用；在此之前 query token 只视为开发兼容路径 |
| 禁止事项 | 不把 query token 风险当成“只是样子难看”；不把 ws_ticket 做成另一个长期静态 token |

## Batch User-4：RAG、AI 入口与知识权限

| 项 | 内容 |
|---|---|
| 目标 | 确保知识检索和索引操作符合 admin/owner/member 权限，并明确玩家读到什么 |
| 允许文件方向 | `src/server/rag_router.py`、`src/server/ai/rag.py`、`src/server/router_admin.py`、`tests/server/test_rag_security.py`、`tests/server/test_rag_router.py`、`tests/server/test_rag.py`、相关文档 |
| 主要任务 | 保持 admin 全局读写、owner 房间级写、成员房间级读；补“成员能 search 不等于能看原始 chunk”的规则；把玩家结果过滤责任写清楚并补测试 |
| 测试命令 | `pytest tests/server/test_rag_security.py tests/server/test_rag_router.py tests/server/test_rag.py -q` |
| 预期结果 | player 不能写 index；非成员不能 search；玩家结果不会直接泄露 `scenario_truth` 或未发现线索；相关过滤行为有测试覆盖 |
| 禁止事项 | 不在 RAG 层直接把原始世界书 chunk 返回给普通玩家；不把结果可见性假装成已由成员鉴权自动解决 |

## Batch User-5：回归验收与权限矩阵补齐

| 项 | 内容 |
|---|---|
| 目标 | 对 User 权限边界做集中回归，形成后续模块可复用的验收口径 |
| 允许文件方向 | 测试与小范围修复文件；发现跨模块缺陷时记录到对应模块文档或 `docs/30-DeepSeek任务包/` |
| 后端测试 | `pytest tests/server/test_room_security.py tests/server/test_rag_security.py tests/server/test_ws_auth.py tests/server/test_player_intent.py tests/server/test_reconnect.py tests/server/test_character_join_import.py -q` |
| 前端测试 | 涉及登录页、Admin 面板、身份 slot、Host/Player 页面时运行 `npm run build` |
| 手动验收 | admin 注册/登录；admin 提升 host；host 创建房间；player 加入并 ready；错误 token 被拒绝；player 不能访问他人 action；非成员不能 RAG search |
| 预期结果 | `account/owner/player` 三层身份边界清晰；主链路无越权；公开 DTO 和 WS 广播脱敏；生产基线缺口有明确落点 |
| 禁止事项 | 不为了过测试删除安全校验；不把权限判断只放前端；不把“文档写了”当成“生产风险已解决” |

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
$lintPattern = 'T' + 'O' + 'D' + 'O|T' + 'B' + 'D|待' + '补|待' + '定|' + ('<' * 7) + '|' + ('=' * 7) + '|' + ('>' * 7)
rg -n $lintPattern docs/50-AI-Keeper-Platform/02-User用户与权限系统
rg -n "^#+\\s*$" docs/50-AI-Keeper-Platform/02-User用户与权限系统
```

## 最终交付标准

- User 三份文档与当前代码口径一致。
- `account_token`、`owner_token`、`player_token` 三层身份边界明确。
- 文档已把 `room_id / room_code / invite_token / ws_ticket` 与凭证体系对齐。
- DeepSeek 每个 Batch 都有目标、允许文件方向、测试命令、预期结果和禁止事项。
- 文档明确区分了“当前代码事实”“正式环境安全基线”“后续演进方向”。
- 安全验收覆盖账号角色、房主权限、玩家角色隔离、RAG 权限、WS 鉴权和公开 DTO 脱敏。
- 文档完成不等于生产安全完成；只有 bootstrap admin、`JWT_SECRET`、`ws_ticket`、token 生命周期、RAG 结果裁剪真正实现并通过测试后，User 才能进入生产安全完成版。
