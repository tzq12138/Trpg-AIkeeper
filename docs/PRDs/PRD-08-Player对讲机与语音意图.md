# PRD-08 - Player 对讲机与语音意图

**版本**: 1.0  
**状态**: 待开发  
**来源**: Player 模块 2、PRD-01  
**适用范围**: useAudioRecorder、PushToTalkButton、STT API

## 1. 背景

跑团中的手机端输入应尽量轻量，对讲机式按住说话比键盘输入更贴近桌面现场。但语音不能绕过 Engine：STT 只负责转写，转写文本仍必须通过统一意图网关提交。

## 2. 目标

- 提供按住说话、上滑取消、松开发送的移动端语音入口。
- 支持 iOS/Android/桌面浏览器可用的录音 MIME 选择。
- 麦克风不可用时降级为文本输入。
- STT 结果通过 `submitIntent('voice_command')` 提交。

## 3. 范围边界

**包含**
- 录音 hook、PTT 按钮交互。
- `/api/player/speech-to-text` 上传。
- STT 成功后转意图。
- 权限拒绝、上传失败、空转写处理。

**不包含**
- 离线 STT 模型。
- 语音频道实时对讲。
- 语音原始文件长期存储。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-08-1 | 作为玩家，我希望按住按钮说出行动，松开后系统自动提交给 KP。 | P0 |
| US-08-2 | 作为玩家，我说错时需要上滑取消，不发送错误行动。 | P1 |
| US-08-3 | 作为玩家，如果麦克风被拒绝，我仍能用文字继续游戏。 | P0 |

## 5. 功能需求

1. `useAudioRecorder` 检测 `MediaRecorder.isTypeSupported()`，优先选择 `audio/webm;codecs=opus`，再降级到 webm/mp4/aac。
2. `PushToTalkButton` 支持 pointer down 开始录音、pointer up 结束录音、上滑超过 80px 取消。
3. 录音开始、取消、发送失败可触发移动端震动反馈。
4. 录音结束后上传到 `POST /api/player/speech-to-text`，header 带 `X-Room-Token`。
5. STT 返回 `transcribedText` 后调用 `submitIntent('voice_command', transcribedText)`。
6. 转写为空时不提交意图，提示“未识别到有效内容”。
7. 麦克风权限拒绝后展示文本输入降级，提交 `dialogue` 或 `voice_command` 文本意图。
8. 所有错误使用 toast，不使用 `alert()`。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Browser API | `navigator.mediaDevices.getUserMedia` | 获取麦克风 |
| Browser API | `MediaRecorder` | 录音 |
| REST | `POST /api/player/speech-to-text` | 音频转写 |
| REST | `POST /api/player/intent` | 提交语音意图 |
| Header | `X-Room-Token` | 身份凭证 |

## 7. 状态与错误处理

- 录音失败时设置 `micDenied=true` 并切到文本模式。
- 上传失败时 toast 提示，并保持动作状态可重试。
- STT 服务超时不锁死 UI。
- `actionState !== IDLE` 时按钮禁用，避免并发意图。
- 组件卸载或取消录音时必须停止所有 audio tracks。

## 8. 验收标准

- 麦克风权限允许时可完成录音、上传、转写、意图提交闭环。
- 麦克风权限拒绝时出现文本输入降级。
- 上滑取消不会调用 STT 或意图接口。
- STT 空文本不会提交 action。
- 无 `alert()`，错误均通过 toast 或内联状态呈现。

## 9. 测试场景

1. 模拟录音成功，STT 返回文本，`submitIntent('voice_command')` 被调用。
2. 模拟 pointer 上滑取消，录音停止且无网络请求。
3. 模拟 getUserMedia 抛错，展示文本输入。
4. 模拟 STT 500，按钮解锁并显示 toast。

## 10. 风险依赖

- iOS Safari 对 MediaRecorder 支持有限，需要真机验证。
- STT 服务的文件大小、格式和时长限制需后端确认。
- 语音隐私策略后续需要补充。

