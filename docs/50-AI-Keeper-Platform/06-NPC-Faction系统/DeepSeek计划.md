# NPC / Faction 系统 DeepSeek 计划初版

## 执行定位

NPC / Faction 的第一批实现不做完整势力模拟，而是加固现有“剧本 NPC 资产 -> AI 上下文 -> 防剧透投影 -> 遭遇临时参与者”的链路。

DeepSeek 执行前必须查看当前代码：`src/server/ai/ai_kp.py`、`src/server/scenario/router_scenarios.py`、`src/server/scenario/quality.py`、`src/server/ai/rag.py`、`src/server/rag_router.py`、`src/server/engine/spoiler_guard.py`、`src/server/ai/spoiler_control.py`、`src/server/agent/tools.py`、`src/server/encounter_persistence.py`、`src/server/host/router_host.py`、`src/server/map_persistence.py`、`src/client/src/components/EncounterPanel.tsx`。

## 全局约束

- 先运行 `git status --short`，确认只改本批相关文件。
- 不新增完整 Faction 大系统，除非已有 WorldBook/Timeline 任务明确承接。
- 不让玩家读取完整 `knowledge_graph.npcs`。
- 不让 AI 直接把 NPC、秘密或势力行动写成世界事实。
- 不把遭遇临时 NPC 当成长期 NPC 档案。
- 所有 NPC 公开、隐藏、解锁都必须有事件或状态来源。
- 前端改动必须同步处理当前中文乱码文案。

## Batch NPC-0：现状审计与测试缺口清单

| 项 | 内容 |
|---|---|
| 目标 | 建立 NPC/Faction 当前实现清单，确认表结构、接口、RAG、防剧透、地图、遭遇覆盖 |
| 允许改的文件方向 | 文档、必要测试清单；不改业务逻辑 |
| 建议检查 | `rg -n "npcs|npc|faction|encounter|hidden_npc|npcsPresent|source_type = 'npc'" src tests` |
| 验收命令 | `python -m pytest tests/server/test_quality.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py -q` |
| 禁止事项 | 不在审计批次里新建 NPC/Faction 表 |

产出要求：

- 明确没有独立 NPC/Faction 主表。
- 明确剧本 NPC、地图 NPC、RAG NPC、隐藏 NPC、遭遇 NPC 的不同含义。
- 列出缺失测试：遭遇 API、NPC RAG 房间搜索、地图 NPC 防泄露。

## Batch NPC-1：剧本 NPC schema 与质量报告

| 项 | 内容 |
|---|---|
| 目标 | 稳定 `knowledge_graph.npcs[]` 字段，让导入结果能支持 AI、RAG、防剧透 |
| 允许改的文件方向 | `src/server/ai/ai_kp.py`、`src/server/scenario/quality.py`、`tests/server/test_ai_kp.py`、`tests/server/test_quality.py` |
| 验收命令 | `python -m pytest tests/server/test_ai_kp.py tests/server/test_quality.py -q` |
| 禁止事项 | 不让 AI 结构化结果直接创建运行态 NPC；不把字段缺失静默当作完整档案 |

验收点：

- 结构化结果兼容旧字段，并规范新字段：`npc_id/name/role/type/description/public_description/personality/motivation/is_hidden`。
- 缺少 name 或 description 的 NPC 在质量报告中被提示。
- 隐藏 NPC 没有 `public_description` 时生成质量警告。
- 不破坏已有 mock 结构化测试。

## Batch NPC-2：NPC RAG 索引与房间隔离

| 项 | 内容 |
|---|---|
| 目标 | 确保当前房间能搜索本剧本 NPC，且不会跨房搜索其他房间或其他剧本 NPC |
| 允许改的文件方向 | `src/server/ai/rag.py`、`src/server/rag_router.py`、`tests/server/test_rag.py`、`tests/server/test_rag_search.py`、`tests/server/test_rag_security.py`、`tests/server/test_rag_router.py` |
| 验收命令 | `python -m pytest tests/server/test_rag.py tests/server/test_rag_search.py tests/server/test_rag_security.py tests/server/test_rag_router.py -q` |
| 禁止事项 | 不把 `room_id IS NULL` 的所有 NPC chunk 暴露给任意房间 |

验收点：

- `source_type='npc'` 的 scenario-scoped chunk 能被对应剧本房间检索。
- A 房间不能检索 B 房间专属 NPC。
- 管理员和房主可重建 NPC 索引，普通玩家不能写索引。
- RAG 结果的 metadata 带 `npc_name` 和来源索引。

## Batch NPC-3：隐藏 NPC 防剧透与解锁事件

| 项 | 内容 |
|---|---|
| 目标 | 强化隐藏 NPC 的敏感索引、输出拦截和公开解锁事件约定 |
| 允许改的文件方向 | `src/server/engine/spoiler_guard.py`、`src/server/engine/projection.py`、`src/server/events/`、`tests/server/test_spoiler_guard.py`、`tests/server/test_spoiler.py` |
| 验收命令 | `python -m pytest tests/server/test_spoiler_guard.py tests/server/test_spoiler.py -q` |
| 禁止事项 | 不让 hidden NPC 通过 party/player 投影绕过 SpoilerGuard |

验收点：

- `is_hidden=true` NPC 的 name、role、description、aliases 被索引。
- party/player 文本命中隐藏 NPC 时被拦截或改写。
- `s2c_public_observation.payload.npcName` 能解锁已公开 NPC。
- 解锁前后行为有测试覆盖。

## Batch NPC-4：玩家/Host 可见 NPC 与地图防泄露

| 项 | 内容 |
|---|---|
| 目标 | 让玩家只看到已公开 NPC，地图和匿名访问不泄露 NPC/线索名 |
| 允许改的文件方向 | `src/server/map_persistence.py`、`src/server/router_map.py`、`src/server/ai/spoiler_control.py`、`src/client/src/pages/PlayerActionPage.tsx`、`src/client/src/components/HostMapPanel.tsx`、地图相关测试 |
| 验收命令 | `python -m pytest tests/server/test_map_persistence.py tests/server/test_map_router.py tests/server/test_spoiler.py -q`；前端改动补跑 `cd src/client && npm run build` |
| 禁止事项 | 不向无 token 请求返回完整节点 NPC/线索；不把隐藏 NPC 名放进玩家节点详情 |

验收点：

- 无 token 调用地图接口时不返回 `npcsPresent`、`cluesAvailable`、完整描述。
- 玩家未探索节点只看到邻接提示。
- 玩家已探索节点仍需过滤隐藏 NPC。
- Host 视角可查看完整地图 NPC 摘要。

## Batch NPC-5：遭遇临时 NPC 稳定化

| 项 | 内容 |
|---|---|
| 目标 | 补齐 Host 遭遇 NPC 的名称持久化、事件同步和后端测试 |
| 允许改的文件方向 | `src/server/encounter_persistence.py`、`src/server/host/router_host.py`、`src/server/models.py`、`src/client/src/components/EncounterPanel.tsx`、新增 `tests/server/test_encounters.py` |
| 验收命令 | `python -m pytest tests/server/test_encounters.py tests/server/test_host_room_lifecycle.py -q`；前端改动补跑 `cd src/client && npm run build` |
| 禁止事项 | 不把 `npc:{uuid}` 写入 `characters` 表；不把临时敌人当长期 NPC 档案 |

验收点：

- Host confirm AI 遭遇建议能创建 active encounter。
- Host reject 能取消 suggested encounter。
- Host 创建临时 NPC 后，名称、HP、DEX、MOV、武器、伤害、主技能可查询。
- next-round 重置 acted 状态。
- resolve 后发出 `s2c_encounter_resolved`。

## Batch NPC-6：玩家已知 NPC 列表最小版

| 项 | 内容 |
|---|---|
| 目标 | 提供玩家可见 NPC 摘要 DTO，来源为公开事件、已探索场景和已发现线索 |
| 允许改的文件方向 | `src/server/player/`、`src/server/engine/spoiler_guard.py`、`src/server/events/`、`src/client/src/pages/PlayerActionPage.tsx`、对应测试 |
| 验收命令 | `python -m pytest tests/server/test_spoiler.py tests/server/test_spoiler_guard.py tests/server/test_player_features.py -q` |
| 禁止事项 | 不直接返回完整 `knowledge_graph.npcs`；不把 Host-only secrets 传给玩家 |

验收点：

- 玩家能查看已公开 NPC 的名称、公开描述、首次出现来源。
- 隐藏 NPC 未公开前不出现在列表。
- 同名 NPC 解锁逻辑稳定，避免误解锁其他 NPC。

## Batch NPC-7：Faction 轻量模型评审

| 项 | 内容 |
|---|---|
| 目标 | 只输出势力最小模型设计，等待 WorldBook/Timeline 模块确认后再实现 |
| 允许改的文件方向 | docs 文档，必要时新增设计草案 |
| 验收命令 | 文档检查命令即可 |
| 禁止事项 | 不在本批创建复杂势力资源经济、不改核心事务链路 |

建议最小模型：

- `faction_id`、`name`、`public_description`、`secret_goal`、`known_members`、`resources_summary`、`relationship_edges`。
- 势力时钟必须由 Timeline 负责推进。
- 势力行动必须产生 Journal 事件。

## Batch NPC-8：端到端回归

| 项 | 内容 |
|---|---|
| 目标 | 验证 NPC 从导入到 AI、投影、防剧透、遭遇的主链路 |
| 后端命令 | `python -m pytest tests/server/test_quality.py tests/server/test_ai_kp.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py tests/server/test_rag_security.py tests/server/test_rag_router.py tests/server/test_rag_search.py -q` |
| 前端命令 | `cd src/client && npm run build` |
| 禁止事项 | 不在回归批次扩大范围做新功能 |

手动验收链路：

1. Admin 导入一个含公开 NPC 和隐藏 NPC 的剧本。
2. 质量报告显示 NPC 数量和字段问题。
3. Host 创建房间并开局。
4. 玩家探索公开场景，只看到授权 NPC 摘要。
5. 玩家询问 NPC，AI 输出不泄露隐藏身份。
6. Host 公开某 NPC 后，玩家侧可见摘要更新。
7. AI 建议遭遇，Host 确认并快速创建临时 NPC。
8. 遭遇推进一轮并结束，日志可查。
