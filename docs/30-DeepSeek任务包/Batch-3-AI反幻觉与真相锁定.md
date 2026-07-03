# Batch 3：AI 反幻觉与真相锁定

## 目标

强化 AI-KP 安全边界：AI 只能提出叙事和结算建议，不能把猜测变事实，不能泄露未授权真相，不能直接写权威状态。

## 范围

- AI 输出 schema 归一化和校验。
- 机制编译器兼容 DeepSeek/MCP 常见字段别名，但非法输出必须降级或拒绝。
- 叙事上下文按可见范围过滤，未发现线索和 KP-only 真相不进入 Player 可见上下文。
- 规则结果和级联状态后果必须注入叙事阶段，防止事实时差。
- AI 建议的状态变化必须由 Engine 校验后写入。

## 文件方向

| 区域 | 可能涉及路径 |
|---|---|
| AI 契约 | `src/server/ai/contracts.py` |
| 机制编译 | `src/server/ai/mechanic_compiler.py` |
| AI Gateway | `src/server/ai/gateway.py`、`src/server/ai/providers.py` |
| 剧透控制 | `src/server/ai/spoiler_control.py`、`src/server/engine/spoiler_guard.py` |
| 裁决管线 | `src/server/engine/resolution_pipeline.py` |
| 规则执行 | `src/server/engine/rule_executor.py` |
| RAG 上下文 | `src/server/ai/rag_context.py`、`src/server/ai/rag.py` |
| 测试 | `tests/server/test_mechanic_compiler.py`、`test_spoiler_guard.py`、`test_resolution_pipeline.py` |

## 验收命令

```powershell
python -m pytest tests/server/test_mechanic_compiler.py tests/server/test_spoiler_guard.py tests/server/test_resolution_pipeline.py tests/server/test_ai_kp.py -q
```

预期：AI 编译、剧透过滤、裁决管线和 AI KP 测试通过。

## 安全场景

- 玩家猜测凶手身份，AI 不能因为猜对或猜错而改写真相。
- 未发现线索不能出现在玩家提示词、Player event 或公共日志。
- AI 建议扣 SAN，Engine 必须校验触发条件和规则后再落库。
- AI 输出坏 JSON 或非法枚举时，系统能归一化、降级或给出可解释错误。

## 禁止事项

- 不把完整世界书直接塞进玩家上下文。
- 不让 AI 生成 SQL、JSON Patch 或数据库写入命令后直接执行。
- 不把 prompt、KP note、隐藏真相写进 Player 可见事件。
