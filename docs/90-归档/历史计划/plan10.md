# 日志回放、检查点与战役导出计划

## Summary
- 把已有后端归档能力接成可用产品：Host 看全量审计与公共重播，Player 看“自己 + 公共”的个人档案。
- 检查点支持手动创建 + 关键节点自动创建；恢复需要 Admin 或房主二次确认。
- 回放 v1 做“时间线 + 片段重播”，不做完整录像式舞台重演。
- 导出支持 Markdown + JSON：Markdown 给人读，JSON 给调试和后续工具用。
- 本轮顺手修复乱码文案、权限过滤、检查点覆盖范围不足的问题。

## Key Changes
- Host 归档页：
  - HostStage 的“日志”tab 接真实数据，替换静态骨架。
  - 显示完整时间线：玩家行动、AI叙事、骰子、状态变化、线索、地图、遭遇、系统事件。
  - 支持筛选：事件类型、玩家/角色、关键词、时间/sequence 范围。
  - 支持点击某条公共叙事/骰子/状态变化进行“片段重播”，只在 Host 前端回放，不重新写状态。
  - 增加检查点面板：手动创建、查看自动/手动标记、恢复前二次确认。

- Player 个人档案：
  - Player 的“日志”tab 接 `/api/player/archive`，展示公共叙事 + 自己行动 + 自己检定 + 自己私密线索 + 自己状态变化。
  - 不展示其他玩家私密线索、私密检定、个人状态 patch。
  - 支持按“剧情 / 行动 / 检定 / 线索 / 状态”过滤。
  - 保留当前本地即时消息，但刷新后以服务端档案为准。

- 检查点策略：
  - 手动检查点：Host/房主/Admin 可创建，可填写备注。
  - 自动检查点：开局、每轮结算完成、遭遇开始/结束、地图场景切换、战役结束前自动创建。
  - 自动检查点默认每房间保留最近 20 个；手动检查点不自动清理。
  - 快照覆盖当前核心表：rooms、characters、actions、events、clues、inventory、objectives、room_turns、map state、encounters、host_states、room_ai_config。
  - 恢复后写入 `s2c_checkpoint_restored` 事件，并主动推送 Host/Player snapshot，避免前端还停在旧状态。

- 权限与审计：
  - `/api/rooms/{room_id}/events`、checkpoint、restore、export 等 Host 级接口必须校验 owner token、admin account 或房主权限。
  - `/api/rooms/{room_id}/events/public` 只返回公共可见事件，不泄露 host/private/player 单播内容。
  - 所有 restore/export 操作写审计事件，记录操作者、checkpoint_id、原因。
  - 不把完整 player_token 暴露到前端导出；JSON 调试导出中 token 默认脱敏。

- 导出：
  - `GET /api/rooms/{room_id}/export?format=markdown|json&scope=public|full`
  - public Markdown：剧情摘要、关键事件、骰子、线索公开记录、结局。
  - full JSON：完整审计数据，限 Admin/房主使用，敏感字段脱敏。
  - 战役结束后可生成最终 Markdown 战报，复用已有 `campaign_archives` 摘要。

## API / Interfaces
- Host/Admin：
  - `GET /api/rooms/{room_id}/timeline`
  - `GET /api/rooms/{room_id}/timeline/{sequence}`
  - `POST /api/rooms/{room_id}/checkpoint`
  - `GET /api/rooms/{room_id}/checkpoints`
  - `POST /api/rooms/{room_id}/restore/{checkpoint_id}`
  - `GET /api/rooms/{room_id}/export`

- Player：
  - `GET /api/player/archive`
  - `GET /api/player/archive/actions`
  - `GET /api/player/archive/clues`
  - `GET /api/player/archive/skill-checks`

- 新增事件：
  - `s2c_checkpoint_created`
  - `s2c_checkpoint_restored`
  - `s2c_replay_marker`

## Test Plan
- 后端：
  - Host timeline 返回全量审计，Player archive 只返回自己 + 公共。
  - public events 不泄露 player/private/host-only payload。
  - 手动检查点创建成功，自动检查点在关键节点创建。
  - 自动检查点只保留最近 20 个，手动检查点不被清理。
  - restore 能恢复角色、行动、事件、线索、背包、地图、遭遇、回合状态。
  - restore 后写审计事件并推送 snapshot。
  - Markdown 和 JSON 导出权限正确，JSON 默认脱敏 token。

- 前端：
  - `npm run build` 通过。
  - Host 日志 tab 可筛选、搜索、查看详情、片段重播。
  - Host 检查点面板可创建、查看、二次确认恢复。
  - Player 日志 tab 刷新后仍能看到历史记录。
  - 无事件、加载中、权限失败、恢复失败都有可读状态。

## Assumptions
- 本轮不做完整“录像式全舞台重演”，只做时间线和片段重播。
- JSON 导出面向调试，不作为公开分享格式。
- 检查点恢复是房间级操作，不支持只恢复单个角色。
- 如果 DeepSeek 正在改地图/遭遇表，检查点实现要把这些新表纳入快照白名单。
