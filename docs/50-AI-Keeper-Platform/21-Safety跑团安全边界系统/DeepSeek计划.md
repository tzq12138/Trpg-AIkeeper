# Safety 跑团安全边界系统 DeepSeek 计划初版

## 执行定位

Safety 模块在公开测试前必须补齐，当前先写边界，等主链路稳定后拆实现。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Safety-1 | 房间内容分级和玩家边界 | `src/server/models.py`、`src/server/router_rooms.py` | `python -m pytest tests/server/test_rooms.py -q` | 不公开玩家私密禁区。 |
| Safety-2 | X-Card 暂停事务 | `src/server/engine/resolution_pipeline.py`、`src/server/host/ws_manager.py` | `python -m pytest tests/server/test_resolution_pipeline.py -q` | 不忽略正在播放的阻塞事务。 |
| Safety-3 | AI 安全上下文和输出限制 | `src/server/ai/rag_context.py`、`src/server/ai/contracts.py` | `python -m pytest tests/server/test_ai_kp.py -q` | 不把敏感原文写入 prompt 日志。 |

## DeepSeek 执行规则

- 安全设置优先于演出效果。
- 个人边界默认私密。
- AI 生成内容必须受安全边界影响。

