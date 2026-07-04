# Schedule 日程与招募系统 DeepSeek 计划初版

## 执行定位

Schedule 模块在文字团基础稳定后推进，先做房间内日程，不做公开招募大厅。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Schedule-1 | 房间日程和可用时间投票 | `src/server/router_rooms.py`、`src/server/models.py` | `python -m pytest tests/server/test_rooms.py -q` | 不做公开匹配算法。 |
| Schedule-2 | 站内提醒和缺席记录 | `src/server/events/`、`src/server/player/` | `python -m pytest tests/server/test_event_log.py -q` | 不发送外部通知。 |
| Schedule-3 | 跑团历史索引 | `src/server/campaign_archive.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不公开私密房间历史。 |

## DeepSeek 执行规则

- 招募大厅后置。
- 评价系统后置。
- 日程信息默认房间内可见。

