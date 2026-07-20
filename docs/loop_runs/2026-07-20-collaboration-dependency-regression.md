# 2026-07-20 协同行动依赖回归记录

## 本轮变更

- 协同行动草稿可由玩家明确选择必须先完成行动的同契约队友。
- 草稿修订保留协作契约的高风险、队伍可见和确认要求；不允许跨契约、指向自己、重复或循环依赖。
- 全员确认后，服务端才把角色依赖映射为行动 ID，并以依赖优先、契约邀请顺序为稳定次序建立批次。
- 战斗回合先尊重确认后的依赖，再以 DEX 作为可执行行动的稳定排序依据。
- 若前置行动被拒绝或超时，直接依赖项转入 `awaiting_host_exception`；不会自动跳过前置条件或写入替代状态，独立行动可继续处理。

## 自动化证据

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/server/test_collaboration_contracts.py tests/server/test_combat_round_planner.py tests/server/test_turn_manager.py tests/server/test_action_drafts_v2.py tests/server/test_action_state_machine_v2.py tests/server/test_resolution_pipeline.py -q` | 135 passed |
| `python -m pytest tests/server/test_collaboration_contracts.py tests/server/test_combat_round_planner.py -q` | 19 passed |
| `cd src/client && npm run test -- --run tests/player-action-composer.test.tsx` | 13 passed |
| `cd src/client && npm run test -- --run` | 45 files / 164 tests passed |
| `cd src/client && npm run build` | passed |

## 追加：依赖动作的第二阶段展示重排

- 前置公开动作成功写入 `resolved_public_facts` 后，只要锁定计划中存在尚未结算的**真实规则依赖**，运行时才调用现有 `resolve_combat_round` 供应商链。
- 重排上下文仅包含已验证的公开事实与剩余公开依赖动作；供应商输出仍受 `CombatRoundSuggestion` 校验，且只能更改这些剩余动作的展示簇与建议依赖。
- 已完成动作、私密动作、锁定顺序、规则绑定、骰子、状态补丁和目标均不在重排权限内；失败或不可用供应商保留原锁定计划。
- `presentation_replan_after_action_ids` 按实际执行顺序记录已触发的重排，防止同一前置事实重复调用供应商。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/server/test_collaboration_contracts.py tests/server/test_combat_round_planner.py tests/server/test_turn_manager.py tests/server/test_narrator_runtime.py tests/server/test_host.py tests/server/test_action_drafts_v2.py tests/server/test_action_state_machine_v2.py tests/server/test_resolution_pipeline.py tests/server/test_ai_gateway.py -q` | 266 passed |
| `git diff --check` | passed（仅既有 CRLF 提示） |

## 未完成门禁

- 尚未重启本地后端，因此不能把当前浏览器会话当作本轮代码的验收证据。
- 待重启后需以两名玩家完成：建立协作契约、勾选前置队友、两人确认、检查批次顺序；再验证前置失败时依赖行动进入异常队列。
- 本轮没有把 AI 建议升级为权威依赖，也没有让 Narrator 修改规则或世界状态。

## 追加：锁定回合的公开事实回写

- 战斗回合中，每一条已发布的 `stage_projection.narrativeText` 会按锁定的规则顺序写回 `combat_plan.resolved_public_facts`。
- 私密动作、未发布投影与解析失败文本不会写入该字段；回合计划的动作、规则顺序与状态权威不因展示重排而变化。
- 玩家叙事流与 Host 公开投影均会避免把“当前局势”与最后一条公开事实重复展示。

| 命令 | 结果 |
| --- | --- |
| `python -m pytest tests/server/test_collaboration_contracts.py tests/server/test_combat_round_planner.py tests/server/test_turn_manager.py tests/server/test_narrator_runtime.py tests/server/test_host.py tests/server/test_action_drafts_v2.py tests/server/test_action_state_machine_v2.py tests/server/test_resolution_pipeline.py -q` | 231 passed |
| `cd src/client && npm run test -- --run` | 45 files / 166 tests passed |
| `cd src/client && npm run build` | passed |

## 当前全量自动化复验

| 命令 | 结果 | 说明 |
| --- | --- | --- |
| `python -m pytest tests/server -q` | 1170 passed，1259.74s | 包含本轮协作依赖、公开事实回写与第二阶段展示重排；该结果替代本文件中较早的定向统计，不替代浏览器门禁。 |
| `cd src/client && npm run test -- --run` | 45 files / 166 tests passed | 当前前端全量回归。 |
| `cd src/client && npm run build` | passed | TypeScript 检查与 Vite 生产构建。 |
