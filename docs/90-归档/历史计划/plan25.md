# 修复大厅实时、Host 舞台、日志乱码与 AI/MCP 剧本链路

## Summary
- 已确认 P0 根因：`src/server/main.py` 使用 `EngineEvent` 但未导入，玩家 WS 连接反复崩溃，直接导致大厅聊天互相不可见、玩家端收不到 AI/事件投影。
- Host 舞台还有独立问题：日志中有 `Host WS auth failed`、`Failed to push initial HUD`，并且开局广播里 `from ..engine.projection` 导入错误，导致房主/玩家开局状态不同步。
- 乱码不是单纯终端显示问题：多个源码字符串已经变成 `鈹€/鍔犺浇/璇峰厛` 这类 mojibake，会污染 UI、日志和 AI prompt。
- MCP 有消息：`kp-mcp.log` 有调用记录，`ai_call_logs` 显示 `structure_scenario` 最终由 `mcp` 成功；问题是 DeepSeek 直连先 400、网关顺序/质量校验/展示反馈不够稳定。

## Key Changes
- **实时通道与大厅聊天**
  - 在 `main.py` 正确导入 `EngineEvent`，确保玩家 WS catch-up 使用标准 `eventId/type/roomSequence/payload`。
  - 修复开局广播导入路径：`router_rooms.py` 使用 `.engine.projection`，确保房主点击开始后广播 `s2c_room_lobby_snapshot(room_status=active)`。
  - 大厅聊天只通过 `ProjectionDispatcher.emit()` 写库并广播一次；前端发送时带 `clientMessageId`，服务端回显同一 `messageId`，前端按 `messageId` 去重，避免修复 WS 后自己消息重复。
  - `HostStore.HOST_VISIBLE_EVENTS` 增加 `s2c_team_message`，Host 舞台也能看到队内消息。
  - `PlayerWS` 对缺失/非法 `roomSequence` 做兼容保护，旧事件不再把客户端状态弄坏。

- **Host 舞台与玩家状态**
  - Host WS 支持 `ownerToken` 和 `accountToken` 两种认证；Admin/房主从管理页打开舞台也能通过账号 token 建连。
  - `HostStage` 的 `/api/host/{room}/hud` 请求同时带 `X-Owner-Token` 和 `Authorization`，失败时显示明确错误面板，不再白屏。
  - `host_ws_endpoint` 初始 HUD 推送失败时记录完整异常；`build_hud()` 从 `character_runtime_state` 读状态，缺失时回退 `xlsx_data` 的 HP/SAN/MP/LUCK。
  - 保持玩家大厅为准备/聊天页面；房主开始后，玩家端自动跳转到 `/player/{roomId}`。

- **日志与乱码**
  - `dev.py` 默认关闭 ANSI 彩色输出，或仅在显式 `--color` 时启用；修正 ANSI 清理正则为 `\x1b\[[0-9;]*m`。
  - 避免 backend 同时由 `LOG_FILE` 和 dev stream 写同一个 `backend.log`；统一写入 `log/YYYY-MM-DD/backend.log/frontend.log/kp-mcp.log/combined.log`。
  - 启动时打印日志目录；所有子进程设置 UTF-8 环境，并在 Python 启动器里 `stdout/stderr.reconfigure(encoding="utf-8")`。
  - 只修主流程文件中的 mojibake 文案和 prompt：`main.py/dev.py/gateway.py/providers.py/kp_mcp_server/kp_brain.py/HostStage/PlayerLobby/HostCreate/navigation`，不做全库盲目重写。

- **AI Gateway、MCP 与剧本结构化**
  - 默认 `AI_PROVIDER_ORDER` 统一为 `mcp,deepseek,local`；DeepSeek 直连失败时记录 HTTP 状态和脱敏响应摘要，避免只有 `400 Bad Request`。
  - 修复 `gateway.py/providers.py/kp_mcp_server` 中损坏的中文 prompt；所有 AI prompt 文件保持 UTF-8。
  - `structure_scenario` 输出做规范化：兼容 `scenarioTitle/title`、`triggerMechanics/trigger_mechanics`，落库前统一为 `title/scenes/npcs/clues/truth/endings/trigger_mechanics`。
  - 导入后生成并保存 `quality_report`；Admin 剧本页显示 provider、fallback chain、质量等级、缺失项，而不是只显示“已结构化”。
  - 玩家行动 AI 回复优先通过 WS 投影；WS 断开时玩家日志页可从事件归档补看结果。

- **多模态模型接入建议**
  - 可以接，小米 `mimo2.5` 适合测试阶段，但先作为服务端 `MimoProvider`，不要直接替换核心 KP 裁决链路。
  - 新增 env：`MIMO_API_KEY`、`MIMO_API_BASE`、`MIMO_MODEL=mimo-2.5`；仅用于 `ocr_scanned_pdf`、`extract_handout`、`extract_map_nodes`、`describe_scene_image` 等多模态任务。
  - 核心裁决、规则判定、剧情推进仍走 `mcp/deepseek/local` 文本链路，避免多模态不稳定影响跑团主流程。
  - 测试使用 mock provider，不依赖真实小米 key。

## Test Plan
- 后端：
  - `python -m pytest tests/server -q`，确认仍只打 `aikeeper_test`，不得清空开发库。
  - 新增测试覆盖：玩家 WS catch-up 不崩、双玩家大厅聊天互相可见且不重复、开局广播 active、Host WS 账号认证、HUD 回退 xlsx 状态、Host 可接收 `s2c_team_message`。
  - 新增 AI 测试：MCP 优先顺序、DeepSeek 400 记录、剧本 KG 规范化、quality_report 落库、MimoProvider mock 多模态任务。
- 前端：
  - 用直接 node 路径跑 `tsc --noEmit` 和 Vite build，避开 `D&D` 路径下 npm `.bin` 问题。
  - 手动验收：两个玩家标签页在大厅互聊；房主开始后玩家自动进游戏；Admin/房主打开 Host 舞台能看到玩家 HP/SAN；日志文件无 ANSI 方块和乱码。
- 剧本验收：
  - 导入 `向火独行.pdf` 后重启服务，Admin 剧本页仍能看到已导入剧本。
  - 剧本详情显示结构化质量、NPC/线索/场景数量、原始 PDF 保存路径和处理 provider。

## Assumptions
- 不提交任何真实 API key。
- 不做完整生产迁移框架，只保留当前 idempotent schema 初始化。
- 不把多模态模型用于默认核心裁决；它先作为测试/素材解析增强入口。
