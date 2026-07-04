# Player Client 玩家私人端 DeepSeek 计划初版

## 执行定位

Player Client 是第一轮手动验收主链路的一半，优先稳定入房、ready、行动、回执、重连和私密投影。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Player-1 | 入房、角色绑定、ready 闭环 | `src/client/src/pages/PlayerJoinPage.tsx`、`src/client/src/pages/PlayerLobby.tsx` | `npm run build`、`python -m pytest tests/server/test_character_join_import.py -q` | 不把 token 写入公共日志。 |
| Player-2 | 行动提交和回执状态 | `src/client/src/pages/PlayerActionPage.tsx`、`src/client/src/shared/api.ts` | `npm run build`、`python -m pytest tests/server/test_player_intent.py -q` | 不绕过后端意图网关。 |
| Player-3 | 重连和 stateVersion barrier | `src/client/src/shared/ws.ts`、`tests/server/test_reconnect.py` | `npm run build`、`python -m pytest tests/server/test_reconnect.py -q` | 不用旧 patch 覆盖新 snapshot。 |

## DeepSeek 执行规则

- 前端只做视图和交互。
- 所有提交带幂等 action id。
- 错误提示不能泄露隐藏真相。

