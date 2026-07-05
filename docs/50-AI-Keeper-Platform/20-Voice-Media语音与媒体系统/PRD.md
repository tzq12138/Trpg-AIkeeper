# Voice / Media 语音与媒体系统 PRD V2.0

## 背景

AI-Keeper 当前已经有轻量语音转文字和 Host 氛围事件雏形：玩家端有录音组件，后端有 STT provider，HostStore 能接收 BGM、SFX 和视觉氛围指令。问题是这些能力还没有形成完整产品边界：语音提交行动存在稳定性风险，Host 舞台还未真实播放 BGM/SFX，媒体素材权限需要和 Asset、Projection、Safety 统一。

本 PRD 的目标是把 Voice / Media 的 v1 边界固定下来，让它服务核心跑团链路，而不是替代核心链路。

## 目标

1. 玩家可以用语音输入，并在确认文本后发队伍消息或提交行动。
2. 语音转写只产生文本草稿，不直接进入规则结算或状态写入。
3. Host 舞台可以接收安全的氛围指令，并逐步支持 BGM、SFX 和视觉效果。
4. 媒体素材必须走 Asset 的受控引用，不能把本地路径或隐藏素材直接暴露给客户端。
5. 原始语音默认只做临时处理，不保存为长期资产或日志内容。

## 非目标

- 不实现 WebRTC 实时语音房。
- 不实现视频会议、屏幕共享和直播推流。
- 不保存玩家原始语音录音作为长期回放。
- 不做社区音效市场、素材交易或版权审核。
- 不让 AI、Host 或媒体事件绕过 Engine 写世界状态。

## 用户角色

| 角色 | 诉求 | 权限边界 |
| --- | --- | --- |
| Player | 用语音快速表达行动或队伍消息 | 只能上传自己的短录音，只能提交自己确认后的文本 |
| Host | 在公共舞台播放氛围并看清当前状态 | 可接收 host/system 可见氛围事件，不能看到玩家私密语音原件 |
| Admin/Ops | 配置 STT provider 和媒体存储策略 | 可配置 provider、资产白名单、大小限制和日志策略 |
| AI-Keeper | 可建议氛围和音频动作 | 只能产生命令或建议，不能直接播放未授权素材或写状态 |
| STT Provider | 把音频转成文本 | 只能处理请求音频，不应获得房间真相和玩家 token |
| Future Observer | 观众或旁观者 | 不进入 v1，后续只接收公开且延迟的媒体视角 |

## 范围

### v1 进入

- 玩家短语音录制、取消、上传和转写。
- STT provider：disabled、mock、http。
- STT 鉴权、MIME、大小、时长和临时文件清理。
- 转写文本编辑确认。
- 转写文本发队伍频道。
- 转写文本提交行动，继续走 Player Intent。
- Host 音频解锁入口。
- `s2c_atmosphere`、`AtmosphereCommand`、`audioAction` 的统一口径。
- HostStore 氛围状态保存和 WS 推送。
- 媒体素材引用必须接 Asset 的安全 URL 或 asset id。
- 日志只保存确认文本和氛围事件，不保存原始语音。

### v1 不进入

- 实时语音、视频、屏幕共享。
- 长期录音存档和音轨回放。
- 自动语音主持、语音合成 KP。
- 玩家声音身份识别。
- 自动内容审核服务集成。
- 跨房间音效库和社区素材包。

## 用户故事

| 编号 | 用户故事 | 验收 |
| --- | --- | --- |
| VM-US-01 | 作为 Player，我希望按住说话后得到文字草稿 | 成功录音后显示可编辑转写文本 |
| VM-US-02 | 作为 Player，我希望识别错了可以修改 | 文本框可编辑，提交使用编辑后的内容 |
| VM-US-03 | 作为 Player，我希望把语音内容发给队伍而不是触发裁决 | 选择队伍发送后产生 `s2c_team_message`，不进入 Engine 裁决 |
| VM-US-04 | 作为 Player，我希望把语音内容当作行动提交 | 选择提交行动后产生 Player Intent，状态仍由 Engine 决定 |
| VM-US-05 | 作为 Host，我希望浏览器先解锁音频再播放素材 | 未解锁时不会自动播放失败，解锁后可以播放授权素材 |
| VM-US-06 | 作为 Host，我希望场景切换时舞台有 BGM、音效和视觉氛围 | 收到 `s2c_atmosphere` 后 HostStage 更新对应效果 |
| VM-US-07 | 作为 Admin，我希望 STT 默认关闭，配置后才调用外部服务 | 默认 provider 为 disabled，配置 mock/http 后行为可测 |
| VM-US-08 | 作为安全负责人，我希望玩家原始语音不被长期保存 | STT 请求完成后无长期音频资产和日志内容 |

## 核心流程

### 语音转行动

1. Player 在行动页按住录音。
2. 前端请求麦克风权限，使用 `MediaRecorder` 生成短音频。
3. 前端把音频、MIME 和真实 `durationMs` 上传到 `/api/player/speech-to-text`。
4. 后端用 `X-Room-Token` 找到角色，校验格式、大小和时长。
5. STT provider 返回 `transcribedText`、`confidence` 和 provider 名称。
6. 前端展示可编辑文本。
7. Player 点击提交行动。
8. 前端以确认文本提交 `/api/player/intent`。
9. Engine、AI、Rule、Transaction、State、Projection 继续处理。

### 语音转队伍消息

1. Player 完成转写并确认文本。
2. 前端调用 `/api/player/team-message`，body 包含 `text` 和 `source=voice`。
3. 后端写入或广播 `s2c_team_message`。
4. Player 与 Host 端按 Projection 可见范围展示消息。
5. Journal 记录确认后的文本，不记录原始音频。

### Host 氛围播放

1. AI / Transaction / Projection 生成 `s2c_atmosphere`。
2. Host WS 验证该事件可给 Host。
3. HostStore 调用 `apply_atmosphere`，合并 BGM、SFX 队列和 visual 状态。
4. Host WS 发送 `atmosphere_update`。
5. HostStage 若已解锁音频，则播放授权 BGM/SFX；未解锁时只更新状态和提示。
6. 视觉效果可立即作用于公共舞台。

## 功能需求

| 编号 | 需求 | 优先级 |
| --- | --- | --- |
| VM-FR-01 | 支持浏览器录音、取消、上传和错误反馈 | P0 |
| VM-FR-02 | STT endpoint 必须验证 `X-Room-Token` | P0 |
| VM-FR-03 | STT endpoint 必须限制 MIME、大小和时长 | P0 |
| VM-FR-04 | STT provider 默认 disabled，支持 mock 和 http | P0 |
| VM-FR-05 | HTTP provider 使用临时文件时必须清理 | P0 |
| VM-FR-06 | 转写结果必须可编辑，并由玩家确认后才发送 | P0 |
| VM-FR-07 | 队伍消息必须标记语音来源 | P0 |
| VM-FR-08 | 语音提交行动必须使用确认文本，不能提交旧输入框内容 | P0 |
| VM-FR-09 | STT 不得直接写 actions、state patch 或 truth state | P0 |
| VM-FR-10 | HostStage 必须支持浏览器音频解锁 | P0 |
| VM-FR-11 | HostStore 必须保存和恢复 atmosphere 状态 | P0 |
| VM-FR-12 | `s2c_atmosphere` payload 必须使用统一 schema | P0 |
| VM-FR-13 | BGM/SFX 必须引用 Asset 的 asset id 或受控 URL | P1 |
| VM-FR-14 | SFX 必须有一次性消费语义，避免刷新重复播放 | P1 |
| VM-FR-15 | `audioAction` 必须定义 suspend、duck、resume 等可枚举动作 | P1 |
| VM-FR-16 | STT 请求必须有速率限制和可观测错误 | P1 |
| VM-FR-17 | 用户可见中文文案必须恢复可读 | P0 |
| VM-FR-18 | 日志只保存确认文本、provider、耗时和结果状态，不保存音频原件 | P1 |

## 数据与事件口径

### `POST /api/player/speech-to-text`

请求：

- Header：`X-Room-Token`
- Form：`audio`
- Form：`durationMs`

响应：

- `transcribedText`
- `confidence`
- `provider`
- `durationMs`

错误：

- 401：缺少 token
- 403：token 无效
- 400：MIME 不支持、空音频、时长超限
- 413：音频过大
- 503：STT 未配置
- 500：provider 失败

### `POST /api/player/team-message`

请求：

- Header：`X-Room-Token`
- JSON：`text`
- JSON：`source`，取值 `text` 或 `voice`

结果：

- 发出 `s2c_team_message`
- Journal 记录确认后的文本

### `s2c_atmosphere`

建议 payload：

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
  }
}
```

要求：

- `assetId` 优先于裸 URL。
- URL 必须来自受控路由或短期授权。
- `onceKey` 用于避免重复播放一次性音效。
- visual 只能影响舞台表现，不能写世界事实。

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

## 安全与隐私

- 原始音频默认只存在于请求体和临时文件。
- 日志不得记录原始音频、token、完整外部 provider 密钥。
- 转写文本属于玩家确认输入，确认前不进入 Journal。
- 外部 STT provider 默认关闭。
- 前端需要说明外部转写服务可能处理音频。
- STT endpoint 需要速率限制，避免成本和带宽滥用。
- 媒体素材必须经 Asset 可见性过滤后再发给 Player 或 Host。
- AI 输出的媒体 cue 必须经 schema 校验和授权检查。

## 验收标准

1. 未配置 STT 时，语音入口返回可读错误，文本行动不受影响。
2. 无 token、错 token、非音频、空音频、超大音频、超长音频都被拒绝。
3. mock provider 可在测试环境返回稳定转写文本。
4. HTTP provider 请求结束后不留下临时音频文件。
5. 转写文本必须由玩家确认后才发送队伍消息或提交行动。
6. 语音提交行动使用确认文本，不受 React state 异步更新影响。
7. Host 收到 `s2c_atmosphere` 后能更新 visual，并在实现播放器后播放授权 BGM/SFX。
8. SFX 刷新后不会重复播放已消费的一次性音效。
9. Journal 可查询语音来源的队伍消息和氛围事件，但不含原始音频。
10. `npm run build` 通过，VoiceInput 与 HostStage 用户文案可读。

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
