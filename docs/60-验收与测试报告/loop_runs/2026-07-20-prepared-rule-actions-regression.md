# 2026-07-20 准备动作规则事件回归记录

## 本轮范围

- 玩家可用自然语言或结构化确认建立一条高风险准备动作；确认后为 `armed`，不占用普通行动名额。
- 仅规则引擎构造的公开 `PreparedRuleEvent` 可触发准备动作；玩家请求、AI 输出和 Host 手动操作都不能直接触发。
- 已接入的真实事件源为：黑熊遭遇的“敌人公开宣告攻击”、规则引擎实际创建的单人战斗、可见敌方从非近战距离进入 `engaged`，以及公开规则结算造成另一名玩家受伤。触发后生成普通内部战斗行动，仍由既有确定性规则引擎结算。
- `take_cover`、`withdraw` 映射到现有 `defend`、`flee` 规则；`protect_ally` 必须由玩家在确认时指定同房角色，内部行动保留该目标，不能由 AI 或事件替换。
- 准备动作会在刷新时恢复为可观察状态，但不会阻止玩家继续提交普通行动。取消、完成、拒绝和超时均保留可审计终态。

## 自动化证据

| 命令 | 结果 | 覆盖 |
| --- | --- | --- |
| `python -m pytest tests/server/test_reconnect.py tests/server/test_prepared_rule_actions.py -q` | 26 passed | `armed` 重连恢复、唯一触发、客户端伪事件拒绝、取消、盟友目标保留、拒绝收口。 |
| `python -m pytest tests/server/test_prepared_rule_actions.py tests/server/test_reconnect.py tests/server/test_action_drafts_v2.py tests/server/test_resolution_pipeline.py tests/server/test_solo_adventure_runtime.py -q` | 178 passed | 草稿、重连、战斗规则、黑熊真实事件源和单人运行时回归。 |
| `python -m pytest tests/server -q` | 1184 passed，1394.58s | 全量后端回归；夹具会在每个 API 测试前后清理全局假供应商，避免跨文件污染准备动作判定。 |
| `cd src/client && npm run test -- --run` | 45 files / 167 tests passed | 玩家行动状态显示与其他前端合同回归。 |
| `cd src/client && npm run build` | passed | TypeScript 与 Vite 生产构建。 |
| `python -m pytest tests/server/test_prepared_rule_actions.py tests/server/test_combat_round_planner.py tests/server/test_turn_manager.py tests/server/test_action_state_machine_v2.py tests/server/test_reconnect.py -q` | 83 passed，81.17s | 四类真实规则事件、私密伤害隔离、当前遭遇过滤、`armed` 重连、战斗轮计划和状态机回归。 |
| `python -m pytest tests/server -q`（干净复跑） | 1189 passed，1313.47s | 本轮规则事件、既有后端功能与测试数据库隔离的全量回归。 |
| `cd src/client && npm run test -- --run`（复跑） | 45 files / 167 tests passed | 玩家行动状态、管理页与既有前端合同。 |
| `cd src/client && npm run build`（复跑） | passed | TypeScript 检查与 Vite 生产构建。 |

## 未完成门禁

- 还没有重启本工作区的后端，因此本轮没有把旧浏览器会话当作新代码的验收证据。
- 三个原先未接线的白名单事件（进入近战、盟友公开受伤、遭遇开始）现已绑定确定性规则输出；它们仍不会被 AI、Host 或客户端伪造触发。单人“遭遇开始”目前仅覆盖规则引擎创建的黑熊遭遇，其他剧本的遭遇创建器需要沿用同一事件契约。
- 仍需在重启后完成至少两名玩家的浏览器验收：布防、刷新、四类规则事件、内部反应结算和结果卡可见性。
