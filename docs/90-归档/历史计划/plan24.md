# AI-Keeper 开发态稳定性、Host 信息汇总与 AI 回复修复计划

## Summary
- 先修最危险的问题：测试不能再清空开发库，剧本/房间/角色必须在开发库稳定持久。
- 补齐本地日志：`log/YYYY-MM-DD/` 自动落盘，终端和文件都保证 UTF-8，不再出现中文 `����`。
- 修 Host 舞台玩家汇总：页面打开立即拉 HUD，Host WS 连接后也主动推送一次当前 HUD。
- 修玩家行动 AI 回复：机制编译允许 DeepSeek 输出别名归一化，叙事上下文使用真实角色、剧本、行动，不再只复述“我是谁”。

## Key Changes

### 1. 测试库隔离 P0
- 修改 `tests/server/conftest.py`：测试必须连接 `TEST_DATABASE_URL`，默认值改为 `postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper_test`。
- 新增测试库创建逻辑：测试启动时连接 maintenance DB `postgres`，若 `aikeeper_test` 不存在则创建。
- 增加强保护：如果测试库名不包含 `test`，直接抛错，禁止 `TRUNCATE` 开发库 `aikeeper`。
- 更新 `scripts/test.ps1`：设置 `TEST_DATABASE_URL`，不要覆盖普通 `DATABASE_URL`。
- 新增测试：确认非 test 数据库 URL 会被拒绝。

### 2. 剧本持久化与重复导入
- 保留现有 `scenarios.raw_text/knowledge_graph/import_status` 入库逻辑。
- 扩展 `scenarios` 字段：`source_filename TEXT`、`source_sha256 TEXT`、`original_file_path TEXT`，用 idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- `POST /api/scenarios/import-pdf` 和 `/api/admin/scenarios/import-pdf`：导入时计算 PDF SHA256，把原始 PDF 复制到 `data/scenarios/{scenario_id}/original.pdf`。
- 若同一 SHA256 已存在，返回已有 `scenario_id` 和 `status: already_imported`，不重复结构化。
- Admin 剧本页显示来源文件名、导入时间、导入状态，刷新后仍从数据库加载已有剧本。
- 手动验收：导入一次 PDF，重启 `dev.py` 后仍能在 Admin 剧本页看到；重复导入同一 PDF 不新增第二条。

### 3. 日志落盘与乱码修复
- 修改 `src/server/log_config.py`：console formatter 继续彩色；file formatter 改用 `%(levelname)s`，避免 `coloured_level` 缺失。
- 修改 `dev.py`：
  - 启动子进程时设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`、`PYTHONUNBUFFERED=1`。
  - 自动创建 `log/YYYY-MM-DD/`。
  - 分别写入 `backend.log`、`frontend.log`、`kp-mcp.log`、`combined.log`。
  - 文件日志去掉 ANSI 控制码，终端保留彩色前缀。
- 后端默认 `LOG_FILE` 设为当天 `log/YYYY-MM-DD/backend.log`，除非用户显式覆盖。
- 新增测试：`setup_logging(log_file=...)` 能写入中文日志且无 formatter 报错。
- 手动验收：提交中文行动“我是谁？”，`combined.log` 和 `backend.log` 里必须正常显示中文。

### 4. Lobby 实时闭环
- 新建 `src/server/room_lobby.py`，统一提供：
  - `build_lobby_snapshot(conn, room_id)`
  - `emit_lobby_snapshot(app, room_id)`
- 玩家加入成功后广播 `s2c_room_lobby_snapshot`。
- 玩家 ready toggle 成功后继续广播统一 snapshot。
- 房主开始游戏成功后广播 `room_status: active` 的 snapshot，让玩家等待室自动进入游戏。
- `/team-message` 只通过 `ProjectionDispatcher.emit()` 写事件并广播，不再先手动 `EventLog.log_event()`，避免聊天重复入库。
- 修 WebSocket catch-up：后端补发事件统一为前端 `EngineEvent` 形状，包含 `type`、`roomSequence`、`payload`。
- 新增测试：加入玩家、ready、start room 都会触发一次 lobby snapshot；team message 事件日志只新增一条。

### 5. Host 舞台玩家信息汇总
- 新建或抽取 `src/server/host/hud_builder.py`：从数据库合成玩家公开状态，字段包括玩家昵称、调查员名、HP/SAN/MP/LUCK、ready、status、status_tags。
- 修改 `/api/host/{room_id}/hud`：每次请求都从 DB 刷新玩家状态，再返回 HUD，避免 `HostStore.players` 陈旧或为空。
- 修改 `host_ws_endpoint`：Host WS 认证成功并 accept 后，立即发送一次 `host_state_update`，包含当前 HUD。
- 修改 `src/client/src/pages/HostStage.tsx`：组件 mounted 后主动 fetch `/api/host/{roomId}/hud`，不要只等 WS。
- Host 右侧玩家卡展示：玩家昵称 / 调查员名、HP、SAN、MP、LUCK、ready、角色状态。
- 新增测试：房间已有两个角色时，Host HUD 返回两个玩家和正确 HP/SAN/ready。

### 6. AI 回复与机制编译修复
- 修改 `src/server/ai/mechanic_compiler.py`：
  - DeepSeek JSON 先进入 `_normalize_raw_result(raw)`，再构造 `MechanicCompileResult`。
  - 归一化规则：`skillCheck/skill-check` -> `skill_check`；`identity_check` -> `dialogue`；`normal/medium/普通/一般` -> `regular`；`None` 的 `itemConsumed` -> `false`；字符串 `consequence` 包成 `{"note": text}`。
  - 若归一化后仍非法，记录原始 JSON 摘要，再降级 Python fallback。
- 按 DeepSeek 官方 API 文档保留 `deepseek-v4-pro/deepseek-v4-flash` 可配置模型；不要写死旧模型。参考官方文档：[DeepSeek API Docs](https://api-docs.deepseek.com/)。
- 修改 `ResolutionPipeline` 的 dialogue 叙事：
  - 对 `dialogue` 行动优先调用 `AiGateway.generate_narrative()`，上下文包含剧本标题、调查员名、职业、背景摘要、玩家原话、当前房间公开事件摘要。
  - AI 不可用时本地 fallback：如果玩家问“我是谁/我又是谁”，回答角色身份，例如“你是{调查员名}，职业是{职业}。你目前身处本剧本场景中，记忆与状态以角色卡为准。”
  - 不允许 fallback 只原样复述玩家输入。
- 修 `_settle_turn_background`：`character_name` 使用调查员名或玩家昵称，`declared_intent` 保留玩家原话，不要把 `declared_intent` 塞进 `character_name`。
- 新增测试：DeepSeek 风格非法枚举能归一化；“我是谁？”在无 AI 情况下返回角色身份；turn narrative 上下文包含正确角色名和行动文本。

## Test Plan
- 后端重点测试：
  - `python -m pytest tests/server/test_db_isolation.py tests/server/test_host_room_lifecycle.py tests/server/test_character_join_import.py tests/server/test_mechanic_compiler.py tests/server/test_turn_narrative.py -q`
- 后端全量测试：
  - `python -m pytest tests/server -q`
  - 验证后再查开发库，确认 `aikeeper` 不被清空。
- 前端测试：
  - `cd src/client; npm.cmd test`
  - `cd src/client; npm.cmd run build`
- 手动流程：
  - `python dev.py`
  - Admin 登录，导入剧本 PDF，刷新页面仍存在。
  - 停止并重启 `dev.py`，剧本仍存在。
  - 创建房间、两个玩家加入、ready、房主开始。
  - Host 舞台右侧立即显示两个玩家 HP/SAN/ready。
  - 玩家输入“我是谁？”，玩家端和 Host 日志能看到中文正常、回复包含调查员身份。

## Assumptions
- 本轮不引入正式迁移框架，只使用 idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`。
- `data/scenarios/`、`data/scenario_assets/`、`log/` 默认本地运行使用，不纳入 Git 提交。
- 开发库名固定为 `aikeeper`，测试库名固定为 `aikeeper_test`，除非显式设置 `TEST_DATABASE_URL`。
- AI 真实调用失败时必须有可读本地 fallback，不能让玩家端空等或只复述玩家原话。
