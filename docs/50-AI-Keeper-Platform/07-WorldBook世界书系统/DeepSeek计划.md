# WorldBook 世界书系统 DeepSeek 计划初版

## 执行定位

WorldBook 模块应先服务 AI 上下文、防剧透和剧本结构化。编辑器和版本管理进入第二阶段。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| WorldBook-1 | RAG 检索结果带来源和可见性 | `src/server/ai/rag.py`、`src/server/ai/rag_context.py`、`tests/server/test_rag.py` | `python -m pytest tests/server/test_rag.py tests/server/test_rag_security.py -q` | 不返回未授权真相。 |
| WorldBook-2 | 真相层和玩家已知层分离 | `src/server/ai/spoiler_control.py`、`tests/server/test_spoiler.py` | `python -m pytest tests/server/test_spoiler.py -q` | 不把猜测写成事实。 |
| WorldBook-3 | 世界书条目引用和审计 | `src/server/events/`、`src/server/router_archive.py` | `python -m pytest tests/server/test_event_log.py -q` | 不记录完整敏感 prompt。 |

## DeepSeek 执行规则

- 每次 AI 上下文构建都要经过可见性过滤。
- 检索结果必须保留来源 id。
- 编辑器功能后置，不在 RAG 安全批里顺手做 UI。

