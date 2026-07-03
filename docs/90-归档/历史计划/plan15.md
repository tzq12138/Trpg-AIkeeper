# AI Gateway 收束与后台可配置计划

## Summary
- 这版目标不是“再加一个 AI 功能”，而是把现有 AI 调用收束到统一 `AiGateway`。
- Provider 默认顺序改为 `mcp,deepseek,local`：优先实验 Hermes MCP，失败自动走 DeepSeek，再失败走本地 fallback。
- AI 权限模型保持“建议型为主”：AI 只给结构化建议、叙事、检定建议、地图建议、知识回答；权威状态仍由 Engine / 规则层校验写入。
- 后台增加 AI 管理能力：配置 provider 顺序、健康检查、调用日志、debug 日志开关和知识问答测试。
- 默认测试按你的要求必须跑真实链路；缺 Hermes/DeepSeek/key 时测试失败并明确提示。

## API / Interfaces
- 调整 `AiGateway` 契约：不再强制所有任务都塞进 `KpResponse`，改为按任务类型校验结果：
  - `structure_scenario` → 剧本结构化 JSON。
  - `compile_mechanic` → `MechanicCompileResult`。
  - `generate_narrative` → 叙事文本或 `NarrativePayload`。
  - `generate_map` → `{ nodes, edges, generatedBy }`。
  - `query_knowledge` → `KnowledgeAnswer`。
- 保留并强化现有接口：
  - `GET/PATCH /api/admin/ai/config`
  - `POST /api/admin/ai/health-check`
  - `GET/PATCH /api/rooms/{room_id}/ai-config`
- 新增后台接口：
  - `GET /api/admin/ai/logs`：按 room、task、provider、status 查询调用日志。
  - `POST /api/admin/ai/query`：后台测试知识问答，走 Gateway + RAG/Hermes/DeepSeek。
  - 可选 `GET /api/admin/ai/debug-logs`：仅 `AI_DEBUG_LOG=true` 时可用。

## Key Changes
- **Gateway 收束**
  - 剧本 PDF 导入结构化改走 `AiGateway.structure_scenario()`，失败时自动 local fallback。
  - 机制编译改走 `AiGateway.compile_mechanic()`，本地关键词编译作为 fallback，不再散落直连 DeepSeek。
  - 回合叙事改走 `AiGateway.generate_narrative()`，所有 provider 失败时使用模板叙事继续推进。
  - 地图生成改走 `AiGateway.generate_map()`，Hermes/DeepSeek 失败后使用 Python 地图生成。
  - 知识问答改走 `AiGateway.query_knowledge()`，优先 Hermes，失败走 DeepSeek/local，并返回 citations/confidence。
- **Provider 策略**
  - 默认 `AI_PROVIDER_ORDER=mcp,deepseek,local`。
  - Hermes 不可用不能卡死游戏流程；Gateway 记录 fallback 链并继续。
  - DeepSeek key 只从环境变量读取，不写入配置表、日志或前端。
- **后台 AI 面板**
  - Admin 新增“AI 设置”页：显示 provider 顺序、Hermes URL、DeepSeek 是否配置、健康检查结果。
  - 可调整全局 provider 顺序和超时时间；房间详情里可覆盖房间级 AI 配置。
  - 显示调用日志：任务类型、provider、耗时、状态、fallback 链、响应摘要、错误摘要。
  - 提供一个知识问答测试框，用来验证规则书/剧本/RAG/Hermes 是否真的可用。
- **日志与调试**
  - 默认记录摘要日志：task、room、provider、duration、status、fallback_chain、response_summary、error_message。
  - `AI_DEBUG_LOG=true` 时记录完整 prompt/response 到独立 debug 表，并标注开发用途。
  - 不记录 API key；debug 日志提供清理策略或最多保留最近 N 条。
- **失败体验**
  - 所有 provider 失败时自动 local/template fallback。
  - Player/Host 收到正常完成回执和安全兜底叙事，不展示原始异常。
  - Admin AI 日志标红失败链路，便于回头排查。

## Test Plan
- 默认后端测试必须验证真实 AI 链路：
  - 测试启动前检查 `DEEPSEEK_API_KEY`、`KP_MCP_SERVER_URL`、Hermes health、PostgreSQL/pgvector。
  - 任一真实依赖不可用时测试失败，并输出缺失项。
- 单测/集成覆盖：
  - Gateway provider 顺序为 `mcp -> deepseek -> local`。
  - Hermes 失败时自动 fallback DeepSeek；DeepSeek 失败时 fallback local。
  - 五个核心任务分别通过真实链路返回可解析结构。
  - AI 输出不能直接写 HP/SAN/物品/线索，必须走 Engine 校验。
  - AI 调用日志写入成功，debug 模式下写完整 prompt/response，默认不写。
- 前端验证：
  - Admin AI 设置页可查看健康状态、改 provider 顺序、查询日志。
  - 剧本导入、机制编译、回合叙事、地图生成、知识问答都能在真实 provider 下跑通。
  - 关闭 Hermes 后游戏仍能通过 DeepSeek 或 local fallback 继续。

## Assumptions
- 本轮不把 STT 和实验性 `GameAgent` 全量并入 Gateway，只保留后续接入边界。
- Hermes MCP 是优先实验 provider，但不可用时不阻塞游戏。
- 默认测试强依赖真实 AI 服务，会带来网络、费用和服务状态风险；这是本轮按你的选择作为验收标准。
- 不提交任何密钥；DeepSeek key、Hermes URL、debug 开关都用环境变量或后台配置保存非敏感项。
