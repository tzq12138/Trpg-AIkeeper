# Rule 规则与骰子系统 DeepSeek 计划初版

## 执行定位

Rule 模块先巩固 COC 7e 检定和状态变更，插件化只保留接口方向，不在当前批次扩完整多规则。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Rule-1 | 稳定 COC 技能检定 | `src/server/engine/skill_check.py`、`tests/server/test_skill_check.py` | `python -m pytest tests/server/test_skill_check.py -q` | 不让前端提交骰子结果。 |
| Rule-2 | 骰子日志和暗骰投影 | `src/server/events/`、`src/server/engine/projection.py` | `python -m pytest tests/server/test_event_log.py tests/server/test_projection.py -q` | 不把暗骰广播给公共频道。 |
| Rule-3 | SAN/HP/MP 状态写入校验 | `src/server/engine/rule_executor.py`、`tests/server/test_rule_executor.py` | `python -m pytest tests/server/test_rule_executor.py -q` | 不让 AI 直接扣状态。 |

## DeepSeek 执行规则

- RuleExecutor 的结果是数学事实，叙事不能改写。
- 所有状态扣减必须写事件日志。
- 规则插件化只能做接口预留，不引入任意代码执行。

