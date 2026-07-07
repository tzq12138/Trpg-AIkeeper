# Voice / Media 语音与媒体系统 PRD V2.1

## 当前阶段说明

- 本 PRD 当前阶段为：`P0 主链路 + 语音转写安全、确认提交与 Host 氛围事件风险识别版`。
- 当前代码已经具备轻量 STT 入口、Host 氛围事件和音频解锁雏形，但还没有形成完整的产品边界和验收口径。
- 本轮以仓库真实代码为基础，只收口产品边界、数据边界、权限边界、接口方向和验收标准。
- 本轮不是生产安全完成版；文档中的状态模型、DTO、速率限制、媒体引用和 Journal/export 边界，仍需要后续工程回执与测试验收。

## 背景

AI-Keeper 当前已经有 Voice / Media 雏形：

- 玩家端有录音组件；
- 后端有 STT provider 层；
- HostStore 能接收 BGM、SFX 和 visual 氛围指令；
- `s2c_atmosphere` 已进入事件注册与回放测试。

但它还不是完整的产品化模块，当前缺口包括：

- 前端未上传真实 `durationMs`；
- 语音提交行动存在 React state 同步风险；
- STT 缺少专门测试与专门速率限制；
- HTTP provider 错误分级偏粗；
- `AtmosphereCommand`、`audioAction` 仍未收口成硬 DTO；
- HostStage 只有音频解锁，没有实际 BGM/SFX 播放器；
- SFX 队列缺少一次性消费语义；
- Journal / export 边界还没明确禁止原始音频。

本 PRD 的目标，是把 Voice / Media 的 v1 边界固定下来，让它服务核心跑团链路，而不是替代核心链路。

## 目标

1. 玩家可以用语音输入，并在确认文本后发队伍消息或提交行动。
2. STT 只产生文本草稿，不直接进入规则结算或状态写入。
3. Host 舞台可以接收安全的氛围指令，并逐步支持 BGM、SFX 和 visual 效果。
4. 媒体素材必须走 Asset 的 `assetId` 或受控 URL，不暴露本地路径。
5. 原始语音默认只做临时处理，不进入长期资产、Journal 或导出。

## 非目标

- 不实现 WebRTC 实时语音房。
- 不实现视频会议、屏幕共享和直播推流。
- 不保存玩家原始语音作为长期回放。
- 不做社区音效市场、素材交易或版权审核。
- 不让 AI、Host 或媒体事件绕过 Engine / State 写世界事实。

## 用户角色

| 角色 | 诉求 | 权限边界 |
| --- | --- | --- |
| Player | 用语音快速表达行动或队伍消息 | 只能上传自己的短录音，只能提交自己确认后的文本 |
| Host | 在公共舞台播放氛围并看清当前状态 | 可接收 host/system 可见氛围事件，不能看到玩家私密语音原件 |
| Admin/Ops | 配置 STT provider 与媒体策略 | 可配置 provider、白名单、大小限制和日志策略 |
| AI-Keeper | 可建议氛围和音频动作 | 只能产生命令或建议，不能直接播放未授权素材或写状态 |
| STT Provider | 把音频转成文本 | 只能处理请求音频，不应获得房间真相和玩家 token |
| Future Observer | 观众或旁观者 | 不进入 v1 |

## 产品范围

### v1 进入

- 玩家短语音录制、取消、上传和转写；
- STT provider：disabled、mock、http；
- STT 鉴权、MIME、大小、时长和临时文件清理；
- 转写文本编辑确认；
- 转写文本发队伍频道；
- 转写文本提交行动，继续走 Player Intent；
- Host 音频解锁入口；
- `s2c_atmosphere`、`AtmosphereCommand`、`audioAction` 的统一口径；
- HostStore 氛围状态保存和 WS 推送；
- 媒体素材引用必须接 Asset 的安全 URL 或 `assetId`；
- Journal 只保存确认文本和氛围事件，不保存原始语音。

### v1 不进入

- 实时语音、视频、屏幕共享；
- 长期录音存档和音轨回放；
- 自动语音主持、语音合成 KP；
- 玩家声音身份识别；
- 自动内容审核服务集成；
- 跨房间音效库和社区素材包。

## 数据分层

| 层级 | 数据对象 | 说明 |
| --- | --- | --- |
| L0 `BrowserRecording` | 浏览器 `Blob` / `MediaRecorder` 输出 | 临时录音 |
| L1 `SpeechToTextRequest` | `audio + durationMs + room token` | STT 请求 |
| L2 `TempMedia` | 临时音频文件 | provider 临时处理 |
| L3 `TranscriptDraft` | `transcribedText/confidence/provider/status` | 玩家本地草稿 |
| L4 `ConfirmedTranscript` | 玩家编辑确认文本 | 队伍消息或行动输入 |
| L5 `TeamVoiceMessage` | `source=voice` 的队伍消息 | Channel / Journal 视图 |
| L6 `VoiceIntent` | 语音来源 Player Intent | 进入 AI / Rule / Transaction |
| L7 `AtmosphereCommand` | `bgm/sfx/visual` | Host 舞台氛围命令 |
| L8 `AudioAction` | `suspend/duck/resume/stop/play_sfx` 等 | 事务演出音频动作 |
| L9 `RuntimePlaybackState` | HostStore atmosphere | 舞台播放状态 |
| L10 `MediaAssetReference` | `assetId / assetUrl` | 媒体素材引用 |
| L11 `VoiceMediaJournalView` | 确认文本与媒体事件 | 日志 / 回放 / 导出视图 |

关键边界：

- `TranscriptDraft` 不是已提交行动；
- `ConfirmedTranscript` 不是已裁决结果；
- `AtmosphereCommand` 不写世界事实；
- `RuntimePlaybackState` 不是 State 真相源；
- `TempMedia` 不进入 AssetRecord / Journal / export。

## DTO 契约

### 最低 DTO 集合

- `SpeechToTextRequestDTO`
- `SpeechToTextResultDTO`
- `SpeechToTextErrorDTO`
- `TranscriptDraftDTO`
- `ConfirmedTranscriptDTO`
- `VoiceTeamMessageDTO`
- `VoiceIntentSubmitDTO`
- `AtmosphereCommandDTO`
- `BgmCommandDTO`
- `SfxCommandDTO`
- `VisualEffectDTO`
- `AudioActionDTO`
- `HostPlaybackStateDTO`
- `VoiceMediaAuditDTO`

### 关键 DTO 口径

#### `SpeechToTextResultDTO`

```json
{
  "transcribedText": "我检查书桌",
  "confidence": 0.91,
  "provider": "mock|http",
  "durationMs": 3200,
  "status": "success|disabled|provider_error|provider_timeout|invalid_audio"
}
```

#### `ConfirmedTranscriptDTO`

```json
{
  "text": "我检查书桌",
  "source": "voice",
  "confirmedAt": "2026-07-08T12:00:00Z",
  "target": "team_message|player_intent"
}
```

#### `AtmosphereCommandDTO`

```json
{
  "bgm": {
    "assetId": "bgm-001",
    "url": "/api/assets/bgm-001/stream",
    "volume": 0.7,
    "loop": true,
    "fadeMs": 1200
  },
  "sfx": [
    {
      "assetId": "sfx-door",
      "url": "/api/assets/sfx-door/stream",
      "volume": 0.9,
      "onceKey": "event-123:sfx-door"
    }
  ],
  "visual": {
    "filter": "cold_blue",
    "shake": false,
    "vignette": true
  },
  "sourceEventSequence": 123,
  "transactionId": "tx-001"
}
```

#### `AudioActionDTO`

```json
{
  "type": "suspend_bgm|resume_bgm|duck_bgm|restore_bgm|stop_bgm|play_sfx|clear_sfx_queue|set_volume",
  "target": "bgm|sfx|all",
  "durationMs": 1200,
  "reason": "reveal_transaction"
}
```

DTO 总约束：

- 未确认 transcript draft 不得进入公开 DTO；
- `s2c_atmosphere` 不得包含 `player-only patch`、状态 mutation、本地路径、未授权 URL；
- 媒体相关 DTO 不返回本地绝对路径、token、provider key。

## STT provider 状态模型

建议统一使用以下状态：

- `success`
- `disabled`
- `invalid_audio`
- `duration_exceeded`
- `size_exceeded`
- `unsupported_mime`
- `auth_failed`
- `rate_limited`
- `provider_timeout`
- `provider_auth_failed`
- `provider_bad_response`
- `provider_error`

前后端状态名必须统一使用这一套完整状态模型，禁止在接口、前端分支和日志中混用 `timeout` / `provider_timeout`。

日志只允许记录：

- `provider`
- `status`
- `durationMs`
- `sizeBytes`
- `latencyMs`
- `errorClass`
- `roomId`
- `characterId`

禁止记录：

- 原始音频
- provider API key
- `owner_token` / `player_token`
- 未确认 transcript
- provider 原始响应全文

## Transcript 边界

### `TranscriptDraft`

- 只在当前玩家前端本地展示；
- 未确认前不进入 Journal；
- 未确认前不进入 `team-message`；
- 未确认前不进入 Player Intent；
- 未确认前不触发 AI。

### `ConfirmedTranscript`

- 玩家点击“发给队伍”或“提交行动”后才形成；
- Journal 只记录确认后的文本；
- 如果玩家编辑了转写文本，提交时以编辑后的文本为准；
- STT 返回什么，不等于系统就裁决什么。

## 核心流程

### 1. 语音转行动

1. Player 在行动页按住录音。
2. 前端请求麦克风权限，使用 `MediaRecorder` 生成短音频。
3. 前端把音频、MIME 和真实 `durationMs` 上传到 `/api/player/speech-to-text`。
4. 后端用 `X-Room-Token` 找到角色，校验格式、大小和时长。
5. STT provider 返回 `transcribedText`、`confidence`、`provider` 和 `status`。
6. 前端展示可编辑文本草稿。
7. Player 点击提交行动。
8. 前端必须直接把确认文本作为参数提交 `/api/player/intent`，并带 `source=voice`、`inputSource=voice` 或等价来源字段。
9. Engine、AI、Rule、Transaction、State、Projection 继续处理。

### 2. 语音转队伍消息

1. Player 完成转写并确认文本。
2. 前端调用 `/api/player/team-message`，body 包含 `text` 和 `source=voice`。
3. 后端写入或广播 `s2c_team_message`。
4. Player 与 Host 端按 Projection 可见范围展示消息。
5. Journal 记录确认后的文本，不记录原始音频。

### 3. Host 氛围播放

1. AI / Transaction / Projection 生成 `s2c_atmosphere`。
2. Host WS 验证该事件可给 Host。
3. HostStore 调用 `apply_atmosphere`，合并 BGM、SFX 队列和 visual 状态。
4. Host WS 发送 `atmosphere_update`。
5. HostStage 若已解锁音频，则播放授权 BGM/SFX；未解锁时只更新状态和提示。
6. visual 只影响舞台表现，不写世界事实。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| VM-FR-01 | 支持浏览器录音、取消、上传和错误反馈 | P0 |
| VM-FR-02 | STT endpoint 必须验证 `X-Room-Token` | P0 |
| VM-FR-03 | STT endpoint 必须限制 MIME、大小和时长 | P0 |
| VM-FR-04 | STT provider 默认 disabled，支持 mock 和 http | P0 |
| VM-FR-05 | HTTP provider 使用临时文件时必须清理 | P0 |
| VM-FR-06 | 转写结果必须可编辑，并由玩家确认后才发送 | P0 |
| VM-FR-07 | 队伍消息必须标记语音来源 `source=voice` | P0 |
| VM-FR-08 | 语音提交行动必须使用确认文本，不得提交旧输入框内容 | P0 |
| VM-FR-09 | STT 不得直接写 actions、state patch 或 truth state | P0 |
| VM-FR-10 | 前端必须提交真实 `durationMs` | P0 |
| VM-FR-11 | 后端不得只信任客户端 `durationMs`，缺失/非数字要有稳定处理 | P0 |
| VM-FR-12 | STT endpoint 必须有专门速率限制或明确遗留说明 | P0/P1 |
| VM-FR-13 | `Player Intent` 或 action metadata 必须能审计语音来源 | P1 |
| VM-FR-14 | HostStage 必须支持浏览器音频解锁 | P0 |
| VM-FR-15 | HostStore 必须保存和恢复 atmosphere 状态 | P0 |
| VM-FR-16 | `s2c_atmosphere` payload 必须使用统一 schema | P0 |
| VM-FR-17 | `audioAction` 必须定义为可枚举动作 | P1 |
| VM-FR-18 | BGM/SFX 必须引用 Asset 的 `assetId` 或受控 URL | P1 |
| VM-FR-19 | SFX 必须有一次性消费语义，避免刷新重复播放 | P1 |
| VM-FR-20 | `onceKey` 的消费记录位置必须在回执中说明 | P1 |
| VM-FR-21 | Host 氛围 schema 完成不等于 BGM/SFX 播放器完成，回执不得混写 | P1 |
| VM-FR-22 | 用户可见中文文案必须恢复可读 | P0 |
| VM-FR-23 | Journal 只保存确认文本、provider summary、耗时和结果状态，不保存音频原件 | P1 |

## 接口方向

### `POST /api/player/speech-to-text`

请求：

- Header：`X-Room-Token`
- Form：`audio`
- Form：`durationMs`

服务端口径：

- `durationMs` 由前端真实上传，但后端只能把它当作校验提示；
- 仍需结合文件大小、MIME、空文件检查和 provider 限制共同判断；
- `durationMs` 缺失、非数字、明显异常时，必须返回稳定错误或在回执中说明兼容策略。

响应：

- `transcribedText`
- `confidence`
- `provider`
- `durationMs`
- `status`

错误方向：

- 401：缺少 token
- 403：token 无效
- 400：MIME 不支持、空音频、时长超限
- 413：音频过大
- 429：语音转写速率限制
- 503：STT 未配置
- 5xx：provider 失败或外部服务异常

### `POST /api/player/team-message`

请求：

- Header：`X-Room-Token`
- JSON：`text`
- JSON：`source`，取值 `text | voice`

约束：

- `source=voice` 只表示来源；
- 不触发 AI 裁决；
- Journal 记录确认后的文本。

### `POST /api/player/intent`

请求方向：

- Header：`X-Room-Token`
- JSON：`declared_intent`
- JSON：`source=voice`、`inputSource=voice` 或等价来源字段

约束：

- 必须直接提交确认文本；
- 不得依赖 `setState` 后立即读取旧值；
- 语音来源只作为审计来源，不改变 Rule / AI / Transaction 的裁决语义。

### `s2c_atmosphere`

要求：

- `bgm` / `sfx` / `visual` 结构固定；
- `assetId` 优先于裸 URL；
- URL 必须来自受控路由或短期授权；
- `onceKey` 用于避免一次性 SFX 重复播放；
- `onceKey` 的消费记录位置必须在工程回执中说明，是前端内存、HostStore 运行态还是事件 cursor；
- visual 只影响舞台表现；
- 不得携带 `player-only patch`、状态 mutation、本地路径、未授权 URL、AI raw prompt。

## 权限边界

| 动作 | 权限 |
| --- | --- |
| 玩家上传 STT 音频 | 必须有有效 `X-Room-Token` |
| 玩家查看转写文本 | 仅当前玩家本地可见 |
| 玩家发送队伍消息 | 必须是房间角色成员 |
| 玩家提交行动 | 必须走 `/api/player/intent` |
| Host 接收氛围事件 | 必须通过 Host WS 鉴权 |
| Host 播放素材 | 只能播放公开或 Host 可见的受控素材 |
| Admin 配置 STT | 仅 admin 或 Ops 环境配置 |
| 外部 STT 调用 | 不携带房间真相、owner token、player token |

## 安全、隐私与 Journal / export 边界

- 原始音频默认只存在于请求体和临时文件；
- 日志不得记录原始音频、token、完整 provider 密钥；
- 转写文本确认前不进入 Journal；
- 外部 STT provider 默认关闭；
- 前端需要提示“语音可能发送到配置的转写服务”；
- STT endpoint 需要速率限制，避免成本和带宽滥用；
- 媒体素材必须经 Asset 可见性过滤后再发给 Host 或 Player；
- AI 输出的媒体 cue 必须经 schema 校验和授权检查。

### Journal / replay / export 禁止包含

- 原始音频文件
- 临时音频路径
- provider API key
- `owner_token` / `player_token`
- 未确认 transcript draft
- provider 原始响应
- 未授权媒体 URL
- 本地绝对路径

### 允许记录

- confirmed text
- `source=voice`
- provider summary
- `durationMs`
- `latencyMs`
- `status`
- `s2c_atmosphere` 的 safe payload

## 验收标准

1. 未配置 STT 时，语音入口返回可读错误，文本行动不受影响。
2. 无 token、错 token、非音频、空音频、超大音频、超长音频都被拒绝。
3. mock provider 可在测试环境返回稳定转写文本。
4. HTTP provider 请求结束后不留下临时音频文件。
5. 转写文本必须由玩家确认后才发送队伍消息或提交行动。
6. 语音提交行动使用确认文本，不受 React state 异步更新影响。
7. `Player Intent` 或 action metadata 能审计 `source=voice` / `inputSource=voice`。
8. 前端上传真实 `durationMs`，后端不只信任客户端时长。
9. Host 收到 `s2c_atmosphere` 后能更新 visual；如播放器未完成，回执必须明确仍是未完成能力。
10. SFX 刷新后不会重复播放已消费的一次性音效，且回执说明 `onceKey` 消费记录位置。
11. Journal 可查询语音来源的队伍消息和氛围事件，但不含原始音频。
12. `npm run build` 通过，VoiceInput 与 HostStage 用户文案可读。

## 与其他模块关系

| 模块 | 关系 |
| --- | --- |
| Player Client | 承载录音、转写确认和提交 |
| Channel | 承接语音转写后的队伍消息 |
| AI-Keeper | 接收确认后的文本意图，不能处理原始音频 |
| Transaction | 可携带 `audioAction`，驱动舞台音频动作 |
| Projection | 过滤并分发 `s2c_atmosphere` 和 team message |
| Host Client | 播放氛围和公共舞台视觉 |
| Asset | 提供 BGM/SFX/video/image 的存储、URL 和权限 |
| Safety | 管 STT 隐私、速率限制、素材泄露和反绕过 |
| Journal | 记录确认文本和媒体事件 |
| Admin/Ops | 管 provider 配置、密钥、存储和监控 |
