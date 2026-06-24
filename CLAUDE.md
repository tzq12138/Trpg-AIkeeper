# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI-Keeper（AI 自动 KP 跑团系统）—— Python FastAPI 后端 + React/TypeScript 前端（Vite），SQLite 存储，DeepSeek API 驱动 AI 守秘人。

**核心产品假设：** AI 是 KP（守秘人），人类房主只负责开房/邀请/暂停/重试；玩家手机竖屏优先，语音输入优先；Host 大屏展示公共舞台；PDF 剧本自动导入结构化。

## 常用命令

```bash
# 后端开发服务器（端口 3001）
uvicorn src.server.main:app --reload --port 3001

# 运行所有后端测试（pytest + asyncio auto 模式）
python -m pytest tests/server/ -v

# 运行单个测试文件
python -m pytest tests/server/test_engine.py -v

# 前端开发服务器（端口 5173，自动代理 /api 到 3001）
cd src/client && npm run dev

# 前端构建 + 类型检查
cd src/client && npm run build

# 前端测试
cd src/client && npm test
```

Python 版本 >= 3.11。后端依赖见 `pyproject.toml`，前端依赖见 `src/client/package.json`。

## 架构

### 分层与数据流

```
Player Mobile (React) ──REST──▶ FastAPI ──▶ Engine (唯一权威写入口)
                                      │
Host Big Screen (React) ◀──WebSocket──┘
                                      │
                          SQLite (WAL, foreign_keys=ON)
```

- **Engine** 是唯一权威状态写入者。AI、Host、Player 均不能直接写数据库——所有变更必须经过 Engine 校验后落库。
- **REST 负责写入**，WebSocket 负责服务器→客户端事件推送。
- **ProjectionBuilder** 按 `audience` 拆分事件：`host` / `player` / `party`（拆成 host+player 两份）/ `system`，确保 Host 不会收到 Player 私密事件。

### 核心源文件

| 文件 | 职责 |
|------|------|
| `src/server/main.py` | FastAPI 应用组装、CORS、startup 时初始化 DB + Engine，注册三个 router |
| `src/server/config.py` | `Settings` 从环境变量读取（`DEEPSEEK_API_KEY`、`DATABASE_PATH`、`PORT` 等） |
| `src/server/database.py` | SQLite 连接管理 + 5 表 schema（rooms / characters / scenarios / events / actions） |
| `src/server/models.py` | 共享 Pydantic 模型：`EngineEvent`（20 种事件类型）、`PlayerIntent`（7 种意图）、`ActionReceipt`、`RoomCreate` |
| `src/server/engine.py` | 意图提交（幂等去重）、动作完成（写 actions + 插 event） |
| `src/server/events.py` | `EventBus`——内存 pub/sub，按 room_id 路由 |
| `src/server/projection.py` | `ProjectionBuilder`——按 audience 拆分/复制事件 |
| `src/server/ws_manager.py` | WebSocket `ConnectionManager`——按 room_id + role 管理连接，广播时按 audience 过滤 |
| `src/server/router_rooms.py` | `POST /api/rooms`、`GET /api/rooms/:id`、`POST /api/rooms/:id/start`（需 `X-Owner-Token`） |
| `src/server/router_player.py` | `POST /api/player/rooms/:id/join`、`POST /api/player/character/import-xlsx`、`POST /api/player/intent`、`GET /api/player/sync` |
| `src/server/router_scenarios.py` | `POST /api/scenarios/import-pdf`（上传、抽取、扫描检测）、`GET /api/scenarios/import-jobs/:id` |
| `src/server/pdf_parser.py` | PDF 文本提取：优先 pdfplumber，回退 pypdf；扫描版检测（总字符数 < 50）；文本分块 |
| `src/server/xlsx_parser.py` | XLSX 角色卡解析：按工作表名匹配（人物卡/简化卡/Sheet1），提取姓名/HP/SAN/MP/LUCK + 技能字典 |
| `src/server/quality.py` | 剧本质量报告：评估 scenes/npcs/clues/truth/endings 五维度完整性，输出 ready/warning/highRisk/blocked |
| `src/server/batch.py` | 行动批次收集器：时间窗口（默认 10s）或容量触发（>= 4 条），按 room_id 隔离 |

### 鉴权模式

- **房主**：创建房间时获得 `owner_token`，操作时通过 `X-Owner-Token` header 传递。
- **玩家**：加入房间时获得 `player_token`，操作时通过 `X-Room-Token` header 传递。**身份以 token 解密结果为准，不接受前端传入的 characterId 作为安全身份。**
- 前端将 token 存储在 `localStorage`。

### PlayerIntent 生命周期

```
客户端 POST /api/player/intent
  → Engine.submit_intent()：幂等检查 → INSERT actions(status='queued') → INSERT events(s2c_action_queued)
  → BatchCollector 收集窗口到期 → 生成 batch（未来会对接 AI KP）
  → AI KP 结算 → Engine.complete_action() → UPDATE actions + INSERT events(s2c_action_completed)
```

状态机：`idle → submitting → queued → batched → resolving → resolved`（另有 `rejected` / `timeout` 终端态）

### 事件类型（20 种 EngineEventType）

全部定义为 `Literal` 类型，在 `src/server/models.py`。分为 host 事件（`s2c_host_snapshot`、`s2c_reveal_transaction`、`s2c_atmosphere` 等）、player 事件（`s2c_full_snapshot`、`s2c_private_notice`、`s2c_action_*`、`s2c_tactical_prompt` 等）、和通用事件（`s2c_campaign_ended`）。

### 前端类型约定

客户端 TypeScript 类型（`src/client/src/types.ts`）镜像服务端 Pydantic 模型。**字段命名差异：** Python 端 `snake_case`，TypeScript 端 `camelCase`（例如 `event_id` ↔ `eventId`）。FastAPI 自动做序列化转换，WebSocket 下发的 JSON 用 `model_dump_json()` 默认 snake_case，**客户端需自行处理映射或服务端调整序列化**。

### 测试基础设施

- `conftest.py` 提供 `test_db`（临时 SQLite 文件）、`engine`、`client`（FastAPI TestClient）三个 fixture。
- 所有测试使用内存/临时文件 SQLite，不依赖外部数据库。
- 集成测试 `test_integration.py` 覆盖完整流程：创建房间 → 玩家加入 → 提交意图 → 幂等重提交 → 开始游戏。

## 当前实现状态

**已实现（Batch 1+2）：**
- 协议与 Engine 基础（PRD-00/01）：事件信封、EventBus、ProjectionBuilder、意图提交与幂等
- 房间管理（PRD-21）：创建/查询/开始房间
- PDF 导入（PRD-22）：文本抽取、扫描检测、分块
- 质量报告（PRD-23）：五维度评估
- 玩家入房与角色导入（PRD-12/13）：加入房间、XLSX 解析
- 行动面板（PRD-14/15）：前端提交意图 + 回执链
- 批次收集（PRD-25）：时间窗口/容量触发的 BatchCollector

**未实现（后续批次）：**
- AI KP 主持循环（PRD-24）、防剧透策略（PRD-26）
- WebSocket 服务端端点（`ws_manager.py` 已就绪，`main.py` 未挂载 WebSocket 路由）
- Host 大屏演出模块（PRD-02~06）
- Player 对讲机/语音 STT（PRD-08）
- 私密线索分享（PRD-16）、澄清纠错（PRD-18）
- 断线重连（PRD-19）、检查点/回放/复盘（PRD-20/27/28）
- 剧本知识图谱结构化（当前 quality.py 只做评估，不做抽取）

## 关键设计约束

1. **AI 不写状态**：AI 只输出建议，HP/SAN/物品/线索/场景进度必须 Engine 校验后写入。
2. **Player 不越权**：所有写操作走 `POST /api/player/intent`，不接受前端传入 characterId 作为身份。
3. **Host 不判定**：Host 只消费事件播放公共演出，不承载规则逻辑。
4. **房主不剧透**：房主可开房/暂停/急救，但不能看到完整真相或未发现线索。
5. **PDF 本地优先**：剧本原文本地存储，云端 AI 只接收处理所需片段。
6. **MVP 不做网络流式叙事**：`narrative_text` 完整文本下发，客户端本地打字机播放。
7. **不做任意事件回滚**：首版只有检查点恢复，无分支时间线。
