# Projection 投影系统 DeepSeek 计划初版

## 执行定位

Projection 模块直接引用 `docs/20-核心链路/AI-Keeper核心链路架构.md` 和 Batch 2，优先修重连乱序和剧透时序。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Projection-1 | 受众过滤和字段最小化 | `src/server/engine/projection.py`、`tests/server/test_projection.py` | `python -m pytest tests/server/test_projection.py -q` | 不靠前端隐藏敏感字段。 |
| Projection-2 | stateVersion barrier | `src/client/src/shared/ws.ts`、`src/server/player/router_reconnect.py` | `python -m pytest tests/server/test_reconnect.py -q`、`npm run build` | 不让旧 patch 覆盖新状态。 |
| Projection-3 | executeAfter 投影时序 | `src/server/engine/resolution_pipeline.py`、`src/server/host/ws_manager.py` | `python -m pytest tests/server/test_resolution_pipeline.py tests/server/test_host.py -q` | 不提前发送私密剧透。 |

## DeepSeek 执行规则

- 投影 payload 要从源头过滤敏感字段。
- 所有 WS 消息都带版本或序列。
- Player 重连优先 snapshot，再应用可验证 patch。

