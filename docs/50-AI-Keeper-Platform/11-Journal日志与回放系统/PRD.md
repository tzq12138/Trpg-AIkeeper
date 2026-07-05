# Journal 日志与回放系统 PRD V2.0

## 背景

AI-Keeper 的核心体验不是让 AI 随口讲故事，而是让每次玩家意图、裁决、状态变化、投影展示都留下可追溯证据。Journal 是这条证据链的产品化承载层：Host 用它复盘和回滚，Player 用它查自己的行动与线索，系统用它导出战报和审计安全边界。

当前代码已经有 `events`、`checkpoints`、`campaign_archives`、Host 日志面板、Player archive、Markdown/JSON export，但权限和可见性过滤仍分散，需要先把边界统一。

## 目标

1. 为每个权威变化保留可查询、可分页、可引用的事件记录。
2. 为 Host 提供全量日志、checkpoint、恢复和导出能力。
3. 为 Player 提供仅限自身权限范围内的行动、检定、线索、公开剧情档案。
4. 让 public/full export 明确分层，避免剧透和 token 泄露。
5. 让战役结束后的归档摘要来自真实事件，而不是 AI 自由补写。

## 非目标

1. 不在 Journal 内执行规则裁决。
2. 不在 Journal 内直接修改世界状态或角色数值。
3. 不把 Admin/Ops 的 AI 调用日志开放给普通玩家。
4. 不在本模块实现完整社区战报、语音回放、多媒体剪辑。
5. 不把 Host 全知视角等同于玩家可见战报。

## 用户角色

| 角色 | 权限目标 | 不允许 |
| --- | --- | --- |
| Host/Owner | 查看全量事件、创建/恢复 checkpoint、导出 full、结束归档。 | 绕过 State/Engine 直接改真相。 |
| Admin | 用于排查和安全审计，可访问全量日志与运维审计。 | 把 AI prompt、token、私密线索公开给玩家。 |
| Player | 查看公开事件、自己的行动、自己的私密线索和检定结果。 | 查看 Host-only、其他玩家私密事件、未发现线索。 |
| Observer | 未来只读公开视角。 | 访问 private/player 事件。 |
| AI-Keeper | 读取授权范围内历史摘要作为上下文。 | 读取未授权私密事件或把原始 prompt 写入公共日志。 |

## 核心流程

### 事件沉淀

Engine、State、Projection 完成校验后写入 `events`。每条事件必须包含 `room_id`、`sequence`、`event_type`、`audience`、`payload`、`issued_at`。关键事件应在 payload 中保留来源引用，例如 `actionId`、`transactionId`、`stateVersion`、`characterId`、`clueId`、`sourceEventSequence`。

### Host 审计与回放

Host 通过 timeline 查看全量事件，支持按 sequence、event_type、关键词定位。Host 可以查看单个事件详情，用于排查“玩家做了什么、系统怎么判、状态怎么变、投影给了谁”。

### Player 档案

Player archive 展示玩家可见的记录。party/public 事件可见，player/private 事件必须明确归属当前 `character_id`。缺失归属字段的私密事件默认不展示。

### Checkpoint 与恢复

Host/Admin 可以创建和恢复 checkpoint。恢复必须二次确认，并写入 `s2c_checkpoint_restored` 审计事件。当前实现会删除并重插部分房间数据，后续需要明确事件序列保留策略，并补齐间接关联表。

### 战役归档

Host 结束房间后生成 `campaign_archives`。归档摘要、highlights、character arcs 必须来自已发生事件、actions 和角色数据。面向 Player 的 summary 只能使用玩家可见事件。

### 导出

导出分为 public 和 full。public 需要 Player token 或更高权限，只包含公开事件和脱敏角色信息。full 需要 Owner/Admin，仍必须脱敏 token、API key、内部 prompt、账户敏感字段。

## 功能需求

| 编号 | 需求 | 优先级 | 验收 |
| --- | --- | --- | --- |
| JR-FR-1 | 记录权威事件流水 | P0 | 每次行动到投影都有事件记录和递增 sequence。 |
| JR-FR-2 | Host 全量 timeline | P0 | Owner/Admin 可查看全量事件，Player 请求返回 403。 |
| JR-FR-3 | Player 权限过滤 | P0 | Player 看不到其他玩家私密事件、Host-only 事件、AI debug。 |
| JR-FR-4 | public event 显式白名单 | P0 | 所有 public 查询不再依赖 `audience != 'player'`。 |
| JR-FR-5 | Checkpoint 创建和恢复 | P0 | 创建、列表、恢复接口权限正确，恢复后写审计事件。 |
| JR-FR-6 | public/full 导出分层 | P0 | public 无 token、私密线索、世界真相、原始 prompt。 |
| JR-FR-7 | campaign summary 鉴权 | P0 | 未授权用户不能读取战役摘要。 |
| JR-FR-8 | 事件 registry 覆盖 | P1 | 实际发出的 Journal 事件能在 registry 或兼容表中找到。 |
| JR-FR-9 | 来源引用链 | P1 | 关键事件可追到 action、transaction、stateVersion 或 clue。 |
| JR-FR-10 | 前端日志筛选一致 | P1 | Host/Player 面板筛选项与后端 API 支持一致。 |

## 接口方向

| 接口 | 当前状态 | 目标权限 | 返回范围 |
| --- | --- | --- | --- |
| `GET /api/rooms/{room_id}/events` | 已有 | Owner/Admin | 全量事件。 |
| `GET /api/rooms/{room_id}/events/public` | 已有，需收紧 | Room Player | 显式公开事件。 |
| `GET /api/rooms/{room_id}/timeline` | 已有 | Owner/Admin | 全量事件，可筛选。 |
| `GET /api/rooms/{room_id}/timeline/{sequence}` | 已有 | Owner/Admin | 单事件详情。 |
| `POST /api/rooms/{room_id}/checkpoint` | 已有 | Owner/Admin | 新建 checkpoint。 |
| `GET /api/rooms/{room_id}/checkpoints` | 已有 | Owner/Admin | checkpoint 列表。 |
| `POST /api/rooms/{room_id}/restore/{checkpoint_id}` | 已有 | Owner/Admin | 恢复结果和审计事件。 |
| `GET /api/player/archive` | 已有，需对齐类型 | Player | 玩家可见档案。 |
| `GET /api/player/archive/actions` | 已有 | Player | 本角色行动。 |
| `GET /api/player/archive/clues` | 已有，需强化归属 | Player | 本角色线索和公开线索。 |
| `GET /api/player/archive/skill-checks` | 已有 | Player | 本角色检定。 |
| `GET /api/rooms/{room_id}/campaign` | 已有，需加鉴权 | Player 或 Owner/Admin | 按权限裁剪的摘要。 |
| `POST /api/rooms/{room_id}/end` | 已有 | Owner/Admin | 战役结束归档。 |
| `GET /api/rooms/{room_id}/export` | 已有，需脱敏 | public: Player, full: Owner/Admin | Markdown 或 JSON。 |

## 可见性策略

| 视角 | 可见内容 | 不可见内容 |
| --- | --- | --- |
| Host/Owner full | 房间全量事件、checkpoint、内部审计摘要。 | API key、原始密钥、非必要完整 AI prompt。 |
| Player private | 公开事件、本角色私密事件、本角色行动和检定。 | 其他玩家私密事件、Host-only、未发现线索、模组真相。 |
| Public export | 已公开剧情、公开线索、脱敏角色信息、公开结局。 | token、账号 ID、角色卡原始私密字段、AI prompt、世界书真相。 |
| Admin audit | 运维排查需要的全量日志和安全审计。 | 不应进入玩家 UI 或 public export。 |
| AI context | 授权范围内的事件摘要和引用。 | 未授权私密内容、未来事件、未发现线索。 |

## 数据边界

1. `events.payload` 可以保存结构化结果，但不应保存原始密钥、API key、完整未裁剪 prompt。
2. 私密事件必须包含明确归属字段，例如 `characterId` 或 `recipientCharacterId`。
3. 线索事件必须能关联 `clueId` 和来源事件，避免战报虚构证据。
4. public export 使用字段白名单，而不是对 full 数据做简单删减。
5. checkpoint 快照可以包含内部状态，但只能由 Owner/Admin 读取。

## 验收标准

1. Host 能完成“查看全量日志 -> 搜索事件 -> 创建 checkpoint -> 恢复 checkpoint -> 看到恢复审计事件”。
2. Player 能完成“查看自己的行动、检定、线索和公开剧情”，且无法读取他人私密事件。
3. public event API、Player archive、public export 使用一致的可见性规则。
4. 未授权请求不能读取 campaign summary、full export、checkpoint、Host timeline。
5. public export 不包含 token、Host-only 事件、未发现线索、世界真相、AI 原始 prompt。
6. 事件日志能追溯一次主链路：提交行动 -> AI/规则裁决 -> 状态变化 -> Host/Player 投影 -> 日志沉淀。
