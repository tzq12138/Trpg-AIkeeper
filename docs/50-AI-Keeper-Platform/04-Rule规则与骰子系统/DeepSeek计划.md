# Rule 规则与骰子系统 DeepSeek 计划

## 执行定位

Rule 第一轮只修 COC 7e 主链路和规则口径，不扩完整多规则平台。DeepSeek 必须优先保证：骰点服务端生成、成功等级全链路一致、AI 只建议不裁决、状态写入仍由 StateService 负责。

## 代码现状依据

| 方向 | 文件 |
|---|---|
| 独立技能检定 | `src/server/engine/skill_check.py` |
| 玩家检定入口 | `src/server/player/router_player.py`、`src/client/src/pages/PlayerCharacter.tsx` |
| 机制编译 | `src/server/ai/mechanic_compiler.py` |
| 规则执行 | `src/server/engine/rule_executor.py` |
| 规则 Handler | `src/server/rules/base.py`、`src/server/rules/coc_handlers.py`、`src/server/rules/encounter_handlers.py` |
| 注册表与触发器 | `src/server/rules/registry.py`、`src/server/rules/triggers.py` |
| 裁决管线 | `src/server/engine/resolution_pipeline.py` |
| 前端展示 | `src/client/src/pages/PlayerActionPage.tsx`、`src/client/src/pages/PlayerCharacter.tsx` |
| 测试基线 | `tests/server/test_skill_check.py`、`tests/server/test_rules.py`、`tests/server/test_rule_executor.py`、`tests/server/test_mechanic_compiler.py`、`tests/server/test_resolution_pipeline.py` |

## Batch Rule-0：规则口径盘点与测试同步

目标：确认当前失败点和口径漂移，不先改业务语义。

允许修改：

- `tests/server/test_rules.py`
- `tests/server/test_skill_check.py`
- `tests/server/test_resolution_pipeline.py`
- 必要时只补测试注释或断言名称

执行要点：

- 明确当前两套成功等级：`critical/extreme/hard/regular/failure/fumble` 与 `critical_success/success/failure/fumble`。
- 写出或调整测试，暴露主链路 `s2c_action_completed` 缺 `success_level/successLevel` 的问题。
- 不为了通过测试而先改前端兜底。

验收命令：

```bash
python -m pytest tests/server/test_skill_check.py tests/server/test_rules.py tests/server/test_resolution_pipeline.py -q
```

禁止事项：

- 不删除已有规则测试。
- 不把成功等级断言改宽到没有意义。
- 不修改源码来掩盖测试问题。

## Batch Rule-1：统一 COC 技能检定成功等级

目标：让主链路、fallback 接口、前端展示和日志都使用统一成功等级枚举。

允许修改：

- `src/server/engine/skill_check.py`
- `src/server/rules/coc_handlers.py`
- `src/server/engine/resolution_pipeline.py`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/pages/PlayerCharacter.tsx`
- `tests/server/test_skill_check.py`
- `tests/server/test_rules.py`
- `tests/server/test_resolution_pipeline.py`

执行要点：

- 统一枚举为 `critical/extreme/hard/regular/failure/fumble`。
- `CocSkillCheckHandler` 应返回统一枚举，并保留 `is_success`。
- `s2c_action_completed` payload 同时给出 `success_level` 与 `successLevel`，保留 `level` 兼容。
- 前端不应把未知成功等级默认为 regular；未知值应显示为 failure 或系统提示。

验收命令：

```bash
python -m pytest tests/server/test_skill_check.py tests/server/test_rules.py tests/server/test_resolution_pipeline.py -q
cd src/client && npm run build
```

禁止事项：

- 不让前端计算成功等级。
- 不删除 `level` 兼容字段导致旧 UI 崩溃。
- 不改变 action lifecycle 状态机。

## Batch Rule-2：奖励/惩罚骰接入主链路

目标：让 `skill_check` intent、AI rollRequests、Rule Handler 都能正确使用 bonusDice。

允许修改：

- `src/server/models.py`
- `src/server/ai/contracts.py`
- `src/server/ai/mechanic_compiler.py`
- `src/server/engine/rule_executor.py`
- `src/server/rules/coc_handlers.py`
- `tests/server/test_skill_check.py`
- `tests/server/test_rule_executor.py`

执行要点：

- 参数统一接受 `bonusDice` 和兼容 `bonus_dice`。
- `CocSkillCheckHandler` 复用或等价实现 `roll_skill_check` 的十位骰逻辑。
- metadata 与 reveal step 写明 `bonusDice`。
- `bonusDice` 允许负数表示惩罚骰，限制绝对值上限，避免异常循环。

验收命令：

```bash
python -m pytest tests/server/test_skill_check.py tests/server/test_rules.py tests/server/test_rule_executor.py -q
```

禁止事项：

- 不在前端生成额外十位骰结果。
- 不把 bonusDice 静默丢弃。
- 不允许无限数量奖励/惩罚骰。

## Batch Rule-3：骰子结果结构与归档追溯

目标：让规则结果能稳定进入 action result、事件日志、玩家归档和 Host timeline。

允许修改：

- `src/server/engine/resolution_pipeline.py`
- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/client/src/components/HostLogsPanel.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `tests/server/test_archive.py`
- `tests/server/test_resolution_pipeline.py`

执行要点：

- 定义统一 RollResult payload 字段：`dice/roll/target/skillName/successLevel/difficulty/visibility/actionId`。
- action result 中保留完整 metadata。
- 玩家 archive 的 `skill_checks` 能返回 roll、target、successLevel。
- Host timeline 能识别 roll 相关事件或 action result 摘要。

验收命令：

```bash
python -m pytest tests/server/test_archive.py tests/server/test_resolution_pipeline.py tests/server/test_event_log.py -q
cd src/client && npm run build
```

禁止事项：

- 不新建与 events/actions 冲突的第二套权威日志。
- 不把其他玩家私密骰结果暴露给当前玩家。
- 不让 Host UI 自己推断成功等级。

## Batch Rule-4：SAN/HP/Luck 与 StateService 边界

目标：确保规则 Handler 只产生 mutation，由 StateService 统一应用并投影。

允许修改：

- `src/server/rules/coc_handlers.py`
- `src/server/engine/rule_executor.py`
- `src/server/engine/resolution_pipeline.py`
- `src/server/engine/state_service.py`
- `tests/server/test_rules.py`
- `tests/server/test_rule_executor.py`
- `tests/server/test_state_service.py`
- `tests/server/test_resolution_pipeline.py`

执行要点：

- SAN/HP mutation 路径与 StateService 支持路径保持一致。
- `parse_dice` 可扩展到 `XdY+N`，但不做复杂表达式解释器。
- RuleExecutor 不直接写库；StateService 失败时要有日志和 rejected/partial 策略。
- Luck 检定与 Luck 花费分开，不在本批偷偷加入花费规则。

验收命令：

```bash
python -m pytest tests/server/test_rules.py tests/server/test_rule_executor.py tests/server/test_state_service.py tests/server/test_resolution_pipeline.py -q
```

禁止事项：

- 不让 AI 直接扣 SAN/HP。
- 不在 Rule Handler 内执行 SQL。
- 不引入自定义脚本执行能力。

## Batch Rule-5：触发器 DSL 与规则注册安全

目标：让剧本触发器可验证、可失败、可解释，避免导入非法机制后运行时才炸。

允许修改：

- `src/server/rules/triggers.py`
- `src/server/rules/registry.py`
- `src/server/scenario/quality.py`
- `src/server/scenario/router_scenarios.py`
- `tests/server/test_rules.py`
- `tests/server/test_quality.py`

执行要点：

- 定义 triggers 支持的最小 schema：`condition.$action`、`condition.itemId`、`mechanics[].type`、`mechanics[].params`。
- 剧本质量报告能发现未知 mechanic、缺 params、非法 dice 表达式。
- registry 只接受 `BaseRuleHandler` 实例。
- 未注册 mechanic 在运行时给 warning，并让 action 有可理解结果。

验收命令：

```bash
python -m pytest tests/server/test_rules.py tests/server/test_quality.py tests/server/test_resolution_pipeline.py -q
```

禁止事项：

- 不允许剧本上传 Python/JS 脚本。
- 不在质量检查里调用 AI 判定数学规则。
- 不把未知 mechanic 当成功事实。

## Batch Rule-6：端到端回归

目标：验证规则系统支撑主跑团链路。

手动验收链路：

1. 玩家加入房间并导入角色卡。
2. 玩家点击角色卡“侦查”技能。
3. 后端写 action，机制编译为 skill_check。
4. RuleExecutor 服务端掷骰并生成统一 successLevel。
5. Host 收到 roll reveal step。
6. Player 收到 `s2c_action_completed`，角色卡显示检定结果。
7. 如果触发 SAN/HP mutation，StateService 写入状态并推送 patch。
8. 玩家归档可查到该次检定。

验收命令：

```bash
python -m pytest tests/server/test_skill_check.py tests/server/test_rules.py tests/server/test_rule_executor.py tests/server/test_mechanic_compiler.py tests/server/test_resolution_pipeline.py tests/server/test_player_intent.py tests/server/test_archive.py -q
cd src/client && npm run build
```

禁止事项：

- 不把 `/api/player/skill-check` 作为端到端验收主入口。
- 不绕过 `POST /api/player/intent`。
- 不修改 Room/User/Channel 无关行为。

## DeepSeek 交付要求

- 每个 Batch 必须写清测试命令和实际结果。
- 涉及随机数的测试要使用 seed 或 monkeypatch，避免 flaky。
- 涉及权限和私密骰时，必须补 REST/WS/Archive 服务端过滤测试。
- 所有规则字段要同时考虑 Python snake_case、API camelCase、前端 TypeScript 类型。

