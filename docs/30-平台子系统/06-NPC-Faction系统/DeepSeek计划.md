# NPC / Faction 系统 DeepSeek 计划初版

## 执行定位

NPC / Faction 的第一批实现不做完整势力模拟，而是加固现有“剧本 NPC 资产 -> AI 上下文 -> 防剧透投影 -> 地图展示 -> 遭遇临时参与者”的链路。

DeepSeek 执行前必须查看当前代码：

- `src/server/ai/ai_kp.py`
- `src/server/scenario/quality.py`
- `src/server/agent/tools.py`
- `src/server/ai/spoiler_control.py`
- `src/server/engine/spoiler_guard.py`
- `src/server/ai/rag.py`
- `src/server/rag_router.py`
- `src/server/map_persistence.py`
- `src/server/router_map.py`
- `src/server/encounter_persistence.py`
- `src/server/host/router_host.py`
- `src/client/src/components/HostMapPanel.tsx`
- `src/client/src/components/EncounterPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`

当前阶段说明：

- 本计划对应的是`P0 主链路 + NPC 可见性风险识别版`的执行包，不是 NPC/Faction 的最终生产安全完成版。
- 当前文档已识别 `npc_id` 稳定标识、字段级 visibility、RAG entitlement、地图 DTO、隐藏 NPC reveal、临时 NPC 命名持久化、Faction 范围控制等关键问题。
- 文档完成不等于风险关闭；只有相关批次实现并通过测试后，这些风险才算真正关闭。

## 全局约束

- 先运行 `git status --short`，确认只改本批相关文件。
- 不新增完整 `npcs` / `factions` / `faction_clocks` 大系统，除非后续 WorldBook / Timeline / State 文档明确承接。
- 不让玩家读取完整 `knowledge_graph.npcs`。
- 不让 AI 直接把 NPC、秘密或势力行动写成世界事实。
- 不把遭遇临时 NPC 当成长期 NPC 档案。
- 不只依赖 `is_hidden`；至少补上字段级 visibility 方向或统一 DTO 过滤口径。
- 不再让 reveal、RAG metadata、地图引用只靠 `npcName`；后续优先使用 `npcId`。
- `room_id IS NULL` 不等于所有房间可读；NPC RAG 仍必须经过 scenario entitlement。
- 匿名或无 token 的地图接口不允许返回 `npcsPresent/cluesAvailable/完整描述`。
- 前端改动必须同步处理当前中文乱码文案。

## Batch NPC-0：现状审计与测试缺口清单

| 项 | 内容 |
|---|---|
| 目标 | 建立 NPC/Faction 当前实现清单，确认剧本资产、RAG、防剧透、地图、遭遇、测试覆盖 |
| 允许改的文件方向 | 文档、测试清单；不改业务逻辑 |
| 建议检查 | `rg -n "npcs|npc_id|npcs_present|npcsPresent|hidden_npc|query_npcs|source_type = 'npc'|npc:\\{" src tests` |
| 验收命令 | `python -m pytest tests/server/test_quality.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py -q` |
| 禁止事项 | 不在审计批次里新建 NPC/Faction 主表 |

产出要求：

- 明确当前没有独立 NPC/Faction 主表。
- 明确剧本 NPC、场景 NPC、地图 NPC、RAG NPC、隐藏 NPC、遭遇临时 NPC 的不同含义。
- 产出 NPC 数据分层清单和敏感字段清单：`public_name/name/true_name/aliases/role/type/public_description/description/personality/motivation/secret_goal/faction_refs/scene_refs/clue_refs/is_hidden`。
- 列出缺失测试：地图 DTO / 匿名地图、NPC reveal、遭遇临时 NPC、RAG entitlement。

## Batch NPC-1：剧本 NPC schema、稳定 npc_id 与质量报告

| 项 | 内容 |
|---|---|
| 目标 | 稳定 `knowledge_graph.npcs[]` 字段，让导入结果能支撑 AI、RAG、防剧透和后续 reveal |
| 允许改的文件方向 | `src/server/ai/ai_kp.py`、`src/server/scenario/quality.py`、`src/server/ai/spoiler_control.py`、`tests/server/test_ai_kp.py`、`tests/server/test_quality.py`、`tests/server/test_spoiler.py` |
| 验收命令 | `python -m pytest tests/server/test_ai_kp.py tests/server/test_quality.py tests/server/test_spoiler.py -q` |
| 禁止事项 | 不把字段缺失静默当作“完整 NPC 档案”；不在此批创建运行态 NPC 表 |

验收点：

- 结构化结果兼容旧字段，并尽量稳定到 `npc_id/public_name/name/role/type/public_description/description/personality/motivation/is_hidden`。
- AI 未提供 `npc_id` 时，系统可生成稳定 ID。
- 质量报告不只检查“有没有 NPC”，还要对关键字段缺失发出 warning。
- 隐藏 NPC 缺少 `public_description` 时给出质量警告。

## Batch NPC-2：AI 查询 NPC 与 RAG entitlement

| 项 | 内容 |
|---|---|
| 目标 | 让 AI 查询和 RAG 索引都围绕稳定 `npc_id` 与 entitlement 工作 |
| 允许改的文件方向 | `src/server/agent/tools.py`、`src/server/ai/rag.py`、`src/server/rag_router.py`、`src/server/ai/spoiler_control.py`、`tests/server/test_rag.py`、`tests/server/test_rag_search.py`、`tests/server/test_rag_security.py`、`tests/server/test_rag_router.py` |
| 验收命令 | `python -m pytest tests/server/test_rag.py tests/server/test_rag_search.py tests/server/test_rag_security.py tests/server/test_rag_router.py -q` |
| 禁止事项 | 不把 `room_id IS NULL` 的所有 NPC chunk 暴露给任意房间；不让 player-facing AI 读取 truth 层 NPC 字段 |

验收点：

- `query_npcs` 不再只靠 `name` 匹配；至少兼容 `npc_id` 优先。
- `source_type='npc'` 的 metadata 至少预留 `npc_id/npc_name/scenario_id/visibility/is_hidden` 方向。
- 同 scenario 房间可以检索 scenario-scoped NPC，不同 scenario 不能串。
- player-facing RAG 不能直接读 hidden/truth 字段。

## Batch NPC-3：隐藏 NPC 防剧透与 reveal 事件

| 项 | 内容 |
|---|---|
| 目标 | 强化隐藏 NPC 的敏感索引、输出拦截和 reveal 契约 |
| 允许改的文件方向 | `src/server/engine/spoiler_guard.py`、`src/server/events/`、`src/server/engine/projection.py`、`tests/server/test_spoiler_guard.py`、`tests/server/test_spoiler.py` |
| 验收命令 | `python -m pytest tests/server/test_spoiler_guard.py tests/server/test_spoiler.py -q` |
| 禁止事项 | 不让 hidden NPC 通过 party/player 投影绕过 SpoilerGuard；不再只依赖 `npcName` 解锁 |

验收点：

- `is_hidden=true` NPC 的 name、别名、角色描述可进入敏感索引。
- public / party 输出命中隐藏 NPC 时会被拦截或改写。
- 解锁优先使用 `npcId`，`npcName` 只作兼容辅助。
- 至少区分 `appearance_revealed / identity_revealed / secret_revealed` 三层 reveal 语义。

## Batch NPC-4：地图 DTO 与玩家/匿名防泄露

| 项 | 内容 |
|---|---|
| 目标 | 让地图接口按 DTO 分层，避免匿名和玩家接口泄露 NPC/线索 |
| 允许改的文件方向 | `src/server/map_persistence.py`、`src/server/router_map.py`、`src/server/ai/spoiler_control.py`、`src/client/src/components/HostMapPanel.tsx`、`src/client/src/pages/PlayerActionPage.tsx`、可新增 `tests/server/test_map_visibility.py` |
| 验收命令 | `python -m pytest tests/server/test_spoiler.py tests/server/test_host.py tests/server/test_map_visibility.py -q`；前端改动补跑 `cd src/client && npm run build` |
| 禁止事项 | 不向无 token 请求返回完整节点 NPC/线索；不把隐藏 NPC 真名直接放进玩家节点详情 |

验收点：

- 匿名地图视图走 `MapNodePublicDTO` 或等价结构。
- 玩家已探索节点走 `MapNodePlayerDTO`，只给授权 NPC 摘要。
- Host 视图走 `MapNodeHostDTO`，可看完整节点。
- 地图里“节点有 NPC”不等于“玩家已知道 NPC 身份”。

## Batch NPC-5：遭遇临时 NPC 稳定化

| 项 | 内容 |
|---|---|
| 目标 | 补齐 Host 遭遇 NPC 的名称持久化、DTO 稳定性和后端测试 |
| 允许改的文件方向 | `src/server/encounter_persistence.py`、`src/server/host/router_host.py`、`src/server/models.py`、`src/server/db_adapter.py`、`src/client/src/components/EncounterPanel.tsx`、可新增 `tests/server/test_encounters.py` |
| 验收命令 | `python -m pytest tests/server/test_host.py tests/server/test_host_room_lifecycle.py tests/server/test_encounters.py -q`；前端改动补跑 `cd src/client && npm run build` |
| 禁止事项 | 不把 `npc:{uuid}` 写入 `characters`；不把临时敌人升级成长期 NPC 档案 |

验收点：

- Host confirm / reject / next-round / resolve / create npc 都有测试。
- 临时 NPC 至少稳定到 `participantId/displayName/source/sourceNpcId/hp/dex/mov/mainSkill`。
- 创建后后续查询和广播仍能读到名称，不只是在创建响应里返回一次。
- resolve 后只保留日志，不升级长期 NPC。

## Batch NPC-6：玩家已知 NPC 列表最小版

| 项 | 内容 |
|---|---|
| 目标 | 提供玩家可见 NPC 摘要 DTO，来源于公开事件、探索结果和已发现线索 |
| 允许改的文件方向 | `src/server/player/`、`src/server/events/`、`src/server/engine/`、`src/client/src/pages/PlayerActionPage.tsx`、对应测试 |
| 验收命令 | `python -m pytest tests/server/test_player_features.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py -q` |
| 禁止事项 | 不直接返回完整 `knowledge_graph.npcs`；不把 Host-only truth 字段传给玩家 |

验收点：

- 玩家已知 NPC 列表来自投影或 reveal 结果，不直接扫描 `knowledge_graph.npcs`。
- 隐藏 NPC 未公开前不出现在列表。
- 同名 NPC 不会因为 `npcName` 文本误解锁另一个 NPC。

## Batch NPC-7：Faction 轻量模型评审

| 项 | 内容 |
|---|---|
| 目标 | 只输出势力最小模型设计，等待 WorldBook / Timeline 模块确认后再实现 |
| 允许改的文件方向 | docs 文档，必要时新增设计草案 |
| 验收命令 | 文档检查命令即可 |
| 禁止事项 | 不在本批创建 faction clock、资源经济系统或复杂社会模拟 |

建议最小模型：

- `faction_id`
- `name`
- `public_description`
- `secret_goal`
- `known_members`
- `relationship_edges`

边界要求：

- 06 只定义 NPC 与 Faction 的引用关系。
- `faction_clock` 由 `10-Timeline` 或 `13-State/14-Transaction` 承接。
- faction lore 由 `07-WorldBook` 承接。
- faction 事件由 `11-Journal` 记录。

## Batch NPC-8：端到端回归

| 项 | 内容 |
|---|---|
| 目标 | 验证 NPC 从导入到 AI、投影、防剧透、地图、遭遇的主链路 |
| 后端命令 | `python -m pytest tests/server/test_ai_kp.py tests/server/test_quality.py tests/server/test_spoiler.py tests/server/test_spoiler_guard.py tests/server/test_rag.py tests/server/test_rag_search.py tests/server/test_rag_security.py tests/server/test_rag_router.py tests/server/test_host.py tests/server/test_host_room_lifecycle.py -q` |
| 前端命令 | `cd src/client && npm run build` |
| 禁止事项 | 不在回归批次扩大范围做新功能 |

手动验收链路：

1. Admin 导入一个含公开 NPC 和隐藏 NPC 的剧本。
2. 质量报告显示 NPC 数量和字段问题。
3. Host 创建房间并开局。
4. 玩家探索公开场景，只看到授权 NPC 摘要。
5. 玩家询问 NPC，AI 输出不泄露隐藏身份。
6. Host 公开某 NPC 后，玩家侧可见摘要更新。
7. 玩家匿名访问地图时看不到 NPC/线索明细。
8. Host 快速创建临时 NPC 进入遭遇并推进一轮。
9. 遭遇结束后日志可查，临时 NPC 没有写入 `characters` 或长期 NPC 档案。
