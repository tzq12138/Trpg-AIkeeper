# PRD-06 - Host 舞台演出与剧情渲染

**版本**: 1.0  
**状态**: 待开发  
**来源**: Host 模块 5、PRD-04、PRD-05  
**适用范围**: StageRenderer、SceneBackground、TypewriterSubtitle、Dice3DNode

## 1. 背景

Host 舞台是公共演出的最终呈现层。设计要求组件尽量常驻，状态从 Store 流入，避免因为挂载/卸载造成字幕丢失、背景闪烁或动画重复。只有 3D 骰子这类瞬时节点按需挂载。

## 2. 目标

- 构建全屏 Host 舞台布局。
- 背景、HUD、字幕和氛围层常驻响应 Store。
- `narrative_text` 用本地 rAF 打字机展示完整文本。
- 骰子动画按 `currentRollEvent` 条件挂载并回调事务播放器。

## 3. 范围边界

**包含**
- `StageRenderer` 总控组合。
- `SceneBackground` 双图层交叉淡入淡出。
- `TypewriterSubtitle` requestAnimationFrame 打字机。
- `Dice3DNode` 生命周期接口。
- `HostMinimalConsole` 音频解锁和紧急重置入口。

**不包含**
- 具体 Three.js 骰子建模细节。
- 图片生成或素材管理系统。
- Player 手机端界面。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-06-1 | 作为观众，我需要背景切换、骰子和字幕在同一舞台自然衔接。 | P0 |
| US-06-2 | 作为 KP，我需要大屏卡住时可以紧急重置演出状态。 | P0 |
| US-06-3 | 作为开发者，我需要字幕打字机不受 React 闭包陈旧和 Strict Mode 双执行影响。 | P0 |

## 5. 功能需求

1. `StageRenderer` 挂载 `SceneBackground`、`GlobalHUD`、`TypewriterSubtitle`、`Dice3DNode`、`HostMinimalConsole`。
2. `SceneBackground` 监听 `currentSceneImageUrl`，只保留最近两张图做交叉淡入淡出。
3. 背景 key 使用 URL 本身，避免数组下标导致 reconciliation 问题。
4. `TypewriterSubtitle` 从 `chatMessages` 合并 keeper/npc 文本。
5. 打字机使用 requestAnimationFrame 和 ref 镜像，避免 setInterval 泄漏。
6. MVP 阶段 `narrative_text` 始终按非阻塞字幕处理，并依赖事务步骤顺序保证叙事通常位于最后一步；`narrative_text.blocking=true` 时由字幕完成后触发事务播放器推进属于二期扩展。
7. `Dice3DNode` 仅在 `currentRollEvent` 非空时挂载，完成后调用 `notifyDiceSettled`。
8. 紧急重置调用 `resetRoomStore()`，但不刷新浏览器。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Store | `currentSceneImageUrl` | 背景切换 |
| Store | `chatMessages` | 字幕文本源 |
| Store | `currentRollEvent` | 骰子节点挂载 |
| Callback | `notifyDiceSettled` | 通知 roll step 完成 |
| Callback | `notifyTypewriterDone` | 通知 blocking 字幕完成（二期） |

## 7. 状态与错误处理

- 背景 URL 为空时保持当前背景或显示默认底图。
- 图片加载失败时显示默认背景，不中断事务。
- 打字机目标文本变短或被清空时重置 displayedText。
- 骰子渲染失败时由事务 Watchdog 兜底推进。
- 紧急重置需要同时清空骰子、队列、字幕和氛围音效。

## 8. 验收标准

- 舞台组件除 Dice 外常驻，不因事务推进频繁卸载。
- `narrative_text` 完整文本能以打字机形式显示。
- MVP 阶段不要求 blocking 字幕阻塞事务；`notifyTypewriterDone` 回调链作为二期验收。
- 背景连续切换时最多保留两个图层。
- 紧急重置后无旧字幕、旧骰子、旧队列残留。

## 9. 测试场景

1. 下发两个 scene_transition，第二张背景淡入，第一张淡出后移除。
2. 追加 keeper 字幕，打字机逐字显示。
3. 二期启用 blocking 字幕时，下一个 status_delta 在字幕完成后继续。
4. currentRollEvent 设置后 Dice 挂载，回调后卸载。

## 10. 风险依赖

- 依赖 PRD-04 提供稳定事务回调。
- 3D 骰子若引入 Three.js，需要单独做渲染验证。
- 大屏分辨率差异大，CSS 需要额外响应式验收。
