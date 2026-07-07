# Voice / Media 语音与媒体系统 DeepSeek 计划 V2.1

## 当前阶段说明

- 本计划当前阶段为：`P0 主链路 + 语音转写安全、确认提交与 Host 氛围事件风险识别版`。
- 第一轮目标不是“做实时语音房”，而是把 `录音 -> 转写草稿 -> 玩家确认 -> 队伍消息/行动提交 -> Host 氛围事件` 这条链路做稳。
- 当前代码已有轻量 STT 入口和 Host 氛围事件，但还没有完整播放器、速率限制和专门验收闭环。
- 如文档与代码冲突，以当前代码为准，并在回执中明确写出差异与遗留风险。

## 执行原则

本模块服务核心跑团链路，不抢核心链路优先级。近期只做“现有语音转文字入口稳定、安全可测、文案可读”和“Host 氛围事件闭环”。实时语音、视频会议、直播和长期录音全部后移。

所有修改必须先核对当前工作区状态，不覆盖无关改动。每个 Batch 完成后给出测试命令、结果和剩余风险。

## 现状依据

- 语音输入：`src/client/src/components/VoiceInput.tsx`
- 玩家行动页：`src/client/src/pages/PlayerActionPage.tsx`
- STT endpoint：`src/server/player/router_player.py`
- STT provider：`src/server/stt.py`
- STT 配置：`src/server/config.py`
- Host 氛围状态：`src/server/host/host_store.py`
- Host WS：`src/server/host/router_host.py`
- Host 舞台：`src/client/src/pages/HostStage.tsx`
- 事件注册：`src/server/events/events_registry.py`
- 媒体素材入口：`src/server/router_admin.py`、`src/client/src/pages/AdminDashboard.tsx`
- 现有测试：`tests/server/test_host.py`、`tests/server/test_events.py`、`tests/server/test_archive.py`

## 全局实现规则

1. STT 只产生 `TranscriptDraft`，不能直接写 actions、state patch 或 truth。
2. 未确认 transcript 不得进入 Journal、`team-message`、Player Intent 或 AI。
3. 语音提交行动必须直接提交 `confirmedText`，不能依赖 `setState` 后立刻读取旧值。
4. 前端必须提交真实 `durationMs`；后端不得只信任客户端时长，仍需结合文件大小、MIME、空文件和 provider 约束共同判断。
5. STT provider 状态必须统一，至少区分 disabled、invalid_audio、rate_limited、provider_timeout、provider_error。
6. `s2c_atmosphere` 必须使用统一 DTO，不能夹带 `player-only patch`、状态 mutation、本地路径或未授权 URL。
7. `audioAction` 必须是可枚举动作，不再使用自由字符串。
8. BGM / SFX / video / image 必须走 Asset 的 `assetId` 或受控 URL。
9. 原始音频、临时文件路径、provider key、未确认 transcript 不得进入 Journal / replay / export。
10. 如本轮仍未完成 HostStage BGM/SFX 播放器，回执必须明确写成“未完成能力”，不能写成“已闭环”。
11. 语音来源 action 必须带 `source=voice`、`inputSource=voice` 或等价审计字段。

## 全局禁止事项

1. 禁止把完整原始音频保存到 `data/` 或长期目录。
2. 禁止让 STT 文本绕过 `/api/player/intent`。
3. 禁止让 AI 或 Host 直接播放未授权素材。
4. 禁止把本地绝对路径发给客户端。
5. 禁止把 `owner_token`、`player_token`、STT API key 写入日志。
6. 禁止实现实时语音房、视频会议或直播推流。
7. 禁止把 HostStore 当作世界状态真相源。
8. 禁止在前端自动提交未经玩家确认的转写文本。

## Batch VoiceMedia-0：现状核对与风险基线

### 目标

- 跑通 Voice / Media 相关代码索引，确认实际入口、配置和测试覆盖。
- 确认 `router_player.py` 中 STT provider 导入在当前包结构下是否可执行。
- 列出前端可见乱码文件和构建风险。

### 允许改动

- 只读代码和测试。
- 可新增一份临时本地核对笔记，但最终结论应回写到本模块文档或任务包。

### 建议命令

```bash
rg -n "speech-to-text|stt|VoiceInput|MediaRecorder|s2c_atmosphere|audioAction|AtmosphereCommand" src tests
python -m pytest tests/server/test_host.py tests/server/test_events.py tests/server/test_archive.py -q
cd src/client && npm run build
```

### 验收

- 明确 speech-to-text endpoint 是否能被测试 client 调用。
- 明确当前 build 是否受历史乱码或 TSX 字符串破损影响。
- 明确 VoiceInput 是否提交 `durationMs`。
- 明确 PlayerActionPage 是否存在旧 state 提交风险。
- 明确 HostStage 是否真的播放 BGM/SFX，还是只有音频解锁。

### 禁止事项

- 不接入新的外部 STT 服务。
- 不重构 PlayerActionPage 或 HostStage。
- 不顺手改源码。

## Batch VoiceMedia-1：STT 后端稳定性与测试

### 目标

- 新增 STT endpoint 测试。
- 覆盖无 token、错 token、unsupported MIME、空音频、超大音频、超长音频、disabled provider、mock provider。
- 修正 STT provider 导入方式，如果测试证明当前导入不可用。
- 确认 HTTP provider 临时文件清理。

### 允许文件方向

- `src/server/player/router_player.py`
- `src/server/stt.py`
- `src/server/config.py`
- `tests/server/test_player_speech_to_text.py`
- 必要的测试 fixture

### 建议命令

```bash
python -m pytest tests/server/test_player_speech_to_text.py -q
python -m pytest tests/server/test_player_intent.py tests/server/test_room_security.py -q
```

### 验收

- speech-to-text endpoint 有稳定测试覆盖。
- disabled provider 返回 503。
- mock provider 返回稳定 `transcribedText`。
- 超限和鉴权错误使用预期状态码。
- 请求结束后无长期音频文件。
- 覆盖空文件、`durationMs` 缺失、`durationMs` 非数字、provider 返回空文本、provider 返回非 JSON。
- 回执明确说明后端如何处理 `durationMs` 缺失、非数字和明显异常值。

### 禁止事项

- 不把玩家音频保存到 `data/`。
- 不把 provider API key 写入日志。
- 不改变 Player Intent 的裁决语义。

## Batch VoiceMedia-2：Player 语音输入前端修正

### 目标

- 修复 `VoiceInput.tsx` 用户可见中文文案。
- 记录真实录音开始和结束时间，上传 `durationMs`。
- 修正“语音转行动可能提交旧文本”的问题。
- 保持“玩家确认后才提交”的交互。

### 允许文件方向

- `src/client/src/components/VoiceInput.tsx`
- `src/client/src/pages/PlayerActionPage.tsx`
- 必要的前端测试文件

### 建议命令

```bash
cd src/client && npm run build
cd src/client && npm run test
```

### 验收

- 麦克风权限拒绝、STT 未配置、网络失败均显示可读中文。
- FormData 包含 `durationMs`。
- 点击“提交行动”后请求体中的 `declared_intent` 等于确认文本。
- 行动请求体包含 `source=voice`、`inputSource=voice` 或等价来源字段。
- 点击“发给队伍”后请求体包含 `source=voice`。

### 禁止事项

- 不自动提交未经玩家确认的转写文本。
- 不在前端绕过 `/api/player/intent`。
- 不引入实时语音 SDK。

## Batch VoiceMedia-3：STT 安全、隐私和可观测性

### 目标

- 为 STT endpoint 增加速率限制或复用现有安全限流组件。
- 明确外部 HTTP STT 的超时、错误分级和日志字段。
- 增加 provider 响应格式校验。
- 增加隐私提示文案，不记录原始音频。

### 允许文件方向

- `src/server/stt.py`
- `src/server/player/router_player.py`
- `src/server/log_config.py`
- `src/client/src/components/VoiceInput.tsx`
- `tests/server/test_player_speech_to_text.py`

### 建议命令

```bash
python -m pytest tests/server/test_player_speech_to_text.py tests/server/test_room_security.py -q
cd src/client && npm run build
```

### 验收

- 单玩家短窗口重复上传会被限制。
- HTTP provider 超时、认证失败、响应非 JSON 有稳定错误。
- 日志只包含 provider、耗时、状态和大小，不包含音频内容与 token。
- 前端有外部 STT 隐私提示。

### 禁止事项

- 不默认启用外部 STT。
- 不把音频传给 AI-Keeper prompt。
- 不把转写失败内容写入 Journal。

## Batch VoiceMedia-4：Host 氛围事件 schema 收口

### 目标

- 固化 `s2c_atmosphere` 的 payload schema。
- 规范 `bgm`、`sfx`、`visual` 字段。
- 为 SFX 增加 `onceKey` 或等价一次性播放标识。
- 为 `audioAction` 定义枚举口径。

### 允许文件方向

- `src/server/models.py`
- `src/server/host/host_store.py`
- `src/server/host/router_host.py`
- `src/server/events/events_registry.py`
- `tests/server/test_host.py`
- `tests/server/test_events.py`

### 建议命令

```bash
python -m pytest tests/server/test_host.py tests/server/test_events.py tests/server/test_archive.py -q
```

### 验收

- `AtmosphereCommand` 对非法 payload 有清晰校验。
- HostStore 合并 BGM、SFX、visual 的语义有测试。
- 一次性 SFX 不会因为状态恢复而无限重复播放。
- `audioAction` 的值可枚举、可测试。
- 回执说明 `consumedOnceKeys` 或等价消费记录落在前端内存、HostStore 还是事件 cursor。

### 禁止事项

- 不让 HostStore 成为世界状态真相源。
- 不把 player-only 或 private patch 作为氛围事件发给 Host。

## Batch VoiceMedia-5：HostStage BGM/SFX 播放器

### 目标

- 在 HostStage 实现安全的 BGM/SFX 播放。
- 支持音频解锁、播放、停止、音量、循环和失败提示。
- BGM 切换支持淡入淡出方向。
- SFX 播放完成后标记消费。

### 允许文件方向

- `src/client/src/pages/HostStage.tsx`
- 可新增 `src/client/src/components/HostAudioLayer.tsx`
- 可新增前端测试文件

### 建议命令

```bash
cd src/client && npm run build
cd src/client && npm run test
```

### 验收

- 未点击解锁时不会静默报错或反复播放。
- 解锁后 `bgm.url` 可循环播放，切换 BGM 后旧音轨停止。
- `sfx` 按 `onceKey` 播放一次。
- 播放失败时 Host 有可读提示。
- 如本轮只完成 schema/状态更新、未完成实际播放器，回执必须明确写成“未完成能力”。

### 禁止事项

- 不直接播放本地绝对路径。
- 不在 HostStage 中硬编码素材文件。
- 不把音频播放状态写入世界状态。

## Batch VoiceMedia-6：Asset 安全引用闭环

### 目标

- 让 BGM/SFX/video/image 引用统一走 Asset 的安全 URL 或 `assetId`。
- 禁止 atmosphere payload 直接携带本地绝对路径。
- 校验 Player/Host 对素材的可见性。

### 允许文件方向

- `src/server/router_admin.py`
- Asset 相关服务或 DTO
- `src/server/host/router_host.py`
- `src/server/engine/projection.py`
- `tests/server/test_asset_security.py`
- `tests/server/test_projection.py`

### 建议命令

```bash
python -m pytest tests/server/test_asset_security.py tests/server/test_projection.py tests/server/test_host.py -q
cd src/client && npm run build
```

### 验收

- 氛围事件引用 `assetId` 时，服务端能解析成受控 URL。
- 未公开素材不会被发给 Player。
- Host 可访问 Host 可见素材，但响应不包含本地绝对路径。

### 禁止事项

- 不把 `data/scenario_assets/...` 直接当客户端公开路径。
- 不跳过 Asset 可见性校验。
- 不在日志中输出签名 URL 的敏感参数。

## Batch VoiceMedia-7：Journal 和回归验收

### 目标

- 确认语音来源的队伍消息、行动和氛围事件可追踪。
- 明确 Journal 保存确认文本，不保存原始音频。
- 跑完整后端回归和前端 build。

### 允许文件方向

- `src/server/router_archive.py`
- `src/server/events/event_log.py`
- `src/server/export.py`
- `tests/server/test_archive.py`
- `tests/server/test_player_speech_to_text.py`

### 建议命令

```bash
python -m pytest tests/server/test_player_speech_to_text.py tests/server/test_archive.py tests/server/test_host.py -q
python -m pytest tests/server -q
cd src/client && npm run build
```

### 验收

- 队伍消息能显示 `source=voice`。
- 行动日志能追踪“来自语音确认文本”的来源，但不含音频。
- `Player Intent` 或 action metadata 能稳定标记 `source=voice` / `inputSource=voice`。
- replay 和 export 不暴露 token、原始音频和本地路径。
- 失败转写不进公开 Journal。
- 未确认草稿不进 Journal。

### 禁止事项

- 不把失败转写内容写入公开日志。
- 不改变已有 archive 权限边界。

## 端到端验收场景

1. Admin 或 Host 创建房间并启动。
2. Player 加入房间，进入行动页。
3. Player 录音 3 秒，STT mock 返回文本。
4. Player 编辑文本并发给队伍，Host 和 Player 可见队伍消息。
5. Player 再次录音，编辑后提交行动。
6. Engine 接收 Player Intent，后续裁决链路不因语音来源而绕过规则。
7. Projection 发送 `s2c_atmosphere`，HostStage 更新 visual 状态。
8. Host 解锁音频后播放受控 BGM 和一次性 SFX。
9. Journal 可查队伍消息、行动和氛围事件，查不到原始音频文件。

## 总禁止事项

- 不实现实时语音房或视频会议。
- 不保存原始玩家语音到长期目录。
- 不让 STT 文本绕过 Player Intent。
- 不让 AI 输出直接播放未授权素材。
- 不把本地绝对路径发给客户端。
- 不把 `owner_token`、`player_token`、STT API key 写入日志。
- 不改动 Room、State、Transaction、Projection 的核心口径。
