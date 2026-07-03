# 房主开房、真实多账号与单机测试流程计划

## Summary
- 把主流程改成：登录账号 → 房主创建房间并选择剧本 → 玩家登录/注册加入 → 车卡/导入 → 玩家准备 → 房主确认并开始 → 进入 Host 舞台。
- 新增正式 `host` 角色：`admin` 管全局，`host` 开房和启动自己房间，`player` 加入房间。
- 支持同一浏览器内多身份测试：用“身份槽”隔离不同账号、房主 token、玩家 token，方便单机开多个号。

## API / Interfaces
- 账号角色扩展为 `admin | host | player`。
- 注册默认 `player`；只有 `admin` 能在账号管理里把账号改为 `host`。
- `POST /api/rooms` 改为 `host/admin` 可用：
  - `host` 必须登录，只能创建自己作为房主的房间。
  - `admin` 可创建房间并指定房主账号。
  - `scenario_id` 必填，创建房间时必须选剧本。
- Host 权限校验统一支持两种方式：
  - 新方式：`Authorization: Bearer account_token`，账号必须是房间 `owner_account_id` 或 `admin`。
  - 旧方式：`X-Owner-Token` 继续兼容。
- 新增或固化 `GET /api/rooms/mine`：返回当前 host/admin 可管理的房间列表，供房主工作台使用。

## Key Changes
- `/host/create` 重做为正式房主开房页：
  - 未登录先跳登录。
  - 非 `host/admin` 显示“需要房主权限，请联系管理员”。
  - 创建前必须选择剧本。
  - 创建成功后进入 `/host/{roomId}` 大厅，不直接跳舞台。
- `/host/{roomId}` 大厅变成真正启动页：
  - 显示剧本、房间码、玩家加入链接、已加入玩家、调查员名、准备状态。
  - 剧本在 `draft/lobby` 且未开始前可改。
  - “开始游戏”默认要求至少 1 名玩家且所有玩家已准备。
  - 如果有人未准备，显示未准备名单，并允许房主二次确认“强制开始”。
- Admin 页保留全局管理定位：
  - 可查看/创建/修改房间，但不作为主要开房入口。
  - 房间详情增加“打开房主大厅”“打开玩家入口”。
  - 账号管理支持把 `player` 提升为 `host`。
- 正式多身份功能：
  - 新增“身份槽/多账号”入口。
  - 每个身份槽保存独立的 `account_token/account/owner_token/player_token`。
  - 每个浏览器标签页用 `sessionStorage` 记录当前使用哪个身份槽，避免多个标签页互相挤掉登录态。
  - 旧的全局 `localStorage` token 首次进入时迁移到默认身份槽，保持兼容。
- 玩家加入页：
  - 玩家加入正式要求登录账号。
  - 未登录时先登录/注册，再回到加入页。
  - 加入成功后角色绑定 `account_id`，进入玩家终端并可点击准备。

## Test Plan
- 后端测试：
  - 注册默认是 `player`，第一个账号仍是 `admin`。
  - `admin` 可把账号改为 `host`。
  - `player` 创建房间返回 403。
  - `host` 创建房间必须带 `scenario_id`，成功后 `owner_account_id` 是自己。
  - `host` 不能管理别人房间，`admin` 可以。
  - 启动房间：无剧本失败、未准备返回名单、强制开始成功。
- 前端验证：
  - `npm run build` 通过。
  - `/host/create` 未登录会引导登录。
  - `player` 账号看不到开房能力。
  - `host` 账号能选剧本创建房间。
  - 同一浏览器开多个标签页，切不同身份槽后能同时保持房主和多个玩家。
  - 玩家加入、车卡选择、准备状态能实时显示到 Host 大厅。
  - 房主点击开始后进入 `/host/{roomId}/stage`。
- 手动单机流程：
  - Admin 登录，创建或提升一个 host 账号。
  - Host 身份槽登录，创建房间并选剧本。
  - Player A/B/C 身份槽分别登录或注册，加入同一房间，选择/导入车卡，点击准备。
  - Host 大厅看到全部玩家 OK，点击开始游戏。

## Assumptions
- 本轮不做复杂权限邀请系统；`host` 角色由 `admin` 手动授予。
- 剧本必须在创建房间时选择，但开局前允许房主改。
- “网页内多身份”是正式功能，不隐藏到开发模式。
- Admin 管理页负责兜底管理，Host 大厅负责真实跑团启动流程。
