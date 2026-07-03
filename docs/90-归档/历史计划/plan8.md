# Host 资料库 / RAG 跑团查询台计划

## Summary
- 把现有 `/rag-test` 的规则书测试能力升级为 HostStage 的“资料库”tab，成为跑团现场可用的 KP 查询台。
- v1 查询范围：规则书、当前剧本、NPC/线索结构、玩家角色卡。
- Host 支持双视角查询：`主持全知` 可看真相/隐藏线索；`玩家可见` 只按当前房间公开信息回答。
- 回答形式为“AI 摘要 + 来源片段”：先给简明结论，再列命中的规则/剧本/角色来源，避免纯 AI 胡编。
- 本轮只做轻量管理：刷新/重建当前房间相关索引；完整上传和资产管理仍归 Admin。

## Key Changes
- 新增 Host 查询层：
  - 新增 `POST /api/host/{room_id}/knowledge/query`。
  - 输入：`query`、`mode=keeper/player_visible`、`sourceTypes`、`topK`。
  - 输出：`answer`、`citations`、`sourceBreakdown`、`mode`、`usedFallback`。
  - `citations` 必须包含来源类型、标题/名称、chunk 内容、相似度、metadata。

- RAG 视角与权限：
  - `keeper` 模式可查当前剧本 raw_text、knowledge_graph、NPC、规则书、角色卡。
  - `player_visible` 模式只查已公开线索、公共事件、玩家已知场景摘要和必要规则；隐藏真相不进入 prompt。
  - 规则书默认对两种模式都可见。
  - 角色卡默认 Host 可见；后续若要玩家互查，再单独设计权限。

- AI 摘要生成：
  - 有 DeepSeek key 时，用命中片段生成结构化中文答案。
  - 无 AI 或 AI 失败时，返回模板摘要：按来源分组列出最相关片段，并标记 `usedFallback=true`。
  - Prompt 明确要求：只能依据 citations 回答；不知道就说不知道；剧透内容必须标注“主持信息”。
  - 答案不写入权威游戏状态，只作为 Host 辅助查询。

- 索引与重建：
  - 复用现有 `document_chunks`、`rule_documents`、`RAGStore.index_*`。
  - 补充当前房间索引重建入口：`POST /api/host/{room_id}/knowledge/reindex`。
  - 重建内容包括：当前剧本正文、NPC 图谱、房间角色卡；规则书索引不在 Host 页上传，只显示状态。
  - 修正现有 RAG 测试页和资料库 UI 的乱码文案，至少保证 HostStage 资料库全中文可读。

- 前端 HostStage：
  - 替换 `database` tab 骨架为真实资料库面板。
  - UI 包含：查询框、视角切换、来源筛选、重建索引按钮、答案区、引用片段列表。
  - 来源筛选默认勾选：规则、剧本、NPC、角色。
  - 查询结果用 Bauhaus 风格卡片展示：答案在上，引用在下，引用可展开查看原文片段。
  - 保留 `/rag-test` 作为开发测试页，但不作为主流程入口。

## API / Interfaces
- `POST /api/host/{room_id}/knowledge/query`
  - Request: `{ query, mode, sourceTypes, topK }`
  - Response: `{ answer, citations, sourceBreakdown, mode, usedFallback }`

- `POST /api/host/{room_id}/knowledge/reindex`
  - Response: `{ scenarioChunks, npcChunks, characterChunks, ruleDocs, status }`

- Citation shape:
  - `sourceType`
  - `sourceId`
  - `title`
  - `content`
  - `similarity`
  - `metadata`

## Test Plan
- 后端：
  - 查询规则书能返回 rule citations。
  - 查询当前剧本能返回 scenario/npc citations。
  - 查询玩家角色能返回 character citations。
  - `keeper` 模式可返回隐藏真相片段；`player_visible` 模式不会返回隐藏真相。
  - DeepSeek 失败时返回 fallback 摘要和 citations。
  - reindex 当前房间能重建 scenario/npc/character chunks。
  - 无 RAG 服务时返回明确 503，不让 HostStage 崩溃。

- 前端：
  - `npm run build` 通过。
  - HostStage 资料库 tab 可查询、切换视角、筛选来源、展开引用。
  - 无结果、加载中、错误、RAG 不可用都有可读状态。
  - `/rag-test` 仍可访问，且不影响 Host 主流程。

## Assumptions
- 本轮不做规则书上传管理；规则书导入仍通过现有 RAG/Admin/脚本流程。
- 本轮不把事件日志纳入默认查询，避免资料库噪声过高。
- 资料库答案是辅助信息，不作为游戏状态写入依据。
- 玩家端暂不开放完整资料库查询。
