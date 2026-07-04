# Host Client 公共舞台端 DeepSeek 计划初版

## 执行定位

Host Client 是第一轮手动验收主链路的另一半，优先稳定 Lobby、Stage、HUD、WS 和事务播放。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Host-1 | Lobby ready/start 实时同步 | `src/client/src/pages/HostLobby.tsx`、`src/server/host/router_host.py` | `npm run build`、`python -m pytest tests/server/test_host_room_lifecycle.py -q` | 不用轮询覆盖 WS 问题。 |
| Host-2 | Stage 公共投影和 HUD | `src/client/src/pages/HostStage.tsx`、`src/server/host/hud_builder.py` | `npm run build`、`python -m pytest tests/server/test_host.py -q` | 不显示 KP-only 真相。 |
| Host-3 | Watchdog 和事务恢复 | `src/client/src/components/HostLogsPanel.tsx`、`src/server/host/ws_manager.py` | `npm run build`、`python -m pytest tests/server/test_host.py -q` | 不让 Host 自己裁决规则。 |

## DeepSeek 执行规则

- Host 只消费事件和有限控制。
- Host 不写权威状态。
- Host 错误恢复必须可审计。

