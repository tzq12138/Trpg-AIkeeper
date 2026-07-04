# AI-Keeper 核心系统 DeepSeek 计划初版

## 执行定位

本模块直接引用 `docs/20-核心链路/` 和 `docs/30-DeepSeek任务包/Batch-3-AI反幻觉与真相锁定.md`，不得另起冲突口径。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| AI-1 | 统一 AiGateway provider 和 fallback | `src/server/ai/gateway.py`、`src/server/ai/providers.py`、`tests/server/test_ai_kp.py` | `python -m pytest tests/server/test_ai_kp.py -q` | 不散落直接调用 DeepSeek。 |
| AI-2 | 输出 schema 校验和越权拦截 | `src/server/ai/contracts.py`、`src/server/engine/resolution_pipeline.py` | `python -m pytest tests/server/test_resolution_pipeline.py -q` | 不让 AI 直接落库。 |
| AI-3 | 上下文过滤和真相锁定 | `src/server/ai/rag_context.py`、`src/server/engine/spoiler_guard.py` | `python -m pytest tests/server/test_spoiler.py tests/server/test_spoiler_guard.py -q` | 不把未发现线索放入 Player 上下文。 |

## DeepSeek 执行规则

- AI 只建议，Engine 写状态。
- schema 校验失败走 fallback。
- AI 调用日志脱敏，不记录 API key。

