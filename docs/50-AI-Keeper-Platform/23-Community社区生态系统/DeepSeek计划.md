# Community 社区生态系统 DeepSeek 计划初版

## 执行定位

Community 模块不进入当前阶段。等核心产品、模组编辑和安全边界稳定后，再从只读内容广场开始。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Community-1 | 公开模组索引和隐私检查 | `src/server/export.py`、`src/server/scenario/` | `python -m pytest tests/server/test_quality.py -q` | 不发布私密房间数据。 |
| Community-2 | 战报生成和公共日志过滤 | `src/server/campaign_archive.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不使用私密日志生成公开战报。 |
| Community-3 | 收藏和评论基础 | 后续新增社区路由和测试 | 后续按实现补充 | 不做付费和订阅。 |

## DeepSeek 执行规则

- 社区发布必须先过隐私过滤。
- 付费能力不进入社区第一批。
- 评价和评论需考虑治理成本。

