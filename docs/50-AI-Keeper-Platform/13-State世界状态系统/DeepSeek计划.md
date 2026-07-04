# State 世界状态系统 DeepSeek 计划初版

## 执行定位

State 模块直接引用 `docs/30-DeepSeek任务包/Batch-2-状态版本屏障与投影时序.md`，优先解决版本屏障和快照一致性。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| State-1 | stateVersion 屏障和冲突检测 | `src/server/engine/state_service.py`、`tests/server/test_state_service.py` | `python -m pytest tests/server/test_state_service.py -q` | 不用前端版本作为权威。 |
| State-2 | 快照生成和恢复 | `src/server/events/event_log.py`、`tests/server/test_state_service_consistency.py` | `python -m pytest tests/server/test_state_service_consistency.py -q` | 不静默覆盖状态。 |
| State-3 | 状态变更审计 | `src/server/events/`、`tests/server/test_event_log.py` | `python -m pytest tests/server/test_event_log.py -q` | 不写无来源 mutation。 |

## DeepSeek 执行规则

- Engine 唯一写入口不可破坏。
- 每次 mutation 必须产生事件。
- 恢复快照也要生成新版本。

