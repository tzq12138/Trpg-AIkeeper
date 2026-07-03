# AI 主持场景回合闭环计划

## Summary
- 跑团进入 `active` 后改为“场景回合制”：每个在场角色每轮提交 1 个行动，全员提交后自动进入 AI 统一结算。
- AI 默认自动推送结果，不需要 Host 审核；Host 只保留暂停、跳过缺席玩家、重试本轮、手动兜底结算。
- 状态修改走受限规则管线：规则执行器和剧本触发器可产生 HP/SAN/物品/线索 patch；AI 负责叙事、补充说明和战术提示，不直接随意改状态。
- AI Provider v1 以 DeepSeek 为主；预留 MCP stdio Provider 接口，但 Hermes-agent 尚未 ready，本轮不把主链路押在 MCP 上。
- DeepSeek 不可用时，继续用规则结果 + 中文模板叙事降级，保证跑团不中断。

## Key Changes
- 新增场景回合模型：
  - 新增 `room_turns` 表：`turn_id`、`room_id`、`turn_index`、`status=collecting/resolving/resolved/blocked`、开始/结束/结算时间、摘要。
  - `actions` 增加 `turn_id`；兼容填充现有 `batch_id=turn_id`，避免旧查询失效。
  - 房间开始时创建第 1 轮；每轮结算完成后自动创建下一轮。
  - 同一角色同一回合只能提交一次行动；v1 提交后不可修改，避免状态竞态。

- 玩家行动入口调整：
  - `/api/player/intent` 在 active 房间内不再立即单行动后台结算，而是写入当前 `collecting` 回合并返回 `202 accepted/queued`。
  - 玩家提交后前端进入“本轮已提交，等待其他玩家”状态，直到收到新回合事件才重新开放输入。
  - 如果行动描述不清，AI/规则层可发 `s2c_clarification_prompt` 给该玩家；玩家补充后继续参与当前回合。
  - 后验物品主张仍按现有快速判定逻辑，可同步返回 `403/409/429`，成功后也进入事件投影。

- 自动结算规则：
  - 当前回合所有 `joined/ready/active` 角色都有行动后，后台自动触发 `resolve_turn`。
  - Host 可对未提交角色点“本轮跳过”；系统为该角色生成一条“保持观察/待机”的系统行动，用来满足全员提交条件。
  - 结算时先逐条跑现有四阶段规则管线，收集 `ResolutionResult`；再把整轮结果交给叙事 Provider 生成统一场景叙事。
  - 任何单个行动规则异常只拒绝该行动并写明原因，不让整轮卡死；严重 Provider 失败才进入模板降级。

- 事件投影与可见性：
  - 新增/固化事件：`s2c_turn_opened`、`s2c_turn_snapshot`、`s2c_turn_resolving`、`s2c_turn_resolved`、`s2c_private_notice`。
  - 公共主叙事发给全员和 Host；个人检定结果、私密线索、伤害细节可单独发给对应玩家；Host 永远收到完整审计。
  - 每个行动仍发送 `s2c_action_completed`，保证玩家端技能检定和状态刷新不丢。
  - 事件写库后再推 WS，继续使用正确 `roomSequence`。

- AI Provider 层：
  - 新增 `NarrativeProvider` 接口，输入为整轮上下文：房间、剧本、RAG 摘要、角色状态、行动列表、规则结果、可见性要求。
  - `DeepSeekNarrativeProvider` 为 v1 主实现；有 `DEEPSEEK_API_KEY` 时启用。
  - `TemplateNarrativeProvider` 为默认降级；输出可读中文叙事、行动摘要、必要的公共观察。
  - 预留 `McpStdioNarrativeProvider` 配置和接口边界，但本轮只做不可用时自动 fallback，不要求 Hermes-agent 真连接。
  - 清理本次触达文件里的乱码中文 fallback 文案，至少保证 Host/Player/AI 降级输出可读。

- Host 与 Player UI：
  - HostStage 增加当前回合面板：轮次、AI 状态、已提交/未提交玩家、跳过按钮、重试本轮、手动结算遗留 queued actions。
  - 玩家行动页提交后显示“等待其他调查员行动”；收到公共叙事、私密通知、行动完成后更新日志和角色状态。
  - Host 的“手动触发 AI 回合”保留为兜底：优先结算当前已满足条件的回合；其次处理旧的无 `turn_id` queued actions。

## API / Interfaces
- 新增 `GET /api/rooms/{room_id}/turns/current`：返回当前回合、参与角色、提交状态、AI 状态。
- 新增 `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character`：Host 跳过某个未提交角色。
- 新增 `POST /api/rooms/{room_id}/turns/{turn_id}/retry`：Host 重试失败或 blocked 的本轮结算。
- 扩展 `/api/rooms/{room_id}/ai-status`：返回 provider、fallback 状态、当前 turn 状态、连续失败次数。
- `/api/player/intent` 返回增加 `turnId`、`turnIndex`、`waitingFor`，便于前端展示等待状态。

## Test Plan
- 后端：
  - 房间 start 后自动创建第 1 个 `room_turn`。
  - 玩家提交行动只入当前回合，不立即单行动完成。
  - 全员提交后自动结算本轮，并创建下一轮。
  - Host 跳过缺席角色后可触发自动结算。
  - 单个行动异常只拒绝该行动，其他行动仍完成。
  - DeepSeek Provider 失败时降级到模板叙事，回合状态仍为 resolved。
  - 私密事件只推给目标玩家，公共观察推给全员，Host 收到完整审计。
  - legacy 无 `turn_id` queued actions 仍可由手动 AI 回合处理。

- 前端：
  - `npm run build` 通过。
  - 手动验证：Host 开局后看到第 1 轮；玩家提交后被锁定等待；全员提交后自动出叙事；新一轮打开后玩家可继续提交。
  - 手动验证：Host 跳过未提交玩家后能结算。
  - 手动验证：DeepSeek 未配置时仍能看到中文模板叙事，不出现乱码或永久等待。

## Assumptions
- 本轮不做战斗/追逐专用规则回合，只做通用“场景回合”。
- 本轮不要求 Hermes-agent/MCP 真正跑通，只预留 MCP stdio Provider 边界和配置位。
- AI 不直接写任意数据库状态；所有权威状态变化必须来自规则执行器、剧本触发器或已有受限服务。
- Host 默认不审核 AI 输出，但可以暂停、跳过、重试和查看完整审计。
