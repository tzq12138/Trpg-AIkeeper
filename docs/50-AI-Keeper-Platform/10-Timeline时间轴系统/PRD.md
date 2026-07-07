# Timeline 时间轴系统 PRD V2.1

## 背景

AI-Keeper 的核心链路需要可靠的顺序感：玩家什么时候提交行动，属于哪一轮，哪一次结算先发生，Host 先看到哪些步骤，Player 从哪里补发历史，checkpoint 恢复后怎样解释时间线，故事内时间又如何与真实写入时间分开。

当前仓库已经存在：

- `room_turns`
- `actions.turn_id`
- `events.sequence`
- `player_sequences`
- checkpoint / restore
- Host timeline / Player archive / reconnect

但这些能力还没有被统一定义成一个完整的 Timeline 边界，尤其在 duplicate action、turn 并发结算、system 事件可见性、reconnect 过滤、restore 语义和 gameTime 写入权威上仍然松散。

## 当前阶段说明

本 PRD 对应 `P0 主链路 + 时间线顺序与可见性风险识别版`。

本轮目标是把 Timeline 收束成工程可执行版本，不追求完整年表产品、复杂历法、势力时钟或分支世界线。

## 产品目标

1. 保证 active 房间始终有清晰的当前回合。
2. 保证玩家行动稳定归属到当前 turn。
3. 保证回合结算只发生一次，并按明确顺序推进。
4. 保证 Host 和 Player 看到的时间线符合权限边界。
5. 保证 archive、reconnect、WS catch-up 使用同一可见性规则。
6. 保证 checkpoint/restore 在时间线上有可解释断点。
7. 保证 gameTime 与真实写入时间分离，并通过受控入口写入。

## 非目标

- 不做完整战役日历 UI
- 不做 NPC 自动日程推演
- 不做多世界线和时间旅行分支
- 不让 Timeline 直接裁决行动结果
- 不让 Timeline 直接写世界真相或角色数值
- 不让 AI 直接写 sequence、turn status、gameTime

## 角色与权限

| 角色 | 能力 | 限制 |
| --- | --- | --- |
| Host | 查看完整房间时间线、当前回合、checkpoint、恢复断点 | 只能管理自己房间，操作应可审计 |
| Player | 查看公开历史、自己的行动历史、自己的私密事件 | 不能读 host-only 和其他玩家 private 事件 |
| Admin | 调试全量时间线和归档 | 默认导出和 player-facing 视图仍需脱敏 |
| AI-Keeper | 读取允许范围内的近期事件和当前回合上下文 | 只能读投影后的上下文，不能绕过权限 |
| Engine | 推动 action 状态和 turn 结算 | 不直接定义前端展示口径 |
| Journal | 保存事件正文、checkpoint、archive | Timeline 只引用顺序、断点和索引 |
| StateService | 管理 gameTime 等状态字段 | Timeline 不直接越权写状态 |

## 模块边界

| 边界 | Timeline 负责 | 不负责 |
| --- | --- | --- |
| Room | 开局后的首回合、当前回合查询规则 | 房间成员、ready、审批本身 |
| Transaction | turn 顺序、事件 sequence、补发游标 | 规则裁决实现 |
| Projection | Host / Player 时间线视图过滤 | 其他模块的业务投影 |
| Journal | 顺序索引、断点解释 | 全量正文存储和导出 |
| State | gameTime 的展示和索引接入 | gameTime 权威写入逻辑 |

## Timeline 数据分层

| 层级 | 数据对象 | 用途 | 禁止混用 |
| --- | --- | --- | --- |
| L0 | `issued_at / created_at / completed_at` | 审计、真实服务器时间、排序辅助 | 不等于故事内时间 |
| L1 | `events.sequence` | timeline / archive / reconnect / replay 主游标 | 不等于 turn_index |
| L2 | `room_turns.turn_index`、`actions.turn_id` | 行动收集和结算批次 | 不等于事件顺序 |
| L3 | `player_sequences.last_delivered_sequence` | 玩家补发位置 | 不等于权限过滤结果 |
| L4 | `HostTimelineView` | Host 审计与回放视图 | 不能给 Player 复用 |
| L5 | `PlayerArchiveView` | 玩家过滤后历史 | 不能含 host-only 或他人 private |
| L6 | `checkpoints` | 状态恢复点、时间线断点 | 不等于“时间回滚本身” |
| L7 | `gameTime` | 故事世界里的时间和倒计时 | 不等于 `issued_at` |
| L8 | Journal 内容正文 | 日志正文、payload、摘要 | Timeline 只索引顺序，不替代内容存储 |

## TimelineEntry DTO 契约

### 最小公共结构 `TimelineEntryDTO`

```json
{
  "sequence": 123,
  "eventType": "s2c_public_observation",
  "audience": "party",
  "issuedAt": "2026-07-06T12:00:00Z",
  "turnId": "turn_xxx",
  "turnIndex": 3,
  "visibility": "party",
  "payload": {}
}
```

### `HostTimelineEntryDTO`

允许：

- `TimelineEntryDTO` 全字段
- 完整安全范围内 payload
- 审计字段、恢复断点字段、原因字段

### `PlayerTimelineEntryDTO`

允许：

- `sequence`
- `eventType`
- `issuedAt`
- `turnId`
- `turnIndex`
- `visibility`
- 已过滤的安全 payload

禁止：

- host-only payload
- 其他玩家 private payload
- 未白名单的 system payload
- 未过滤的线索正文、地图内部字段、真相字段

### `ReconnectEventDTO`

与 `PlayerTimelineEntryDTO` 同口径，不允许 reconnect 比 archive 拿到更多内容。

## 可见性规则

原始事件 `audience`：

- `host`
- `party`
- `player`
- `system`

Timeline 派生 `visibility` 建议统一为：

- `host`
- `party`
- `self`
- `system_safe`
- `private_filtered`

规则：

| 原始 audience | Host timeline | Player archive / reconnect |
| --- | --- | --- |
| `host` | 可见 | 不可见 |
| `party` | 可见 | 可见 |
| `player` 且为本人 | 可见 | 可见 |
| `player` 且为他人 | 可见 | 不可见 |
| `system` | 可见 | 仅安全白名单可见 |

补充要求：

- archive、reconnect、WS catch-up 必须复用同一 `can_player_see_event` 或等价 helper
- `payload.characterId` 与 `payload.character_id` 命名需统一适配，避免 self event 误判

建议的最小 system 白名单示例：

- 可 Player-visible：`s2c_turn_resolved`、`s2c_game_time_updated` 的 safe payload、`s2c_checkpoint_created` 的安全摘要（如果产品允许）
- 默认不可见：`s2c_checkpoint_restored` 原始审计、内部错误、debug 事件、restore reason、admin override

## events.sequence scope

- `events.sequence` 当前允许继续是全局 BIGSERIAL。
- 但所有查询、补发、回放、导出都必须以 `room_id + sequence` 为边界。
- “房间内 sequence 单调递增”是本模块真正依赖的产品语义。
- 是否引入 room-local sequence 属于后续优化，不在本轮强做。

## player_sequences 更新规则

`player_sequences.last_delivered_sequence` 必须更新为：

- 该玩家“实际安全收到”的最大 sequence

不能更新为：

- 房间全量 events 最大 sequence
- 过滤前的最大 sequence

否则会出现：

- host-only/system 非白名单事件把玩家游标推过头
- 之后 public event 被错误跳过
- reconnect 与 archive 口径不一致

## 回合生命周期与幂等

### 状态

- `collecting`
- `resolving`
- `resolved`
- `blocked`

### 约束

1. active 房间应最多只有一个 collecting turn。
2. active 房间在 resolving 阶段，当前 turn 可以是 `resolving`；不能为了“始终有 collecting turn”而提前开放下一 collecting turn。
3. duplicate action 不得产生第二条有效 action，也不得留下孤儿 queued action。
4. `collecting -> resolving` 必须通过条件更新或事务锁完成。
5. 只有成功抢到状态转移的 worker 才能进入 `_settle_turn_background`。
6. 一个 turn 最终只允许 resolve 一次。
7. 创建下一回合前必须检查是否已存在更新的 collecting turn。

duplicate 的“有效 action”状态默认包括：

- `queued`
- `batched`
- `resolving`
- `resolved`
- `completed`
- `blocked`

`rejected / cancelled` 默认不计入 duplicate 阻塞；如代码状态枚举与此不同，工程回执需明确实际实现集合。

建议工程口径：

```sql
UPDATE room_turns
SET status = 'resolving'
WHERE turn_id = ? AND status = 'collecting';
```

返回 1 才允许继续结算；返回 0 说明该 turn 已被其他 worker 接管或已不在 collecting。

## 合法参与者集合

all_submitted 使用的参与者集合必须与 `01-Room` / `05-Character` 对齐：

- `joined`：参与
- `pending_approval`：不参与
- `left/removed`：不参与
- `ready`：仅用于开局前，不作为 active 回合是否参与的唯一口径
- `active`：仅 legacy read compatibility，不应继续作为新写状态口径

## Host skip / retry 审计契约

### skip

最少记录：

- `roomId`
- `turnId`
- `turnIndex`
- `targetCharacterId`
- `actorAccountId`
- `reason`
- `createdAt`

### retry

最少记录：

- `roomId`
- `turnId`
- `fromStatus`
- `actorAccountId`
- `reason`
- `affectedActionIds`
- `newResolutionAttemptId`
- `createdAt`

补充要求：

- `skip / retry` 都要求 `reason`
- retry 默认只允许 `blocked` 或显式标记为 `retryable` 的 `resolved` turn
- `collecting / resolving` turn 不允许 retry

## checkpoint / restore 语义

本轮默认语义写死为：

1. restore 不删除旧历史的产品解释，只定义“从某个 snapshot 恢复出新历史分支”。
2. 当前实现允许 restore 重新插入 snapshot 内事件，因此旧 `sequence` 不保留。
3. restore 后必须写新的 `s2c_checkpoint_restored` 审计 marker。
4. 之后产生的新事件属于恢复后的新历史。
5. Player replay/export 继续走安全过滤，不得因为 restore 拿到 host-only 历史。

补充口径：

- `s2c_checkpoint_restored` 默认应作为 Host 可见审计事件
- 如产品需要通知 Player，应另发 party-safe 摘要事件，不直接下发 restore reason、snapshot 内容或 host-only payload

## gameTime 边界

gameTime 不是 `issued_at`。

它表示故事内时间，例如：

- `1927-10-03 23:40`
- `仪式还剩 3 轮`
- `暴风雨 2 小时后到达`

第一版要求：

- 只能由 Host 显式接口或 Engine/StateService 事务结果写入
- AI 只能建议，不直接落库
- Player 只读安全展示字段
- 如果 reason 带剧透，需要降级为 `safeReason`

建议字段：

| 字段 | 说明 |
| --- | --- |
| `gameTime.label` | 展示文本 |
| `gameTime.sortKey` | 排序值，可为 ISO 或数值 tick |
| `gameTime.turnIndex` | 关联最近一次 turn |
| `gameTime.updatedBy` | host / engine / system |
| `gameTime.reason` | 内部原因 |
| `gameTime.safeReason` | 面向玩家的安全说明 |

## 关键用户故事

### 1. 开局创建第 1 回合

Host 开局后，系统把 room 置为 active，并创建第 1 个 collecting turn。

验收标准：

- 开局后 exactly one collecting turn
- 非 active 房间不会因为查看 current turn 而自动生成 turn

### 2. 玩家提交行动并绑定 turn

Player 在 active 房间提交行动，系统先确认当前 turn 和 duplicate，再让 action 进入本轮。

验收标准：

- action 必带 `turn_id`
- duplicate 返回 409
- duplicate 不产生孤儿 action

### 3. 回合结算幂等

当所有合法参与者已提交或被 skip 后，系统只允许一个 worker 完成 resolving -> resolved -> next turn。

验收标准：

- 并发 settle 只成功一次
- 不会创建多个下一回合

### 4. Player archive 与 reconnect

Player 查看 archive 或断线重连，只能拿到同一套安全事件。

验收标准：

- archive 与 reconnect 过滤结果一致
- host-only、他人 private、非白名单 system 不可见
- `player_sequences` 只推进到安全返回的最大 sequence

### 5. checkpoint 恢复和时间线断点

Host 恢复 checkpoint 后，时间线中必须有清晰断点。

验收标准：

- 有 `checkpoint_restored` 审计 marker
- restore 后的新事件能与旧历史区分解释

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| TL-FR-1 | active 房间必须有当前 collecting turn | P0 |
| TL-FR-2 | 玩家行动必须绑定 turn 后才算进入本轮 | P0 |
| TL-FR-3 | 同一玩家同一回合只能有一个非 rejected action | P0 |
| TL-FR-4 | duplicate 提交不得产生孤儿 action | P0 |
| TL-FR-5 | all submitted 必须基于合法参与者集合 | P0 |
| TL-FR-6 | 回合结算必须幂等 | P0 |
| TL-FR-7 | timeline / archive / reconnect 必须按 `room_id + sequence` 使用顺序游标 | P0 |
| TL-FR-8 | Player archive / reconnect 必须复用统一可见性 helper | P0 |
| TL-FR-9 | `player_sequences` 只能按安全返回事件更新 | P0 |
| TL-FR-10 | Host timeline 必须 owner/admin 鉴权 | P0 |
| TL-FR-11 | `s2c_turn_resolved` 必须进入 registry / model / frontend type | P1 |
| TL-FR-12 | checkpoint restore 必须写审计事件并形成断点解释 | P1 |
| TL-FR-13 | gameTime 初版必须由 StateService 管理 | P1 |

## 接口方向

| 接口 | 使用方 | 作用 | 权限 |
| --- | --- | --- | --- |
| `GET /api/rooms/{room_id}/turns/current` | Host | 查看当前回合快照 | owner/admin |
| `POST /api/player/intent` | Player | 提交行动 | player token |
| `POST /api/rooms/{room_id}/turns/{turn_id}/skip-character` | Host | skip 某玩家本回合 | owner/admin |
| `POST /api/rooms/{room_id}/turns/{turn_id}/retry` | Host | 重试一个 turn | owner/admin |
| `GET /api/rooms/{room_id}/timeline` | Host | 读取完整房间时间线 | owner/admin |
| `GET /api/rooms/{room_id}/timeline/{sequence}` | Host | 读取单事件详情 | owner/admin |
| `GET /api/player/archive` | Player | 读取过滤后历史 | player token |
| `GET /api/player/reconnect` | Player | 断线重连补发 | player token |
| `GET /api/rooms/{room_id}/checkpoints` | Host | 查看 checkpoint 列表 | owner/admin |
| 未来 `GET /api/rooms/{room_id}/clock` | Host/Player | 读取 gameTime | 分层投影 |

## 事件方向

| 事件 | Audience | 用途 | 约束 |
| --- | --- | --- | --- |
| `s2c_action_queued` | player | 行动入队 | 只给所属玩家 |
| `s2c_action_completed` | player | 行动结算完成 | 只给所属玩家 |
| `s2c_public_observation` | party | 公开叙事 | 可进入玩家公开时间线 |
| `s2c_reveal_transaction` | host | Host 演出步骤 | 不进入玩家 archive/reconnect |
| `s2c_turn_resolved` | party | 本轮结算完成 | 需补入 registry/model/TS |
| `s2c_checkpoint_created` | system | checkpoint 创建 | Player 是否可见取决于白名单 |
| `s2c_checkpoint_restored` | host | checkpoint 恢复审计 | 默认仅 Host 可见；如要通知 Player，应另发 party-safe 摘要 |
| 未来 `s2c_game_time_updated` | system/party | gameTime 推进 | Player 只收安全展示字段 |

## 验收标准

1. 开局后存在第 1 回合，状态为 collecting，且仅有一个 collecting turn。
2. `GET /turns/current` 在非 active 房间不产生新 turn。
3. 玩家提交行动后，action 带当前 `turn_id` 和 `turn_index`。
4. duplicate 提交不会产生第二条有效 action，也不会留下孤儿 queued action。
5. `all_submitted` 只计算合法参与者，`pending_approval/left` 不阻塞回合。
6. 同一 turn 无论多少入口触发结算，最终只 resolve 一次，只创建一个下一回合。
7. Host timeline 按 `room_id + sequence` 稳定读取完整房间事件。
8. Player archive / reconnect 使用相同过滤规则，不看到 host-only、他人 private、非白名单 system。
9. `player_sequences` 只推进到实际安全返回事件的最大 sequence。
10. checkpoint restore 后有 `checkpoint_restored` 标记，时间线断点可解释。
11. `s2c_turn_resolved` 在后端 registry、Pydantic Literal 和前端 TS 类型中一致。
12. gameTime 与真实写入时间分离，不再混用 `issued_at` 表示故事时间。
