# Module 模组编辑器 DeepSeek 计划初版

## 执行定位

Module 模块已有 PRD-22/23 基础，后续重点是编辑器和测试模式。当前先稳 PDF 到一键开局链路。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Module-1 | PDF 导入和结构化稳定 | `src/server/scenario/pdf_parser.py`、`src/server/ai/gateway.py` | `python -m pytest tests/server/test_pdf_parser.py tests/server/test_ai_kp.py -q` | 不把坏结构静默当成功。 |
| Module-2 | 质量报告和缺口检查 | `src/server/scenario/quality.py`、`tests/server/test_quality.py` | `python -m pytest tests/server/test_quality.py -q` | 不跳过防剧透检查。 |
| Module-3 | 一键开房初始化状态 | `src/server/scenario/router_scenarios.py`、`src/server/router_rooms.py` | `python -m pytest tests/server/test_rooms.py tests/server/test_integration.py -q` | 不让模组真相进入 Host/Player 公共状态。 |

## DeepSeek 执行规则

- AI 结构化输出必须 schema 校验。
- 模组和房间运行态分离。
- 测试模式不能污染正式数据。

