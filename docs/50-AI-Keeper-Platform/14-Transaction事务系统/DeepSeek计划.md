# Transaction 事务系统 DeepSeek 计划初版

## 执行定位

Transaction 模块直接服务核心链路，重点参考 `docs/30-DeepSeek任务包/Batch-2-状态版本屏障与投影时序.md`。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| TX-1 | 事务 step 模型和日志 | `src/server/engine/resolution_pipeline.py`、`src/server/events/` | `python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_event_log.py -q` | 不让事务只存在内存。 |
| TX-2 | Host 完成信号和 Player 解锁 | `src/server/host/`、`src/client/src/pages/HostStage.tsx` | `python -m pytest tests/server/test_host.py -q`、`npm run build` | 不信任玩家伪造完成信号。 |
| TX-3 | 私密 patch 延迟和恢复 | `src/server/engine/projection.py`、`tests/server/test_projection.py` | `python -m pytest tests/server/test_projection.py -q` | 不提前下发剧透 patch。 |

## DeepSeek 执行规则

- 事务必须有 txId 和 sourceActionId。
- 完成信号需要鉴权。
- Watchdog 只能解锁 UI，不能编造裁决结果。

