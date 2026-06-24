# PRD-01 - Engine 意图生命周期与状态写入边界

**版本**: 1.0  
**状态**: 待开发  
**来源**: 全局协议、Player 模块 1/3/5、Host 模块 3  
**适用范围**: Engine、REST API、AI Tool Adapter、ProjectionBuilder

## 1. 背景

v2 架构的关键不是让前端更炫，而是把状态权威收回 Engine。AI 只能提出建议，Player 只能提交意图，Host 只能播放公共演出。所有 HP、SAN、物品、线索、场景进度变更必须由 Engine 校验、落库、生成审计序列，再投影到各端。

## 2. 目标

- 建立 `POST /api/player/intent` 到 `s2c_action_completed` 的完整动作生命周期。
- 明确 AI、Engine、Host、Player 的权限边界。
- 确保状态变更先落库后广播，广播失败可通过快照恢复。
- 为 Host 公共事务和 Player 私密 patch 提供同源结算。

## 3. 范围边界

**包含**
- Player 意图接收、幂等、并发版本校验。
- AI 结算建议进入 Engine 校验的流程。
- Engine 权威状态写入与投影输出。
- 动作完成、拒绝、超时和取消的前端解锁事件。

**不包含**
- 具体 COC 规则插件完整实现。
- 大模型供应商选择。
- 生产级登录注册。
- 复杂战斗/追逐二期规则。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-01-1 | 作为玩家，我点击行动后需要手机立即锁定，直到 Engine 明确完成或失败。 | P0 |
| US-01-2 | 作为开发者，我需要所有状态写入经过同一入口，以便避免 AI 或前端绕过规则。 | P0 |
| US-01-3 | 作为 KP，我需要公共演出和私密状态来自同一结算，以便玩家看到的结果一致。 | P0 |

## 5. 功能需求

1. `POST /api/player/intent` 请求体包含 `actionId`、`intentType`、`declaredIntent`、`baseStateVersion`、`params`。
2. `characterId` 必须由服务端从 `X-Room-Token` 解出，前端不得提交。
3. Engine 必须按 `actionId` 做幂等去重，重复请求返回原处理状态。
4. `baseStateVersion` 过期时返回 HTTP 409，并触发客户端快照重拉。
5. AI 输出只能作为 `ProposedResolution`，不得直接写角色、物品、线索或场景。
6. Engine 校验规则后写入权威状态，生成 `roomSequence` 和审计记录。
7. ProjectionBuilder 从同一权威结算生成 Host 事务、Player patch、私密通知、公共观察。
8. 每个已受理动作最终必须下发 `s2c_action_completed`，状态为 `resolved | rejected | expired | cancelled | timeout`。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| REST | `POST /api/player/intent` | 玩家行动、语音、物品、战术按钮统一入口 |
| Header | `X-Room-Token` | 轻量身份凭证 |
| Event | `s2c_action_completed` | 前端动作状态机解锁 |
| Event | `s2c_reveal_transaction` | Host 公共演出 |
| Event | `s2c_state_patch` | Player 状态同步 |
| Event | `s2c_private_notice` | 私密结果提醒 |

## 7. 状态与错误处理

- REST 返回 202 后，Player 状态进入 `RESOLVING`，等待 WebSocket 完成事件。
- HTTP 409 表示本地状态过期，Player 展示 toast 并调用同步接口。
- HTTP 429 表示频率限制，Player 解锁并提示稍后重试。
- AI 超时或 JSON 解析失败时，Engine 可降级为纯文本或 rejected，但必须发送 `s2c_action_completed`。
- Player 动作状态只允许 `IDLE | SUBMITTING | RESOLVING`，失败通过 toast 和 completed payload 表达，不新增 `REJECTED` 状态。

## 8. 验收标准

- 所有 Player 写操作都走 `POST /api/player/intent`，不存在 WebSocket 上行写请求。
- Engine 单测证明 AI 不能直接修改权威状态。
- 同一 `actionId` 重复提交不会重复扣血、重复发物品或重复解锁线索。
- 每个 202 动作都有最终 `s2c_action_completed`。
- 409/429/AI 超时都有明确前端恢复路径。

## 9. 测试场景

1. 玩家点击技能检定，REST 返回 202，Engine 结算后 Host 播放骰子，Player 收到 patch 和 completed。
2. 玩家重复提交同一 `actionId`，Engine 返回幂等结果，不产生第二次状态变更。
3. 两个玩家基于旧版本同时操作，后到请求收到 409 并触发同步。
4. AI 返回非法 JSON，Engine 降级为 rejected 并解锁 UI。

## 10. 风险依赖

- 依赖 room token 能稳定映射 `characterId`。
- 依赖数据库或事件日志能保证写入与序列号原子性。
- 规则插件未完成时，只能覆盖基础 skill_check、dialogue、move、use_item。

