# AI-Keeper 最终版本开发文档

**版本**: 1.0  
**状态**: 待开发  
**来源**: `模块设计/最终版本/PRDs` 中 PRD-00 到 PRD-28  
**定位**: 将 PRD 转换为可执行的工程开发说明。  

## 1. 开发目标

本版本目标是实现一个 **AI 自动 KP 跑团系统**：

- 剧本准备者只导入文字版 PDF，系统自动结构化并生成质量报告。
- 房主创建房间、选择剧本、邀请玩家、启动 Host 大屏；房主可以作为普通玩家参与。
- 玩家用手机加入房间、导入 xlsx 角色卡、ready、语音提交行动、接收私密线索和复盘档案。
- AI KP 接收玩家自由行动批次，按防剧透策略生成叙事和结算建议。
- Engine 是唯一权威状态写入者，负责规则校验、落库、事件日志和投影。
- Host 大屏展示公共舞台、骰子、状态、场景、字幕和氛围。
- Player 手机展示个人状态、行动回执、私密线索、目标、纠错和个人档案。

## 2. 工程分层

### 2.1 服务端分层

| 层 | 职责 | 关键能力 |
|---|---|---|
| API Layer | REST/WebSocket 入口 | 房间、玩家、剧本、意图、同步、回放 |
| Engine Core | 权威状态与规则结算 | 状态写入、幂等、版本校验、事件序列 |
| AI KP Orchestrator | 自动主持循环 | 行动批次、上下文过滤、AI 输出解析 |
| Scenario Pipeline | 剧本导入处理 | PDF 抽取、结构化、质量报告 |
| ProjectionBuilder | 事件投影 | Host/Player/Party/System 拆包 |
| Event Log | 审计、回放、检查点 | EventLogEntry、Checkpoint、Archive |

### 2.2 前端分层

| 端 | 职责 | 关键页面/模块 |
|---|---|---|
| Host | 公共演出大屏 | 舞台、HUD、事务播放器、氛围、骰子 |
| Player Mobile | 玩家个人终端 | 入房、角色导入、行动面板、线索、档案 |
| Owner Console | 房主薄权限控制 | 开房、邀请、ready、暂停、重试 |
| Scenario Import | 剧本准备入口 | PDF 导入、任务进度、质量报告、一键开局 |

## 3. 核心边界

1. **AI 不写状态**  
   AI 只输出建议。HP、SAN、物品、线索、场景进度必须由 Engine 校验后写入。

2. **Player 不越权**  
   Player 只能通过 `POST /api/player/intent` 提交意图。角色身份以 `X-Room-Token` 解密结果为准。

3. **Host 不判定**  
   Host 只消费事件，播放公共演出，不承载规则逻辑。

4. **房主不剧透**  
   房主可开房、暂停、重试和有限急救，但不能看到完整真相、未发现线索或其他玩家私密信息。

5. **PDF 本地优先**  
   剧本原文和结构化结果本地保存；云 AI 只接收当前处理所需片段。

## 4. 核心类型

### 4.1 通信信封

```typescript
interface EngineEvent<T = unknown> {
  eventId: string;
  roomId: string;
  type: EngineEventType;
  roomSequence: number;
  hostSequence?: number;
  playerSequence?: number;
  audience: 'host' | 'player' | 'party' | 'system';
  visibility: 'public' | 'private' | 'party' | 'hostOnly';
  transactionId?: string;
  sourceActionId?: string;
  issuedAt: number;
  payload: T;
}
```

### 4.2 必备业务类型

| 类型 | 用途 |
|---|---|
| `ScenarioImportJob` | PDF 导入任务状态 |
| `ScenarioKnowledgeGraph` | 场景、NPC、线索、真相、结局结构 |
| `ScenarioQualityReport` | 剧本可开局质量报告 |
| `SpoilerProfile` | 防剧透档位：strict/standard/cinematic |
| `PlayerOnboardingState` | 玩家入房和 ready 状态 |
| `CharacterCompatibilityReport` | xlsx 角色与剧本标签适配报告 |
| `ActionReceipt` | 玩家单个行动回执 |
| `ActionBatch` | 自由行动归并批次 |
| `ActionBatchStatus` | queued/batched/resolving/completed |
| `PrivateClueShareRequest` | 私密线索分享请求 |
| `PersonalObjective` | 可选个人目标 |
| `EventLogEntry` | 权威事件日志 |
| `Checkpoint` | 场景或暂停恢复点 |
| `PlayerArchiveQuery` | 玩家个人档案查询 |
| `EndingReport` | 结局和战役档案摘要 |

## 5. REST 接口

| 方法 | 路径 | Auth | 职责 |
|---|---|---|---|
| POST | `/api/scenarios/import-pdf` | 本地会话 | 上传文字 PDF，创建导入任务 |
| GET | `/api/scenarios/import-jobs/:jobId` | 本地会话 | 查询导入进度 |
| GET | `/api/scenarios/:scenarioId/quality-report` | 本地会话 | 查询质量报告 |
| POST | `/api/scenarios/:scenarioId/create-room` | 房主本地会话 | 从剧本一键创建房间 |
| POST | `/api/rooms` | 房主本地会话 | 创建房间 |
| POST | `/api/rooms/:roomId/join` | 一次性邀请码/二维码签名 | 玩家加入房间 |
| POST | `/api/rooms/:roomId/start` | 房主本地会话 | 开始游戏 |
| POST | `/api/player/character/import-xlsx` | `X-Room-Token` | 导入 xlsx 角色卡 |
| POST | `/api/player/intent` | `X-Room-Token` | 玩家所有写操作入口 |
| GET | `/api/player/sync` | `X-Room-Token` | Player 全量同步 |
| GET | `/api/player/actions/:actionId` | `X-Room-Token` | 查询 pending action |
| GET | `/api/player/archive` | `X-Room-Token` | 查询个人档案 |
| GET | `/api/rooms/:roomId/replay` | 房主/玩家权限 | 公共回放 |
| POST | `/api/rooms/:roomId/restore/:checkpointId` | 房主权限 | 从检查点恢复 |

## 6. WebSocket 事件

### 6.1 Host 事件

- `s2c_host_snapshot`
- `s2c_reveal_transaction`
- `s2c_resume_transaction`
- `s2c_cancel_transaction`
- `s2c_atmosphere`
- `s2c_engine_state`
- `s2c_scene_sync`
- `s2c_campaign_ended`

### 6.2 Player 事件

- `s2c_room_lobby_snapshot`
- `s2c_full_snapshot`
- `s2c_state_patch`
- `s2c_private_notice`
- `s2c_public_observation`
- `s2c_tactical_prompt`
- `s2c_action_queued`
- `s2c_action_batched`
- `s2c_action_completed`
- `s2c_clarification_prompt`
- `s2c_clarification_result`
- `s2c_campaign_ended`

## 7. 核心流程

### 7.1 PDF 到可开房

1. 准备者上传文字 PDF。
2. Scenario Pipeline 抽取文本并按页/标题/段落切片。
3. AI/脚本生成 `ScenarioKnowledgeGraph`。
4. 系统生成 `ScenarioQualityReport`。
5. 报告为 `ready/warning/highRisk` 时可一键开局；`blocked` 不允许开局。
6. 创建房间并绑定剧本结构、防剧透档位和房主权限。

### 7.2 房主开房

1. 房主选择剧本和防剧透档位。
2. 系统生成房间码、玩家二维码、Host 大屏链接。
3. 房主可作为玩家导入角色卡。
4. 全员 ready 后房主开始游戏。
5. 游戏中房主可暂停、继续、重试最近 AI 回合或提交急救说明。

### 7.3 玩家入局

1. 玩家扫码或输入房间码。
2. 输入玩家名，获得 `roomToken`。
3. 上传 xlsx 角色卡。
4. 查看解析预览和适配报告。
5. 确认导入，点击 ready。
6. 等待 AI KP 开场。

### 7.4 自由行动批次

1. 玩家在手机行动面板按住说话。
2. STT 转写后通过 `POST /api/player/intent` 提交。
3. Engine 返回 202，Player 显示 queued。
4. 收集窗口到达条件后生成 `ActionBatch`。
5. Player 收到 `s2c_action_batched`，显示“守秘人裁决中”。
6. AI KP 读取批次并生成结算建议。
7. Engine 校验、落库、投影 Host/Player 事件。
8. Player 收到 `s2c_action_completed`，输入恢复。

### 7.5 AI KP 主持

1. AI KP 输入当前场景、公开事实、玩家行动批次、暴露度和可见线索。
2. Projection/Context Builder 按 `SpoilerProfile` 过滤未授权真相。
3. AI 输出结构化结果：叙事、检定建议、状态建议、线索建议、下一目标。
4. Engine 校验 AI 建议并生成权威事件。
5. Host 播放公共事务；Player 接收私密 patch、通知和战术 prompt。

### 7.6 私密线索分享

1. Engine 单播私密线索给拥有者。
2. 玩家可在手机线索详情点击分享。
3. Player 提交 `share_clue`。
4. Engine 校验拥有权，并生成团队可见 `publicSummary`。
5. Host/其他 Player 只看到公开版本。

### 7.7 澄清纠错

1. 玩家对最近行动或结算提交 `clarification_request`。
2. 默认窗口为最近 5 分钟或最近 3 个 AI KP 回合。
3. AI KP 返回解释、补问或重算建议。
4. Engine 只有确认规则或输入错误时才生成修正事务。
5. 超出窗口的请求只记录备注，不触发重算。

### 7.8 存档回放

1. 所有权威状态变更写入 `EventLogEntry`。
2. 场景开始/结束和手动暂停创建 `Checkpoint`。
3. 公共 Host 事件可只读回放。
4. 房主可从检查点恢复继续。
5. 首版不做任意事件回滚和分支时间线。

### 7.9 自动结局和复盘

1. AI KP 判断可能达成结局。
2. Engine 校验结局条件。
3. Host 播放公共结局事务。
4. 房间进入只读/回放状态。
5. Player 进入个人档案，可自由查询线索、行动、检定、状态变化和回放片段。

## 8. 开发里程碑

### M1: 协议与数据底座

- 实现共享 `EngineEventType` 和 payload 类型。
- 建立 Engine 事件日志、序列号、幂等和快照基础。
- 实现 `ProjectionBuilder` 的 Host/Player 拆包。
- 建立基础 REST/WebSocket 框架。

**验收**: 能创建房间、连接 Host/Player、发送快照和基础事件。

### M2: PDF 导入到一键开房

- 实现文字 PDF 抽取和导入任务。
- 生成基础 `ScenarioKnowledgeGraph`。
- 生成质量报告。
- 一键创建房间和二维码。

**验收**: 上传文字 PDF 后能创建一个可进入的房间。

### M3: 玩家手机入局

- 实现扫码/房间码加入。
- 实现 xlsx 角色卡导入和适配报告。
- 实现大厅 ready 和 `s2c_room_lobby_snapshot`。

**验收**: 玩家可仅用手机完成入房、导入角色、ready。

### M4: 行动批次与 AI KP

- 实现语音/文字/按钮统一意图提交。
- 实现 `queued -> batched -> completed`。
- 实现 AI KP 主持循环和 Engine 校验。
- 实现 Host 公共事务播放。

**验收**: 多玩家提交行动后，AI KP 能生成公共叙事和个人反馈。

### M5: 私密信息与防剧透

- 实现 `SpoilerProfile` 三档。
- 实现私密线索单播和主动分享。
- 实现个人目标和当前团队目标。

**验收**: 未发现线索不泄漏，玩家主动分享后团队可见。

### M6: 稳定性与复盘

- 实现断线重连和全量同步。
- 实现澄清请求。
- 实现事件日志、检查点、公共回放。
- 实现自动结局和个人档案查询。

**验收**: 手机刷新可恢复，房间可暂停恢复，局后可自由查询档案。

## 9. MVP 边界

### 首版必须做

- 文字 PDF 导入，扫描 PDF/OCR 后置。
- xlsx 角色卡导入，图片/PDF 角色卡后置。
- Host 大屏公共演出。
- Player 手机竖屏行动面板。
- 语音优先，文字兜底。
- 自由行动批次，不做严格回合制。
- 事件日志 + 检查点，不做任意事件回滚。
- `narrative_text` 完整文本下发，本地打字机播放。

### 明确后置

- 内置 OCR。
- 完整剧本编辑器。
- 远程队伍聊天。
- 队长投票系统。
- 任意事件回滚和分支时间线。
- `notifyTypewriterDone` blocking 字幕回调链。
- 完整战斗/追逐规则扩展。
- 精美 PDF 战报导出。

## 10. 测试策略

### 10.1 协议测试

- 所有事件都属于 `EngineEventType`。
- snake_case payload 被拒绝。
- 重复 `eventId` 和旧序列号被幂等丢弃。
- Host 不接收 Player 私密事件。

### 10.2 API 测试

- join 端点校验邀请码/二维码签名和速率限制。
- `POST /api/player/intent` 不接受前端传入的 `characterId` 作为安全身份。
- pending action 可查询。
- sync 能恢复完整 Player 状态。

### 10.3 剧本导入测试

- 文字 PDF 可抽取并结构化。
- 扫描 PDF 返回 `requires_ocr` 或 blocked。
- 质量报告能标出缺真相、缺结局、缺线索风险。

### 10.4 玩家流程测试

- 手机完成入房、导入角色、ready。
- 语音提交后看到完整回执链。
- 断线重连后恢复私密线索和 pending action。
- 私密线索分享前不出现在队友端。

### 10.5 AI KP 测试

- 多玩家行动能归并成批次。
- AI 越界输出未授权真相时被 Engine 拦截。
- AI 输出非法状态变更时不落库。
- 澄清请求在窗口内可解释或重算。

### 10.6 Host 演出测试

- 普通事务按 step 顺序播放。
- Urgent 可插队并恢复。
- Dice 失败时 Watchdog 推进。
- 背景、字幕、HUD、氛围不互相阻塞。

### 10.7 存档复盘测试

- 场景检查点可恢复。
- 公共 Host 事件可回放。
- Player 档案按权限过滤。
- 结局后房间默认只读。

## 11. 开发注意事项

- 不要把 AI 输出当作数据库写入命令。
- 不要让 URL `characterId` 参与权限判定。
- 不要让房主看到 KP-only 真相。
- 不要把未发现线索放进玩家提示词上下文。
- 不要在 MVP 中实现网络分块叙事流。
- 不要把 Player 手机端做成桌面后台式密集 UI。
- 不要让 `join` 成为无保护的刷房入口。
- 不要绕过事件日志直接修改状态。

## 12. 参考 PRD

- 协议与 Engine: PRD-00, PRD-01
- Host: PRD-02 到 PRD-06
- Player 基础模块: PRD-07 到 PRD-11
- 玩家手机旅程: PRD-12 到 PRD-20
- 房主与剧本: PRD-21 到 PRD-23
- AI KP 与存档复盘: PRD-24 到 PRD-28

