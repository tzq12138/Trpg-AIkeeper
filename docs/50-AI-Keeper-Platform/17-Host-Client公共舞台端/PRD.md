# Host Client 公共舞台端 PRD 初版

## 目标

提供稳定公共舞台，展示 AI-Keeper 的共同现实、场景、事务演出和玩家状态摘要。

## 范围

包含 Host Lobby、公共旁白、场景展示、HUD、事务状态、Watchdog、紧急清屏和演出恢复。不包含完整 KP 后台、直播适配和复杂视频特效。

## 角色

| 角色 | 权限 |
|---|---|
| 房主 | 启动大屏、暂停/恢复、有限急救。 |
| 玩家 | 共同观看公共舞台。 |
| Engine | 下发公共投影和事务状态。 |
| Projection | 过滤 Host 可见内容。 |

## 用户故事

| 编号 | 用户故事 | 优先级 |
|---|---|---:|
| HOST-1 | 作为房主，我能看到玩家 ready 并开始游戏。 | P0 |
| HOST-2 | 作为玩家，我能在大屏看到公共旁白。 | P0 |
| HOST-3 | 作为系统，我能在演出卡住时恢复。 | P0 |
| HOST-4 | 作为房主，我能看到公共状态摘要但不剧透。 | P0 |

## 数据边界

Host 接收公共投影、公共 HUD 和事务演出状态。私密线索、KP-only 真相和玩家个人暗线不进入 Host payload，除非 Engine 生成公共摘要。

## 接口 / 事件方向

- REST：查询 HUD、查询当前房间、执行有限急救。
- WS：Host snapshot、transaction step、stage narrative、scene update、HUD update。
- Event：Host 操作写审计。

## 验收标准

- Host 大屏可从 Lobby 进入 Stage。
- 公共旁白、场景和 HUD 实时更新。
- Host 不接收玩家私密线索。
- 演出超时后能恢复或清屏。

