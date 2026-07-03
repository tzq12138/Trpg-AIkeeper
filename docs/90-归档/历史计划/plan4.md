# 玩家加入、车卡选择/复用、准备与恢复链路计划

## Summary
- `/player/join` 做成完整玩家入口：可游客加入，也可登录/注册后加入；登录只提示收益，不阻塞继续。
- 玩家进入房间前必须完成角色来源选择：上传 xlsx、本地预设、剧本推荐模板、复用自己旧角色、或最小手动车卡。
- 同一账号在同一房间允许创建多个调查员；每张角色卡独立 token、准备状态、房间状态。
- 房间 `lobby` 阶段可直接加入；房间 `active` 后新角色进入 `pending_approval`，需 Host 批准后才算正式入场。
- 玩家进入终端后必须手动点“准备好了”；Host 以角色为单位看准备状态和玩家/调查员信息。

## Key Changes
- 修正当前加入页回归点：
  - `/player/join` 所有加入请求都带 `Authorization`，让登录账号能绑定 `account_id`。
  - 移除页面 DEBUG 面板。
  - 剧本模板不能再伪装成 `preset_id=tpl_*`；改成正式 `template_id` 或 `source_type=template`。
  - 预设、上传、模板、复用旧角色、手动车卡都统一进入同一套“预览确认”UI。

- 新增/固化玩家加入接口：
  - `GET /api/player/rooms/{room_id}/join-info`：返回房间是否存在、房间状态、剧本标题、可加入策略、当前角色摘要、预设卡摘要、剧本模板摘要。
  - 扩展 `POST /api/player/rooms/{room_id}/join-with-character`：支持 `file | preset_id | template_id | copy_character_id | character_data` 五选一。
  - `GET /api/player/me/characters`：登录后返回当前账号已有角色，包含房间、剧本、调查员名、职业、状态、是否可恢复/可复制。
  - `POST /api/player/characters/{character_id}/restore-session`：仅账号本人可调用，返回该角色 `player_token` 并恢复到对应房间。
  - 保留现有 `/api/auth/login`、`/api/auth/register`、`/api/player/intent`，不引入新认证体系。

- 数据与状态规则：
  - `characters.status` 使用：`joined`、`ready`、`pending_approval`、`inactive`、`left`。
  - `lobby` 房间创建的新角色默认 `joined`；玩家点准备后变为 `ready`，取消准备回到 `joined`。
  - `active` 房间新建角色默认 `pending_approval`；Host 批准后变为 `joined`，再由玩家手动准备。
  - 同一账号同一房间允许多角色，不加唯一约束；Host 和 AI 都按 `character_id` 区分。
  - 游客角色只靠本地 `player_token` 恢复；登录角色可跨设备通过账号恢复 token。

- 前端流程：
  - `/player/join` 分四步：房间码与账号提示、昵称、角色来源选择、预览确认。
  - 顶部账号条显示“已登录/游客模式”，提供登录/注册入口；登录成功后回到加入页。
  - 角色来源卡片展示：本地预设、剧本推荐、我的旧角色、上传 xlsx、手动创建。
  - 加入成功后保存 `player_token`，跳转 `/player/{room_id}`；若状态是 `pending_approval`，玩家终端显示“等待 Host 批准”。
  - 玩家终端增加明确准备按钮：未准备、已准备、等待批准三种视觉状态；只通过 `intent_type=ready_toggle` 修改准备状态。

- Host 可见性：
  - Host 房间/舞台玩家列表显示“玩家昵称 / 调查员名 / 职业 / 状态 / 是否准备”。
  - 对 `pending_approval` 角色提供批准/拒绝入口；拒绝后角色变为 `inactive` 或 `left`，不进入 AI 主持上下文。
  - Host 开局按钮只统计 `joined/ready` 角色；`pending_approval` 不阻塞开局，但要单独提示。

## API / Interfaces
- `join-info` 返回结构建议：
  - `roomId`、`roomStatus`、`scenarioTitle`、`joinMode: direct | hostApproval | closed`
  - `players`: 当前房间角色摘要，供玩家确认是否进错房间。
  - `presets`: 本地预设卡，包含是否已被该房间占用。
  - `templates`: 剧本推荐模板，来自 `character_templates`，只作为复制源。
- `join-with-character` 请求字段：
  - 必填：`player_name`
  - 五选一：`file`、`preset_id`、`template_id`、`copy_character_id`、`character_data`
  - 登录态可选但应自动绑定；游客不写 `account_id`。
- 角色公开字段统一：
  - `player_name/playerName` = 玩家昵称。
  - `investigator_name/investigatorName/name` = 调查员名。
  - `status` = 当前角色状态。
  - `is_ready` 继续兼容旧字段，但前端以 `status === ready` 优先展示。

## Test Plan
- 后端测试：
  - 游客上传 xlsx 加入成功，角色无 `account_id`。
  - 登录玩家加入时正确写入 `account_id`。
  - 同一账号同一房间可创建两名不同调查员。
  - `template_id` 加入会复制模板数据，不再走本地 preset 文件。
  - `copy_character_id` 只能复制本人角色，不能复制其他账号角色。
  - `active` 房间新角色进入 `pending_approval`；Host 批准后可准备。
  - `restore-session` 只有角色所属账号可恢复 token。
  - 预设卡同房间重复选择仍返回 `409`。

- 前端验证：
  - `npm run build` 通过。
  - 手动跑通：游客上传卡加入、登录后选择预设、登录后复用旧角色、选择剧本模板、同账号同房间创建多角色。
  - 手动验证：active 房间加入显示等待批准，Host 批准后玩家能点准备。
  - 手动验证：刷新或换浏览器后，登录账号能从“我的角色”恢复进入房间。

## Assumptions
- 本轮不做完整玩家资料中心，只在加入页提供“我的旧角色/恢复会话”最小入口。
- 本轮不要求 Host 审核车卡数值，只审核 active 后加入的新角色是否允许入场。
- 不限制一个账号管理多张卡；AI 和 Host 后续全部以 `character_id` 为准。
- 不新增复杂权限系统；继续使用现有账号 token 和 `player_token`。
