# Timeline 时间轴系统 DeepSeek 计划初版

## 执行定位

Timeline 模块先绑定事件日志和当前游戏内时间，后续再推进未来事件和阵营时钟。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Timeline-1 | 当前游戏内时间字段和推进事件 | `src/server/engine/state_service.py`、`src/server/events/` | `python -m pytest tests/server/test_state_service.py tests/server/test_event_log.py -q` | 不让前端本地时间成为权威。 |
| Timeline-2 | 时间线查询和权限过滤 | `src/server/router_archive.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不返回私密事件。 |
| Timeline-3 | 未来事件轻量模型 | `src/server/turn_manager.py`、`tests/server/test_game_loop.py` | `python -m pytest tests/server/test_game_loop.py -q` | 不做复杂阵营模拟。 |

## DeepSeek 执行规则

- 时间推进必须有事件来源。
- 隐藏未来事件不进入 Player 投影。
- AI 建议耗时需由 Engine 应用。

