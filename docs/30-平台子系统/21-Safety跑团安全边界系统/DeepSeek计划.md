# Safety 跑团安全边界系统 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + 鉴权、可见性、反剧透与导出安全风险识别版`。
- 第一轮目标不是“做一个安全后台”，而是把 `REST/WS -> catch-up/reconnect -> archive/export -> RAG/AI -> 文件/媒体 -> 部署基线` 这条安全链路做成统一口径。
- 当前代码已经有部分基础：生产 `JWT_SECRET` 启动拒绝、Player map token 强制、EventLog 局部 helper、RAG 房间成员权限、SpoilerGuard、asset 上传基础校验。
- 当前主要风险仍在 reconnect/export/archive/system_safe/CORS/RAG prompt 二次过滤，桌面安全工具必须后置。

## 执行原则

Safety 的执行顺序必须先修真实泄露风险，再做体验型桌面安全工具。任何安全改动都要先写或更新测试，不能只靠前端隐藏，不能为了兼容旧逻辑放宽鉴权。

每个 Batch 开始前先执行 `git status --short`，确认只改本批相关文件。遇到已有未提交改动时先读懂，不覆盖无关内容。

## 现状依据

- 账号鉴权：`src/server/router_auth.py`
- 生产密钥与 CORS：`src/server/main.py`
- 事件可见性与 public events：`src/server/events/event_log.py`
- Host / Player WS 与 reconnect：`src/server/main.py`、`src/server/host/ws_manager.py`、`src/server/player/router_reconnect.py`
- 玩家 archive：`src/server/player/router_player_archive.py`
- Host timeline / export：`src/server/router_archive.py`、`src/server/export.py`
- 地图：`src/server/router_map.py`
- 投影：`src/server/engine/projection.py`
- 反剧透：`src/server/engine/spoiler_guard.py`、`src/server/ai/spoiler_control.py`
- RAG：`src/server/rag_router.py`
- 文件上传：`src/server/router_admin.py`、`src/server/scenario/router_scenarios.py`、`src/server/stt.py`
- 现有测试：`tests/server/test_room_security.py`、`test_ws_auth.py`、`test_rag_security.py`、`test_reconnect.py`、`test_archive.py`、`test_spoiler_guard.py`

## 全局实现规则

1. 统一使用 `can_view_event(event, viewer, scope)` + `build_event_view(event, viewer, scope)` 作为 Safety helper 合约。
2. `scope` 至少覆盖 `live/catch_up/reconnect/archive/public_events/public_export/full_export/admin_audit`。
3. `host` 事件永远不进 Player / public。
4. `player` 事件必须有目标角色字段；缺失 owner/target 时默认拒绝。
5. `system` 事件默认不可见；只有 `event type + payload field whitelist` 同时通过才可进入 Player/public。
6. `public_export` 只能包含 `party + system_safe`；绝不再使用 `audience != 'player'` 作为公开判断。
7. RAG search 权限通过，不等于可以进入玩家 prompt；进入 prompt 前必须再次按 viewer/room/scenario/character/visibility/unlock_state 过滤。
8. token、API key、本地绝对路径、未授权素材 URL、raw prompt/raw response 不得进入 public DTO、日志、export、AI prompt。
9. X-card、fade、private feedback 只产生事件、通知和审计，不直接改 State。
10. 如本轮仅完成 schema、helper 或审计链，而未完成播放器 / 轮换 / 撤销等长期能力，回执必须明确写成“未完成能力”。
11. Host 视角不等于可见所有玩家私密结果；`player-only state_patch`、`private_notice`、私密 `action_completed` 必须持续留在 Host 视角之外。
12. EventLog 现有 helper 只能被提升和复用，不能在 Projection / Archive / Export / Reconnect 中各自复制出第二套规则。

## 全局禁止事项

1. 禁止为了兼容旧功能放宽鉴权。
2. 禁止把安全过滤写在前端。
3. 禁止让 admin 权限影响 `public_export` 的脱敏范围。
4. 禁止把 `owner_token`、`player_token`、`account_token`、API key 写入 public DTO、日志、export、AI prompt。
5. 禁止把 host-only truth、ending、未发现 clue、hidden asset title 放进玩家 prompt。
6. 禁止把本地绝对路径、未授权素材 URL 或 hidden asset URL 发给客户端。
7. 禁止让 AI、Host、桌面安全工具直接写世界状态。

## Batch Safety-0：安全基线与失败/回归测试

### 目标

- 固化当前高优链路的失败测试和回归测试。
- 对“已经修掉的点”加回归锁，例如生产 `JWT_SECRET` 拒绝启动、地图匿名访问拒绝。
- 对“仍未修的点”写失败测试，例如 reconnect snapshot / delta、public export、archive fail-open。

### 允许文件方向

- `tests/server/test_reconnect.py`
- `tests/server/test_ws_auth.py`
- `tests/server/test_archive.py`
- `tests/server/test_room_security.py`
- 可新增 `tests/server/test_safety_visibility.py`
- 可新增部署安全相关测试文件

### 建议命令

```bash
python -m pytest tests/server/test_reconnect.py tests/server/test_ws_auth.py tests/server/test_archive.py tests/server/test_room_security.py -q
```

### 验收

- 有测试证明玩家重连不会拿 host/private/他人 player 事件。
- 有测试证明无 token 地图访问 401、错房 token 403。
- 有测试证明生产默认 `JWT_SECRET` 不通过。
- 有测试证明 `public export` 不含 host-only、player-only、token、本地路径。

### 禁止事项

- 不修改业务逻辑。
- 不因为现状失败而降低测试期望。
- 不把“已经修复的安全点”从测试里删掉。

## Batch Safety-1：统一 visibility helper

### 目标

- 把当前 `EventLog._can_player_see_event()` 提升成模块级 helper 契约。
- 统一 `live/catch_up/reconnect/archive/public_events/public_export/full_export/admin_audit` 口径。
- `player` audience 缺目标角色时默认拒绝。
- `system` audience 必须按 `event type + safe fields` 白名单进入 Player/public。

### 允许文件方向

- 可新增 `src/server/security/visibility.py` 或 `src/server/events/visibility.py`
- `src/server/events/event_log.py`
- `src/server/main.py`
- `src/server/player/router_reconnect.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/server/export.py`
- `src/server/engine/projection.py`
- 相关测试文件

### 建议命令

```bash
python -m pytest tests/server/test_safety_visibility.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_room_security.py -q
```

### 验收

- 玩家实时补发、reconnect、archive、public events、export 的事件集合一致。
- host-only 永远不进玩家视角。
- player-only 只给目标 character。
- public export 只含 `party + system_safe`。
- `system_safe` 使用事件类型和字段白名单，而不是事件名 alone。

### 禁止事项

- 不用 `audience != "player"` 当 public 判断。
- 不把 filtering 写在前端。
- 不让 admin 权限影响 `public_export` 的脱敏范围。

## Batch Safety-2：reconnect、地图、state patch 与投影边界

### 目标

- 修复 `/api/player/reconnect` snapshot 返回全量 events 的问题。
- 修复 `ws_manager.reconnect()` delta 路径返回未过滤 events 的问题。
- 锁死地图 token 强制访问，避免回退到匿名基础布局。
- 明确私密 `s2c_state_patch` 和 party 公共状态摘要的分层。

### 允许文件方向

- `src/server/player/router_reconnect.py`
- `src/server/host/ws_manager.py`
- `src/server/router_map.py`
- `src/server/engine/state_service.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/events/events_registry.py`
- `src/server/engine/projection.py`
- `tests/server/test_map.py`
- `tests/server/test_projection.py`
- `tests/server/test_reconnect.py`

### 建议命令

```bash
python -m pytest tests/server/test_map.py tests/server/test_projection.py tests/server/test_reconnect.py -q
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py -q
```

### 验收

- reconnect snapshot 和 delta 路径都复用统一 helper。
- 无 token 地图访问 401，错房 token 403。
- 玩家地图视图不返回隐藏节点数量、hidden NPC、未发现 clue。
- 私密 patch 不以 party audience 广播。
- Host 不收到 player-only state patch。

### 禁止事项

- 不把全图给 Player。
- 不在 Host Client 或 Player Client 里靠隐藏 UI 修安全。
- 不把私密 patch 包在 party payload 里再让前端自己藏。

## Batch Safety-3：部署安全基线与权限 helper 收口

### 目标

- 保持生产 `JWT_SECRET` 拒绝启动的现有能力，并补测试。
- 把 CORS 从硬编码 `*` 改成配置化 allowlist。
- 日志和导出统一脱敏 token、API key、签名 URL 参数。
- 梳理 owner/admin/player 权限 helper，减少散落判断。

### 允许文件方向

- `src/server/config.py`
- `src/server/main.py`
- `src/server/router_auth.py`
- `src/server/log_config.py`
- `src/server/router_rooms.py`
- `src/server/host/router_host.py`
- `src/server/router_archive.py`
- `tests/server/test_room_security.py`
- 可新增部署安全测试文件

### 建议命令

```bash
python -m pytest tests/server/test_room_security.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_archive.py -q
```

### 验收

- 开发环境不破坏 `dev.py`。
- 生产环境默认 secret 不通过。
- 生产环境 `CORS=*` 不通过，或健康检查失败。
- 日志和导出不出现完整 owner/player/account token 或 API key。
- 回执明确说明哪个环境变量代表 production，`CORS_ALLOW_ORIGINS` 如何配置，dev 是否显式允许宽松模式。

### 禁止事项

- 不把默认 secret 用作生产 fallback。
- 不在错误响应中返回密钥、token 或完整内部路径。
- 不把 dev 宽松配置偷偷带到生产。

## Batch Safety-4：AI 反剧透、RAG 最终过滤与审计字段

### 目标

- 固化玩家 prompt 裁剪，禁止 raw truth、ending、未发现线索、hidden asset title 进入玩家上下文。
- 把 RAG “搜索权限”与“进入玩家 prompt” 两层过滤分开实现。
- 固定 `SpoilerAuditDTO` 字段。
- AI call log 摘要脱敏。

### 允许文件方向

- `src/server/engine/spoiler_guard.py`
- `src/server/ai/spoiler_control.py`
- `src/server/ai/gateway.py`
- `src/server/rag_router.py`
- `src/server/engine/projection.py`
- `src/server/engine/resolution_pipeline.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_spoiler.py`
- `tests/server/test_ai_kp.py`
- `tests/server/test_rag_security.py`

### 建议命令

```bash
python -m pytest tests/server/test_spoiler_guard.py tests/server/test_spoiler.py tests/server/test_ai_kp.py tests/server/test_rag_security.py -q
python -m pytest tests/server/test_projection.py -q
```

### 验收

- 玩家 prompt 不含 raw truth、ending、未发现 clue、hidden asset title。
- RAG search 通过后，进入玩家 prompt 前仍有二次过滤。
- 命中后 retry 成功或 fallback，并写结构化 `SpoilerAudit`。
- `SpoilerAudit` 为 admin-only，不进 `public_export`。
- AI call logs 不记录完整 prompt、token 或密钥。
- Host 视角仍看不到 player-only 私密结果。

### 禁止事项

- 不把 raw scenario text 原样放入玩家 prompt。
- 不因为 SpoilerGuard 命中就跳过 Journal 审计。
- 不让 AI 直接写状态。

## Batch Safety-5：文件、素材、PDF、STT 安全

### 目标

- 在已有 asset 上传基础校验上，补 Safety 视角的统一回归口径。
- PDF 导入增加 MIME、文件头、大小和临时文件清理。
- xlsx 上传和 STT 增加安全测试。
- 确保客户端不见本地绝对路径和未授权素材 URL。

### 允许文件方向

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/player/router_player.py`
- `src/server/stt.py`
- `src/server/export.py`
- `tests/server/test_asset_security.py`
- `tests/server/test_character_join_import.py`
- `tests/server/test_player_speech_to_text.py`

### 建议命令

```bash
python -m pytest tests/server/test_asset_security.py tests/server/test_character_join_import.py tests/server/test_player_speech_to_text.py -q
python -m pytest tests/server/test_room_security.py tests/server/test_archive.py -q
```

### 验收

- 危险扩展名、伪装 MIME、超大文件被拒绝。
- PDF、xlsx、STT 临时文件成功或失败后都清理。
- 删除文件前 `resolve()` 后确认仍在资产根目录。
- STT 音频有 MIME、大小、时长、速率限制。
- 客户端响应和 export 不含本地绝对路径、未授权素材 URL。

### 禁止事项

- 不把用户上传文件路径直接回传给客户端。
- 不保存 STT 原始音频到长期目录。
- 不允许目录穿越或覆盖已有系统文件。

## Batch Safety-6：桌面安全工具初版

### 目标

- 增加 X-card、fade、private feedback 的产品最小闭环。
- 安全工具只产生事件、通知和日志，不直接改 HP/SAN、地图、线索或房间事实。
- 增加限速和滥用审计。

### 允许文件方向

- `src/server/player/router_player.py` 或新建 safety router
- `src/server/events/events_registry.py`
- `src/server/engine/projection.py`
- `src/server/player/router_player_archive.py`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/pages/HostStage.tsx`
- `tests/server/test_safety_tools.py`

### 建议命令

```bash
python -m pytest tests/server/test_safety_tools.py tests/server/test_archive.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

### 验收

- Player 可触发 X-card，Host 收到 public-safe pause 提示。
- private feedback 只给 Host/Admin 可见，不进 `public_export`。
- 高频触发返回 429 或进入冷却。
- 安全事件不改变世界状态。

### 禁止事项

- 如果 Safety-1 到 Safety-5 未完成，不建议先做 X-card UI。
- 不把 X-card 做成踢人、回滚或任意改状态入口。
- 不公开 private feedback 内容。
- 不绕过 Projection 可见性过滤。

## Batch Safety-7：全量回归与安全验收

### 目标

- 跑后端安全相关全量测试。
- 跑前端 build。
- 手动验证一条核心链路和一条越权链路。

### 建议命令

```bash
python -m pytest tests/server/test_room_security.py tests/server/test_ws_auth.py tests/server/test_rag_security.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_spoiler_guard.py tests/server/test_spoiler.py -q
python -m pytest tests/server -q
cd src/client && npm run build
```

### 验收

- 创建房间、玩家加入、ready、开局、提交行动、AI/规则裁决、投影、日志可查。
- 玩家 A 断线后重连，看不到玩家 B private event。
- Host 刷新舞台，看不到 player-only patch。
- `public_export` 即使由 owner/admin 发起，也不能导出 host-only/private。
- 无 token 地图访问失败。
- AI 剧透输出被拦截并审计。
- owner/player token 轮换和 account token 撤销如未实现，回执必须明确列为遗留风险。

### 禁止事项

- 不在测试失败时删除安全测试。
- 不用宽泛异常吞掉安全失败。
- 不把安全失败降级为前端提示。

## 总禁止事项

- 不放宽任何鉴权来换取旧功能通过。
- 不依赖前端隐藏实现权限。
- 不把 owner/player/account token 写入 public DTO、日志、export、AI prompt。
- 不把 Host-only 真相、raw truth、ending、未发现线索放进玩家上下文。
- 不让 AI、Host、桌面安全工具直接写世界状态。
- 不把本地绝对路径、未授权素材或隐藏 asset URL 发给客户端。
