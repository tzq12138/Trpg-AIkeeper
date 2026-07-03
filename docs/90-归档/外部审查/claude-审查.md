🔴 严重问题（会导致运行时故障）

1. WebSocket 消息序列化不匹配 — 前端收不到任何字段值

这是当前最严重的实际 bug。调用链：

服务端: ws_manager.send_event() → event.model_dump_json()
        输出: {"event_id":"...", "room_id":"...", "room_sequence":5, ...}  ← snake_case

前端:   ws.ts PlayerWS.onmessage → JSON.parse(msg.data) → event.roomSequence
        TypeScript 类型: { roomSequence: number }            ← camelCase
        实际 JSON key:  room_sequence                        ← snake_case
        结果: event.roomSequence === undefined ❌

影响范围： HostStage.tsx 中 WebSocket 收到的 data.type、data.hud、data.image_url、data.message、data.atmosphere 全部是 undefined，Host 大屏完全无法响应 Engine 事件。PlayerWS 同理。

修复方向： 要么在 model_dump_json(by_alias=True) 上配置 Pydantic alias，要么前端改用 snake_case，要么服务端做 camelCase 映射。

2. Player WebSocket 连接被服务端主动断开

# main.py:42-48
@app.websocket("/ws")
async def ws_handler(websocket: WebSocket, room: str = "", role: str = ""):
    if role == "host":
        await host_ws_endpoint(websocket, room)
    else:
        await websocket.accept()
        await websocket.close()  # ← 非 host 直接关闭！

前端 PlayerWS 以 role=player 连接 → 服务端 accept 后立即 close。Player 端的事件推送（s2c_action_queued、s2c_private_notice 等）完全无法送达。

3. /tmp/ 硬编码路径在 Windows 上不可用

# router_player.py:50
tmp_path = f"/tmp/{char['character_id']}.xlsx"

# router_scenarios.py:17
tmp_path = f"/tmp/{scenario_id}.pdf"

Windows 上没有 /tmp/ 目录。这会导致 xlsx 导入和 PDF 导入在实际运行时报 FileNotFoundError。测试通过是因为 pytest 用 Linux 路径风格的临时目录。

---
🟠 中等偏差

┌─────┬────────────────────────────────────────┬─────────┬──────────────────────────────────────────────────────────────────────────────────┐
│  #  │                  问题                  │  涉及   │                                       详情                                       │
│     │                                        │   PRD   │                                                                                  │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 4   │ baseStateVersion 冲突检测未实现        │ PRD-01  │ engine.submit_intent() 不检查版本，永远不返回 "status":                          │
│     │                                        │ §5.4    │ "conflict"。router_player.py:78 中的 409 代码永远不会触发。                      │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 5   │ POST /api/player/intent 返回 200 而非  │ PRD-01  │ PRD 要求 202 Accepted（异步处理中），当前返回 200。                              │
│     │ 202                                    │ §7      │                                                                                  │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 6   │ join 端点无速率限制                    │ PRD-12  │ 无 IP 限制（每分钟 5 次），无一次性邀请码/二维码签名校验。唯一有速率限制的是     │
│     │                                        │ §5.8    │ clarification（60s cooldown）。                                                  │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 7   │ ready_toggle 意图不更新 is_ready       │ PRD-12  │ Engine 收到 ready_toggle 与普通 intent 一样处理，不更新                          │
│     │                                        │ §5.6    │ characters.is_ready。HostLobby.tsx 中玩家 ready 状态始终为 false。               │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 8   │ EngineEvent 缺少                       │ PRD-00  │ HostStore 用 room_sequence 做去重（line 59-63）作为                              │
│     │ hostSequence/playerSequence            │ §5.3    │ workaround，但缺少按角色的专用序列号影响重连补发精度。                           │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│     │                                        │         │ 在 async FastAPI 上下文中使用 urllib.request.urlopen(req,                        │
│ 9   │ ai_kp.py 同步 HTTP 阻塞事件循环        │ —       │ timeout=30)（同步阻塞），会阻塞整个 event loop 30 秒。应使用 httpx（已在         │
│     │                                        │         │ pyproject.toml 中声明但未在 ai_kp.py 中使用）。                                  │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 10  │ AI                                     │ PRD-22  │ PDF 导入后只存文本，knowledge_graph 列写入流程空白。quality.py 评估的是          │
│     │ 结构化（ScenarioKnowledgeGraph）缺失   │ §5.4    │ knowledge_graph 但没有人生产它——质量报告永远返回 blocked。                       │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 11  │ GET /api/scenarios/:id/quality-report  │ PRD-23  │ quality.py 代码存在且被测试覆盖，但 REST 端点未注册——API                         │
│     │ 端点缺失                               │ §6      │ 消费者无法获取质量报告。                                                         │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 12  │ POST /api/scenarios/:id/create-room    │ PRD-23  │ 一键开局能力不存在。                                                             │
│     │ 端点缺失                               │ §6      │                                                                                  │
├─────┼────────────────────────────────────────┼─────────┼──────────────────────────────────────────────────────────────────────────────────┤
│ 13  │ 房主鉴权过于简单                       │ PRD-21  │ 暂停/重试/重置端点只校验 room_id 是否存在，不需要 X-Owner-Token                  │
│     │                                        │ §7      │ 或任何鉴权。任何人都可以暂停任意房间。                                           │
└─────┴────────────────────────────────────────┴─────────┴──────────────────────────────────────────────────────────────────────────────────┘

---
🟡 轻微偏差

┌─────┬──────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────────────────────────┐
│  #  │                     问题                     │                                         详情                                         │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 14  │ FastAPI on_event 已废弃                      │ 应迁移至 lifespan async context manager。                                            │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 15  │ CharacterCompatibilityReport 类型缺失        │ models.py 中没有此类型；xlsx 导入后不生成剧本适配报告。                              │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 16  │ PlayerOnboardingState 类型缺失               │ PRD-12 要求的状态机未实现。                                                          │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 17  │ QualityReport 维度不完整                     │ 只检查 scenes/npcs/clues/truth/endings                                               │
│     │                                              │ 五维存在性，不检查防剧透边界、角色适配、素材缺口。                                   │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 18  │ Schema 中 inventory 表无 source 或           │ 线索有 source 和 discovered_at，物品没有——无法追溯物品来源。                         │
│     │ acquired_at 字段                             │                                                                                      │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 19  │ check_same_thread=False 潜在线程安全问题     │ database.py:65 中关闭了 SQLite 线程检查，在 FastAPI 的多 worker                      │
│     │                                              │ 场景下可能是必要的但需注意。                                                         │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 20  │ 前端 PlayerInventory.tsx 引用 show_item      │ PlayerIntent.intent_type Literal 中无此类型——服务端会拒绝。                          │
│     │ intent_type                                  │                                                                                      │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 21  │ HostLobby.tsx 轮询 HUD 每 3 秒一次           │ 大厅已有 WebSocket 能力但用 REST 轮询——资源浪费。                                    │
├─────┼──────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────────────────────────┤
│ 22  │ ws.ts 中 PlayerWS 断线重连用固定 3 秒        │ 无指数退避，可能造成重连风暴。对比 HostStage.tsx 的 useHostWS                        │
│     │                                              │ 有指数退避（1s→1.5x+random→max 30s）。                                               │
└─────┴──────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────┘

---
✅ 第一轮审计后已被修复的问题

以下是我第一轮标记为"严重"但实际已实现的功能：

- ✅ WebSocket 端点已挂载（main.py:42）
- ✅ Host Store + 事务播放器（host_store.py 204 行）
- ✅ AI KP 模块 + DeepSeek 集成（ai_kp.py 252 行）
- ✅ 防剧透三档系统（spoiler_control.py 203 行）
- ✅ 事件日志 + 检查点（event_log.py 163 行）
- ✅ 战役档案（campaign_archive.py 173 行）
- ✅ 私密线索 + 分享（router_clues.py 108 行）
- ✅ 目标系统（router_objectives.py 53 行）
- ✅ 澄清纠错 + 速率限制（router_clarification.py 108 行）
- ✅ 断线重连（router_reconnect.py 104 行）
- ✅ 玩家档案查询（router_player_archive.py 226 行）
- ✅ 房主暂停/重试/重置（router_host.py 79-77 行）
- ✅ COC 7e 技能检定（skill_check.py 68 行）
- ✅ 前端 HostStage 含打字机字幕 + 骰子动画 + HUD（HostStage.tsx 392 行）
- ✅ 前端角色卡 + 触控检定（PlayerCharacter.tsx 141 行）
- ✅ 前端背包 + 线索软木板（PlayerInventory.tsx 224 行）
- ✅ 数据库 Schema 完整（11 张表）

---
修复优先级（精简后的更新版）

P0 - 阻塞核心流程:
  1. 修复 WebSocket snake_case/camelCase 序列化不匹配
  2. 实现 Player WebSocket 连接（main.py /ws 端点支持 player role）
  3. /tmp/ → tempfile 或 Path(tmpdir) 跨平台适配
  4. baseStateVersion 冲突检测 + HTTP 202

P1 - 功能完整:
  5. AI 结构化（知识图谱生产端）
  6. ready_toggle 的 Engine 逻辑
  7. join 端点速率限制
  8. 房主端点鉴权（X-Owner-Token）
  9. 缺失的 REST 端点（quality-report, create-room）
  10. ai_kp.py 从 urllib 迁移到 httpx (async)

P2 - 打磨:
  11. hostSequence / playerSequence
  12. FastAPI lifespan 迁移
  13. CharacterCompatibilityReport + PlayerOnboardingState
  14. HostLobby.tsx 用 WebSocket 替代 3s 轮询
  15. PlayerWS 指数退避重连