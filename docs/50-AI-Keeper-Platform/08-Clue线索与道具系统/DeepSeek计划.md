# Clue 线索与道具系统 DeepSeek 计划初版

## 执行定位

Clue 模块和第一轮 Batch 4 强相关。优先做线索归属、分享、公共摘要、事件日志引用和可见范围。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Clue-1 | 线索归属和私密可见性 | `src/server/player/router_clues.py`、`tests/server/test_clues.py` | `python -m pytest tests/server/test_clues.py -q` | 不让未授权玩家查询私密线索。 |
| Clue-2 | 分享生成公共摘要 | `src/server/engine/projection.py`、`tests/server/test_projection.py` | `python -m pytest tests/server/test_projection.py tests/server/test_clues.py -q` | 不直接公开完整私密原文。 |
| Clue-3 | 线索来源和事件引用 | `src/server/events/event_log.py`、`src/server/router_archive.py` | `python -m pytest tests/server/test_event_log.py tests/server/test_archive.py -q` | 不写无法追溯的线索变化。 |

## DeepSeek 执行规则

- 未发现线索不进入 Player 上下文。
- AI 建议线索必须经过 Engine 确认。
- 分享行为由玩家主动触发或 Engine 明确生成，不由前端伪造。

