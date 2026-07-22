# AI-Keeper — AI 自动 KP 跑团系统

AI-Keeper 是一个 AI 驱动的桌面角色扮演游戏（TRPG）主持人系统。AI 扮演 KP（守秘人），人类房主只负责开房/邀请/暂停/重试。当前主线为 **CoC 7e（克苏鲁的呼唤七版）** 调查短团。

## 技术栈

| 层级 | 技术 |
|------|------|
| **后端** | Python 3.11+, FastAPI, uvicorn, psycopg2 |
| **前端** | TypeScript 5.5, React 18.3, Vite 5.3, Vitest 1.6 |
| **数据库** | PostgreSQL 16 + pgvector（向量检索） |
| **缓存** | Redis 7（可选，透明降级） |
| **AI Provider** | DeepSeek API（主）, OpenAI-compatible（可配置）, KP MCP Server（内部契约）, 本地规则编译器（兜底） |
| **Embedding** | sentence_transformers（`text2vec-base-chinese`）+ SHA-256 哈希回退（768 维） |
| **实时通信** | WebSocket（FastAPI 原生） |
| **容器化** | Docker Compose（PG + Redis） |
| **PDF 解析** | pdfplumber, pypdf |
| **Excel 解析** | openpyxl |
| **MCP Server** | FastMCP（`kp_mcp_server/`，端口 9100） |
| **加密** | cryptography (Fernet + HKDF)，用于 AI provider API key 静态加密 |

---

## 1. 项目目录树

```
CodeX-aikeeper/
├── src/
│   ├── server/                       # Python FastAPI 后端
│   │   ├── main.py                   #   应用入口 + lifespan 初始化
│   │   ├── config.py                 #   环境变量配置（Settings.from_env）
│   │   ├── models.py                 #   Pydantic 数据模型（全项目共享）
│   │   ├── db_adapter.py             #   PostgreSQL 连接池 + SQL 翻译层
│   │   ├── db_pg.py                  #   PG 特定辅助
│   │   ├── turn_manager.py           #   回合生命周期管理
│   │   ├── game_loop.py              #   GameAgent 驱动的自动回合循环
│   │   ├── redis_cache.py            #   Redis 缓存层（可选）
│   │   ├── export.py                 #   公开导出（脱敏）
│   │   ├── stt.py                    #   语音转文本集成
│   │   ├── log_config.py             #   统一日志配置
│   │   ├── router_rooms.py           #   房间路由
│   │   ├── router_admin.py           #   管理后台路由 + AI provider 配置
│   │   ├── router_ai.py              #   AI 触发/状态路由
│   │   ├── router_auth.py            #   鉴权路由
│   │   ├── router_map.py             #   地图路由
│   │   ├── router_archive.py         #   归档路由
│   │   ├── router_migration.py       #   迁移路由
│   │   ├── rag_router.py             #   RAG 检索路由
│   │   ├── encounter_persistence.py  #   遭遇战 CRUD
│   │   ├── map_persistence.py        #   地图节点持久化
│   │   ├── map_store.py              #   地图内存缓存
│   │   ├── combat_round_planner.py   #   战斗轮规划器
│   │   ├── global_reset.py           #   全局重置
│   │   ├── room_migration.py         #   房间迁移
│   │   ├── v2_cutover.py             #   V2 切换
│   │   ├── narrative_provider.py     #   叙事文本提供者
│   │   ├── campaign_archive.py       #   战役归档
│   │   ├── turn_timeout_worker.py    #   回合超时 worker
│   │   ├── engine/                   #   引擎子系统
│   │   │   ├── engine.py             #     Engine — 唯一权威状态写入者
│   │   │   ├── resolution_pipeline.py#     ResolutionPipeline — 意图→结算主链路
│   │   │   ├── rule_executor.py      #     RuleExecutor — 规则执行器
│   │   │   ├── state_service.py      #     StateService — 结构化状态变更
│   │   │   ├── projection.py         #     ProjectionDispatcher — 按 audience 投影
│   │   │   ├── spoiler_guard.py      #     SpoilerGuard — 反剧透安全网
│   │   │   ├── skill_check.py        #     CoC D100 技能检定引擎
│   │   │   ├── batch.py              #     BatchCollector — 行动批次收集
│   │   │   ├── retro_items.py        #     RetroactiveItemService — 后验物品主张
│   │   │   ├── host_autonomy.py      #     Host 自主决策
│   │   │   ├── prepared_rule_actions.py#   预制规则行动
│   │   │   ├── ending_conditions.py  #     结局条件判定
│   │   │   ├── compensation_service.py#    补偿服务
│   │   │   ├── action_lifecycle.py   #     行动生命周期
│   │   │   ├── action_state.py       #     行动状态机
│   │   │   ├── roll_receipt.py       #     骰点回执
│   │   │   ├── fallback_narrative.py #     回退叙事模板
│   │   │   ├── secure_random.py      #     安全随机数
│   │   │   └── solo_combat_reactions.py#   单人战斗反应
│   │   ├── ai/                       #   AI 子系统
│   │   │   ├── gateway.py            #     AiGateway — 统一 AI 调用入口 + provider 链
│   │   │   ├── director.py           #     Director — 玩家意图理解 + 裁决计划
│   │   │   ├── narrator.py           #     Narrator — 叙事生成 + fact-ref 校验
│   │   │   ├── contracts.py          #     AI 输出 schema + 权限矩阵
│   │   │   ├── providers.py          #     BaseAiProvider 及实现（DeepSeek/OpenAI/MCP/Local）
│   │   │   ├── provider_config.py    #     AiProviderConfigStore — 加密配置管理
│   │   │   ├── mechanic_compiler.py  #     MechanicCompiler — 自然语言→游戏机制
│   │   │   ├── ai_kp.py             #     AIKP — AI 守秘人高层入口
│   │   │   ├── embedding.py          #     HybridEmbedding（text2vec + hash fallback）
│   │   │   ├── rag.py               #     RAGStore — 规则书向量检索
│   │   │   ├── rag_context.py        #     RAG 上下文构建
│   │   │   ├── spoiler_control.py    #     剧透控制器
│   │   │   ├── kp_mcp_client.py      #     KP MCP Server 客户端
│   │   │   ├── map_generator.py      #     地图生成器
│   │   │   └── ai_config.py          #     AI 配置
│   │   ├── player/                   #   玩家端路由（11 个 router）
│   │   │   ├── router_player.py      #     主路由
│   │   │   ├── router_actions_v2.py  #     行动意图提交（v2）
│   │   │   ├── router_campaign_v2.py #     战役（含 host/evidence/library 子路由）
│   │   │   ├── router_collaboration_contracts.py # 协作合约
│   │   │   ├── router_player_settings.py  # 玩家设置
│   │   │   ├── router_action_reviews.py   # 行动审查
│   │   │   ├── router_clues.py       #     线索
│   │   │   ├── router_objectives.py  #     目标
│   │   │   ├── router_clarification.py #   澄清
│   │   │   ├── router_reconnect.py   #     断线重连
│   │   │   ├── router_player_archive.py  # 玩家档案
│   │   │   ├── action_service.py     #     行动草稿分析服务
│   │   │   ├── team_messages.py      #     队伍消息
│   │   │   └── private_data.py       #     私密数据
│   │   ├── host/                     #   房主端路由
│   │   │   ├── router_host.py        #     Host 路由 + WebSocket endpoint
│   │   │   ├── router_action_reviews.py  # 行动审查
│   │   │   ├── ws_manager.py         #     WebSocket ConnectionManager
│   │   │   ├── host_store.py         #     Host 内存状态
│   │   │   ├── hud_builder.py        #     HUD 数据构建
│   │   │   └── public_stage.py       #     公共舞台
│   │   ├── scenario/                 #   剧本子系统
│   │   │   ├── router_scenarios.py   #     剧本路由
│   │   │   ├── pdf_parser.py         #     PDF 剧本解析
│   │   │   ├── xlsx_parser.py        #     XLSX 角色卡解析
│   │   │   ├── import_service.py     #     剧本导入服务
│   │   │   ├── quality.py            #     质量报告生成
│   │   │   ├── content_package.py    #     内容包构建
│   │   │   ├── content_projection.py #     内容投影
│   │   │   ├── module_compiler.py    #     模块编译器
│   │   │   ├── review_service.py     #     剧本审查服务
│   │   │   ├── scene_image_service.py#     场景图片服务
│   │   │   ├── solo_adventure.py     #     单人冒险定义
│   │   │   ├── solo_runtime.py       #     单人冒险运行时
│   │   │   ├── asset_binding.py      #     素材绑定
│   │   │   ├── golden_suite.py       #     黄金样本套件
│   │   │   └── character_presets.py  #     角色预设
│   │   ├── events/                   #   事件子系统
│   │   │   ├── events.py             #     EventBus（内存 pub/sub）
│   │   │   ├── event_log.py          #     EventLog（持久化+检查点+可见性过滤）
│   │   │   └── events_registry.py   #     事件注册表
│   │   ├── rules/                    #   CoC 规则引擎
│   │   │   ├── base.py               #     BaseRuleHandler + RuleResult
│   │   │   ├── registry.py           #     Handler 注册表
│   │   │   ├── triggers.py           #     触发器评估
│   │   │   ├── coc_handlers.py       #     CoC 核心处理器（技能/理智/战斗/幸运）
│   │   │   └── encounter_handlers.py #     遭遇战处理器
│   │   └── agent/                    #   GameAgent（可选）
│   │       ├── game_agent.py         #     DeepSeek 驱动的 KP 代理
│   │       └── tools.py              #     工具定义（含权限分级）
│   └── client/                       # React/Vite 前端
│       ├── src/
│       │   ├── main.tsx              #     入口
│       │   ├── App.tsx               #     根组件（路由分发）
│       │   ├── navigation.ts         #     路由解析中枢
│       │   ├── api.ts                #     fetch 封装（apiFetch<T>）
│       │   ├── ws.ts                 #     WebSocket 管理（PlayerWS）
│       │   ├── types.ts              #     TypeScript 类型定义
│       │   ├── styles.css            #     Bauhaus brutalist 设计系统
│       │   ├── pages/                #     页面组件
│       │   │   ├── HostStage.tsx     #       Host 大屏演出
│       │   │   ├── HostLobby.tsx     #       房间等待大厅
│       │   │   ├── HostCreate.tsx    #       创建房间
│       │   │   ├── HostConsole.tsx   #       Host 控制台
│       │   │   ├── PlayerActionPage.tsx #   玩家统一面板（5 标签）
│       │   │   ├── PlayerCharacter.tsx  #   玩家角色卡
│       │   │   ├── PlayerInventory.tsx  #   玩家背包
│       │   │   ├── PlayerLobby.tsx   #       玩家等待大厅
│       │   │   ├── PlayerJoinPage.tsx#       加入房间
│       │   │   ├── AdminDashboard.tsx#      管理后台
│       │   │   ├── AdminAcceptancePage.tsx # 管理验收页
│       │   │   ├── CharacterBuilderPage.tsx#角色构建器
│       │   │   ├── LoginPage.tsx     #       登录页
│       │   │   └── RagTestPage.tsx   #       RAG 测试页
│       │   └── components/           #     可复用 UI 组件
│       │       ├── BauhausShell.tsx  #       共享布局（BauhausPage/BrutalProgress）
│       │       ├── PlayerTerminal.tsx#       玩家移动端外壳
│       │       ├── PlayerActionComposer.tsx # 行动编写器
│       │       ├── TacticalButtons.tsx #     战术行动按钮组
│       │       ├── CollaborationContractPanel.tsx # 协作合约面板
│       │       ├── CampaignHomePanel.tsx   # 战役首页
│       │       ├── EncounterPanel.tsx      # 遭遇战面板
│       │       ├── HostCampaignControls.tsx# Host 战役控制
│       │       ├── HostLogsPanel.tsx       # Host 日志面板
│       │       ├── HostMapPanel.tsx        # Host 地图面板
│       │       ├── HostSkeletonPanels.tsx  # Host 骨架面板
│       │       ├── IdentitySwitcher.tsx    # 身份切换器
│       │       ├── AbsentPolicyControl.tsx # 缺席策略控制
│       │       ├── RedactedCitationDisclosure.tsx # 脱敏引用展示
│       │       ├── ScenarioReviewWorkbench.tsx   # 剧本审查工作台
│       │       └── VoiceInput.tsx          # 语音输入
│       ├── tests/                   #     前端测试（vitest）
│       ├── dist/                    #     构建输出
│       └── package.json             #     前端依赖与脚本
├── kp_mcp_server/                   # 独立 KP MCP Server（FastMCP）
│   ├── server.py                    #   ASGI 应用（4 个 tool）
│   ├── kp_brain.py                  #   核心逻辑
│   ├── config.py                    #   配置
│   ├── __main__.py                  #   入口
│   └── prompts/                     #   prompt 契约
│       ├── soul.md                  #     KP 人设
│       ├── rules.md                 #     规则契约
│       └── contract.md              #     输出契约
├── tests/
│   └── server/                      # 后端测试（~100 个文件，pytest）
│       ├── conftest.py              #   共享 fixture（test_db/engine/client）
│       ├── test_engine.py           #   引擎测试
│       ├── test_resolution_pipeline.py
│       ├── test_director_runtime.py
│       ├── test_narrator_runtime.py
│       ├── test_spoiler_guard.py
│       ├── test_state_service.py
│       ├── test_collaboration_contracts.py
│       └── ...（90+ 测试文件，覆盖所有子系统）
├── scripts/                         # 辅助脚本
│   ├── run_golden_module_suite.py   #   黄金模块 E2E 验证
│   ├── run_multiplayer_loop.py      #   多人循环测试
│   ├── check_text_quality.py        #   文本质量检查
│   └── reset_content_projection.py  #   内容投影重置
├── data/                            # 本地开发数据
│   ├── golden_modules/              #   三套原创黄金样本剧本
│   ├── scenarios/                   #   导入的剧本数据
│   ├── scenario_assets/             #   剧本素材（图片/音频/PDF）
│   ├── character_presets/           #   角色预设
│   ├── prototypes/                  #   原型/实验代码
│   └── test_assets/                 #   测试素材
├── docs/                            # 文档
│   ├── 00-产品规范/                  #   M0 产品宪法 + ADR
│   ├── 20-核心链路/                  #   核心架构 + 数据流
│   ├── 25-深挖优势与设计原则/         #   战略设计笔记
│   ├── 30-DeepSeek任务包/            #   可执行任务批次
│   ├── 50-AI-Keeper-Platform/       #   24 个平台模块 PRD
│   ├── 60-验收与测试报告/             #   全部验收/测试/审计报告
│   ├── PRDs/                        #   产品需求文档（PRD-00 ~ PRD-30）
│   ├── 设计前端/                     #   前端设计稿
│   └── 90-归档/                     #   历史文档归档
├── dev.py                           # 一键启动脚本（Docker + BE :3001 + FE :5173 + KP :9100）
├── docker-compose.yml               # PostgreSQL :5432 + Redis :6379
├── pyproject.toml                   # Python 项目配置
├── uv.lock                          # 依赖锁定文件
├── .editorconfig                    # 编辑器配置
├── .gitignore
├── CLAUDE.md                        # Claude Code 项目指南
├── AGENTS.md                        # 仓库指南
└── README.md                        # 本文件
```

---

## 2. 主要配置文件

| 文件 | 用途 | 关键内容 |
|------|------|----------|
| `pyproject.toml` | Python 项目元数据、依赖、pytest 配置 | `requires-python >= 3.11`，`asyncio_mode = "auto"`，本地 temp 目录 `.pytest-tmp-local` |
| `docker-compose.yml` | 本地开发基础设施 | PostgreSQL 16 pgvector + Redis 7，用户/密码/库名均为 `aikeeper` |
| `src/server/config.py` | 运行时配置（`Settings.from_env()`） | 所有环境变量集中定义（见下表） |
| `.editorconfig` | 编辑器统一风格 | UTF-8, LF, Python 4 空格, TS/MD/JSON 2 空格 |
| `.gitignore` | Git 忽略规则 | `.runtime/`, `log/`, `.pytest-*`, `__pycache__/`, `node_modules/`, `dist/` |
| `src/client/package.json` | 前端依赖与脚本 | React 18.3, Vite 5.3, TypeScript 5.5, Vitest 1.6 |
| `src/client/vite.config.ts` | Vite 构建配置 | 开发代理到 `:3001` |
| `kp_mcp_server/config.py` | KP MCP Server 配置 | `OPENAI_API_KEY`/`OPENAI_MODEL` 或 `DEEPSEEK_API_KEY` |

### 环境变量完整列表

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql://aikeeper:aikeeper123@localhost:5432/aikeeper` | PG 连接串 |
| `DEEPSEEK_API_KEY` | `""` | 空值时 AI 以 mock 模式运行（本地规则兜底） |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | DeepSeek 模型名 |
| `REDIS_URL` | `""` | 空值时缓存层透明 no-op |
| `AGENT_ENABLED` | `false` | 启用 GameAgent + GameLoop |
| `KP_MCP_SERVER_URL` | `http://127.0.0.1:9100/mcp` | KP MCP Server 地址 |
| `AI_PROVIDER_ORDER` | `mcp,deepseek,local` | AI provider 优先级链 |
| `AI_TIMEOUT_SECONDS` | `30` | AI 调用超时 |
| `AI_CONFIG_MASTER_KEY` | `""` | 管理员 AI provider 配置加密主密钥（回退到 `JWT_SECRET`） |
| `STT_PROVIDER` | `disabled` | 语音转文本 provider |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_FILE` | `""` | 日志文件路径 |
| `PORT` | `3001` | 后端端口 |
| `AIKEEPER_DEV_MODE` | `false` | 设为 `1` 绕过生产 JWT_SECRET 检查 |
| `JWT_SECRET` | — | 生产环境必须设置强随机值 |
| `OPENAI_API_KEY` | `""` | KP MCP Server 使用的 OpenAI-compatible API 密钥 |
| `OPENAI_MODEL` | `""` | KP MCP Server 使用的模型名 |

**关键判断：** 当前项目行为主要通过**环境变量配置**控制（AI provider 切换、Agent 启停、缓存层开关、日志级别），无需改代码。

---

## 3. 主流程与状态机

### 3.1 应用启动流程（11 步）

```
Database → Auth → Embedding → RAG → Engine → MechanicCompiler →
Redis（可选）→ SpoilerGuard → ResolutionPipeline → StateService →
GameAgent+GameLoop（可选，需 AGENT_ENABLED）
```

### 3.2 核心业务链路：PlayerIntent 生命周期

```
客户端 POST /api/player/intent
  → 前端幂等检查（action_id 已存在 → 直接返回）
  → Engine.submit_intent()：版本冲突检测(state_version)
  → INSERT actions(status='queued')
  → [Host 手动触发 OR 自动批次收集 OR GameLoop.process_turn()]
  → TurnManager.mark_resolving()（条件 UPDATE，幂等）
  → ResolutionPipeline.resolve_action()
    → Director：构建上下文 → AiGateway 调用 AI 理解意图 → DirectorPlanDTO
      → 低置信度(<0.6) → player_clarification_required → host_exception
      → 高置信度 → director_plan_validated
    → MechanicCompiler.compile()（DeepSeek / 本地兜底）
    → RuleExecutor.execute()（COC 规则处理）
    → StateService.apply_change()（结构化状态变更）
    → Narrator：AiGateway 调用 AI 生成叙事 → validate_narration_result()
      → 校验失败 → build_verified_narration() 本地回退
    → SpoilerGuard.review()（反剧透）
    → 写 actions(status='resolved') + INSERT events + Redis 缓存
    → ProjectionDispatcher 推送 4 条事件（host + player + party）
    → 回合结算后自动创建检查点
```

### 3.3 行动状态机

```
idle → submitting → queued → resolving → resolved
                                  ↘ rejected / timeout
```

### 3.4 回合状态机

```
collecting → resolving → resolved
```

### 3.5 核心状态权威

| 概念 | 权威来源 | 说明 |
|------|----------|------|
| HP/SAN/MP/Luck | `character_runtime_state` 表 | 运行时唯一权威，`xlsx_data` 仅作初始值 |
| 世界状态版本 | `rooms.state_version` | 仅在权威状态变更时递增（非动作入队） |
| 游戏事件 | `events` 表（BIGSERIAL） | 不可变事件流 |
| AI 叙事 | Narrator → fact-ref 校验 | 只能引用 `allowed_facts`，否则本地回退 |
| 剧透防护 | SpoilerGuard 索引 | 输出侧确定性匹配 + 重试 + 模板回退 |

---

## 4. 外部服务接口

本项目是纯 Web 应用，无硬件设备接口。以下是依赖的外部服务接口：

| 服务 | 连接方式 | 用途 | 降级策略 |
|------|----------|------|----------|
| **PostgreSQL 16 + pgvector** | TCP :5432, psycopg2 连接池 2-10 | 主数据库 + 向量检索（768 维） | 必须可用 |
| **Redis 7** | TCP :6379 | 事件缓存（最近 200 条）+ HUD 缓存（TTL 60s） | 透明 no-op |
| **DeepSeek API** | HTTPS | 主要 AI provider | → MCP → OpenAI → 本地 |
| **KP MCP Server** | HTTP :9100 (内部 FastMCP) | 剧本结构化 + 裁决计划 + 叙事 | → DeepSeek → OpenAI → 本地 |
| **OpenAI-compatible** | HTTPS (管理员可配置) | 备选 AI provider | → 本地 |
| **sentence_transformers** | 本地 Python 包 | 文本向量化（text2vec-base-chinese） | SHA-256 哈希回退 |

**AI Provider 链路：** `mcp → deepseek → configured_openai → local`（按 `AI_PROVIDER_ORDER` 逐个尝试，失败跳过）

---

## 5. 算法/子系统模块清单

### 5.1 AI 子系统

| 模块 | 文件 | 功能 | 输入 | 输出 | 依赖 | 独立运行 |
|------|------|------|------|------|------|----------|
| **AiGateway** | `ai/gateway.py` | 统一 AI 调用入口 + provider 链路由 | task_type, context dict | 校验后的 JSON dict | providers.py, contracts.py | 否（需 provider 实例） |
| **Director** | `ai/director.py` | 玩家意图理解 + 裁决计划构建 | conn, character, ActionDraftDTO | DirectorPlanDTO（含置信度/语义推进/citations） | EventLog, models | 否（需 DB 连接） |
| **Narrator** | `ai/narrator.py` | 叙事生成 + fact-ref 安全校验 | conn, action, character, room, ResolutionResult | NarrationResultDTO（通过校验）/ 本地回退文本 | models | 否（需 DB 连接） |
| **MechanicCompiler** | `ai/mechanic_compiler.py` | 自然语言→CoC 游戏机制编译 | declared_intent, params | MechanicCompileResult（triggered_mechanic/difficulty/bonus_dice） | DeepSeek API / 本地正则兜底 | 是（mock 模式可独立运行） |
| **HybridEmbedding** | `ai/embedding.py` | 文本向量化 | text: str | 768 维向量 | sentence_transformers / hashlib | 是 |
| **RAGStore** | `ai/rag.py` | 规则书向量检索 | query: str, top_k: int | 匹配文档片段列表 | PgDatabase, HybridEmbedding | 否（需 PG + pgvector） |
| **AiProviderConfigStore** | `ai/provider_config.py` | 加密管理外部 AI provider 配置 | CRUD payloads | 脱敏配置列表 | cryptography (Fernet+HKDF), PostgreSQL | 否（需 DB） |
| **SpoilerController** | `ai/spoiler_control.py` | 剧透控制器 | 敏感项索引 | 重试 prompt / 安全模板 | SpoilerGuard | 否 |
| **KpMcpClient** | `ai/kp_mcp_client.py` | KP MCP Server 客户端 | tool_name, args | AI 响应 dict | httpx | 是（mock 模式） |

### 5.2 引擎子系统

| 模块 | 文件 | 功能 | 输入 | 输出 | 依赖 | 独立运行 |
|------|------|------|------|------|------|----------|
| **Engine** | `engine/engine.py` | 唯一权威状态写入者 | PlayerIntent | 状态变更 + 事件 | PostgreSQL | 否 |
| **ResolutionPipeline** | `engine/resolution_pipeline.py` | 意图→结算主链路 | action_id | resolved action + 投影事件 | Director, Narrator, RuleExecutor, StateService, SpoilerGuard | 否 |
| **RuleExecutor** | `engine/rule_executor.py` | 触发匹配 → handler 执行 | PlayerIntent, MechanicCompileResult, character, inventory | ResolutionResult（含 state_patch/mutations） | rules/registry.py, rules/triggers.py | 否（需 handler 注册表） |
| **StateService** | `engine/state_service.py` | 结构化状态变更（JSON Patch 风格） | mutations list | StateChangeSet（含版本递增/clamping/no-op 检测） | PostgreSQL, ProjectionDispatcher | 否（需 DB） |
| **SpoilerGuard** | `engine/spoiler_guard.py` | 反剧透输出拦截 | text, room_id | SpoilerReviewResult（通过/违规/回退） | PostgreSQL | 否（需敏感项索引） |
| **SkillCheck** | `engine/skill_check.py` | CoC 7e D100 技能检定 | skill_value, difficulty, bonus_dice | 检定结果（success_level/roll_trace） | secure_random | 是 |
| **ProjectionDispatcher** | `engine/projection.py` | 按 audience 拆分事件投影 | event, audience | 写 DB + 推 WebSocket + 写 Redis | EventLog, WebSocket, Redis | 否 |
| **BatchCollector** | `engine/batch.py` | 自动批次收集 | room_id | 批量结算 | TurnManager, ResolutionPipeline | 否 |
| **RetroactiveItemService** | `engine/retro_items.py` | 后验物品主张 | claim, evidence | 校验结果 | PostgreSQL | 否 |
| **EndingConditions** | `engine/ending_conditions.py` | 结局条件判定 | room_state | 触发结局 / 继续 | PostgreSQL | 否 |
| **HostAutonomy** | `engine/host_autonomy.py` | Host 自主决策 | room_id, decision_type | 决策结果 | PostgreSQL | 否 |

### 5.3 CoC 规则处理器

| Handler | 文件 | 触发条件 | 功能 |
|---------|------|----------|------|
| `CocSkillCheckHandler` | `rules/coc_handlers.py` | `triggered_mechanic: "skill_check"` | CoC 7e D100 技能检定（含奖惩骰、Pushed Roll、大成功/大失败） |
| `CocSanityHandler` | `rules/coc_handlers.py` | `triggered_mechanic: "sanity"` | SAN 值扣除、临时/不定期疯狂判定 |
| `CocCombatHandler` | `rules/coc_handlers.py` | `triggered_mechanic: "combat"` | 战斗轮结算（命中/伤害/闪避） |
| `CocLuckHandler` | `rules/coc_handlers.py` | `triggered_mechanic: "luck_spend"` | 幸运值消耗 |
| `CocEncounterHandler` | `rules/encounter_handlers.py` | `triggered_mechanic: "encounter"` | 遭遇战（参与者管理/距离带/状态） |
| `MoveHandler` | `rules/coc_handlers.py` | `intent_type: "move"` | 场景移动 + 语义推进校验 |

### 5.4 剧本编译管线

| 模块 | 文件 | 功能 | 独立运行 |
|------|------|------|----------|
| **PDF 解析** | `scenario/pdf_parser.py` | 提取 PDF 文本（pdfplumber） | 是 |
| **XLSX 解析** | `scenario/xlsx_parser.py` | 解析角色卡 Excel（openpyxl） | 是 |
| **导入服务** | `scenario/import_service.py` | 剧本导入编排 | 否 |
| **内容包构建** | `scenario/content_package.py` | 构建结构化内容包 | 否 |
| **模块编译器** | `scenario/module_compiler.py` | 将内容包编译为 runtime_package | 否（需 AI Gateway） |
| **质量报告** | `scenario/quality.py` | 剧本完整度/缺失项检查 | 是 |
| **黄金套件** | `scenario/golden_suite.py` | 黄金模块 E2E 验证框架 | 否（需 DB） |

### 5.5 安全模块

| 模块 | 文件 | 功能 |
|------|------|------|
| **SpoilerGuard** | `engine/spoiler_guard.py` | 输出侧反剧透：索引→匹配→重试→回退 |
| **SpoilerController** | `ai/spoiler_control.py` | 剧透控制器接口 |
| **ProviderConfig** | `ai/provider_config.py` | API key 加密存储（Fernet）+ SSRF 防护 + 审计日志 |
| **SecureRandom** | `engine/secure_random.py` | 安全随机数（骰点用） |
| **Admin Auth** | `router_auth.py` | 管理员账号体系 + 速率限制 |
| **Asset Security** | `router_admin.py` | 四重上传校验（扩展名+MIME+魔术字节+大小） |

---

## 6. 部署与发布

### 6.1 本地开发

```bash
# 一键启动全部服务（推荐）
python dev.py

# 跳过 Docker（PG/Redis 已在本地运行）
python dev.py --skip-docker

# 分步启动（调试用）
docker compose up -d                                      # 1. 启动 PG + Redis
uvicorn src.server.main:app --reload --port 3001          # 2. 后端（含热重载）
cd src/client && npm run dev                              # 3. 前端（Vite HMR）
python -m kp_mcp_server                                   # 4. KP MCP Server（可选）
```

### 6.2 环境依赖

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Python | >= 3.11 | `pyproject.toml` 声明 |
| Node.js | 任意 LTS | 前端构建 |
| Docker | 任意 | 仅本地开发需要（PG + Redis 可用原生安装替代） |
| PostgreSQL | 16 + pgvector 扩展 | 向量检索必须 pgvector |
| Redis | 7 | 可选，不支持时透明降级 |
| Windows/Linux/macOS | — | 纯 Python + Node，跨平台 |

### 6.3 生产部署要点

1. **`JWT_SECRET`** 必须设置为强随机值，否则启动时 FATAL 退出（dev 模式除外）
2. **`DEEPSEEK_API_KEY`** 设置后 AI 才真正工作，为空时使用本地正则兜底（功能受限）
3. **`AI_CONFIG_MASTER_KEY`** 用于加密管理员通过 UI 添加的外部 AI provider API key
4. 生产建议使用 **gunicorn + uvicorn workers** 而非 `--reload` 模式
5. 前端 `npm run build` 产出静态文件到 `src/client/dist/`，可由 nginx 直接托管
6. KP MCP Server 为内部服务，**不应暴露到公网**
7. 数据库迁移通过 `db_adapter.py` 的 `initialize()` 自动执行（建表 + 索引）
8. 日志写入 `log/YYYY-MM-DD/` 目录，保留 7 天自动清理

### 6.4 数据库初始化

```bash
# Docker 方式（推荐）
docker compose up -d
# 应用启动时自动建表（db_adapter.initialize()）

# 原生 PostgreSQL 方式
# 1. 确保 pgvector 扩展已安装
# 2. 创建数据库和用户
#    CREATE USER aikeeper WITH PASSWORD 'aikeeper123';
#    CREATE DATABASE aikeeper OWNER aikeeper;
#    CREATE EXTENSION vector;
# 3. 设置 DATABASE_URL 环境变量
# 4. 启动应用（自动建表）
```

### 6.5 升级方式

- **应用代码：** `git pull` + 重启服务（uvicorn/gunicorn 需手动重启）
- **数据库 schema：** `db_adapter.initialize()` 幂等，可安全重复执行
- **前端：** `npm run build` 后替换 dist 目录
- **无停机要求：** 当前 M0 阶段，允许短暂停服升级
- **回滚：** git checkout + 重启即可（schema 变更兼容，未使用破坏性迁移）

### 6.6 测试与验证

```bash
# 后端测试（需 PG 运行中）
python -m pytest tests/server/ -v

# 前端测试
cd src/client && npm test

# 前端类型检查 + 构建
cd src/client && npm run build

# 黄金模块 E2E 验证
python scripts/run_golden_module_suite.py

# 健康检查
python dev.py --check
```
