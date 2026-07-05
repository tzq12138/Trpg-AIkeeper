# Channel 聊天与信息流系统 DeepSeek 计划

## 执行定位

Channel 模块第一轮不做完整社交平台，而是修稳“事件流、队伍消息、归档查询、受众过滤”这条链路。DeepSeek 执行时必须以现有代码为准，先补安全和一致性，再扩展正式频道模型。

## 代码现状依据

| 方向 | 文件 |
|---|---|
| 玩家队伍消息 | `src/server/player/router_player.py` |
| WS 入口与补发 | `src/server/main.py`、`src/server/host/ws_manager.py` |
| 事件信封与类型 | `src/server/models.py`、`src/server/events/events_registry.py` |
| 事件落库 | `src/server/events/event_log.py`、`src/server/engine/projection.py` |
| Host 信息流 | `src/server/host/router_host.py`、`src/server/host/host_store.py`、`src/client/src/pages/HostStage.tsx` |
| Player 信息流 | `src/client/src/pages/PlayerLobby.tsx`、`src/client/src/pages/PlayerActionPage.tsx` |
| 归档查询 | `src/server/router_archive.py`、`src/server/player/router_player_archive.py` |
| 测试基线 | `tests/server/test_event_log.py`、`tests/server/test_events.py`、`tests/server/test_projection.py`、`tests/server/test_archive.py`、`tests/server/test_ws_auth.py` |

## Batch Channel-0：现状核对与事件类型一致性

目标：让事件注册表、Pydantic 类型、前端类型、测试枚举保持一致。

允许修改：

- `src/server/models.py`
- `src/server/events/events_registry.py`
- `src/client/src/shared/types.ts`
- `tests/server/test_events.py`

执行要点：

- 核对所有 `s2c_*` 类型，保证 `s2c_team_message`、地图、遭遇、ready 事件都在服务端和前端类型中一致。
- 测试不要写固定数量断言，改为校验关键事件集合。
- 保留 `EngineEvent` camelCase alias，不破坏前端 WS 解析。

验收命令：

```bash
python -m pytest tests/server/test_events.py -q
```

禁止事项：

- 不新增与当前代码无关的频道大表。
- 不删除已有事件类型。
- 不把测试改成只检查“能运行”而不校验事件集合。

## Batch Channel-1：玩家 WS 补发受众过滤

目标：修正玩家重连时从 `events` 全量补发导致的越权风险。

允许修改：

- `src/server/main.py`
- `src/server/events/event_log.py`
- `src/server/host/ws_manager.py`
- `tests/server/test_ws_auth.py`
- 可新增 `tests/server/test_channel_security.py`

执行要点：

- 为玩家补发建立服务端过滤：允许 `party/system`，允许 payload 绑定当前 `characterId/character_id` 的 `player` 事件，拒绝 host-only 和其他角色私密事件。
- Host WS 继续只允许 owner/admin。
- 过滤逻辑应可复用，后续 archive、events/public、reconnect 使用同一口径。
- 补测 `lastSequence` 场景：玩家 B 不能通过重连拿到玩家 A 的 `s2c_private_notice`。

验收命令：

```bash
python -m pytest tests/server/test_ws_auth.py tests/server/test_reconnect.py tests/server/test_event_log.py -q
```

禁止事项：

- 不依赖前端忽略事件来保护隐私。
- 不把所有 player audience 事件直接广播给所有玩家。
- 不让 Host-only 事件进入玩家补发流。

## Batch Channel-2：队伍消息接口加固

目标：把 `/api/player/team-message` 从可用接口加固成稳定 P0 能力。

允许修改：

- `src/server/player/router_player.py`
- `src/server/models.py`
- `tests/server/test_player_features.py`
- 可新增 `tests/server/test_channel_messages.py`

执行要点：

- 增加请求 DTO，例如 `TeamMessageRequest`，字段为 `text` 与 `source`。
- `text` 去首尾空白，空文本返回 400，超长文本返回 413 或 400。
- `source` 限制为 `text/voice/system_import` 中的明确集合。
- 返回服务端生成的 `messageId`，不信任前端提交的发送者身份。
- 保留 `ProjectionDispatcher.emit(room_id,"s2c_team_message","party",payload)` 路径。

验收命令：

```bash
python -m pytest tests/server/test_player_features.py tests/server/test_projection.py -q
```

禁止事项：

- 不让玩家传入 `characterId` 覆盖服务端身份。
- 不在 team-message 里触发 AI 裁决或状态写入。
- 不把聊天内容写进 actions 表。

## Batch Channel-3：队伍消息历史与玩家归档

目标：刷新页面后能恢复最近队伍消息，玩家归档能按权限查询队伍消息。

允许修改：

- `src/server/player/router_player_archive.py`
- `src/server/router_archive.py`
- `src/client/src/pages/PlayerLobby.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- `tests/server/test_archive.py`

执行要点：

- 将 `s2c_team_message` 纳入玩家可见归档类型，可新增 `type=messages`。
- 大厅加载时查询最近队伍消息，按 `sequence` 升序展示，避免和乐观消息重复。
- 游戏内 logs 面板可显示队伍消息，但不把队伍消息混成公开叙事。
- Host timeline 可过滤 `s2c_team_message`。

验收命令：

```bash
python -m pytest tests/server/test_archive.py tests/server/test_event_log.py -q
cd src/client && npm run build
```

禁止事项：

- 不把其他玩家私密 `player` 事件放入 messages 查询。
- 不一次性加载全量历史，必须限制 limit。
- 不为了历史恢复引入与 events 冲突的第二套真相日志。

## Batch Channel-4：公共叙事、OOC、系统、骰子语义分层

目标：让不同信息类型在协议和 UI 上可区分，避免 AI 上下文混淆。

允许修改：

- `src/server/events/events_registry.py`
- `src/server/player/router_player.py`
- `src/server/rules/`
- `src/server/engine/resolution_pipeline.py`
- `src/client/src/pages/PlayerActionPage.tsx`
- `src/client/src/components/HostLogsPanel.tsx`
- 对应测试文件

执行要点：

- 保持 `s2c_public_observation` 作为公开叙事。
- 队伍消息标注为 `source=player_chat`，OOC 后续标注为 `mode=ooc`。
- 骰子与检定结果继续由 Rule/Engine 生成，不允许前端直接声明结果。
- AI 消费上下文时必须把 `player_chat/ooc/system/narrative` 分开传入。

验收命令：

```bash
python -m pytest tests/server/test_rule_executor.py tests/server/test_resolution_pipeline.py tests/server/test_spoiler_guard.py -q
cd src/client && npm run build
```

禁止事项：

- 不把 OOC 或队伍闲聊自动写入世界状态。
- 不把前端骰子展示当成权威检定结果。
- 不复制一套与 Journal 冲突的日志格式。

## Batch Channel-5：端到端回归

目标：验证 Channel 能支撑主链路，而不破坏 Room/User/Projection。

手动验收链路：

1. Host 创建房间并进入大厅。
2. 玩家加入房间并进入大厅。
3. 玩家发送队伍消息，Host 和玩家都收到。
4. 玩家 ready，Host 开局。
5. 玩家在游戏内提交行动，收到公开叙事和行动回执。
6. 玩家刷新页面，最近队伍消息与事件日志可恢复。
7. 玩家 A 的私密事件不会出现在玩家 B 的 WS、archive、public events。

验收命令：

```bash
python -m pytest tests/server/test_ws_auth.py tests/server/test_archive.py tests/server/test_event_log.py tests/server/test_projection.py tests/server/test_player_intent.py -q
cd src/client && npm run build
```

禁止事项：

- 不修改无关平台模块。
- 不重命名既有公开接口。
- 不把长期社区功能混入本轮 Channel 主链路。

## DeepSeek 交付要求

- 每个 Batch 提交前先运行定向测试，并在提交说明里写清命令和结果。
- 触碰权限、WS、archive 时必须新增或更新安全测试。
- 所有新增响应字段要保持 camelCase 前端友好格式，数据库内部字段可继续 snake_case。
- 若发现旧文档与当前代码冲突，以当前代码为准，并在对应模块文档记录风险。

