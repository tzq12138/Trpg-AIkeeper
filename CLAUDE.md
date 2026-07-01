# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI-Keeper（AI 自动 KP 跑团系统）—— Python FastAPI 后端 + React/TypeScript 前端（Vite），PostgreSQL（pgvector）存储，DeepSeek API 驱动 AI 守秘人。

**核心产品假设：** AI 是 KP（守秘人），人类房主只负责开房/邀请/暂停/重试；玩家手机竖屏优先，语音输入优先；Host 大屏展示公共舞台；PDF 剧本自动导入结构化。

## 快速开始

```bash
# 1. 启动 PostgreSQL（pgvector）+ Redis
docker compose up -d

# 2. 后端开发服务器（端口 3001）
uvicorn src.server.main:app --reload --port 3001

# 3. 前端开发服务器（端口 5173，自动代理 /api → 3001，/ws → ws://3001）
cd src/client && npm run dev
```

Python >= 3.11。`DEEPSEEK_API_KEY` 环境变量为空时，AI 模块以 mock 模式运行（本地规则编译器兜底）。`REDIS_URL` 为空时，缓存层透明降级为 no-op。`AGENT_ENABLED` 控制 GameAgent + GameLoop 是否启动。

## 常用命令

```bash
# 后端测试（需要 PostgreSQL 运行中，pytest + asyncio auto 模式）
python -m pytest tests/server/ -v

# 运行单个测试文件
python -m pytest tests/server/test_engine.py -v

# 前端构建 + 类型检查（tsc --noEmit + vite build）
cd src/client && npm run build

# 前端测试（vitest）
cd src/client && npm test
```

## 架构

### 分层与数据流

```
Player Mobile (React) ──REST──▶ FastAPI ──▶ Engine (唯一权威写入口)
                                      │         │
Host Big Screen (React) ◀──WebSocket──┘         │
                                      │         ▼
                          ResolutionPipeline ◀── MechanicCompiler (DeepSeek)
                                      │         │
                                      │         ▼
                                      │    RuleExecutor ──▶ rules/ (COC handlers)
                                      │         │
                                      ▼         ▼
                          PostgreSQL (pgvector, 连接池 2-10)
                              ▲         │
                              │         ▼
                          RAGStore    Redis (可选缓存层)
                              ▲
                              │
                    HybridEmbedding (local text2vec-base-chinese / hash fallback)
```

- **Engine** 是唯一权威状态写入者。AI、Host、Player 均不能直接写数据库。
- **ResolutionPipeline** 是意图→结算的主链路：`MechanicCompiler` 将自然语言编译为游戏机制 → `RuleExecutor` 执行 COC 规则处理器 → `ProjectionDispatcher` 拆分事件按 audience 分发（写 DB + 推 WebSocket + 写 Redis 缓存）。
- **REST 负责写入**，WebSocket 负责服务器→客户端事件推送。
- **ProjectionDispatcher** 按 `audience` 拆分：`host` / `player` / `party`（复制为 host+player 两份）/ `system`。
- **Redis** 为可选缓存层：缓存最近 200 条房间事件 + HUD 数据（TTL 60s）。`REDIS_URL` 为空时所有操作透明 no-op。
- **GameAgent + GameLoop**（可选，`AGENT_ENABLED` 控制）：Agent 增强的叙事生成路径，包装 ResolutionPipeline 提供 AI 叙事输出。

### 源码组织（子包结构）

代码已从平面文件重组为功能子包：

| 子包 | 路径 | 内容 |
|------|------|------|
| `engine/` | `src/server/engine/` | Engine、ResolutionPipeline、ProjectionDispatcher、RuleExecutor、BatchCollector、RetroItems、SkillCheck |
| `ai/` | `src/server/ai/` | AiKp、MechanicCompiler、SpoilerControl、RAGStore、HybridEmbedding |
| `events/` | `src/server/events/` | EventBus（内存 pub/sub）、EventLog（持久化+检查点）、事件注册表 |
| `player/` | `src/server/player/` | 6 个 player router（主路由、线索、目标、澄清、重连、档案） |
| `host/` | `src/server/host/` | Host router、WebSocket ConnectionManager、HostStore（内存状态） |
| `scenario/` | `src/server/scenario/` | Scenario router、PDF 解析器、XLSX 解析器、质量报告、角色预设 |
| `rules/` | `src/server/rules/` | COC 规则处理器（技能/理智/战斗/幸运）、触发器评估、注册表 |
| `agent/` | `src/server/agent/` | GameAgent（DeepSeek 驱动的 KP 代理）、工具定义 |

### 数据库

- **`db_adapter.py`**：PostgreSQL 连接池（`psycopg2` ThreadedConnectionPool 2-10）、SQL 翻译层（SQLite `?` → PG `%s`、`datetime()` → `NOW()`）、JSONB 自动装箱。**所有 SQL 通过此层执行。**
- **`db_pg.py`**：PostgreSQL 特定辅助（与 db_adapter 配合）。
- **`docker-compose.yml`**：`pgvector/pgvector:pg16`（端口 5432）+ `redis:7-alpine`（端口 6379），用户/密码/库名均为 `aikeeper`。

核心表：`rooms`、`characters`、`scenarios`、`events`（BIGSERIAL 主键）、`actions`、`player_sequences`、`checkpoints`、`campaign_archives`、`clues`、`clue_shares`、`objectives`、`inventory`、`clarifications`、`document_chunks`（含 `vector(768)` 列）、`host_states`、`rule_documents`、`room_turns`。

### 配置

`src/server/config.py` —— `Settings.from_env()` 读取：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATABASE_URL` | `postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper` | PG 连接串 |
| `DEEPSEEK_API_KEY` | `""` | 为空时编译器使用本地正则兜底 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `REDIS_URL` | `""` | 为空时缓存层 no-op |
| `AGENT_ENABLED` | `false` | 启用 GameAgent + GameLoop |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `PORT` | `3001` | 服务端口 |

### 应用启动（`main.py` lifespan）

8 步顺序初始化：Database → Embedding → RAGStore → Engine → MechanicCompiler → Redis（可选）→ ResolutionPipeline → GameAgent+GameLoop（可选，需 `AGENT_ENABLED`）。

注册 14 个 router：rooms、player、scenarios、clues、objectives、clarification、reconnect、player_archive、host、ai、rag、auth、map、admin。

WebSocket 端点 `/ws?room=&role=&token=&lastSequence=`：`role=host` 走 host handler，`role=player` 走 player handler（含断线重连 catch-up）。

### PlayerIntent 生命周期

```
客户端 POST /api/player/intent
  → Engine.submit_intent()：幂等检查(action_id) + 版本冲突检测(state_version)
  → INSERT actions(status='queued') → INSERT events(s2c_action_queued)
  → [Host 手动触发 OR 自动批次收集 OR GameLoop.process_turn()]
  → ResolutionPipeline.resolve_action()
    → MechanicCompiler.compile()（DeepSeek API / 本地规则兜底）
    → RuleExecutor.execute()（匹配 trigger mechanics + 执行 COC handler）
    → 写 actions(status='resolved', result=JSON) + INSERT events + Redis 缓存
    → ProjectionDispatcher 推送 s2c_reveal_transaction(host) + s2c_state_patch(player) + s2c_public_observation(party) + s2c_action_completed(player)
```

状态机：`idle → submitting → queued → resolving → resolved`（另有 `rejected` / `timeout` 终端态）。

### 鉴权模式

- **房主**：创建房间时获得 `owner_token`，操作时通过 `X-Owner-Token` header 传递。
- **玩家**：加入房间时获得 `player_token`，操作时通过 `X-Room-Token` header 传递。**身份以 token 为准，不接受前端传入 characterId 作为安全身份。**
- 加入房间有速率限制（内存计数器，按 IP）。
- `router_auth.py` 提供额外的登录/认证端点。

### 前端架构

前端无第三方路由库——`navigation.ts` 通过 `window.location.pathname` 解析路由，App 组件订阅 `popstate` 事件响应导航。

**设计系统：** Bauhaus brutalist 风格，所有样式集中在 `styles.css`（CSS 自定义属性 `--bh-*`）。核心视觉语言：粗黑边框 + 6px 偏移阴影、Space Grotesk / Impact 字体、黄/黑/红/蓝四色体系、网格纸背景。

| 文件 | 职责 |
|------|------|
| `src/client/src/navigation.ts` | **路由解析中枢**：`getRouteForPath()` 返回 `AppRoute { page, param }`；定义 `HostTabKey`（narrative/combat/database/logs）和 `PlayerTabKey`（action/character/inventory/logs/map）及对应标签配置 |
| `src/client/src/App.tsx` | 根组件：根据 `AppRoute.page` 条件渲染，其余页面包裹在 `BauhausPage` 中 |
| `src/client/src/components/BauhausShell.tsx` | 共享布局：`BauhausPage`（页面容器，支持 `narrow` 模式）、`BrutalProgress`（HP/SAN 进度条）、`SectionLabel` |
| `src/client/src/components/PlayerTerminal.tsx` | 玩家移动端外壳：顶部粘性 header（角色名 + HP/SAN）、中央内容区、底部固定 5 标签导航栏 |
| `src/client/src/components/TacticalButtons.tsx` | 战术行动按钮组：接收 `TacticalAction[]`，通过 `POST /api/player/intent` 提交 |
| `src/client/src/pages/HostStage.tsx` | Host 大屏：三栏布局（KP 工具 + 投影舞台 + 玩家监控），WebSocket 直连（指数退避重连），本地打字机播放 narrative_text |
| `src/client/src/pages/PlayerActionPage.tsx` | **玩家统一页面**：通过 `PlayerTerminal` 切换 5 标签——行动终端、角色卡、背包、调查日志、地图 |
| `src/client/src/api.ts` | `apiFetch<T>()` 封装 fetch（JSON Content-Type + 错误抛出）、`authHeaders()` 读取 `X-Room-Token` |
| `src/client/src/ws.ts` | `PlayerWS` 类：WebSocket 连接管理（自动重连、指数退避 1s→30s）、事件广播 |

### 前端路由表

| 路由 | 渲染组件 | 说明 |
|------|----------|------|
| `/` | App.tsx (Home) | 首页导航（管理后台 / RAG / 创建房间 / 加入房间四张卡片） |
| `/admin` | AdminDashboard | 管理后台 |
| `/rag-test` | RagTestPage | RAG 规则书检索测试 |
| `/host/create` | App.tsx (HostCreate) | 创建房间（调用 POST /api/rooms） |
| `/host/:id` | HostLobby | 房间等待大厅 |
| `/host/:id/stage` | HostStage | Host 大屏演出 |
| `/player/join` | App.tsx (PlayerJoin) | 加入房间 |
| `/player/:id` | PlayerActionPage | 玩家统一面板（5 标签：行动/技能/装备/日志/地图） |

另有 `CharacterBuilderPage`、`LoginPage`、`PlayerJoinPage` 等页面文件存在于 `pages/` 中，可能为旧版或未完全接入路由。

### 测试基础设施

- **后端：** `tests/server/conftest.py`——`test_db`（连接真实 PG + TRUNCATE 所有表 + RESTART IDENTITY CASCADE）、`engine`、`client`（FastAPI TestClient）fixture。自动重置速率限制器。**需要 PostgreSQL 运行中**（`DATABASE_URL` 环境变量可覆盖）。`pyproject.toml` 配置 `asyncio_mode = "auto"`。
- **前端：** `src/client/tests/` 使用 vitest。当前覆盖 navigation 路由解析和 tabs 配置。

## 关键设计约束

1. **AI 不写状态**：AI 只输出建议，HP/SAN/物品/线索/场景进度必须 Engine 校验后写入。
2. **Player 不越权**：所有写操作走 `POST /api/player/intent`，不接受前端传入 characterId 作为身份。
3. **Host 不判定**：Host 只消费事件播放公共演出，不承载规则逻辑。
4. **房主不剧透**：房主可开房/暂停/急救，但不能看到完整真相或未发现线索。
5. **PDF 本地优先**：剧本原文本地存储，云端 AI 只接收处理所需片段。
6. **MVP 不做网络流式叙事**：`narrative_text` 完整文本下发，客户端本地打字机播放。
7. **不做任意事件回滚**：首版只有检查点恢复（`EventLog.create_checkpoint/restore_checkpoint`），无分支时间线。
8. **Embedding 本地优先**：优先用 `text2vec-base-chinese`（sentence_transformers），不可用时回退确定性 SHA-256 哈希向量（768 维），保证无外部依赖也能跑。
9. **Redis 可选**：`REDIS_URL` 为空时缓存层透明 no-op，不影响核心功能。
10. **Agent 可选**：`AGENT_ENABLED` 控制 GameAgent + GameLoop，关闭时走传统 ResolutionPipeline 路径。
