# Plugin / Admin / Ops 开放 API 与后台运维 DeepSeek 计划初版

## 执行定位

本模块作为公开测试前护栏和后期生态入口。先做备份、审计、成本和协议文档，再考虑插件市场和商业化。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Ops-1 | 健康检查、AI 日志和成本摘要 | `src/server/router_admin.py`、`src/server/ai/gateway.py` | `python -m pytest tests/server/test_ai_kp.py -q` | 不记录 API key 和完整 prompt。 |
| Ops-2 | 快照、备份和恢复审计 | `src/server/engine/state_service.py`、`src/server/events/` | `python -m pytest tests/server/test_state_service_consistency.py -q` | 不静默覆盖数据。 |
| Ops-3 | 限流和权限审计 | `src/server/router_auth.py`、`src/server/router_rooms.py` | `python -m pytest tests/server/test_room_security.py -q` | 不把前端隐藏当安全。 |
| Plugin-1 | 协议文档和导出格式 | `docs/`、`src/server/export.py` | `python -m pytest tests/server/test_archive.py -q` | 不开放直接写状态 API。 |

## DeepSeek 执行规则

- 公开测试前优先备份、限流、脱敏、成本统计。
- 插件只通过受控接口表达建议。
- 商业化和市场能力后置。

