# Batch 1：开发态稳定性与实时闭环

## 目标

优先修当前开发态会阻断主流程的问题：WebSocket 崩溃、Host 鉴权、Lobby ready/chat/start 不同步、日志乱码、MCP/DeepSeek 剧本链路不稳定。

## 范围

- 以历史 `plan25` 为主要输入。
- 修复玩家 WS catch-up、Host WS 鉴权、开局广播、Lobby snapshot。
- 修复 Host 舞台 HUD 初始推送和玩家状态聚合。
- 修复日志 UTF-8、ANSI 清理和落盘路径。
- 修复 AI Gateway provider 顺序、DeepSeek 失败诊断、剧本结构化规范化和质量报告展示。

## 文件方向

| 区域 | 可能涉及路径 |
|---|---|
| FastAPI 入口 | `src/server/main.py` |
| 房间流程 | `src/server/router_rooms.py` |
| Player WS/路由 | `src/server/player/router_player.py`、`src/server/player/router_reconnect.py` |
| Host | `src/server/host/router_host.py`、`src/server/host/host_store.py`、`src/server/host/hud_builder.py` |
| 事件 | `src/server/events/events.py`、`src/server/events/events_registry.py` |
| AI/MCP | `src/server/ai/gateway.py`、`src/server/ai/providers.py`、`kp_mcp_server/kp_brain.py` |
| 剧本 | `src/server/scenario/router_scenarios.py`、`src/server/scenario/quality.py` |
| 日志 | `dev.py`、`src/server/log_config.py` |
| 前端 | `src/client/src/pages/HostLobby.tsx`、`HostStage.tsx`、`PlayerLobby.tsx`、`shared/ws.ts` |
| 测试 | `tests/server/test_host_room_lifecycle.py`、`test_ws_auth.py`、`test_character_join_import.py`、`test_mechanic_compiler.py` |

## 验收命令

```powershell
python -m pytest tests/server/test_host_room_lifecycle.py tests/server/test_ws_auth.py tests/server/test_character_join_import.py tests/server/test_mechanic_compiler.py -q
```

预期：相关后端测试通过，且测试库不会清空开发库。

```powershell
cd src/client
node ./node_modules/typescript/bin/tsc --noEmit
```

预期：TypeScript 类型检查通过。

```powershell
python dev.py --check
```

预期：如果服务运行中，健康检查能输出组件状态；如果未运行，应给出明确提示，不出现乱码。

## 手动验收

- 两个玩家在等待室互相可见，聊天不重复，ready 状态双端同步。
- 房主点击开始后 Host 进入舞台，玩家等待室收到 active 状态并进入 Player 端。
- Host 舞台刷新后能立即看到玩家 HP/SAN/ready。
- 导入剧本后 Admin/Host 能看到 provider、质量等级、缺失项或风险说明。

## 禁止事项

- 不新增语音视频或多模态主链路。
- 不为了修 UI 绕过 owner/player token。
- 不把真实 API key 写入代码、日志或测试。
- 不大规模重写前端设计系统。
