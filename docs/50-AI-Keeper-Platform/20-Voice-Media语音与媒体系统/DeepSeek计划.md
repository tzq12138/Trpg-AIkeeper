# Voice / Media 语音与媒体系统 DeepSeek 计划初版

## 执行定位

Voice / Media 模块整体后置。当前只保护 PRD-08 的语音意图入口和文字兜底，不做实时音视频。

## Batch 建议

| Batch | 目标 | 文件方向 | 验收命令 | 禁止事项 |
|---|---|---|---|---|
| Voice-1 | 语音意图 UI 与文字兜底 | `src/client/src/components/VoiceInput.tsx`、`src/client/src/pages/PlayerActionPage.tsx` | `npm run build` | 不接入实时语音频道。 |
| Voice-2 | STT 网关和失败回执 | `src/server/stt.py`、`src/server/player/router_player.py` | `python -m pytest tests/server/test_player_intent.py -q` | 不长期保存原始语音。 |
| Voice-3 | Host 音频触发占位 | `src/client/src/pages/HostStage.tsx`、`src/client/src/components/BauhausShell.tsx` | `npm run build` | 不让音频失败阻塞事务。 |

## DeepSeek 执行规则

- 语音只作为输入方式，不是权限通道。
- STT 文本仍走统一意图网关。
- 实时音视频和录制后置到隐私策略明确之后。

