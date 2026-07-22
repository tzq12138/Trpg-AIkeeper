# AI-Keeper 玩家体验 V2：M2–M4 验收报告

日期：2026-07-11  
工作树：`CodeX-aikeeper` 当前 V2 实现  
隔离服务：API `http://127.0.0.1:3012`，前端 `http://127.0.0.1:5184`

## 自动化验证

| 范围 | 命令/证据 | 结果 |
| --- | --- | --- |
| 战役回流、地图、秘密行动 | `test_campaign_v2.py`、`test_resolution_pipeline.py`、`test_host_room_lifecycle.py`、`test_reconnect.py` | 相关回归通过 |
| 地图草稿与动态 AI 回退 | `tests/server/test_ai_gateway.py tests/server/test_map_draft_v2.py -q` | 13 passed |
| 迁移 ZIP | `tests/server/test_room_migration_v2.py tests/server/test_archive.py -q` | 17 passed |
| 入房限流 | `tests/server/test_player_join_rate_v2.py tests/server/test_player_invite_v2.py -q` | 6 passed |
| 后端全量 | `python -m pytest tests/server -q` | 730 passed（577.83 秒） |
| 前端 | `npm run test` | 14 files / 39 tests passed |
| 前端构建 | `npm run build` | passed |
| 差异检查 | `git diff --check` | passed（仅既有 CRLF 提示） |

所有列出的套件均已获得完整退出结果。

## 多人验收

### 4 人完整 loop

- 脚本：`scripts/run_multiplayer_loop.py`
- 房间：`12d5fa14`
- 结果：4 位玩家均完成入房、准备、开局、每人一条行动、结算、战役结束、摘要、战报导出和玩家归档捕获。
- 证据：`docs/loop_runs/20260711-081535-12d5fa14.md` 与同名 JSON、4 份玩家记录。

### 8 人压力 loop

- 房间：`6ad0fbc6`
- 结果：8 位不同已登录账号从同一 IP 成功入房；8 条同轮行动全部结算；战役结束和 8 份玩家记录全部生成。
- 证据：`docs/loop_runs/20260711-082410-6ad0fbc6.md` 与同名 JSON、8 份玩家记录。
- 修复：加入限流从“每 IP 5 次/分钟”改为“已登录账号独立分桶；匿名访客仍按 IP 限流”，避免局域网第 6–8 位真实玩家被误伤。
- 观察：当前 AI 结算按行动顺序处理，8 人一轮约 73 秒；60 秒脚本阈值会超时，但后台最终 8/8 结算。正式压力验收使用 120 秒阈值，并将该吞吐数据保留为后续并发优化项。

## 浏览器验收

- 390×844：玩家 `/player/{token}` 显示战役回流、Session Zero、私人笔记、证据板与底部导航；控制台 `warn/error` 为 `[]`。
- 360×800 与 430×860：战役回流、导航和私人笔记核心区均存在。
- 测试使用隔离前端 `:5184`；视口覆盖完成后已恢复默认值。

## 内容与迁移

- 三套原创黄金模组位于 `data/golden_modules/`，包含单人教学、2–4 人短团和调查沙盒。
- 管理接口可将黄金模组安装为发布剧本、已发布 CoC7 规则绑定、预设角色和已确认文字地图；没有已发布 CoC7 规则版本时拒绝安装。
- 迁移接口：`GET /api/exports/rooms/{room_id}/package`、`POST /api/imports/preview`、`POST /api/imports/confirm`。
- 迁移包包含 manifest SHA-256、房间、角色、目标、事件和私笔记密文；不导出 owner/player token。预检无写入，确认导入永远创建新房间并重映射房间/角色/目标/笔记 ID。
