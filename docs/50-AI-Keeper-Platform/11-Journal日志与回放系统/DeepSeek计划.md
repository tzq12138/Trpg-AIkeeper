# Journal 日志与回放系统 DeepSeek 计划初版

## 执行定位

Journal 模块是第一轮核心链路的沉淀层，应和 Batch 5 回归验收一起保持稳定。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Journal-1 | 事件日志完整性和分页 | `src/server/events/event_log.py`、`tests/server/test_event_log.py` | `python -m pytest tests/server/test_event_log.py -q` | 不写无法追溯的状态变化。 |
| Journal-2 | 公共/私密回放过滤 | `src/server/router_archive.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不把私密事件混入公共回放。 |
| Journal-3 | 检查点和恢复 | `src/server/engine/state_service.py`、`tests/server/test_state_service_consistency.py` | `python -m pytest tests/server/test_state_service_consistency.py -q` | 不覆盖无关房间状态。 |

## DeepSeek 执行规则

- 每条权威变更必须能定位来源 action 或 transaction。
- 查询接口必须按受众过滤。
- AI debug 日志不得长期保存完整 prompt。

