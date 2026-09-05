# Safety 跑团安全边界系统 PRD V2.1

## 当前阶段说明

- 本 PRD 当前阶段为：`P0 主链路 + 鉴权、可见性、反剧透与导出安全风险识别版`。
- 当前仓库已经具备账号鉴权、HostStore 私密事件丢弃、Player catch-up 局部可见性 helper、RAG 房间成员权限、SpoilerGuard、生产 `JWT_SECRET` 拒绝启动等基础。
- 本轮以真实代码为基础，重点收口统一 visibility helper、reconnect/export 漏洞、system_safe 白名单、RAG 最终 prompt 过滤、SpoilerAudit 字段、deployment 基线和文件/媒体安全口径。
- 本轮不是生产安全完成版；token 轮换、token 撤销、多端 session、观众模式、社区审核、完整安全看板进入后续阶段。

## 背景

AI-Keeper 的核心卖点建立在“AI 可以辅助 KP，但不能破坏跑团安全边界”之上。

当前仓库已经有多条安全链路，但它们还没有被统一成同一套产品边界：

- `main.py` 已对生产默认 `JWT_SECRET` 直接拒绝启动；
- `router_map.py` 已要求 `X-Room-Token`，匿名地图访问已被修掉；
- `EventLog` 已有 `_can_player_see_event()` 和 `get_public_events()`；
- `SpoilerGuard`、`SpoilerController`、`AiGateway` 已形成基础反剧透与调用审计链；
- `rag_router.py` 已限制写入只给 owner/admin，读取要求房间成员；
- `router_admin.py` 已给素材上传加入扩展、MIME、文件头、大小和 `resolve()` 校验。

真正危险的地方已经收敛到这些未闭环出口：

- `/api/player/reconnect` snapshot 仍返回房间全量 events；
- `ws_manager.reconnect()` 仍返回未过滤裸 events；
- `export.py` 的 public scope 仍使用 `audience != 'player'`；
- Player archive 仍可能在缺 owner 字段时 fail-open；
- `system_safe` 白名单只存在于局部 helper，没有推广到 reconnect/archive/export；
- CORS 仍是 `*`；
- RAG 搜索权限通过后，进入玩家 prompt 前的最终过滤尚未被文档写硬；
- 桌面安全工具尚未定义 DTO、限速和导出边界。

本 PRD 的目标，是把 Safety v1 固定成跨 User、Projection、Journal、AI、Asset、Voice 的统一安全底线，而不是做一个独立“安全页面”。

## 目标

1. 玩家不能越权读取其他玩家或 Host-only 内容。
2. Host 公共舞台不接收玩家私密结果。
3. AI 给玩家和 party 的输出不能泄露未解锁真相。
4. RAG、reconnect、WS catch-up、archive、public events、export 复用同一可见性规则。
5. 文件上传、STT、PDF、素材和日志默认安全。
6. 生产配置不能带默认弱密钥和全开放 CORS。
7. 跑团桌面安全工具只产生受控事件，不直接改写世界状态。

## 非目标

- 不实现完整社区审核和举报平台。
- 不实现视频、语音内容审核。
- 不做法务合规报表。
- 不做商业化风控或多租户企业权限。
- 不让 Safety 代替 User、Projection、State、Asset 的实现职责。

## 用户角色

| 角色 | 诉求 | 安全边界 |
| --- | --- | --- |
| Player | 保护自己的私密线索、行动结果和不适反馈 | 只能看自己和公开内容，不能写状态 |
| Host | 管理房间与公共舞台 | 可看 Host 视角，但不能收到 player-only 私密 patch |
| Admin/Ops | 配置、审计、排障 | 可看 full 审计，但 public 导出必须脱敏 |
| AI-Keeper | 读取必要上下文并输出建议 | 不直接写状态，不向玩家泄露未解锁真相 |
| DeepSeek 执行者 | 后续按任务包改代码 | 必须先写测试，不放宽任何权限 |
| Future Observer | 旁观公开内容 | 不进入 v1，只能看延迟且删减的公开视角 |

## 产品范围

### v1 进入

- account、owner、player 三类凭证的安全口径；
- REST 和 WS 鉴权基线；
- 统一事件可见性过滤：`live/catch_up/reconnect/archive/public_events/public_export/full_export/admin_audit`；
- Player reconnect 和 delta catch-up 漏洞修复；
- system_safe 白名单与字段白名单；
- SpoilerGuard 敏感索引、输出审查、retry/fallback 和 audit；
- AI prompt 上下文裁剪和 RAG 权限；
- public/full/admin_audit export 的边界；
- 文件上传、PDF、xlsx、STT、asset 的安全验收口径；
- `JWT_SECRET`、CORS、日志脱敏等部署基线；
- X-card、fade、private feedback 的产品边界定义。

### v1 不进入

- 实时语音视频审核；
- 社区内容审核和用户举报闭环；
- 组织级安全策略；
- 完整安全看板和合规报表；
- 观众模式安全延迟；
- 多端 session 管理和 token 撤销 UI。

## Safety 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `Credential` | `account_token` / `owner_token` / `player_token` / API key | 身份凭证，绝不进入 DTO、日志、AI prompt、export |
| L1 `Principal` | Account / RoomOwner / Character / Admin | 当前请求主体 |
| L2 `AuthDecision` | allowed / denied / reason | REST/WS 鉴权结果 |
| L3 `EventEnvelope` | `audience` / `payload` / `roomId` / `sequence` | 权威事件记录 |
| L4 `VisibilityDecision` | allowed / reason / scope / safeFields | 事件是否可见 |
| L5 `SanitizedPayload` | 安全裁剪后的 payload | live/reconnect/archive/export 输出 |
| L6 `PublicEventView` | `party + system_safe` | public events / public export |
| L7 `PlayerPrivateView` | self player-only + party | 玩家视图 |
| L8 `HostSafeView` | host + party + safe system | Host 视图 |
| L9 `SensitiveIndex` | truth / ending / hidden clue / hidden NPC / hidden asset | 反剧透索引 |
| L10 `UnlockState` | clue share / map reveal / event facts | 已解锁事实 |
| L11 `SpoilerAudit` | 命中、retry、fallback、actor、scope | Admin/Ops 审计 |
| L12 `DeploymentSafetyConfig` | `JWT_SECRET` / CORS / log redaction | 部署基线 |
| L13 `TableSafetyEvent` | X-card / fade / private feedback | 桌面安全事件 |

关键边界：

- `AuthDecision` 不等于 `VisibilityDecision`；
- `EventEnvelope` 不等于可以直接给 Player 的 payload；
- `PublicEventView` 不等于 `audience != player`；
- `SensitiveIndex` 和 `UnlockState` 不给 Player；
- `TableSafetyEvent` 只能产生事件、通知和审计，不直接改 State。

## DTO / Helper 契约

### 最低 DTO 集合

- `AuthDecisionDTO`
- `PrincipalDTO`
- `VisibilityDecisionDTO`
- `SanitizedEventDTO`
- `PublicEventDTO`
- `PlayerVisibleEventDTO`
- `HostVisibleEventDTO`
- `ExportSafetyDecisionDTO`
- `SpoilerReviewResultDTO`
- `SpoilerAuditDTO`
- `RagAccessDecisionDTO`
- `FileSafetyDecisionDTO`
- `DeploymentSafetyCheckDTO`
- `TableSafetyEventDTO`
- `SafetyApiErrorDTO`

### 统一 helper 合约

```python
can_view_event(event, viewer, scope) -> VisibilityDecisionDTO
build_event_view(event, viewer, scope) -> SanitizedEventDTO | None
```

`scope` 至少包括：

- `live`
- `catch_up`
- `reconnect`
- `archive`
- `public_events`
- `public_export`
- `full_export`
- `admin_audit`

当前代码里已存在的 `EventLog._can_player_see_event()` 和 `get_events_for_player()`，应视为这套 helper 的现有起点，而不是平行新逻辑。

工程执行时禁止在 EventLog、Projection、Archive、Export、Reconnect 中复制出多套独立规则，最多保留兼容 wrapper。

## 可见性规则

### 受众规则

| audience | Host | 目标 Player | 其他 Player | public export |
| --- | --- | --- | --- | --- |
| `host` | 可见 | 不可见 | 不可见 | 不可见 |
| `player` + target | 默认不可见 | 只给目标角色 | 不可见 | 不可见 |
| `party` | 可见 | 可见 | 可见 | 可见，但仍需脱敏 |
| `system` | 按白名单 | 按白名单 | 按白名单 | 只允许 system_safe |

### 强制规则

- `host`：只给 Host/Admin，不进 Player/public。
- `player`：必须有 `characterId`、`ownerCharacterId`、`recipientCharacterId` 或等价目标字段；缺目标字段默认拒绝。
- `party`：玩家和 Host 可见，但 payload 仍需脱敏。
- `system`：默认不可见；只有 event type + payload field whitelist 同时通过，才可进入 Player/public。

## `system_safe` 白名单

当前代码中的最小白名单锚点是：

- `s2c_turn_resolved`
- `s2c_checkpoint_created`

V2.1 产品口径要求：

- `system_safe` 必须是“事件类型 + payload 字段白名单”；
- 不能只因为事件名在白名单里，就把完整 payload 直接发给 Player/public。

### 可作为最小 `system_safe` 的样例

- `s2c_turn_resolved` 的安全摘要
- `s2c_game_time_updated.safeReason`
- `s2c_checkpoint_created` 的安全摘要（不含路径、restore reason、debug payload）

### 默认禁止作为 `system_safe`

- `s2c_checkpoint_restored` raw audit
- admin override
- spoiler audit
- internal error/debug
- raw restore reason
- AI call log
- host force move audit

## Export Scope 口径

### `public_export`

- 只给 `party + system_safe`
- 不含 host-only、player-only、token、本地路径、隐藏素材、raw prompt、debug metadata

### `full_export`

- 只给 owner/admin
- 是完整业务导出，不是数据库原样导出
- 仍不含 raw token、API key、明文 secret、raw prompt/raw response、账号敏感字段

### `admin_audit_export`

- 若未来需要导出 AI/Ops 原始审计，必须单独 scope
- 不能复用 `full_export`

## Token 生命周期边界

### P0

- token 不进入 DTO、日志、export、AI prompt；
- 错 token / 跨房 token 一律拒绝；
- owner/player token 仅在受控恢复路径返回；
- public events、public export、RAG、AI prompt 都不能泄露 token。

### P1

- owner token 轮换；
- player token 轮换；
- account token 撤销；
- session 表或 tokenVersion；
- 泄露补救流程。

工程回执必须说明：

- 当前是否仍是长期有效 owner/player token；
- 是否已有轮换能力；
- 如果没有，明确列为遗留风险。

如果 owner/player token 轮换和 account token 撤销本轮未做，回执不得写成“token 安全完成”，只能写成“token 脱敏与跨房拒绝已完成，生命周期治理仍是遗留风险”。

## 核心功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| SF-FR-01 | 非开发环境必须拒绝默认 `JWT_SECRET` | P0 |
| SF-FR-02 | 生产环境 CORS 必须使用 allowlist | P0 |
| SF-FR-03 | public room DTO 不含 owner token、owner account、player token | P0 |
| SF-FR-04 | Host REST 和 WS 只允许 owner token、owner account 或 admin | P0 |
| SF-FR-05 | Player REST 和 WS 只允许有效 player token 且绑定本房间 | P0 |
| SF-FR-06 | 玩家不能直接写状态表或 runtime state | P0 |
| SF-FR-07 | HostStore 必须丢弃 player-only/private 事件 | P0 |
| SF-FR-08 | Player catch-up、delta reconnect、snapshot reconnect 必须按统一 helper 过滤 | P0 |
| SF-FR-09 | archive、public events、public export 必须复用统一 helper | P0 |
| SF-FR-10 | `system_safe` 必须使用事件类型 + payload 字段白名单 | P0 |
| SF-FR-11 | `public_export` 不含 host-only、player-only、token、本地路径和隐藏素材 | P0 |
| SF-FR-12 | `full_export` 也不得退化成 DB dump | P0 |
| SF-FR-13 | 地图玩家视图必须要求有效 token，不能匿名返回基础布局 | P0 |
| SF-FR-14 | 私密 `s2c_state_patch` 必须 audience=`player` 且有 target characterId | P0 |
| SF-FR-15 | party 侧状态变化只能发公共摘要，不发个人私密 patch | P0 |
| SF-FR-16 | RAG 写入只允许 admin/owner，读取只允许 admin/owner/房内玩家 | P0 |
| SF-FR-17 | RAG search 通过后，进入玩家 prompt 前仍需二次过滤 | P0 |
| SF-FR-18 | 玩家 AI prompt 不含 raw truth、ending、未发现线索、hidden asset title | P0 |
| SF-FR-19 | AI 输出给 party/player 前必须经过 SpoilerGuard | P0 |
| SF-FR-20 | SpoilerGuard 命中后必须 retry 或 fallback，并写结构化 audit | P0 |
| SF-FR-21 | 文件上传必须校验类型、大小、文件头、路径根目录 | P0 |
| SF-FR-22 | STT 原始音频默认不入库，且有时长、大小、MIME、速率限制 | P1 |
| SF-FR-23 | Admin 高风险操作必须有结构化审计 | P1 |
| SF-FR-24 | X-card、fade、private feedback 只产生安全事件，不直接改状态 | P1 |
| SF-FR-25 | token 轮换和 account token 撤销进入后续批次 | P1 |

## 接口与内部口径

### 已有关键接口

- `GET /ws?role=host&room=...&ownerToken=...`
- `GET /ws?role=player&room=...&token=...`
- `GET /api/player/reconnect`
- `GET /api/map/{room_id}`
- `GET /api/player/archive`
- `GET /api/rooms/{room_id}/events/public`
- `GET /api/rooms/{room_id}/export`
- `POST /api/rag/index`
- `POST /api/rag/search`
- `GET /api/admin/rooms/{room_id}/spoiler-audits`

### 统一 helper 方向

当前文档不再使用只返回 `bool` 的旧约定作为最终口径。

建议统一为：

```python
can_view_event(event, viewer, scope) -> VisibilityDecisionDTO
build_event_view(event, viewer, scope) -> SanitizedEventDTO | None
require_owner_or_admin(request, room_id) -> PrincipalDTO
require_room_player(request, room_id=None) -> PrincipalDTO
redact_sensitive_fields(obj, scope) -> dict
```

## RAG 与 AI 反剧透链路

1. 剧本导入或 admin rebuild 构建 `SensitiveIndex`。
2. RAG search 先按 room membership / owner / admin 做入口权限检查。
3. 进入玩家 prompt 前，再按 `viewer_role / room_id / scenario_id / character_id / source_type / visibility / unlock_state` 做二次过滤。
4. AI 输出 public narrative。
5. SpoilerGuard 审查输出。
6. 命中未解锁敏感项时触发 retry。
7. retry 失败时使用 fallback。
8. 写 `SpoilerAudit`。
9. Projection 最后一公里再做安全网 redaction。

### `SpoilerAuditDTO` 最低字段

- `auditId`
- `roomId`
- `scenarioId`
- `eventType`
- `source`
- `targetAudience`
- `targetCharacterId`
- `matchedSensitiveIds[]`
- `matchedKinds[]`
- `originalTextHash`
- `sanitizedTextHash`
- `actionTaken: retry | fallback | blocked | allowed`
- `retryCount`
- `provider`
- `createdAt`

规则：

- `SpoilerAudit` 为 `admin_only`
- `never_public_export`

## 文件与媒体安全

- PDF 导入必须校验扩展、MIME、文件头和大小；
- xlsx 角色卡只在临时目录解析，失败后清理；
- STT 音频只用于即时转写，不进入长期素材库；
- Admin 素材上传必须限制扩展、MIME、文件头、大小和路径根目录；
- 删除文件前必须 `resolve()` 并确认仍在资产根目录；
- 客户端只能拿受控 URL 或 asset id，不能拿本地绝对路径；
- public export 不带隐藏素材链接。

## 桌面安全事件

### `TableSafetyEventDTO`

- `eventId`
- `roomId`
- `actorCharacterId`
- `actorAccountId`
- `type: x_card | fade | private_feedback`
- `visibility: party | host | admin_only`
- `message`
- `reasonCategory`
- `createdAt`

### 规则

- X-card：可产生 party-safe pause event；不写 HP/SAN、地图、线索、房间状态；有限速；滥用写审计。
- fade：是叙事/演出级暂停或降强度提示，不改事实状态。
- private feedback：只给 Host/Admin；不进 public export；不触发 AI 自动改状态。

## 验收标准

1. 玩家 A 无法通过 REST、WS、reconnect、archive、export 得到玩家 B 的私密内容。
2. `public_export` 只含 `party + system_safe`，且不含任何 token、本地路径、隐藏素材和 host-only 内容。
3. `full_export` 仍脱敏 raw token、API key、secret、raw prompt/raw response。
4. Host WS 错 token 被拒绝，Player WS 错房 token 被拒绝。
5. reconnect snapshot 和 delta 路径都复用统一 visibility helper。
6. `player` audience 缺目标角色时默认拒绝。
7. 玩家地图视图要求 token，不返回隐藏节点、hidden NPC、未发现 clue 和 hidden count。
8. `s2c_state_patch` 私密版只给目标 Player，Host 不接收 player-only patch。
9. AI 输出包含未解锁真相时，被 retry 或 fallback，并产生 `SpoilerAudit`。
10. RAG 非成员搜索返回 403；search 通过后进入玩家 prompt 仍做二次过滤。
11. 文件上传危险类型、超大文件、路径穿越均被拒绝。
12. 生产配置使用默认 `JWT_SECRET` 或 `CORS=*` 时，不可通过安全健康检查。
13. X-card 等安全事件不改变 HP/SAN、地图、线索、房间状态。
14. Host 视角中看不到 `player-only state_patch`、`private_notice`、私密 `action_completed` 结果。
15. `full_export` 不是数据库原样导出，仍持续脱敏 token、API key、secret、raw prompt/raw response。

## 与其他模块关系

| 模块 | 关系 |
| --- | --- |
| User | 提供身份、角色、token；Safety 定义强制验收 |
| Room | 房间公开 DTO、owner 管理、加入审批必须脱敏 |
| Channel | 队伍消息和安全事件按可见性投影 |
| AI-Keeper | prompt 裁剪、输出审查、反幻觉和反剧透 |
| State | 唯一事实写入层，Safety 禁止前端和 AI 直写 |
| Projection | 执行 visibility helper 和最后一公里审查 |
| Journal | archive、replay、export 必须复用安全过滤 |
| Asset | 文件路径、素材可见性和安全 URL |
| Voice/Media | STT、音频、BGM/SFX 走临时处理和授权素材 |
| Admin/Ops | 密钥、CORS、审计、部署安全和告警 |
