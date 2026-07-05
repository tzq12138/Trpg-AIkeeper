# Safety 跑团安全边界系统 PRD V2.0

## 背景

AI-Keeper 的核心卖点建立在“AI 可以辅助 KP，但不能破坏跑团安全边界”上。当前仓库已经有账号、owner token、player token、RAG 权限、SpoilerGuard、HostStore 私密事件过滤和部分导出脱敏，但安全口径散落在多个 router、WS、archive、export 和 AI 模块中。只要重连、地图、导出或素材某一条链路漏掉过滤，就会出现剧透或越权。

本 PRD 固化 Safety v1：先把工程安全和反剧透边界打牢，再做桌面安全工具。X-card、淡出和私密反馈属于跑团体验安全，但不能抢在权限、投影和导出修复之前。

## 目标

1. 玩家不能越权读写其他玩家或 Host-only 内容。
2. Host 公共舞台不接收玩家私密结果。
3. AI 给玩家和 party 的输出不能泄露未解锁真相。
4. RAG、导出、回放、重连、WS catch-up 与实时投影使用同一可见性规则。
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

## 范围

### v1 进入

- account、owner、player 三类凭证的安全口径。
- REST 和 WS 鉴权基线。
- 统一事件可见性过滤：live、catch-up、reconnect、archive、export。
- Player 重连和地图匿名访问修复。
- SpoilerGuard 敏感索引、输出审查、retry/fallback 和 audit。
- AI prompt 上下文裁剪和 RAG 权限。
- public export、public events、replay 的脱敏。
- 文件上传、PDF、xlsx、STT、asset 的安全验收口径。
- `JWT_SECRET`、CORS、日志脱敏等部署基线。

### v1 不进入

- 实时语音视频审核。
- 社区内容审核和用户举报闭环。
- 组织级安全策略。
- 完整安全看板和合规报表。
- 观众模式安全延迟。
- 多端 session 管理和 token 撤销 UI。

## 数据分类

| 分类 | 示例 | 默认可见范围 | 处理规则 |
| --- | --- | --- | --- |
| 凭证 | `account_token`、`owner_token`、`player_token`、API key | 仅持有端和服务端 | 不进公开 DTO、日志、export、AI prompt |
| Host-only 真相 | truth、ending、隐藏 NPC、隐藏 asset | Host/Admin | 不给 Player/Party，AI 输出要审查 |
| 玩家私密 | 私密线索、个人目标、个人 state patch、action result | 目标玩家 | 缺 owner 字段时默认不展示 |
| Party 公开 | 公共叙事、队伍消息、已分享线索、公开地图变化 | 房间成员 | 可进入 public replay/export |
| System 审计 | spoiler audit、AI call log、checkpoint restore | Admin/Owner | 只在授权后台可见 |
| 文件原件 | PDF、xlsx、音频、素材 | 依类型和权限 | 受控存储，不暴露本地路径 |

## 可见性规则

| 事件 audience | Host | 目标 Player | 其他 Player | Public export |
| --- | --- | --- | --- | --- |
| `host` | 可见 | 不可见 | 不可见 | 不可见 |
| `player` + `characterId` | 不默认可见 | 可见 | 不可见 | 不可见 |
| `party` | 可见 | 可见 | 可见 | 可见，但需脱敏 |
| `system` | 按事件类型 | 按事件类型 | 按事件类型 | 只允许白名单 |

原则：

- player audience 缺少目标角色时默认拒绝。
- host audience 永远不进入玩家 replay、archive、reconnect、export。
- system audience 不能自动当作公开，必须按事件白名单。
- 同一 visibility helper 必须被实时 WS、catch-up、reconnect、archive、export 复用。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| SF-FR-01 | 账号登录、注册、`/me` 使用强哈希和过期 token | P0 |
| SF-FR-02 | 非开发环境必须拒绝默认 `JWT_SECRET` | P0 |
| SF-FR-03 | 生产环境 CORS 必须使用 allowlist | P0 |
| SF-FR-04 | public room DTO 不含 owner token、owner account、player token | P0 |
| SF-FR-05 | Host REST 和 WS 只允许 owner token、owner account 或 admin | P0 |
| SF-FR-06 | Player REST 和 WS 只允许有效 player token 且绑定本房间 | P0 |
| SF-FR-07 | 玩家不能直接写状态表或 runtime state | P0 |
| SF-FR-08 | HostStore 必须丢弃 player-only/private 事件 | P0 |
| SF-FR-09 | Player WS catch-up 必须按玩家可见性过滤 | P0 |
| SF-FR-10 | `/api/player/reconnect` 普通和 snapshot 路径必须过滤事件 | P0 |
| SF-FR-11 | 地图玩家视图必须要求有效 token | P0 |
| SF-FR-12 | public events、replay、archive、export 必须复用统一过滤 | P0 |
| SF-FR-13 | public export 不含 host-only、player-only、token、本地路径和隐藏素材 | P0 |
| SF-FR-14 | RAG 写入只允许 admin/owner，读取只允许 admin/owner/房内玩家 | P0 |
| SF-FR-15 | 玩家 AI prompt 不含 raw truth、ending、未发现线索 | P0 |
| SF-FR-16 | AI 输出给 party/player 前必须经过 SpoilerGuard | P0 |
| SF-FR-17 | SpoilerGuard 命中后必须 retry 或 fallback，并写 audit | P0 |
| SF-FR-18 | 文件上传必须校验类型、大小、文件头、路径根目录 | P0 |
| SF-FR-19 | STT 原始音频默认不入库，且有时长、大小、MIME、速率限制 | P1 |
| SF-FR-20 | Admin 高风险操作必须有结构化审计 | P1 |
| SF-FR-21 | X-card、fade、private feedback 只产生安全事件，不直接改状态 | P1 |
| SF-FR-22 | token 轮换和 account token 撤销进入后续批次 | P1 |

## 接口口径

### 已有接口

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/rooms`
- `GET /api/rooms/{room_id}`
- `GET /ws?role=host&room=...&ownerToken=...`
- `GET /ws?role=player&room=...&token=...`
- `GET /api/player/reconnect`
- `GET /api/map/{room_id}`
- `GET /api/player/archive`
- `GET /api/rooms/{room_id}/events/public`
- `GET /api/rooms/{room_id}/export`
- `POST /api/rag/index`
- `POST /api/rag/search`
- `GET /api/admin/ai/logs`
- `GET /api/admin/rooms/{room_id}/spoiler-audits`
- `POST /api/admin/scenarios/{scenario_id}/spoiler-index/rebuild`

### 建议新增内部 helper

```python
can_deliver_event_to_player(event, character_id) -> bool
can_include_event_in_public_export(event) -> bool
sanitize_event_payload(event, audience, character_id=None) -> dict
require_owner_or_admin(request, room_id) -> AccountOrRoomOwner
require_room_player(request, room_id=None) -> Character
redact_sensitive_fields(obj) -> dict
```

### 后续桌面安全事件

- `s2c_safety_x_card_triggered`
- `s2c_safety_fade_requested`
- `s2c_safety_pause_resolved`
- `s2c_safety_private_feedback_submitted`

要求：

- X-card 可公开暂停当前叙事，但不写世界状态。
- private feedback 只给 Host 或 Admin/Ops 可见，默认不进 public export。
- 安全事件需要限速和滥用审计。

## 反剧透链路

1. 剧本导入或 admin rebuild 构建 sensitive index。
2. AI / RAG / WorldBook 只给玩家链路提供已解锁上下文。
3. Engine/AI 产出 public narrative。
4. SpoilerGuard 以 room unlock state 审查文本。
5. 命中未解锁敏感项时触发一次 retry。
6. retry 仍失败或不可用时使用 fallback。
7. 写入 spoiler audit。
8. Projection 再次作为安全网扫描 player/party payload。

## 文件与媒体安全

- PDF 导入必须校验扩展、MIME、文件头和大小。
- xlsx 角色卡只在临时目录解析，失败后清理。
- STT 音频只用于即时转写，不进入长期素材库。
- Admin 素材上传必须限制类型和大小。
- 删除文件必须 resolve 后确认仍在资产根目录。
- 客户端只能拿受控 URL 或 asset id，不能拿本地绝对路径。
- public export 不带隐藏素材链接。

## 验收标准

1. 玩家 A 无法通过 REST、WS、reconnect、archive、export 得到玩家 B 的私密内容。
2. 玩家无法通过无 token 地图接口获取地图结构。
3. Host WS 错 token 被拒绝，Player WS 错房 token 被拒绝。
4. public export 只含 party/system 白名单事件，且不含任何 token 和本地路径。
5. AI 输出包含未解锁真相时，被 retry 或 fallback，并产生 audit。
6. RAG 非成员搜索返回 403，玩家写索引返回 403。
7. 文件上传危险类型、超大文件、路径穿越均被拒绝。
8. 生产配置使用默认 `JWT_SECRET` 或 `CORS=*` 时不可通过安全健康检查。
9. X-card 等安全事件不改变 HP/SAN、地图、线索、房间状态。

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
