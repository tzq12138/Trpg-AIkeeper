# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

AI-Keeper（AI 自动 KP 跑团系统）—— Python FastAPI 后端 + React/TypeScript 前端（Vite），PostgreSQL（pgvector）存储，DeepSeek API 驱动 AI 守秘人。独立 KP MCP Server（`kp_mcp_server/`）提供 prompt 契约与工具注册。

**核心产品假设：** AI 是 KP（守秘人），人类房主只负责开房/邀请/暂停/重试；玩家手机竖屏优先，语音输入优先；Host 大屏展示公共舞台；PDF 剧本自动导入结构化。

## 快速开始

```bash
# 一键启动全部服务（推荐）—— Docker + Backend :3001 + Frontend :5173 + KP MCP :9100
python dev.py

# 如果 PG/Redis 已在本地运行，跳过 Docker
python dev.py --skip-docker

# 分步启动（调试用）
docker compose up -d                                      # 1. PostgreSQL + Redis
uvicorn src.server.main:app --reload --port 3001          # 2. 后端
cd src/client && npm run dev                              # 3. 前端
```

`dev.py` 还支持 `--check`（健康检查）和 `--stop`（停止 Docker 服务）。Python >= 3.11。`DEEPSEEK_API_KEY` 为空时 AI 以 mock 模式运行（本地规则编译器兜底）。`REDIS_URL` 为空时缓存层透明降级为 no-op。`AGENT_ENABLED` 控制 GameAgent + GameLoop。

## 常用命令

```bash
# 后端测试（需要 PostgreSQL 运行中，pytest + asyncio auto 模式）
python -m pytest tests/server/ -v

# 运行单个测试文件
python -m pytest tests/server/test_engine.py -v

# 运行单个测试函数（-k 支持子串匹配）
python -m pytest tests/server/test_engine.py -v -k "test_submit_intent"

# 前端构建 + 类型检查（tsc --noEmit + vite build）
cd src/client && npm run build

# 前端测试（vitest, 单次运行）
cd src/client && npm test

# 前端测试（watch 模式）
cd src/client && npx vitest

# 仅健康检查（不启动服务）
python dev.py --check

# 分步启动后端（单独终端）
uvicorn src.server.main:app --reload --port 3001

# 分步启动前端（单独终端）
cd src/client && npm run dev

# 运行 Golden Module 完整套件
python scripts/run_golden_module_suite.py

# 运行 Golden Module 单个模块
python scripts/run_golden_module_suite.py --spec 01-solo-tutorial-tide-letter

# 验证 Golden Module JSON 格式
python -m json.tool data/golden_modules/01-solo-tutorial-tide-letter/module.json | Out-Null
```

`pyproject.toml` 配置 `asyncio_mode = "auto"`，本地 temp 目录 `.pytest-tmp-local`。

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
                                      │         ▼
                                      │    StateService.apply_change() (新权威路径)
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
- **StateService**（`engine/state_service.py`）是新权威状态变更路径：`apply_change()` 接收 JSON Patch 风格的 mutations，通过 `MUTATION_PATH_HANDLERS` 映射到具体列（`/character/hp` → `character_runtime_state.hp`），含钳制（HP/SAN/MP 夹在 `[0, max]`）、版本递增和 no-op 检测。
- **SpoilerGuard**（`engine/spoiler_guard.py`）是输出侧反剧透安全网：构建敏感项索引（真相/结局/隐藏 NPC/隐藏线索）→ 确定性匹配 → 发现违规时生成重试 prompt → 二次违规回退到模板化安全叙述。被 Pipeline、ProjectionDispatcher、clue share 等多处调用。
- **AiGateway**（`ai/gateway.py`）是统一 AI 调用入口。Provider 链路：MCP → DeepSeek → 管理员配置的 OpenAI-compatible → 本地回退。每个 task type（`analyze_director_action`、`narrate_action`、`resolve_turn` 等）有对应的校验 schema。本地回退不可用时 Gateway 仍会返回空 dict 继续结算，不抛异常。
- **Director**（`ai/director.py`）分析玩家意图 → 产出 `DirectorPlanDTO`（含解读后意图、机制计划、state_patch（仅 advisory_only）、citations、置信度、语义推进校验）。低置信度或模糊意图触发 `player_clarification_required`，路由到 `host_exception`；高置信度推进到 `director_plan_validated`。Director 输出的 `state_patch` 标记为 `advisory_only`，必须经 Engine → StateService 验证。
- **Narrator**（`ai/narrator.py`）基于已验证 Director plan + 确定性规则结果生成公开叙事。严格 fact-ref 校验：叙事只能引用 runtime package 中声明的 `allowed_facts`。校验失败回退到 `build_verified_narration()`，直接从场景文本渲染，不调用 AI。
- **Contracts**（`ai/contracts.py`）定义 AI 输出 schema（`KpResponse`、`DirectorPlanDTO`、`NarrationResultDTO`、`CombatRoundSuggestion` 等）和 AI 权限矩阵。
- **TurnManager**（`turn_manager.py`）管理回合生命周期：`collecting → resolving → resolved`。`ensure_current_turn()` 获取或创建当前回合，`submit_action()` 关联动作到回合并抑制同角色重复提交。`mark_resolving()` 使用条件 UPDATE（`WHERE status='collecting'`）保证幂等。
- **REST 负责写入**，WebSocket 负责服务器→客户端事件推送。
- **ProjectionDispatcher** 按 `audience` 拆分：`host` / `player` / `party`（复制为 host+player 两份）/ `system`。投影前经过 SpoilerGuard 安全网扫描。
- **Redis** 为可选缓存层：缓存最近 200 条房间事件 + HUD 数据（TTL 60s）。`REDIS_URL` 为空时所有操作透明 no-op。
- **GameAgent + GameLoop**（可选，`AGENT_ENABLED` 控制）：Agent 增强的叙事生成路径，包装 ResolutionPipeline 提供 AI 叙事输出。
- **KP MCP Server**（`kp_mcp_server/`，端口 9100）：独立 ASGI 服务，提供 KP prompt 契约（`prompts/soul.md`、`rules.md`、`contract.md`）与工具注册。通过 `AiGateway` 内部调用，不直接暴露公网。

### 事件可见性模型

`EventLog.get_events_for_player()` 使用统一 helper `_can_player_see_event()`，按 4 级 audience 规则过滤：

| audience | 可见性规则 |
|----------|-----------|
| `host` | 始终不可见（返回 False） |
| `party` | 始终可见 |
| `player` | 仅当 `payload.characterId` 匹配请求者 |
| `system` | 仅当 `event_type` 在 `PLAYER_VISIBLE_SYSTEM_EVENTS` 白名单中 |

`PLAYER_VISIBLE_SYSTEM_EVENTS = {"s2c_turn_resolved", "s2c_checkpoint_created"}`。`get_public_events()` 在 SQL 层直接过滤，仅返回 `party` + 白名单系统事件。

### 源码组织（子包结构）

| 子包 | 路径 | 内容 |
|------|------|------|
| `engine/` | `src/server/engine/` | Engine、ResolutionPipeline、ProjectionDispatcher、RuleExecutor、StateService、SpoilerGuard、SkillCheck、BatchCollector、RetroItems、ActionLifecycle、ActionState、ActionPolicy、RevealLedger、RiskContract、HostAutonomy、ActionConsent、CompensationService、RollReceipt、EndingConditions、FallbackNarrative、RuntimeIntegrity、SecureRandom、SoloCombatReactions、PreparedRuleActions |
| `ai/` | `src/server/ai/` | AiGateway、ProviderChain(DeepSeek/MCP/Local)、Director、Narrator、MechanicCompiler、SpoilerControl、RAGStore、HybridEmbedding、MapGenerator、KpMcpClient、ProviderConfig、DecisionAudit、ProviderHealth、RulePolicyCompiler、AiConfig、RagContext |
| `events/` | `src/server/events/` | EventBus（内存 pub/sub）、EventLog（持久化+检查点+可见性过滤）、事件注册表 |
| `player/` | `src/server/player/` | 11 个 player router、ActionService、TeamMessages、PrivateData |
| `host/` | `src/server/host/` | Host router、WebSocket ConnectionManager、HostStore（内存状态）、HudBuilder |
| `scenario/` | `src/server/scenario/` | Scenario router、PDF 解析器、XLSX 解析器、质量报告、角色预设、单人冒险（extract+runtime）、内容包、黄金套件、资产绑定、场景图片服务、内容投影、审查工装 |
| `rules/` | `src/server/rules/` | COC 规则处理器（技能/理智/战斗/幸运/遭遇）、触发器评估、注册表、遭遇战处理器 |
| `agent/` | `src/server/agent/` | GameAgent（DeepSeek 驱动的 KP 代理）、工具定义（含权限分级） |
| `governance/` | `src/server/governance/` | 运营治理服务（数据保留、操作审计、干运行 Token） |

根级重要模块：

| 文件 | 职责 |
|------|------|
| `turn_manager.py` | 回合生命周期管理（collecting→resolving→resolved），含缺勤策略 |
| `turn_timeout_worker.py` | 后台回合超时协程（5s 轮询过期战斗声明窗口） |
| `encounter_persistence.py` | 遭遇战 CRUD（创建/添加参与者/更新状态） |
| `combat_round_planner.py` | 确定性战斗轮计划（按敏捷排序、冲突键去重、准备动作约束） |
| `map_persistence.py` / `map_store.py` | 地图节点持久化与内存缓存 |
| `export.py` | 公开导出（使用 `clue_shares.public_version` 脱敏） |
| `stt.py` | 语音转文本（STT）集成 |
| `redis_cache.py` | Redis 缓存层（可选，透明降级） |
| `narrative_provider.py` | 叙事文本提供者 |
| `game_loop.py` | GameAgent 驱动的自动回合循环 |
| `campaign_archive.py` | 战役归档（含 CampaignFinalization 只读/终结状态机） |
| `runtime_lifecycle.py` | 进程内+PG 层删除竞态锁（pg_advisory_lock + threading.Lock） |
| `rule_source_lifecycle.py` | 规则源 CRD 生命周期管理 |
| `room_migration.py` | 房间 V2 迁移器 |
| `v2_cutover.py` | V2 切换管理器 |
| `global_reset.py` | 全局重置工具 |
| `log_config.py` | 统一日志配置 |

独立服务：

| 路径 | 职责 |
|------|------|
| `kp_mcp_server/` | 独立 KP MCP Server（`server.py` ASGI 应用，`kp_brain.py` 核心逻辑，`prompts/` 契约文件） |

### 状态管理：双路径

**旧路径（Engine 直写）：** `Engine.submit_intent()` → `ResolutionPipeline` → 直接 INSERT/UPDATE。

**新路径（StateService）：** `StateService.apply_change()` 接收结构化 mutations，映射到 `MUTATION_PATH_HANDLERS`，原子 UPDATE + 版本递增。空变更返回 `no_op=True` 且不递增 `state_version`。

`state_version` 语义：**仅在权威世界状态变更时递增**（HP/SAN/线索/地图等）。动作入队、ready_toggle、空变更均不递增。客户端携带 `base_state_version` 进行乐观锁冲突检测。

角色运行时状态（HP/SAN/MP/Luck）的权威来源是 `character_runtime_state` 表，而非 `characters.xlsx_data`。`characters.xlsx_data` 仅作初始值回退。

### 数据库

- **`db_adapter.py`**：PostgreSQL 连接池（`psycopg2` ThreadedConnectionPool 2-10）、SQL 翻译层（SQLite `?` → PG `%s`、`datetime()` → `NOW()`）、JSONB 自动装箱。**所有 SQL 通过此层执行。**
- **`db_pg.py`**：PostgreSQL 特定辅助（与 db_adapter 配合）。
- **`docker-compose.yml`**：`pgvector/pgvector:pg16`（端口 5432）+ `redis:7-alpine`（端口 6379），用户/密码/库名均为 `aikeeper`。

核心表：`rooms`、`characters`、`character_runtime_state`（权威 HP/SAN/MP/Luck）、`scenarios`、`events`（BIGSERIAL 主键）、`actions`、`action_status_events`、`action_review_requests`、`compensation_transactions`、`player_sequences`、`checkpoints`、`campaign_archives`、`clues`、`clue_shares`（含 `public_version` + `room_id`）、`objectives`、`inventory`、`clarifications`、`document_chunks`（含 `vector(768)` 列）、`host_states`、`rule_documents`、`rule_source_versions`、`room_turns`、`encounters`、`encounter_participants`（含 `display_name`）、`spoiler_sensitive_items`、`scenario_assets`（含 `visibility`）、`ai_provider_configs`、`ai_provider_config_audits`、`resolution_bundles`

### 线索分享机制

玩家通过 `POST /api/player/clues/{clue_id}/share` 分享线索：`share_full_text=true` 需 `confirm_share_full_text=true` 且经过 SpoilerGuard 检查；未提供 `public_version` 时使用安全占位符 `"玩家分享了一条线索，但未公开完整内容。"`。分享后写入 `clue_shares` 表并广播 `s2c_clue_shared` 事件（party 可见）。

### NPC 标识

NPC 使用稳定的 `npc_id`（SHA-256 哈希 `"{name}:{role}"` 取前 8 位，格式 `npc-a1b2c3d4`）。AI 结构化 prompt 要求生成英文 slug 格式 npc_id。`_ensure_npc_ids()` 保证去重。`encounter_participants` 中 NPC 的 `character_id` 为 `"npc:{uuid}"` 格式。

### 检查点系统

`EventLog.create_checkpoint()` 构建完整房间快照（`_build_snapshot`：rooms + SNAPSHOT_DATA_TABLES 全部数据），JSON 序列化后存入 `checkpoints` 表。自动检查点最多保留 20 个（`MAX_AUTO_CHECKPOINTS`），由 `resolution_pipeline.py` 在回合结算后触发。`restore_checkpoint()` 要求 `confirm=true` + `reason`，DELETE 子表数据后重新 INSERT 快照数据。`encounter_participants` 通过 JOIN `encounters` 限定房间范围。

### 配置

`src/server/config.py` —— `Settings.from_env()` 读取：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATABASE_URL` | `postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper` | PG 连接串 |
| `DEEPSEEK_API_KEY` | `""` | 为空时编译器使用本地正则兜底 |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `REDIS_URL` | `""` | 为空时缓存层 no-op |
| `AGENT_ENABLED` | `false` | 启用 GameAgent + GameLoop |
| `KP_MCP_SERVER_URL` | `http://127.0.0.1:9100/mcp` | KP MCP Server 地址 |
| `AI_PROVIDER_ORDER` | `mcp,deepseek,local` | AI provider 优先级 |
| `AI_TIMEOUT_SECONDS` | `30` | AI 调用超时 |
| `STT_PROVIDER` | `disabled` | 语音转文本 provider |
| `STT_HTTP_URL` | `""` | STT HTTP 端点 |
| `STT_HTTP_API_KEY` | `""` | STT API 密钥 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_FILE` | `""` | 日志文件路径 |
| `PORT` | `3001` | 服务端口 |
| `AI_CONFIG_MASTER_KEY` | `""` | 管理员 AI provider 配置加密主密钥（回退到 `JWT_SECRET`） |
| `OPENAI_API_KEY` | `""` | KP MCP Server 使用的 OpenAI-compatible API 密钥 |
| `OPENAI_MODEL` | `""` | KP MCP Server 使用的模型名 |

### AI Provider Config 管理

Admin 面板（`router_admin.py`）管理存储在 `ai_provider_configs` 表的外部 AI provider 配置：
- API 密钥经 Fernet 加密静态存储（HKDF 从 `AI_CONFIG_MASTER_KEY` 或 `JWT_SECRET` 派生密钥）
- SSRF 防护：校验 API base URL，阻止云 metadata 地址（`100.100.100.200`、`192.0.0.192`），非 localhost HTTP 目标被拒绝
- `AiProviderConfigStore`（`ai/provider_config.py`）处理 CRUD、激活（同时只有一个 active）、连通性测试和审计日志（`ai_provider_config_audits` 表）
- Provider 链路顺序由 `AI_PROVIDER_ORDER` 控制（默认 `mcp,deepseek,local`）——运行时逐个尝试，失败则跳过到下一个

### 应用启动（`main.py` lifespan）

11 步顺序初始化：Database → Auth（确保预留 admin 账号）→ Embedding → RAG → Engine → MechanicCompiler → Redis（可选）→ SpoilerGuard → ResolutionPipeline → StateService → GameAgent+GameLoop（可选，需 `AGENT_ENABLED`）。

注册 20+ 个 router：rooms、player（含 actions_v2 / campaign_v2 / collaboration_contracts / settings / action_reviews / clues / objectives / clarification / reconnect / archive）、host（含 action_reviews）、scenarios、ai、rag、auth、map、maps、admin、archive、migration。

WebSocket 端点 `/ws?room=&role=&token=&lastSequence=`：`role=host` 走 host handler，`role=player` 走 player handler（含断线重连 catch-up，使用 `_can_player_see_event()` 过滤）。

### PlayerIntent 生命周期

```
客户端 POST /api/player/intent
  → 前端幂等检查（action_id 已存在 → 直接返回）
  → Engine.submit_intent()：版本冲突检测(state_version)
  → INSERT actions(status='queued') → INSERT events(s2c_action_queued)
  → [Host 手动触发 OR 自动批次收集 OR GameLoop.process_turn()]
  → TurnManager.mark_resolving()（条件 UPDATE，幂等）
  → ResolutionPipeline.resolve_action()
    → Director.build_director_context()：构建完整上下文（角色、场景、runtime package、recent events）
    → AiGateway.analyze_director_action()：AI 理解意图 → normalize_director_plan() 构建 DirectorPlanDTO
      → 低置信度（<0.6）或模糊意图 → player_clarification_required → host_exception 路由
      → 高置信度 → director_plan_validated → 继续结算
    → MechanicCompiler.compile()（DeepSeek API / 本地规则兜底）
    → RuleExecutor.execute()（匹配 trigger mechanics + 执行 COC handler）
    → StateService.apply_change()（结构化状态变更）
    → AiGateway.narrate_action() → Narrator.validate_narration_result()：严格 fact-ref 校验
      → 校验失败 → build_verified_narration() 本地回退（直接从场景文本渲染，不调用 AI）
    → SpoilerGuard.review()（输出侧反剧透检查）
    → 写 actions(status='resolved', result=JSON) + INSERT events + Redis 缓存
    → ProjectionDispatcher 推送 s2c_reveal_transaction(host) + s2c_state_patch(player) + s2c_public_observation(party) + s2c_action_completed(player)
    → 回合结算后自动创建检查点
```

### 动作状态机

`engine/action_state.py` 定义完整动作状态机（14 个状态），`engine/action_lifecycle.py` 提供 `transition_action()` 和 `complete_action()` 执行原子状态跃迁：

```
analyzing ──→ awaiting_confirmation ──→ queued ──→ batched ──→ resolving ──→ completed
       │              │                    │           │              │
       ├── canceled   ├── sync_required    ├── sync    ├── await_host ├── await_player_choice
       └── timeout    └── canceled         └── rejected│   exception  │
                                                        └── canceled   ├── sync_required
                                                                       └── await_host_exception
```

**终端态：** `completed` / `rejected` / `canceled` / `timeout`。`analyzing` 和 `awaiting_confirmation` 是 Director 阶段；`queued`/`batched` 是入队等待结算；`resolving` 是结算中，可能因需要玩家选择或 Host 裁决而进入 `awaiting_player_choice` / `awaiting_host_exception`。

### 鉴权模式

- **房主**：创建房间时获得 `owner_token`，操作时通过 `X-Owner-Token` header 传递。
- **玩家**：加入房间时获得 `player_token`，操作时通过 `X-Room-Token` header 传递。**身份以 token 为准，不接受前端传入 characterId 作为安全身份。**
- **Admin**：通过 `router_auth.py` 的账号体系认证，`_require_admin` 依赖注入。
- 加入房间有速率限制（内存计数器，按 IP）。

### 动作安全层

**ActionPolicy**（`engine/action_policy.py`）：玩家意图提交前的安全分类器。分析意图文本中的事实声明模式（如"已经拿到"、"自动成功"），检测 unsafe candidate markers，按 `PolicyOutcome` 分类：`allow` / `clarify` / `reject` / `timeout_safe_effect`。机械类意图（move/skill_check/combat_action 等）受更严格审查。

**RiskContract**（`engine/risk_contract.py`）：每场遭遇战或场景的伤害风险声明契约。定义 `categories`（伤害类型与最大等级 `low/medium/high`）、`excluded_tags`、`default_harm`（NPC/场景默认伤害等级）、`irreversible_controls`（不可逆后果清单）、`hidden_checks`（隐藏检定声明来源）。由 `normalize_risk_contract()` 从场景元数据编译。

**HostAutonomy**（`engine/host_autonomy.py`）：Host 离线时的动作路由策略。`HostAutonomyPolicy` 三种模式：`host_required`（默认→等待 Host 上线）、`conservative`（仅安全动作自动路由）、`delegated`（信任 AI 处理大部分场景）。`session_mode="ai_only"` 时自动尝试 `offline_autonomy`，复杂动作路由到 `engine_policy`。

**ActionConsent**（`engine/action_consent.py`）：多玩家 PVP 和组决策系统。`PVP_EFFECTS` 定义需要受影响的玩家 consent 的动作类型（damage/resource_take/restrict_action/status_change）。`GROUP_DECISION_KINDS` 定义组决策类型（reversible_route/shared_resource/ending/abandon_ally/risk_expansion），`UNANIMOUS_GROUP_DECISIONS` 要求全票通过（不含 reversible_route）。默认沉默视为拒绝（fail-closed）。

**RevealLedger**（`engine/reveal_ledger.py`）：知识授权的权威、只增账本。`validate_proposals()` 检查事实揭示提案是否满足条件（场景已进入、线索已发现、事件类型已触发），通过 `_REVEAL_EVENT_TYPES` 映射到 `s2c_fact_revealed` / `s2c_fact_corrected` / `s2c_fact_safety_event`。失败时抛 `RevealPolicyError`（玩家安全的错误码，不含源内容）。

### 单人冒险系统

`scenario/solo_adventure.py` 从 PDF 规则书文本提取单人冒险条目（`extract_solo_adventure()`）：按 `NODE_PATTERN`（`数字#`）分割节点，`TARGET_PATTERN` 识别跳转目标，构建有向图。输出完整性报告（节点数、边数、重复 ID、缺失目标、不可达节点）。

`scenario/solo_runtime.py` 实现单人冒险运行时：`SoloRuntime` 类追踪当前节点、历史记录、角色属性，处理检定跳转（`_SOLO_SKILL_CHECK_RE` 正则匹配）、条件分支（属性比较）、选择分支。`SoloTransitionError` 处理无效跳转。

### 运营治理

`governance/retention.py` 提供数据保留和操作审计功能：干运行 Token 机制（15 分钟 TTL）、HMAC-SHA256 签名验证、`RetentionError` 异常（含机器可读错误码）。`governance/__init__.py` 声明为运营治理子包。

### AI 决策审计

`ai/decision_audit.py` 审计 AI 决策日志：定义 `_FORBIDDEN_KEYS`（禁止记录到审计日志的敏感字段，如 token/密码/私人笔记），`_PROPOSAL_KEYS_BY_TASK` 按 task type 声明允许字段白名单（`analyze_director_action` 和 `narrate_action` 各自独立），`_CONTEXT_KEYS` 和 `_CITATION_KEYS` 限定上下文和引用字段。未在白名单中的字段自动从审计日志中删除。

### 补偿服务

`engine/compensation_service.py` 处理 Host 对动作结果的审查和补偿：`resolve_action_review()` 接受 Host 决策（decision + reason + mutations），通过 `StateService.apply_change()` 应用补偿，写 `compensation_transactions` 表。`recalculate_action_review()` 对 skill_check 动作重新解释骰值（更换难度等级），不改变世界状态，验证 roll receipt 的完整性。

### 战斗轮规划

`combat_round_planner.py` 提供确定性战斗轮排序：`build_combat_round_plan()` 按有效敏捷降序排列动作，处理冲突键去重（同一冲突键的先后动作建立依赖关系），支持准备动作约束（`prepared_rule_constraints`），生成 `global_order` / `cluster_id` / `dependencies` 结构供结算引擎消费。

### 队伍消息

`player/team_messages.py` 提供玩家间 OOC 文本/语音消息系统：速率限制（3 msg/s/character），`ALLOWED_TEAM_MESSAGE_SOURCES` 限制来源类型，`MAX_TEAM_MESSAGE_LENGTH` 上限 2000 字符。通过 `ProjectionDispatcher` 广播 `s2c_team_message` 事件（party 可见）。

### Agent 工具权限分级

`src/server/agent/tools.py` 中所有工具按权限分级：

| 级别 | 说明 | 示例 |
|------|------|------|
| `read_only` | 只读查询 | `query_npcs`、`query_clues` |
| `suggest_only` | 输出建议，不直接写入 | `suggest_narrative` |
| `controlled_write` | 通过服务链写入（Engine→StateService→事件） | `engine_save_clue` |
| `disabled` | 默认禁用 | — |

`engine_save_clue` 默认 `controlled_write`：不 direct INSERT，必须走 Clue → State → Journal 服务链。

### 素材上传安全

`POST /api/admin/assets/upload` 四重校验：扩展名白名单（`ALLOWED_EXTENSIONS`）、危险扩展名拦截（`BLOCKED_EXTENSIONS`：.svg/.html/.js 等）、MIME 类型校验（`ALLOWED_MIME_TYPES`）、魔术字节文件头检查（`MAGIC_BYTES`）。大小限制 `MAX_ASSET_SIZE`（50MB）。`visibility` 字段控制可见范围（host_only/party/private/admin_only）。删除时检查引用（`_find_asset_references()`），force delete 要求 `confirm=true` + `reason`。

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

- **后端：** `tests/server/conftest.py`——`test_db`（连接真实 PG + TRUNCATE 所有表 + RESTART IDENTITY CASCADE）、`engine`、`client`（FastAPI TestClient）fixture。自动重置速率限制器。**需要 PostgreSQL 运行中**（`DATABASE_URL` 环境变量可覆盖）。124+ 个测试文件覆盖 engine/ai/events/player/host/scenario/rules 各层。
- **前端：** `src/client/tests/` 使用 vitest。当前覆盖 navigation 路由解析和 tabs 配置。

### Golden Modules（`data/golden_modules/`）

三套原创结构化剧本黄金样本，用于验证剧本导入、RAG、文字地图、预设角色和开房前质量检查：

| 模块 | 人数 | 类型 |
|------|------|------|
| `01-solo-tutorial-tide-letter` | 1 人 | 单人教学 |
| `02-short-team-glass-rain` | 2–4 人 | 短团 |
| `03-investigation-sandbox-lost-property` | 3–5 人 | 调查沙盒 |

每个模块包含 `module.json`（`ScenarioKnowledgeGraph` + `character_templates` + `quality_report`）和 `README.md`。验证命令：

```bash
python scripts/run_golden_module_suite.py          # 完整 suite（需 PostgreSQL 运行中）
python scripts/run_golden_module_suite.py --spec 01-solo-tutorial-tide-letter  # 单个模块
```

## 关键设计约束

1. **AI 不写状态**：AI 只输出建议，HP/SAN/物品/线索/场景进度必须 Engine 校验后写入。
2. **Player 不越权**：所有写操作走 `POST /api/player/intent`，不接受前端传入 characterId 作为身份。
3. **Host 不判定**：Host 只消费事件播放公共演出，不承载规则逻辑。
4. **房主不剧透**：房主可开房/暂停/急救，但不能看到完整真相或未发现线索。SpoilerGuard 在输出侧拦截。
5. **PDF 本地优先**：剧本原文本地存储，云端 AI 只接收处理所需片段。
6. **MVP 不做网络流式叙事**：`narrative_text` 完整文本下发，客户端本地打字机播放。
7. **不做任意事件回滚**：首版只有检查点恢复（`EventLog.create_checkpoint/restore_checkpoint`），无分支时间线。
8. **Embedding 本地优先**：优先用 `text2vec-base-chinese`（sentence_transformers），不可用时回退确定性 SHA-256 哈希向量（768 维），保证无外部依赖也能跑。
9. **Redis 可选**：`REDIS_URL` 为空时缓存层透明 no-op，不影响核心功能。
10. **Agent 可选**：`AGENT_ENABLED` 控制 GameAgent + GameLoop，关闭时走传统 ResolutionPipeline 路径。
11. **state_version 仅世界状态变更递增**：动作入队、ready_toggle、空变更不递增版本号。用于客户端乐观锁冲突检测。
12. **character_runtime_state 是权威来源**：HP/SAN/MP/Luck 以 `character_runtime_state` 为准，`xlsx_data` 仅作初始值导入源。
13. **事件按 audience 严格过滤**：`_can_player_see_event()` 是唯一可见性判定入口。system 事件仅白名单内对玩家可见。
14. **AI 叙事必须通过 fact-ref 验证**：Narrator 输出只能引用 runtime_package 中声明的 `allowed_facts`，未声明的 fact_ref 触发本地回退叙事（`build_verified_narration()`），不调用 AI。
15. **AI Provider 配置加密存储**：管理员添加的外部 AI 提供商 API 密钥必须经 Fernet 加密后存储，且激活前必须通过连通性测试（`test_status = 'passed'`）。
16. **Director 不写状态**：Director 输出的 `state_patch` 标记为 `advisory_only`，必须经 Engine → StateService 验证后才能生效。
17. **动作状态机严格校验**：`action_lifecycle.transition_action()` 运行时检查 `is_allowed_transition()`，非法跃迁直接抛异常，不允许静默容错。
18. **组决策默认沉默即拒绝**：`ActionConsent` 中组决策超时未响应视为拒绝（fail-closed），不假设同意。
19. **单人冒险节点完整性校验**：`solo_adventure.extract_solo_adventure()` 产出完整性报告（重复 ID、缺失目标、不可达节点），运行时 `SoloRuntime` 拒绝无效跳转。
20. **审计日志字段白名单**：`decision_audit.py` 按 task type 声明允许字段，敏感字段（token/密码/私人笔记）在审计前自动删除。
