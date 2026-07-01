# PRD-08 玩家对讲机、STT 与队伍频道计划

## Summary
- 实现玩家端按住说话：录音上传到后端 `/api/player/speech-to-text`，后端通过可插拔 STT Provider 转写。
- 转写成功后不自动裁决，先展示可编辑预览；玩家选择“发给队伍”或“提交行动”。
- 队伍消息对同房间玩家和 Host 可见，写入现有事件日志并通过 WebSocket 实时投影。
- 未配置真实 STT 服务时，后端返回 `503`，前端清楚提示“语音转写未配置”。

## API / Interfaces
- 新增 `POST /api/player/speech-to-text`
  - Header：`X-Room-Token`
  - Body：`multipart/form-data`，字段 `audio`，可选 `durationMs`
  - 支持 MIME：`audio/webm;codecs=opus`、`audio/webm`、`audio/mp4`、`audio/aac`
  - 限制：默认最长 30 秒、最大 8MB；空音频、超限、非法 MIME 返回 400/413
  - 返回：`{ transcribedText, provider, durationMs?, confidence? }`
  - 默认 `STT_PROVIDER=disabled` 返回 503；测试使用 mock；真实服务走 `STT_PROVIDER=http`、`STT_HTTP_URL`、`STT_HTTP_API_KEY`
- 新增 `POST /api/player/team-message`
  - Header：`X-Room-Token`
  - Body：`{ text, source: "voice" | "text", transcriptMeta? }`
  - 只发送队伍频道，不创建 action，不进入裁决队列。
- 新增事件类型 `s2c_team_message`
  - audience 使用 `party`，由现有 `ProjectionDispatcher` 同时发给 Host 和玩家。
  - payload 包含 `messageId`、`characterId`、`playerName`、`investigatorName`、`text`、`source`、`createdAt`。
- 现有 `/api/player/intent` 保持不变；语音选择“提交行动”时发送 `intent_type: "voice_command"`，`declared_intent` 使用转写文本。

## Key Changes
- 后端新增 STT Provider 边界：`disabled`、`mock`、`http` 三种实现；真实音频只临时读取/转发，`finally` 删除临时文件，不长期保存原始音频。
- 后端新增队伍消息路由，校验玩家 token 后复用事件日志和 WS 分发；Host 日志、玩家日志、断线重连都能通过现有事件流看到队聊。
- 前端新增 `useAudioRecorder`：按 PRD 顺序选择 MIME，支持按住录音、松开发送、上滑超过 80px 取消、权限失败降级为文本输入。
- 玩家行动页新增语音预览卡：转写中、失败、空文本、未配置 STT、可编辑文本、两个确认按钮“发给队伍 / 提交行动”。
- 玩家消息流和 Host 舞台增加 `s2c_team_message` 展示，风格沿用现有 Bauhaus/终端 UI，不引入新 UI 依赖。
- 不使用 `DEEPSEEK_API_KEY` 处理音频；密钥只走环境变量，不能写入代码或提交。

## Test Plan
- 后端：覆盖 STT token 缺失/无效、非法 MIME、超大音频、Provider disabled 503、mock 成功、空转写不提交行动。
- 后端：覆盖 `team-message` 能写入 `events`，返回的 live event 带 `roomSequence`，Host 与 Player 都可收到。
- 前端：mock `MediaRecorder` 和 `getUserMedia`，验证开始/取消/上传/转写预览/两种确认按钮/权限拒绝/503 提示。
- 集成：语音转写后选择“提交行动”会创建 `voice_command` action；选择“发给队伍”只产生 `s2c_team_message`，不进入 AI 裁决。
- 构建：`src/client` 下跑 TypeScript/Vite build；后端跑相关 server tests 和全量 `tests/server` 回归。

## Assumptions
- v1 不做实时语音聊天，只做“录音转文字后的队伍消息/行动提交”。
- v1 不保存原始音频，不做语音历史回放，只保存转写文本事件。
- STT 真实服务后续可接 Hermes 或任意 HTTP STT 网关；本计划只要求接口稳定和默认未配置时行为明确。
- 队伍频道默认 Host 可见，作为跑团审计和 AI 上下文的一部分。
