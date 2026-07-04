# User 用户与权限系统 DeepSeek 计划初版

## 执行定位

User 模块先服务核心链路的身份安全，正式账号体系可后置。优先目标是 token、room role、character binding 和权限审计一致。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| User-1 | 统一 Player token 与角色绑定校验 | `src/server/player/`、`src/server/router_auth.py`、`tests/server/test_room_security.py` | `python -m pytest tests/server/test_room_security.py -q` | 不信任前端 characterId。 |
| User-2 | Host 有限权限和审计 | `src/server/host/router_host.py`、`src/server/events/` | `python -m pytest tests/server/test_host.py -q` | 不给房主完整 KP 视角。 |
| User-3 | 旁观者只读模型 | `src/server/router_rooms.py`、`src/server/host/ws_manager.py` | `python -m pytest tests/server/test_ws_auth.py -q` | 不允许旁观者写状态。 |

## DeepSeek 执行规则

- 任何权限绕过都按 P0 处理。
- 前端隐藏按钮不能替代后端鉴权。
- 权限失败要可诊断，但错误信息不能泄露真相。

