# 防剧透输出拦截机制计划

## Summary
- AI KP 可以读取完整“当前剧本私有 RAG”，但所有 AI 输出在投影给 Host/Player 前必须经过 `SpoilerGuard`。
- 第一版采用“结构化敏感表 + RAG 引用证据 + 事件解锁”判定，不用 AI 二次审稿。
- 发现公开输出疑似剧透时：拦截、不发送、带违规原因让 AI 重试一次；仍违规则发送安全模板叙事。
- 被拦截原文、命中项、引用和重试结果仅 Admin 可见；Host/Player 只看到安全输出。

## API / Interfaces
- 新增类型：
  - `SpoilerSensitiveItem`：来自剧本真相、结局、隐藏线索、隐藏 NPC、隐藏素材，含 `itemId/category/label/aliases/sourceRef/defaultAudience`。
  - `SpoilerReviewResult`：`allowed`、`violations[]`、`redactedReason`、`retryPrompt`、`safeFallbackText`。
  - `SpoilerUnlockState`：当前房间已通过事件解锁的线索、NPC、场景、结局阶段、公开事实。
- 新增 Admin 接口：
  - `GET /api/admin/rooms/{room_id}/spoiler-audits`：查看拦截日志。
  - `POST /api/admin/scenarios/{scenario_id}/spoiler-index/rebuild`：从剧本结构化数据和素材 metadata 重建敏感项索引。
- 扩展 AI 调用日志：记录 `spoiler_review_status`、命中敏感项、重试次数、最终是否 fallback。

## Key Changes
- **敏感项索引**
  - 剧本导入/重建时，从 `knowledge_graph`、`scenario_assets`、素材 metadata 中提取敏感项：幕后真相、结局、隐藏线索、隐藏 NPC、未公开地图节点、关键图片/BGM/附件。
  - 每个敏感项生成别名列表，例如 NPC 真名、称号、物品名、场景名、结局关键词。
  - 结构化缺失时按保守策略处理：无法确认公开状态的真相/结局/隐藏项默认不可公开。
- **事件解锁**
  - `SpoilerGuard` 只允许输出已解锁内容；解锁来源包括线索获得/分享、场景进入、NPC 公开出现、地图节点探索、结局阶段开始等权威事件。
  - 解锁状态从事件日志和权威表计算，可缓存到 `host_states`，但事件日志是最终依据。
- **输出通道拦截**
  - 检查所有 AI 投影通道：公开叙事、私密通知、战术按钮、线索释放、状态建议、场景转场、素材播放/展示建议。
  - 公开通道不得包含未解锁敏感项；私密通道只能给已授权玩家；素材建议不能提前暴露隐藏地图、最终 BGM、关键证据图片。
  - 违规时不发送半成品投影，也不写玩家可见事件。
- **重试与兜底**
  - 第一次违规：构造 retry prompt，明确列出“不要公开的类别/引用”，让 AI 重写一次。
  - 第二次仍违规：使用安全模板，例如“空气中的线索仍然模糊，调查需要更具体的行动推进。”并记录 Admin 审计。
  - Local/template fallback 也要过 `SpoilerGuard`，避免非 AI 路径漏剧透。
- **Admin 审计**
  - Admin 可看完整原始输出、违规项、来源引用、最终输出、是否重试/兜底。
  - Host/Player 不显示违规原文；最多收到安全兜底文本。

## Test Plan
- 单测：未解锁真相、结局、隐藏线索、隐藏 NPC、隐藏素材出现在公开叙事时被拦截。
- 单测：已通过事件解锁的线索/NPC 可以公开；未授权玩家的私密线索不能发给其他玩家。
- 集成：AI 第一次输出剧透，重试后合规则正常投影；重试仍违规则模板兜底。
- RAG 联动：AI 使用了完整剧本引用，但公开输出不得泄露未解锁引用内容。
- 审计：Admin 能查到拦截原文和违规原因；Host/Player 查不到原文。

## Assumptions
- 本轮不做 AI 二次审稿；后续可在模糊案例中追加 AI reviewer。
- 房主默认不可查看完整剧本防剧透审计，因为房主可能同时参团。
- 防剧透是输出守门，不改变 Engine 权威状态写入规则。
- 这版先做文本、按钮、素材 metadata 拦截，不做图片/音频内容识别。
