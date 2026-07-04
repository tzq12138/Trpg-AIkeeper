# NPC / Faction 系统 DeepSeek 计划初版

## 执行定位

NPC / Faction 模块先服务剧本结构化和 AI 上下文，运行时状态和势力时钟在核心链路稳定后推进。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| NPC-1 | 剧本 NPC 结构化和查询 | `src/server/scenario/`、`tests/server/test_pdf_parser.py`、`tests/server/test_quality.py` | `python -m pytest tests/server/test_quality.py -q` | 不让 AI 发明核心 NPC。 |
| NPC-2 | NPC 已知/秘密分层 | `src/server/ai/rag_context.py`、`src/server/ai/spoiler_control.py` | `python -m pytest tests/server/test_spoiler.py -q` | 不把 NPC 秘密投给玩家。 |
| NPC-3 | NPC 状态和关系日志 | `src/server/events/`、`src/server/models.py` | `python -m pytest tests/server/test_event_log.py -q` | 不直接修改状态绕过 Engine。 |

## DeepSeek 执行规则

- NPC 运行态必须有来源事件。
- 未发现 NPC 秘密不能进入玩家上下文。
- 势力系统先留轻量模型，不做复杂模拟。

