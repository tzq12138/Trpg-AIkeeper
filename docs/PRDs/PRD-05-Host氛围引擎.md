# PRD-05 - Host 氛围引擎

**版本**: 1.0  
**状态**: 待开发  
**来源**: Host 模块 4、PRD-03  
**适用范围**: AtmosphereOverlay、AudioMixer、useAudioController

## 1. 背景

COC 的公共大屏不仅展示结果，还负责压迫感、声音和视觉环境。氛围层必须独立于事务播放器：环境型 BGM/滤镜可以持续存在，结果型震动/音效可以随事件触发，但都不能阻塞状态结算。

## 2. 目标

- 实现视觉滤镜、暗角、震动、故障等全屏覆盖层。
- 实现 BGM 淡入淡出和 SFX 顺序播放。
- 通过用户手势解锁浏览器音频。
- 保证氛围事件由 Engine 广播，AI 只有建议权。

## 3. 范围边界

**包含**
- `s2c_atmosphere` payload 消费。
- `AtmosphereOverlay` 视觉层。
- `AudioMixer` BGM/SFX 管理。
- Host 隐式控制台音频解锁。

**不包含**
- 音频素材制作。
- 复杂音轨混音台 UI。
- AI 直接操作浏览器音频。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-05-1 | 作为观众，我需要场景进入恐怖状态时大屏颜色、震动和音效同步变化。 | P1 |
| US-05-2 | 作为 KP，我需要开场时手动解锁音频，避免浏览器静音导致演出失败。 | P0 |
| US-05-3 | 作为开发者，我需要 SFX 队列稳定消费，不因为 React 重渲染重复播放。 | P0 |

## 5. 功能需求

1. `AtmospherePayload.visual` 支持 `filter`、`vignette`、`shake`、`glitch`。
2. `AtmospherePayload.bgm` 支持 `trackId | null`、`volume`、`fadeInMs`。
3. `AtmospherePayload.sfx` 支持 `{ clipId, volume? }[]` 顺序入队。
4. `AudioMixer` 统一负责 BGM 和 SFX，React hook 不直接 new Howl。
5. BGM 切换时旧曲 fade out 后 unload，新曲 fade in。
6. SFX 播放完成或加载失败后调用 `shiftSfx()`，再播放下一条。
7. 用户未解锁音频时显示隐式控制台按钮，点击后 resume AudioContext/Howler。
8. `trackId=null` 表示停止当前 BGM。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Event | `s2c_atmosphere` | 氛围切换 |
| Store | `atmosphere.visual` | 视觉覆盖层状态 |
| Store | `atmosphere.bgm` | 当前 BGM 状态 |
| Store | `atmosphere.sfxQueue` | 待播放音效队列 |
| Action | `shiftSfx` | 消费音效队首 |

## 7. 状态与错误处理

- 未知 `trackId` 或 `clipId` 记录 warning 并跳过。
- SFX 加载失败必须出队，不能卡住队列。
- AudioContext suspended 时不报错，提示用户解锁。
- 震动效果按 `durationMs` 自动结束，不改变长期 visual 状态。
- 氛围事件不得清空事务队列或 Player 状态。

## 8. 验收标准

- `AudioMixer` 是唯一音频播放入口。
- Hook 内不出现非法顶层 `await import(...)`。
- 连续下发多个 SFX 时按顺序播放且每条只播放一次。
- BGM 重复下发同一 `trackId` 不重启。
- 音频未解锁时页面提供明确可点击入口。

## 9. 测试场景

1. 下发 `cold_blue` 滤镜，Overlay class 更新。
2. 下发 shake，持续指定时间后停止。
3. 从 `investigation` 切到 `madness`，旧曲淡出，新曲淡入。
4. SFX 队列中第一条加载失败，第二条仍能播放。

## 10. 风险依赖

- 依赖 howler 或等价音频库。
- 浏览器自动播放策略要求用户先交互。
- 素材文件缺失会影响体验，需要资产检查清单。

## 11. 已知架构 Bug：Urgent 抢占时的 BGM 幽灵音 (Audio Ducking Failure)

**来源**：`数据流bug+思考.md` Bug 4

**场景**：
1. Host 播放舒缓探险 BGM（`bgm_investigation`）。
2. 玩家触发即死陷阱，Engine 下发 `priority: 'urgent'` 事务。
3. 屏幕切红、尖叫 SFX 播放——但 BGM 仍在悠然长笛。
4. 因为 `useAudioController` 只监听 `bgm.trackId` 变化，未处理紧急静音。

**防御方案**：
1. `s2c_reveal_transaction` 的 `priority: 'urgent'` payload 增加音频调度字段：
   ```typescript
   { priority: 'urgent', audioAction: 'suspendBGM' | 'duckBGM' }
   ```
2. `EventRouter` 处理 Urgent 事务时，强制调用 `AudioMixer.fadeBGM(0, 500)`（500ms 淡出到静音）。
3. Urgent 事务结束后，Engine 下发恢复指令或 Host 自动恢复默认 BGM 状态。
4. 若 `audioAction: 'duckBGM'`，BGM 淡出到 10% 音量（而非完全静音），适用于紧张但非极端的场景。

**实现要求**：
1. `AudioMixer` 新增 `fadeBGM(targetVolume: number, durationMs: number)` 方法。
2. `useTransactionPlayer` 在处理 `priority: 'urgent'` 事务时，检查 `audioAction` 字段并调用 `AudioMixer`。
3. Urgent 事务完成后（所有 step 播放完毕），自动恢复 BGM 到之前的音量。
4. 若 Urgent 事务被 Watchdog 超时，仍需恢复 BGM。

**新增测试场景**：
5. Urgent 事务到达 → BGM 在 500ms 内淡出到 0 → 事务结束后 BGM 恢复。
6. `audioAction: 'duckBGM'` → BGM 淡出到 10% → 事务结束后恢复。
7. Urgent 事务超时 → BGM 仍正常恢复（兜底）。

