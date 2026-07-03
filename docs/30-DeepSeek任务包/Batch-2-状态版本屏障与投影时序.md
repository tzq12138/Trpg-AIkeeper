# Batch 2：状态版本屏障与投影时序

## 目标

解决分布式状态机的时序问题：Player 重连时 snapshot 与 patch 乱序、私密状态变更早于 Host 公共演出到达、事务完成信号不明确。

## 范围

- Player 端实现 state version barrier。
- `s2c_state_patch` 明确携带 `baseStateVersion`、`stateVersion` 或等价字段。
- 当 patch 版本超前时进入 buffer，并触发 full sync。
- full snapshot 到达后丢弃旧 patch，再按版本应用剩余 patch。
- 涉及公共演出的私密 patch 支持 `executeAfter` 或等价事务节点标记。
- Host 事务播放器能在关键节点完成后回传或触发后续投影。

## 文件方向

| 区域 | 可能涉及路径 |
|---|---|
| 事件契约 | `src/server/events/events.py`、`src/server/events/events_registry.py` |
| 投影 | `src/server/engine/projection.py` |
| Engine 状态 | `src/server/engine/state_service.py`、`src/server/engine/resolution_pipeline.py` |
| Player 同步 | `src/server/player/router_reconnect.py`、`src/client/src/shared/ws.ts` |
| Player 页面 | `src/client/src/pages/PlayerActionPage.tsx`、`PlayerLobby.tsx` |
| Host 事务 | `src/client/src/pages/HostStage.tsx` |
| 测试 | `tests/server/test_reconnect.py`、`tests/server/test_projection.py`、前端 WS 单测 |

## 验收命令

```powershell
python -m pytest tests/server/test_reconnect.py tests/server/test_projection.py tests/server/test_player_runtime_state.py -q
```

预期：重连、投影、Player runtime state 相关测试通过。

```powershell
cd src/client
npm.cmd test -- --run
```

预期：前端测试通过；如果项目没有覆盖该逻辑，需要补前端单测或用最小可测函数提取验证。

## 手动验收

- Player 断线期间发生状态变化，重连后最终状态只应用一次。
- Host 关键演出未到达指定节点前，Player 不提前展示私密奖励或物品。
- Host 演出完成后，Player 收到状态 patch 和 action completed，UI 解锁。

## 禁止事项

- 不用简单延迟计时代替事务节点。
- 不让 Player 忽略版本号直接覆盖状态。
- 不把 Host 本地播放状态作为权威世界状态。
