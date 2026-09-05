# PRD-11 - Player 战术聊天与结构化行动按钮

**版本**: 1.0  
**状态**: 待开发  
**来源**: Player 模块 5、PRD-00、PRD-01  
**适用范围**: Tactical Chat Store、ChatLog、TacticalMessageBubble

## 1. 背景

旧版富文本按钮依赖前端正则解析 `[文本|工具|JSON]`，脆弱且容易泄漏内部结构。v2 由 Engine 解析 AI JSON 后投影为结构化 `s2c_tactical_prompt`，Player 前端只负责渲染 `text` 和 `actions[]`。

## 2. 目标

- 建立结构化战术聊天消息。
- 渲染 AI/KP 文本和 1-3 个快捷行动按钮。
- 按钮点击统一走 REST 意图。
- 防止前端解析伪协议字符串。

## 3. 范围边界

**包含**
- Player chatMessages Store。
- `receiveTacticalPrompt({ text, actions })`。
- `TacticalMessageBubble` 和 `ChatLog`。
- 战术按钮提交意图。

**不包含**
- AI system prompt 全文。
- Markdown 富文本渲染器。
- 玩家之间自由群聊。

## 4. 用户故事

| ID | 用户故事 | 优先级 |
|---|---|---|
| US-11-1 | 作为玩家，我需要看到 KP 给我的私密或个人行动提示。 | P0 |
| US-11-2 | 作为玩家，我希望能点一个快捷按钮提交常见行动，而不是重新输入。 | P0 |
| US-11-3 | 作为开发者，我不想在前端用正则解析 AI 输出。 | P0 |

## 5. 功能需求

1. `s2c_tactical_prompt` payload 统一为 `{ text, actions[] }`。
2. `actions[]` 每项包含 `actionId`、`label`、`intentType`、`params`。
3. `receiveTacticalPrompt` 追加一条 `PlayerChatMessage`，sender 默认为 `kp`。
4. 聊天记录保留最近 50 条，避免手机端 DOM 膨胀。
5. `TacticalMessageBubble` 直接遍历 actions 渲染按钮，不解析文本中的指令。
6. 按钮点击调用 `submitIntent(action.intentType, action.label, action.params)`。
7. `actionState !== IDLE` 时所有战术按钮禁用。
8. 若 actions 为空，则只渲染纯文本消息。
9. JSON 解析失败由 Engine 降级为纯文本，前端不处理半结构化字符串。

## 6. 接口/事件依赖

| 类型 | 名称 | 用途 |
|---|---|---|
| Event | `s2c_tactical_prompt` | 结构化提示 |
| REST | `POST /api/player/intent` | 按钮提交 |
| Store | `actionState` | 按钮锁定 |
| Payload | `{ text, actions[] }` | 唯一 prompt 形态 |

## 7. 状态与错误处理

- action 缺少 `intentType` 或 `label` 时不渲染该按钮，并记录 warning。
- 点击按钮后立即震动反馈并进入动作状态机。
- 已提交动作的按钮不做本地删除，由 completed/后续 prompt 决定界面变化。
- messageId 由前端生成 UUID，防止列表 key 冲突。
- `text` 为空但有 actions 时显示系统默认提示“请选择行动”。

## 8. 验收标准

- 代码中不存在旧式 `[文本|工具|JSON]` 正则解析。
- `s2c_tactical_prompt` 不使用 `narrative` 字段。
- 按钮提交走 `submitIntent`，不直接调用工具或 WebSocket。
- 聊天记录超过 50 条时裁剪旧消息。
- JSON 降级策略在 Engine 侧完成，前端只消费结构化 payload。

## 9. 测试场景

1. 下发包含 3 个 actions 的 prompt，渲染 3 个按钮。
2. 点击“尝试闪避”，提交 `skill_check` 和 `{ skillName: '闪避' }`。
3. actionState 为 RESOLVING 时按钮禁用。
4. 连续追加 60 条 prompt，Store 保留最近 50 条。

## 10. 风险依赖

- 依赖 Engine 对 AI JSON 进行校验和降级。
- 动作按钮过多会挤占手机屏幕，MVP 限制 1-3 个。
- 后续若支持 Markdown，需要确保不会重新引入指令解析漏洞。

