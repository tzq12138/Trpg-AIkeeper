# Batch 4：线索证据链与防剧透

## 目标

让线索系统成为 COC 跑团的可靠事实层：线索有来源、归属、可见范围、分享记录和事件引用，防止私密信息误投影。

## 范围

- 线索发现状态：未发现、私密发现、团队共享、已解析。
- 线索归属：角色、玩家、队伍、房间。
- 私密线索分享生成团队可见摘要，不直接公开原文。
- 线索获得、分享、解析写入事件日志。
- AI 只能使用当前角色或团队已知线索作为可见上下文。

## 文件方向

| 区域 | 可能涉及路径 |
|---|---|
| 线索路由 | `src/server/player/router_clues.py` |
| 投影 | `src/server/engine/projection.py` |
| 事件日志 | `src/server/events/event_log.py`、`src/server/events/events_registry.py` |
| AI 上下文 | `src/server/ai/rag_context.py`、`src/server/ai/spoiler_control.py` |
| Player UI | `src/client/src/pages/PlayerInventory.tsx`、`PlayerActionPage.tsx` |
| Host UI | `src/client/src/pages/HostStage.tsx` |
| 测试 | `tests/server/test_clues.py`、`test_spoiler.py`、`test_player_features.py` |

## 验收命令

```powershell
python -m pytest tests/server/test_clues.py tests/server/test_spoiler.py tests/server/test_player_features.py -q
```

预期：私密线索、分享、防剧透和玩家查询相关测试通过。

## 手动验收

- 玩家 A 获得私密线索后，玩家 B 不可见。
- 玩家 A 主动分享后，玩家 B 和 Host 只看到团队公开摘要。
- 事件日志能查到线索来源行动、分享人和分享时间。
- AI 回复不会引用未授权线索。

## 禁止事项

- 不把私密线索原文直接广播到 party 或 host。
- 不用前端隐藏代替后端权限过滤。
- 不把玩家笔记默认升级为世界事实。
