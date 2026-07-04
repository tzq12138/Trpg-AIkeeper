# Channel 聊天与信息流系统 DeepSeek 计划初版

## 执行定位

Channel 模块应在 Projection 权限稳定后推进，先服务文字团基础体验和日志追溯。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Channel-1 | 建立公共/OOC/系统消息模型 | `src/server/events/`、`src/server/models.py`、`tests/server/test_events_bus.py` | `python -m pytest tests/server/test_events_bus.py -q` | 不让聊天直接改状态。 |
| Channel-2 | 私聊和受众过滤 | `src/server/player/`、`src/server/engine/projection.py` | `python -m pytest tests/server/test_projection.py -q` | 不靠前端过滤私密消息。 |
| Channel-3 | 基础查询和搜索 | `src/server/router_archive.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不返回未授权消息片段。 |

## DeepSeek 执行规则

- 每条消息必须有可见范围。
- AI 使用消息作为上下文前要标明消息类型。
- 搜索和摘要必须继承权限过滤。

