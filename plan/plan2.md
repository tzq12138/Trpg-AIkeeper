# 管理后台、房间持久化与玩家管理打磨计划

## Summary
- 以“全局管理员后台”为第一版主线：首个注册账号自动成为 `admin`，管理页必须登录 admin 才能进入。
- 玩家登录保持可选：匿名玩家仍可加入房间；登录玩家加入时绑定 `account_id`，允许同一玩家进入多个房间。
- 房间从随机 `owner_token + localStorage` 升级为可持久管理对象：后台能列出所有房间、查看房间玩家、切换状态、选择剧本、管理玩家基础状态。
- 剧本管理支持 PDF + 多媒体素材库：素材文件存本地 `data/scenario_assets/{scenario_id}/`，数据库只存元数据和相对路径。
- 第一阶段目标是打通完整后台流程，不做完整权限运营系统、云存储、复杂审计后台。

## API / Data Model
- 扩展账号：
  - `accounts.role`: `admin | player`，首个注册账号为 `admin`，后续默认 `player`。
  - `accounts.last_seen_at`，登录和带账号 token 的请求更新。
  - `/api/auth/register`、`/api/auth/login`、`/api/auth/me` 返回 `role`。
- 扩展房间：
  - `rooms.owner_account_id`、`rooms.status` 支持 `draft/lobby/active/paused/completed/archived`。
  - 保留 `owner_token` 兼容现有 Host 页面。
  - 开局默认要求房间里至少 1 名 active 玩家，且所有 active 玩家已 ready；管理员可先在后台手动调整 ready。
- 扩展玩家角色：
  - `characters.account_id` 继续用于登录玩家绑定。
  - 新增 `characters.status`: `active/removed`，移出房间不删除历史。
  - 基础状态仍写入 `xlsx_data`：HP/SAN/MP/LUCK/status_tags。
- 新增管理员 API：
  - `GET /api/admin/overview`
  - `GET /api/admin/rooms`
  - `GET /api/admin/rooms/{room_id}`
  - `PATCH /api/admin/rooms/{room_id}` 管理状态、剧本、基础信息
  - `GET /api/admin/accounts`
  - `PATCH /api/admin/characters/{character_id}` 管理 ready、HP/SAN/MP/LUCK、状态标签、移出房间
- 新增素材 API：
  - `GET /api/admin/scenarios`
  - `POST /api/admin/scenarios/import-pdf`
  - `POST /api/admin/scenarios/{scenario_id}/assets`
  - `GET /api/admin/scenarios/{scenario_id}/assets`
  - `DELETE /api/admin/scenarios/{scenario_id}/assets/{asset_id}`
  - `POST /api/admin/scenarios/{scenario_id}/classify`
  - 素材内容通过受控文件响应读取，不暴露任意本地路径。

## Key Changes
- 管理页 `/admin`：
  - 未登录跳转 `/login?return=/admin`；非 admin 显示无权限。
  - 首页显示全局概览：房间数、进行中房间、注册账号、在线玩家、待处理行动。
  - 房间页从“手输房间码”改为持久房间列表 + 房间详情。
  - 房间详情显示剧本、状态、玩家 ready 进度、Host/Stage/Join 链接、状态切换按钮。
  - 玩家页同时显示注册账号列表和房间内角色列表，区分登录玩家/匿名玩家、在线/离线、所在房间。
- 房间流程：
  - 管理员导入剧本和素材后，可创建 `draft` 房间。
  - 选好剧本后进入 `lobby`，玩家加入并准备。
  - 所有 active 玩家 ready 后，后台或 Host 可开始游戏进入 `active`。
  - 管理员可暂停、恢复、完成、归档房间。
- 玩家流程：
  - 登录可选；登录后加入房间会把角色绑定账号。
  - 同一账号可加入多个房间，不加唯一限制。
  - 后台移出玩家只影响该房间角色，不删除账号和其他房间角色。
- Host/HUD：
  - Host HUD 从数据库角色数据补齐 investigator、ready、HP/SAN/MP/LUCK/status_tags。
  - 管理员修改玩家基础状态后写事件日志，并通过现有 projection/WS 刷新 Host 与玩家端。

## Test Plan
- 后端测试：
  - 首个注册账号自动成为 admin；后续账号为 player；非 admin 访问 `/api/admin/*` 返回 403。
  - 管理员可列出所有房间、查看房间详情、切换 `draft/lobby/active/paused/completed/archived`。
  - 开局时无玩家或未全员 ready 返回 409；全员 ready 后进入 active。
  - 登录玩家加入多个房间均成功；匿名玩家仍可加入。
  - 管理员可更新 HP/SAN/MP/LUCK/ready/status_tags，并能在 Host HUD 读到新值。
  - 移出玩家后该角色不再出现在普通 Host/Player 活跃列表，但管理详情仍可看到 removed 状态。
  - 上传多媒体素材成功写入本地目录和元数据；坏文件、路径穿越、删除不存在素材都有明确错误。
  - 剧本类型生成在无 DeepSeek key 时走可测试 fallback，有 key 时保留真实调用路径 mock 测试。
- 前端验证：
  - `node ./node_modules/typescript/bin/tsc --noEmit`
  - `node ./node_modules/vite/bin/vite.js build`
  - 手动走通：注册首个 admin -> 进入管理页 -> 导入剧本 -> 上传素材 -> 生成类型 -> 创建房间 -> 玩家匿名/登录加入 -> 车卡/上传卡 -> ready -> 后台开局 -> Host 舞台看到玩家状态。
- 回归验证：
  - 现有 `/host/create`、`/host/:roomId`、`/host/:roomId/stage`、`/player/join`、`/player/:roomId` 保持可用。
  - 现有 `owner_token` 流程不删除，只作为兼容路径。

## Assumptions
- 开发库允许用 idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 扩展，不引入正式迁移框架。
- 多媒体素材存在本地 `data/`，不提交进 Git；只提交目录说明或 `.gitkeep/.gitignore`。
- 第一版管理员只有 `admin/player` 两类角色，不做细粒度权限、禁用账号、密码重置。
- 第一版不限制玩家进入多个房间，也不强制一个账号一个房间只能有一个角色。
- AI 自动主持沿用现有 pipeline/game loop；本计划只让后台能看见和控制完整跑团状态。
