# Safety 跑团安全边界系统 DeepSeek 计划 V2.0

## 执行原则

Safety 的执行顺序必须先修真实泄露风险，再做体验型桌面安全工具。任何安全改动都要先写或更新测试，不能只靠前端隐藏，不能为了兼容旧逻辑放宽鉴权。

每个 Batch 开始前先执行 `git status --short`，确认只改本批相关文件。遇到已有未提交改动时先读懂，不覆盖无关内容。

## 现状依据

- 账号鉴权：`src/server/router_auth.py`
- 房间 owner/admin 鉴权：`src/server/router_rooms.py`
- Player token：`src/server/player/router_player.py`
- Host 鉴权和 HostStore：`src/server/host/router_host.py`、`src/server/host/host_store.py`
- WS 和 catch-up：`src/server/main.py`、`src/server/host/ws_manager.py`
- 重连：`src/server/player/router_reconnect.py`
- 地图：`src/server/router_map.py`
- 投影：`src/server/engine/projection.py`
- 反剧透：`src/server/engine/spoiler_guard.py`、`src/server/ai/spoiler_control.py`
- RAG：`src/server/rag_router.py`
- 导出和归档：`src/server/export.py`、`src/server/router_archive.py`、`src/server/player/router_player_archive.py`
- 文件上传：`src/server/router_admin.py`、`src/server/scenario/router_scenarios.py`、`src/server/stt.py`
- 现有测试：`tests/server/test_room_security.py`、`test_ws_auth.py`、`test_rag_security.py`、`test_reconnect.py`、`test_archive.py`、`test_spoiler_guard.py`

## Batch Safety-0：安全基线与失败测试

目标：

- 固化当前高优缺口的失败测试。
- 覆盖 Player WS catch-up、`/api/player/reconnect`、地图匿名访问、public export、public events。
- 不先修逻辑，只让风险可复现。

允许文件方向：

- `tests/server/test_reconnect.py`
- `tests/server/test_ws_auth.py`
- `tests/server/test_archive.py`
- `tests/server/test_room_security.py`
- 可新增 `tests/server/test_safety_visibility.py`

建议命令：

```bash
python -m pytest tests/server/test_reconnect.py tests/server/test_ws_auth.py tests/server/test_archive.py tests/server/test_room_security.py -q
```

验收：

- 有测试证明玩家重连不会拿 host/private/他人 player 事件。
- 有测试证明无 token 地图访问应返回 401。
- 有测试证明 public export 不含 host-only、player-only、token、本地路径。
- 这些测试在修复前至少能暴露当前风险。

禁止事项：

- 不修改业务逻辑。
- 不因为现状失败而降低测试期望。

## Batch Safety-1：统一可见性过滤

目标：

- 新增统一 visibility helper。
- 让 Player WS catch-up、`/api/player/reconnect`、player archive、public events、public export 复用同一规则。
- player audience 缺目标角色时默认拒绝。
- system audience 必须按白名单进入 public。

允许文件方向：

- 可新增 `src/server/security/visibility.py` 或 `src/server/events/visibility.py`
- `src/server/main.py`
- `src/server/host/ws_manager.py`
- `src/server/player/router_reconnect.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/server/export.py`
- 相关测试文件

建议命令：

```bash
python -m pytest tests/server/test_safety_visibility.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_room_security.py -q
```

验收：

- 玩家实时补发、重连、archive、export 的事件集合一致。
- host-only 永远不进玩家视角。
- player-only 只给目标 character。
- public export 只含 party 和 system 白名单。

禁止事项：

- 不用 `audience != "player"` 当 public 判断。
- 不把 filtering 写在前端。
- 不让 admin 权限影响 public export 的脱敏范围。

## Batch Safety-2：地图、状态 patch 与投影边界

目标：

- 修复 `/api/map/{room_id}` 匿名返回基础地图布局的问题。
- 明确 `s2c_state_patch` 是 player 定向还是 party 公共摘要。
- 修复 state patch、reconnect patch 与 Projection 文档口径冲突。

允许文件方向：

- `src/server/router_map.py`
- `src/server/engine/state_service.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/events/events_registry.py`
- `tests/server/test_map.py`
- `tests/server/test_projection.py`
- `tests/server/test_reconnect.py`

建议命令：

```bash
python -m pytest tests/server/test_map.py tests/server/test_projection.py tests/server/test_reconnect.py -q
python -m pytest tests/server/test_state_service.py tests/server/test_state_service_consistency.py -q
```

验收：

- 无 token 地图访问 401，错房 token 403。
- 玩家地图视图只返回已探索或可见节点。
- 私密 patch 不以 party audience 广播。
- Host 不收到 player-only state patch。

禁止事项：

- 不把全图给 Player。
- 不在 Host Client 或 Player Client 里靠隐藏 UI 修安全。

## Batch Safety-3：部署安全基线

目标：

- 强制生产环境不能使用默认 `JWT_SECRET`。
- CORS 从硬编码 `*` 改为配置化 allowlist。
- 日志和导出统一脱敏 token、API key、签名 URL 参数。
- 梳理 auth helper，减少 owner/admin 判断散落。

允许文件方向：

- `src/server/config.py`
- `src/server/router_auth.py`
- `src/server/main.py`
- `src/server/log_config.py`
- `src/server/router_rooms.py`
- `src/server/host/router_host.py`
- `src/server/router_archive.py`
- `tests/server/test_room_security.py`
- 可新增部署安全测试文件

建议命令：

```bash
python -m pytest tests/server/test_room_security.py tests/server/test_ws_auth.py -q
python -m pytest tests/server/test_archive.py -q
```

验收：

- 开发环境不破坏 `dev.py`。
- 生产环境默认 secret 不通过。
- CORS allowlist 可由环境变量配置。
- 日志和导出不出现完整 owner/player token 或 API key。

禁止事项：

- 不把默认 secret 用作生产 fallback。
- 不在错误响应中返回密钥、token 或完整内部路径。

## Batch Safety-4：AI 反剧透与上下文安全

目标：

- 修复 SpoilerGuard 用户可见乱码文案。
- 强化玩家 prompt 裁剪，禁止 raw truth、ending、未发现线索进入玩家上下文。
- 确保 AI 输出给 player/party 前经过 SpoilerGuard。
- AI call log 摘要脱敏。

允许文件方向：

- `src/server/engine/spoiler_guard.py`
- `src/server/ai/spoiler_control.py`
- `src/server/ai/gateway.py`
- `src/server/engine/projection.py`
- `src/server/engine/resolution_pipeline.py`
- `tests/server/test_spoiler_guard.py`
- `tests/server/test_spoiler.py`
- `tests/server/test_ai_kp.py`

建议命令：

```bash
python -m pytest tests/server/test_spoiler_guard.py tests/server/test_spoiler.py tests/server/test_ai_kp.py -q
python -m pytest tests/server/test_projection.py -q
```

验收：

- fallback、retry prompt、redacted 文案可读。
- 未解锁 truth、ending、hidden clue、hidden NPC、hidden asset 被拦截。
- 命中后 retry 成功或 fallback，并写 spoiler audit。
- AI call logs 不记录完整 prompt、token 或密钥。

禁止事项：

- 不把 raw scenario text 原样放入玩家 prompt。
- 不因为 SpoilerGuard 命中就跳过 Journal 审计。
- 不让 AI 直接写状态。

## Batch Safety-5：文件、素材、STT 安全

目标：

- 给 Admin asset 上传增加 MIME、扩展、文件头、大小和路径根目录校验。
- PDF 导入增加文件头和大小校验，临时文件清理。
- xlsx 上传和 STT 增加安全测试。
- 确保素材 URL 不暴露本地绝对路径。

允许文件方向：

- `src/server/router_admin.py`
- `src/server/scenario/router_scenarios.py`
- `src/server/player/router_player.py`
- `src/server/stt.py`
- `tests/server/test_asset_security.py`
- `tests/server/test_character_join_import.py`
- `tests/server/test_player_speech_to_text.py`

建议命令：

```bash
python -m pytest tests/server/test_asset_security.py tests/server/test_character_join_import.py tests/server/test_player_speech_to_text.py -q
python -m pytest tests/server/test_room_security.py -q
```

验收：

- 危险扩展名、伪装 MIME、超大文件被拒绝。
- 删除文件前 resolve 后确认仍在资产根目录。
- PDF 和 xlsx 临时文件成功或失败后都清理。
- STT 音频有 MIME、大小、时长、速率限制。

禁止事项：

- 不把用户上传文件路径直接回传给客户端。
- 不保存 STT 原始音频到长期目录。
- 不允许目录穿越或覆盖已有系统文件。

## Batch Safety-6：桌面安全工具初版

目标：

- 增加 X-card、fade、private feedback 的产品最小闭环。
- 安全工具只产生事件、通知和日志，不直接改 HP/SAN、地图、线索或房间事实。
- 增加限速和滥用审计。

允许文件方向：

- `src/server/player/router_player.py` 或新建 safety router
- `src/server/events/events_registry.py`
- `src/server/engine/projection.py`
- `src/server/player/router_player_archive.py`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/pages/HostStage.tsx`
- `tests/server/test_safety_tools.py`

建议命令：

```bash
python -m pytest tests/server/test_safety_tools.py tests/server/test_archive.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

验收：

- Player 可触发 X-card，Host 收到公共暂停提示。
- private feedback 只给 Host/Admin 可见，不进 public export。
- 高频触发返回 429 或进入冷却。
- 安全事件不改变世界状态。

禁止事项：

- 不把 X-card 做成踢人、回滚或任意改状态入口。
- 不公开 private feedback 内容。
- 不绕过 Projection 可见性过滤。

## Batch Safety-7：全量回归与安全验收

目标：

- 跑后端安全相关全量测试。
- 跑前端 build。
- 手动验证一条核心链路和一条越权链路。

建议命令：

```bash
python -m pytest tests/server/test_room_security.py tests/server/test_ws_auth.py tests/server/test_rag_security.py tests/server/test_reconnect.py tests/server/test_archive.py tests/server/test_spoiler_guard.py tests/server/test_spoiler.py -q
python -m pytest tests/server -q
cd src/client && npm run build
```

验收：

- 创建房间、玩家加入、ready、开局、提交行动、AI/规则裁决、投影、日志可查。
- 玩家 A 不能读取玩家 B 私密事件。
- 无 token 地图访问失败。
- public export 不含 token、host-only、player-only、隐藏素材、本地路径。
- AI 剧透输出被拦截并审计。

禁止事项：

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
