# 模块 5 —— 战术聊天终端与富文本指令拦截 (Tactical Chat & Inline Buttons) v2.0

## v2.0 修订说明：从正则解析到结构化 JSON + REST 意图

1. **废弃正则解析**：`[文本|工具|JSON]` 的字符串语法和前端正则匹配完全废弃。
2. **AI 输出结构化 JSON**：Engine 通过投影系统下发 `s2c_tactical_prompt`，包含 `{ narrative, actions[] }`，前端直接遍历 `actions` 渲染按钮。
3. **按钮触发走 REST**：点击按钮调用 `submitIntent(intentType, label, params)`，不再直接发 `c2s_tool_invoke`。
4. **防剧透截断由 Engine 负责**：`narrative` 发 Host，`actions` 发 Player，前端不再做正则剔除。
5. **独立聊天消息 Store**。

---

### 第一部分：玩家聊天 Store 扩展

```typescript
// usePlayerStore 扩展
interface PlayerChatMessage {
  messageId: string;
  sender: 'kp' | 'me' | 'system' | 'npc';
  text: string;
  actions?: TacticalAction[];
  timestamp: number;
}

interface TacticalAction {
  actionId: string;
  label: string;
  intentType: string;
  params: Record<string, any>;
}

// Store 中新增
chatMessages: PlayerChatMessage[];
addChatMessage: (msg: PlayerChatMessage) => void;
receiveTacticalPrompt: (prompt: { text: string; actions: TacticalAction[] }) => void;
```

`receiveTacticalPrompt` 由 `PlayerRouter` 在收到 `s2c_tactical_prompt` 事件时调用：

```typescript
receiveTacticalPrompt: (prompt) => set((s) => {
  let newMessages = [...s.chatMessages, {
    messageId: uuidv4(),
    sender: 'kp',
    text: prompt.text,
    actions: prompt.actions || [],
    timestamp: Date.now(),
  }];
  // 手机端严格限制 DOM 节点数量，保留最近 50 条防 OOM
  if (newMessages.length > 50) newMessages = newMessages.slice(-50);
  return { chatMessages: newMessages };
}),
```

### 第二部分：战术消息气泡 (`TacticalMessageBubble.tsx`)

完全替代旧版 `RichTextBubble`——不再使用正则，直接遍历结构化 `actions` 数组。

```typescript
// src/client/player/components/TacticalMessageBubble.tsx
import React from 'react';
import { usePlayerAction } from '../hooks/usePlayerAction';
import { TacticalAction } from '../store/usePlayerStore';
import './TacticalChat.css';

interface Props {
  messageId: string;
  sender: 'kp' | 'me' | 'system';
  text: string;
  actions?: TacticalAction[];
}

export function TacticalMessageBubble({ messageId, sender, text, actions }: Props) {
  const { actionState, submitIntent } = usePlayerAction();
  const isLocked = actionState !== 'IDLE';

  return (
    <div className={`chat-bubble ${sender}`}>
      {/* 纯净叙事文本，无 [] 代码乱码 */}
      <div className="narrative-text">{text}</div>

      {/* 结构化的战术按钮组 */}
      {actions && actions.length > 0 && (
        <div className="action-button-group">
          {actions.map(action => (
            <button
              key={action.actionId}
              disabled={isLocked}
              className={`tactical-btn ${isLocked ? 'locked' : 'ready'}`}
              onClick={() => {
                if (navigator.vibrate) navigator.vibrate(40);
                submitIntent(action.intentType, action.label, action.params);
              }}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

### 第三部分：聊天消息列表 (`ChatLog.tsx`)

```typescript
// src/client/player/components/ChatLog.tsx
import React from 'react';
import { usePlayerStore } from '../store/usePlayerStore';
import { TacticalMessageBubble } from './TacticalMessageBubble';

export function ChatLog() {
  const messages = usePlayerStore(s => s.chatMessages);

  return (
    <div className="chat-log-container">
      {messages.map(msg => (
        <TacticalMessageBubble
          key={msg.messageId}
          messageId={msg.messageId}
          sender={msg.sender}
          text={msg.text}
          actions={msg.actions}
        />
      ))}
    </div>
  );
}
```

### 第四部分：AI 侧的 JSON 输出规范（System Prompt 片段）

Engine 在调用大模型时注入以下输出要求：

> 当玩家面临关键抉择或需要技能检定时，在 JSON 响应的 `actions` 数组中提供 1-3 个快捷选项。
>
> ```json
> {
>   "narrative": "怪物挥舞着触手向你砸来！",
>   "actions": [
>     { "actionId": "act_dodge_01", "label": "🎲 尝试闪避", "intentType": "skill_check", "params": { "skillName": "闪避" } },
>     { "actionId": "act_fire_02", "label": "🔫 绝命反击", "intentType": "skill_check", "params": { "skillName": "手枪" } },
>     { "actionId": "act_flee_03", "label": "🏃 拔腿就跑", "intentType": "move", "params": { "target": "一层大厅" } }
>   ]
> }
> ```
>
> 如果 JSON 解析失败，Engine 将降级为纯文本展示，玩家仍可通过语音对讲机进行下一步操作。

### 第五部分：数据流闭环

1. **AI 输出** → Engine 收到 JSON → 提取 `narrative` 发 Host（大屏字幕），完整 JSON 通过单播 `s2c_tactical_prompt` 发 Player。
2. **Player Router** → `receiveTacticalPrompt(payload)` → Store 追加 `PlayerChatMessage` → `ChatLog` 重新渲染。
3. **玩家点击按钮** → `submitIntent(action.intentType, action.label, action.params)` → `POST /api/player/intent` → Engine 处理 → `s2c_action_completed` → 解锁 UI。

### 模块 5 小结

从"正则解析脆弱字符串"到"结构化 JSON + 类型安全的 React 遍历"的全面升级。前端不再承担从文本中提取指令的职责，AI 输出规范、Engine 投影分发、前端渲染三层各司其职。
