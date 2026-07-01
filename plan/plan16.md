# RAG 知识脑：AI KP 上下文装配计划

## Summary
- 第一版目标：让 AI KP 在玩家行动/回合结算前，稳定拿到“规则、对应剧本、角色、事件记忆、线索、素材”的分层上下文。
- 规则书是全局公开 RAG；剧本是按 `scenario_id` 隔离的私有 RAG，只给 AI KP 和 Admin 查。
- AI KP 可以读取完整对应剧本；防剧透输出拦截后续单独设计，本版先保证检索与引用边界清楚。
- Admin 可预览 AI 本次将吃到的上下文和引用；Host/Player 不展示完整引用，避免剧透。

## API / Interfaces
- 新增 `RAGContext` 类型：包含 `rules`、`scenario`、`characters`、`events`、`clues`、`assets`、`citations`、`queryDebug`。
- 新增 `RAGContextBuilder`：输入 `room_id`、`scenario_id`、玩家行动文本、当前场景/角色信息，输出分层上下文包。
- 新增 Admin 接口：
  - `POST /api/admin/rag/context-preview`：预览某房间/某行动会装配哪些上下文。
  - `GET /api/admin/rag/stats`：按 source type、scenario、room 查看索引数量。
  - `POST /api/admin/rag/reindex`：重建规则、剧本、角色、事件、线索、素材索引。
- 扩展检索：增加混合检索，支持 `scenario_id`、`room_id`、`source_types`、metadata filter、来源配额。

## Key Changes
- 修正当前检索范围问题：带 `room_id` 查询时，也能同时包含全局规则、当前 `scenario_id` 剧本、当前房间记忆，而不是只查 `room_id` 命中的块。
- 自动入库：
  - 规则书：全局 `rule` 索引，所有房间可用于 AI 规则判断。
  - 剧本：PDF 导入后自动索引完整剧本文本、结构化场景、NPC、线索、结局条件，按 `scenario_id` 私有隔离。
  - 角色：玩家选卡/导入车卡后自动索引职业、背景、技能、人物描述。
  - 事件：公共叙事、玩家行动、检定结果、状态变化进入房间记忆索引。
  - 线索：线索获得/分享时入库，保留私密/公开 metadata。
  - 素材：地图、图片、BGM、PDF 附件按文件名、类型、场景绑定、标签、人工描述入库，不做多模态识别。
- 上下文装配优先级：当前场景/剧本片段优先，其次规则、角色、事件记忆、线索、素材。
- AI 主链接入：玩家行动和回合结算前调用 `RAGContextBuilder`，把分层上下文交给 AiGateway/AI KP。
- Admin 调试：记录每次 AI 调用使用的 RAG citations，Admin 可看全量；Host/Player 不显示剧本引用。

## Test Plan
- RAG 单测：规则全局检索、剧本按 `scenario_id` 隔离、房间记忆按 `room_id` 隔离、素材 metadata 检索。
- 检索测试：同一 query 能同时命中当前剧本、全局规则、角色和近期事件；跨剧本不能泄露私有剧本块。
- 自动入库测试：PDF 导入、车卡加入、事件写入、线索创建、素材上传/描述更新后都有对应 chunk。
- 上下文测试：`RAGContextBuilder` 输出分层上下文、citations、来源配额，且场景优先。
- 联调验证：Admin context preview 能看到 AI 将读取的上下文；AI KP 主链实际携带 RAGContext 生成叙事/裁决建议。

## Assumptions
- 本轮不做图片识别、音频理解或 BGM 自动情绪分析，只索引素材 metadata、标签和人工描述。
- 防剧透拦截机制后续单独设计；本轮只保证查询权限和引用展示不泄露。
- 完整剧本 RAG 仅 AI KP 和 Admin 可查；房主默认不可查完整剧本，因为房主可能同时作为玩家参团。
- 混合检索优先使用现有 PostgreSQL/pgvector 表结构，必要时只做小幅字段/metadata 扩展，不引入新向量数据库。
