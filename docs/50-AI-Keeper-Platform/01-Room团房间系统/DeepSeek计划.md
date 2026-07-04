# Room 团房间系统 DeepSeek 计划初版

## 执行定位

Room 模块的实现应在核心链路 Batch 1 稳定后推进，优先修补创建、加入、ready、start 和 Session 状态一致性。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Room-1 | 稳定房间创建和加入 | `src/server/router_rooms.py`、`src/server/models.py`、`tests/server/test_rooms.py` | `python -m pytest tests/server/test_rooms.py -q` | 不引入正式账号体系。 |
| Room-2 | 稳定 Lobby ready/start 同步 | `src/server/host/`、`src/client/src/pages/HostLobby.tsx`、`src/client/src/pages/PlayerLobby.tsx` | `python -m pytest tests/server/test_host_room_lifecycle.py -q`、`npm run build` | 不让前端本地状态成为权威状态。 |
| Room-3 | 增加 Session 状态和归档索引 | `src/server/events/`、`src/server/campaign_archive.py`、`tests/server/test_archive.py` | `python -m pytest tests/server/test_archive.py -q` | 不做社区招募和评价。 |

## DeepSeek 执行规则

- 每批开始先运行 `git status --short`。
- 房间状态只能由后端校验后写入。
- 房主急救能力必须保持有限，不获得完整 KP 真相。
- 所有状态变更必须落事件日志。

