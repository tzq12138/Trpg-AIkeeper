# PRD-00 - 全局协议与投影契约

**版本**: 1.0  
**状态**: 待开发  
**来源**: `HOST_PROTOCOL_CONTRACT.md` v2.0 修正版  
**适用范围**: Engine、Host、Player、AI Tool Schema、共享类型定义

## 1. 背景

现有最终版设计已经明确 Engine 是唯一状态写入者，Host/Player 都只消费投影事件。但文档中仍存在少量协议裂缝：Host 白名单提到 `s2c_host_snapshot`，协议枚举未声明；战术 prompt 同时出现 `text` 与 `narrative`；事务文本是否流式也容易误读。本 PRD 将全局事件信封、事件枚举、投影边界和修正口径冻结为后续开发的单一产品事实源。

## 2. 目标

- 建立统一 `EngineEvent<T>` 信封，所有 Engine 下行消息都通过该信封传输。
- 明确 `ProjectionBuilder` 负责把权威事件拆成 Host、Player、Party、System 四类投影。
- 冻结事件名、字段命名、REST 路径和 MVP 阶段文本策略。
- 防止前端越权、私密信息泄漏和多端协议漂移。

## 3. 范围边界

**包含**
- 事件信封字段、事件类型全集、可见性规则。
- Host/Player 投影拆包规则。
- `s2c_host_snapshot`、`s2c_tactical_prompt`、`narrative_text` 的修正口径。
- 废弃事件迁移声明。

**不包含**
- 具体 UI 组件实现。
- AI 提示词全文。
- 数据库表结构细节。
- 公网账号认证体系。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-00-1 | 作为前端开发者，我需要所有下行事件有同一信封，以便 Host/Player 路由器可以共享类型校验逻辑。 | P0 |
| US-00-2 | 作为 Engine 开发者，我需要明确投影拆分规则，以便同一权威结算不会把私密线索误发到公共大屏。 | P0 |
| US-00-3 | 作为测试人员，我需要事件类型全集稳定，以便编写端到端协议兼容测试。 | P0 |

## 5. 功能需求

1. `EngineEvent<T>` 必须包含 `eventId`、`roomId`、`type`、`roomSequence`、`audience`、`visibility`、`issuedAt`、`payload`。
2. `audience` 仅允许 `host | player | party | system`，禁止出现 `broadcast`。
3. Host 专属事件必须带 `hostSequence`；Player 专属事件必须带 `playerSequence`。
4. 字段统一使用 camelCase，任何 snake_case payload 都视为协议错误。
5. `s2c_host_snapshot` 正式加入事件全集，用于 Host 初始化、重连补发和房间切换后的公共快照。
6. `s2c_tactical_prompt` payload 统一为 `{ text, actions[] }`，禁止使用 `narrative` 字段。
7. `narrative_text` MVP 阶段 payload 使用完整 `text` 下发，由前端本地打字机渲染，不实现分块流式协议。
8. `s2c_status_sync`、`s2c_roll_event`、`s2c_combat_state` 废弃；掷骰和公共状态变化进入 `s2c_reveal_transaction.steps[]`。
9. `EngineEventType` 必须至少包含以下事件全集，新增 PRD 不得绕过本枚举自造事件：

```typescript
export type EngineEventType =
  // Host 公共演出
  | 's2c_reveal_transaction'
  | 's2c_resume_transaction'
  | 's2c_cancel_transaction'
  | 's2c_chat_stream'
  | 's2c_atmosphere'
  | 's2c_engine_state'
  | 's2c_scene_sync'
  | 's2c_host_snapshot'

  // Player 状态与私密信息
  | 's2c_full_snapshot'
  | 's2c_state_patch'
  | 's2c_private_notice'
  | 's2c_public_observation'
  | 's2c_tactical_prompt'

  // 大厅与游戏生命周期
  | 's2c_room_lobby_snapshot'
  | 's2c_campaign_ended'

  // 行动生命周期与批次
  | 's2c_action_queued'
  | 's2c_action_batched'
  | 's2c_action_completed'

  // 玩家交互纠错
  | 's2c_clarification_prompt'
  | 's2c_clarification_result';
```

## 6. 接口/事件依赖

| 类型 | 名称 | Auth | 用途 |
|---|---|---|---|
| WebSocket | `/ws?room={roomId}&role={role}&lastSequence={seq}` | Host/Player token | Host/Player 下行事件通道 |
| REST | `POST /api/rooms` | 房主本地会话 | 创建 AI KP 房间 |
| REST | `POST /api/rooms/:roomId/join` | 一次性邀请码/二维码签名 + 速率限制 | 加入房间并换取 `roomToken` |
| REST | `POST /api/rooms/:roomId/start` | 房主本地会话 | 所有人 ready 后开始游戏 |
| REST | `POST /api/player/intent` | `X-Room-Token` | Player 上行意图统一入口 |
| REST | `GET /api/player/sync` | `X-Room-Token` | Player 超时或重连后的兜底快照 |
| REST | `GET /api/player/actions/:actionId` | `X-Room-Token` | 查询 pending action 状态 |
| Event | `s2c_reveal_transaction` | Engine 投影 | Host 公共演出事务 |
| Event | `s2c_host_snapshot` | Engine 投影 | Host 公共快照 |
| Event | `s2c_full_snapshot` / `s2c_state_patch` | Engine 单播投影 | Player 私有状态同步 |
| Event | `s2c_room_lobby_snapshot` | Engine 投影 | 大厅成员与 ready 状态同步 |
| Event | `s2c_action_queued` / `s2c_action_batched` | Engine 单播投影 | Player 行动入队与归并反馈 |
| Event | `s2c_clarification_prompt` / `s2c_clarification_result` | Engine 单播投影 | 澄清补问与澄清结果 |
| Event | `s2c_campaign_ended` | Engine 投影 | 战役结束与档案入口 |
| Event | `s2c_tactical_prompt` | Engine 单播投影 | Player 结构化行动提示 |

## 7. 状态与错误处理

- 客户端收到 `roomId` 不匹配事件必须静默丢弃。
- 客户端收到序列号小于等于本地最后序列号的事件必须幂等丢弃。
- 客户端收到未知事件类型必须记录 warning，不得崩溃。
- 服务端生成投影时若无法确定 `audience`，必须拒绝发送并写入审计日志。
- JSON Patch 的 `baseStateVersion` 与客户端版本不一致时，客户端必须触发快照重拉。

## 8. 验收标准

- 共享协议类型中包含 `s2c_host_snapshot`，且 Host 路由白名单与枚举一致。
- 全仓库新协议 payload 字段均为 camelCase。
- `s2c_tactical_prompt` 只使用 `{ text, actions[] }`。
- `narrative_text` 示例只包含完整文本，不出现 chunk、seq、streamId 等分块字段。
- 协议测试覆盖未知事件、乱序事件、跨房间事件和重复事件。

## 9. 测试场景

1. Engine 生成公共掷骰结算，ProjectionBuilder 给 Host 生成 `s2c_reveal_transaction`，给相关玩家生成 `s2c_state_patch`。
2. Player A 获得私密线索，只有 A 收到 `s2c_private_notice` 和 `s2c_state_patch`。
3. Host 重连携带 `lastSequence`，Engine 补发缺失事件或下发 `s2c_host_snapshot`。
4. 前端收到 snake_case 字段样例，协议校验失败并记录错误。

## 10. 风险依赖

- 依赖共享类型文件先落地，否则 Host/Player 可能继续复制各自类型。
- `s2c_host_snapshot` 需要 Engine 支持公共快照构造。
- JSON Patch 路径必须与 Player Store 结构同步维护。
