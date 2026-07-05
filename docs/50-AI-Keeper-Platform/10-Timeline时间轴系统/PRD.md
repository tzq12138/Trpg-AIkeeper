# Timeline 时间轴系统 PRD V2.0

## 背景

AI-Keeper 的核心链路需要可靠的顺序感：玩家什么时候提交行动，哪一轮被结算，Host 先看到哪些裁决步骤，玩家什么时候收到投影，断线后从哪里补发，复盘时按什么顺序阅读。当前系统已有 `room_turns`、`actions.turn_id`、`events.sequence`、`player_sequences`、checkpoint 和 archive，但还缺少统一的 Timeline 产品边界。

本 PRD 把 Timeline 定位为“顺序与可见性索引层”。它承接回合、事件和回放，但不替代 Journal 的内容存储，也不替代 State 的游戏内时间。

## 产品目标

1. 保证每个 active 房间始终有清晰的当前回合。
2. 保证玩家行动能稳定归属到当前回合。
3. 保证回合结算只发生一次，并按明确顺序推进。
4. 保证 Host 和 Player 看到的时间线符合权限边界。
5. 保证断线重连和回放使用同一 sequence 口径。
6. 为未来游戏内时间、倒计时、阵营时钟留下稳定接入点。

## 非目标

- 不做完整战役日历 UI。
- 不做 NPC 自动日程推演。
- 不做多世界线和时间旅行分支。
- 不用 Timeline 直接裁决行动结果。
- 不把 host-only 或其他玩家私密事件暴露给 Player。
- 不让 AI 直接写时间线事件或修改 sequence。

## 角色与权限

| 角色 | 能力 | 限制 |
| --- | --- | --- |
| Host | 查看完整房间时间线、当前回合、checkpoint、回放事件 | 只能管理自己房间，操作需要审计 |
| Player | 查看公开历史、自己的行动历史、自己的私密事件 | 不能读取 host-only 和其他玩家 private 事件 |
| Admin | 调试全量时间线和归档 | 导出默认要脱敏 |
| AI-Keeper | 读取允许范围内的近期事件和当前回合上下文 | 只能读投影后的上下文，不能绕过权限 |
| Engine | 推动 action 状态和 turn 结算 | 不直接展示时间线 |
| Journal | 保存事件正文、checkpoint、archive | Timeline 只引用其顺序和索引 |

## 范围

### 本轮进入

- 回合创建、收集、结算、创建下一回合。
- 玩家行动绑定 turn。
- duplicate 行动保护。
- Host skip 和 retry 的时序约束。
- `events.sequence` 作为事件顺序主键。
- Host timeline 查询和单事件回放。
- Player archive 查询和可见性过滤。
- reconnect 补发过滤。
- checkpoint 创建/恢复与时间线关系。

### 本轮暂不进入

- 复杂游戏内历法。
- 阵营自动时钟。
- 长团年表生成。
- 时间线手动重排。
- 多房间共享世界线。

## 核心流程

### 开局创建回合

Host 开始房间后，系统把 room 设为 active，创建 auto checkpoint，并创建第 1 个 collecting turn。开局响应返回 `turn_id` 和 `turn_index`。

验收：同一房间开局后只有一个 collecting turn；非 active 房间不会因为查询当前回合而产生无意义 turn。

### 玩家提交行动

玩家在 active 房间提交非 ready action。系统校验角色身份和当前回合，再写入 action，并把 action 绑定当前 `turn_id`。同一玩家在同一回合只能提交一次有效行动。

验收：重复提交返回 409，且不会留下无 `turn_id` 的 queued action。

### 回合结算

当所有参与者提交或 Host skip 后，当前 turn 从 collecting 进入 resolving。系统顺序 resolve queued actions，生成本轮叙事，写入 resolved 状态，创建下一回合，并发出 turn resolved 事件和公开叙事。

验收：同一个 turn 无论被多少入口触发结算，最终只 resolve 一次，只创建一个下一回合。

### Host 时间线

Host 在舞台日志面板查看完整房间事件，包括 Host 专属事件、系统事件、公开事件、地图/状态/行动事件。Host 可以按 event type、keyword、sequence 查看单事件详情。

验收：非房主、非 admin 不能读取；结果按 sequence 升序稳定返回。

### Player 历史

Player 在调查日志中查看公开叙事、行动结果、线索相关事件和自己的私密通知。Player 不能通过 archive 或 reconnect 看到 Host 专属事件或其他玩家私密事件。

验收：用两个玩家 token 查询 archive 和 reconnect，只能看到各自权限范围内事件。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| TL-FR-1 | active 房间必须有当前 collecting turn | P0 |
| TL-FR-2 | 玩家行动必须绑定 turn 后才算进入本轮 | P0 |
| TL-FR-3 | 同一玩家同一回合只能有一个非 rejected action | P0 |
| TL-FR-4 | duplicate 提交不得产生孤儿 action | P0 |
| TL-FR-5 | all submitted 必须基于合法参与者集合 | P0 |
| TL-FR-6 | 回合结算必须幂等 | P0 |
| TL-FR-7 | 所有投影事件必须有单调递增 sequence | P0 |
| TL-FR-8 | Player timeline/reconnect 必须按 audience 和 character 过滤 | P0 |
| TL-FR-9 | Host timeline 必须 owner/admin 鉴权 | P0 |
| TL-FR-10 | turn 相关事件必须进入事件注册表和前端类型 | P1 |
| TL-FR-11 | checkpoint restore 必须写审计事件 | P1 |
| TL-FR-12 | 游戏内时间初版必须由 StateService 管理 | P1 |

## 接口方向

| 接口 | 使用方 | 当前状态 | 权限 |
| --- | --- | --- | --- |
| `GET /api/rooms/{room_id}/turns/current` | Host | 已有 | owner/admin |
| `POST /api/player/intent` | Player | 已有 | player token |
| `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character` | Host | 已有 | owner/admin |
| `POST /api/rooms/{room_id}/turns/{turn_id}/retry` | Host | 已有 | owner/admin |
| `GET /api/rooms/{room_id}/timeline` | Host | 已有 | owner/admin |
| `GET /api/rooms/{room_id}/timeline/{sequence}` | Host | 已有 | owner/admin |
| `GET /api/player/archive` | Player | 已有 | player token |
| `GET /api/player/reconnect` | Player | 已有 | player token |
| `GET /api/rooms/{room_id}/checkpoints` | Host | 已有 | owner/admin |
| 未来 `GET /api/rooms/{room_id}/clock` | Host/Player | 未实现 | 分层投影 |

## 事件方向

| 事件 | Audience | 用途 | 当前注意点 |
| --- | --- | --- | --- |
| `s2c_action_queued` | player | 行动入队回执 | 当前由 Engine 写入 |
| `s2c_action_completed` | player | 行动结算完成 | 只能发给行动所属玩家 |
| `s2c_public_observation` | party | 公开叙事 | 可进入玩家公开时间线 |
| `s2c_reveal_transaction` | host | Host 演出步骤 | 不进入玩家 archive |
| `s2c_turn_resolved` | party | 本轮结算完成 | 需要补入 registry、model、前端类型 |
| `s2c_checkpoint_created` | system | checkpoint 创建 | system 对玩家是否可见要明确 |
| `s2c_checkpoint_restored` | system | checkpoint 恢复 | 应只给 Host 或安全公开摘要 |

## 可见性规则

| Audience | Host timeline | Player archive | Player reconnect |
| --- | --- | --- | --- |
| `host` | 可见 | 不可见 | 不可见 |
| `party` | 可见 | 可见 | 可见 |
| `system` | 可见 | 仅安全白名单可见 | 仅安全白名单可见 |
| `player` 且 `characterId` 为本人 | 可见 | 可见 | 可见 |
| `player` 且 `characterId` 为别人 | 可见 | 不可见 | 不可见 |

## 游戏内时间边界

游戏内时间不是 `issued_at`。它表示故事世界里的时间，例如“1927 年 10 月 3 日 23:40”“仪式还剩 3 轮”“暴风雨将在 2 小时后到达”。第一版只需要支持 Host 或 Engine 通过 StateService 设置和推进，不做复杂历法和自动推演。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `gameTime.label` | 展示文本，例如“深夜 23:40” |
| `gameTime.sortKey` | 可排序值，例如 ISO 字符串或数字刻度 |
| `gameTime.turnIndex` | 关联最近一次 turn |
| `gameTime.updatedBy` | host、engine 或 system |
| `gameTime.reason` | 推进原因 |

## 验收标准

1. 开局后存在第 1 回合，状态为 collecting。
2. 玩家提交行动后，action 带当前 `turn_id` 和 `turn_index`。
3. 同一玩家重复提交不会产生第二条有效 action，也不会产生孤儿 queued action。
4. Host skip 后该玩家不再阻塞 all submitted。
5. 全员提交后当前 turn 只结算一次，并创建下一回合。
6. 所有事件按 sequence 升序可分页读取。
7. Host timeline 能读取完整房间事件，Player archive 只能读取安全事件。
8. Player reconnect 不补发 Host 专属事件和其他玩家私密事件。
9. `s2c_turn_resolved` 在后端 registry、模型和前端类型中一致。
10. 游戏内时间与真实写入时间分离，不再混用 `issued_at` 表示故事时间。
