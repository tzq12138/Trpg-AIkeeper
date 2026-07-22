# 模块 3 —— 活体角色卡与触控检定 (Living Sheet & Touch-to-Roll) v2.0

## v2.0 修订说明：从 WebSocket sendCommand 到 REST 意图 + 状态机锁

1. **废弃 `sendCommand('c2s_manual_roll', ...)`**：点击技能按钮改为通过 `usePlayerAction().submitIntent('skill_check', ...)` 提交意图。
2. **锁改为状态机**：`isActionLocked: boolean` + `setTimeout` → `actionState: 'IDLE' | 'SUBMITTING' | 'RESOLVING'`，由 `s2c_action_completed` 解锁。
3. **附带 `baseStateVersion`**：每次提交携带当前本地状态版本，Engine 校验防并发。
4. **Store 对齐共享类型**：`PlayerCharacter` 字段与 Host 的 `CharacterNode` 共享基础结构。
5. **camelCase 全面统一**。

---

### 第一部分：Player Store 定义 (`usePlayerStore.ts`)

```typescript
// src/client/player/store/usePlayerStore.ts
import { create } from 'zustand';
import type {
  ActionCompletedPayload, TacticalPromptPayload,
  FullSnapshotPayload, StatePatchPayload,
  PrivateNoticePayload, PublicObservationPayload,
} from 'shared/protocol';

export interface PlayerCharacter {
  characterId: string;
  name: string;
  hp: { current: number; max: number };
  san: { current: number; max: number };
  mp?: { current: number; max: number };
  luck?: { current: number; max: number };
  attributes: Record<string, number>;
  skills: Record<string, number>;
  statusTags: string[];
  isInsane: boolean;
}

export type ActionState = 'IDLE' | 'SUBMITTING' | 'RESOLVING';

export interface Item {
  id: string;
  name: string;
  iconUrl?: string;
  description: string;
  isSecret: boolean;
}

export interface ClueNode {
  id: string;
  title: string;
  summary: string;
  type: 'npc' | 'location' | 'document' | 'truth';
  unlockedAt: string;
}

interface PlayerState {
  character: PlayerCharacter | null;
  roomId: string;
  roomToken: string;
  stateVersion: number;
  lastPlayerSequence: number;

  // 动作状态机
  actionState: ActionState;
  pendingActionId: string | null;
  latestCompletedAction: ActionCompletedPayload | null;

  // 背包与线索
  inventory: Item[];
  clues: ClueNode[];

  // 通知
  privateNotifications: PrivateNoticePayload[];
  publicObservations: PublicObservationPayload[];
  tacticalPrompt: TacticalPromptPayload | null;

  // Actions
  setCharacter: (char: PlayerCharacter) => void;
  markPlayerSequence: (seq: number) => void;
  setActionState: (state: ActionState) => void;
  setPendingAction: (actionId: string | null) => void;
  setLatestCompletedAction: (payload: ActionCompletedPayload) => void;
  receiveItem: (item: Item) => void;
  unlockClue: (clue: ClueNode) => void;
  addPrivateNotification: (notice: PrivateNoticePayload) => void;
  addPublicObservation: (obs: PublicObservationPayload) => void;
  receiveTacticalPrompt: (prompt: TacticalPromptPayload) => void;
  applyFullSnapshot: (snapshot: FullSnapshotPayload) => void;
  applyStatePatch: (patch: StatePatchPayload) => void;
  resetPlayerStore: () => void;
}

export const usePlayerStore = create<PlayerState>((set) => ({
  character: null,
  roomId: '',
  roomToken: localStorage.getItem('roomToken') || '',
  stateVersion: 0,
  lastPlayerSequence: -1,

  actionState: 'IDLE',
  pendingActionId: null,
  latestCompletedAction: null,

  inventory: [],
  clues: [],
  privateNotifications: [],
  publicObservations: [],
  tacticalPrompt: null,

  setCharacter: (char) => set({ character: char }),
  markPlayerSequence: (seq) => set({ lastPlayerSequence: seq }),
  setActionState: (state) => set({ actionState: state }),
  setPendingAction: (actionId) => set({ pendingActionId: actionId }),
  setLatestCompletedAction: (payload) => set({ latestCompletedAction: payload }),

  receiveItem: (item) => set((s) => ({ inventory: [...s.inventory, item] })),
  unlockClue: (clue) => set((s) => ({ clues: [...s.clues, clue] })),
  addPrivateNotification: (notice) => set((s) => ({
    privateNotifications: [...s.privateNotifications, notice],
  })),
  addPublicObservation: (obs) => set((s) => ({
    publicObservations: [...s.publicObservations, obs],
  })),
  receiveTacticalPrompt: (prompt) => set({ tacticalPrompt: prompt }),

  applyFullSnapshot: (snapshot) => set({
    character: snapshot.character,
    inventory: snapshot.inventory || [],
    clues: snapshot.clues || [],
    stateVersion: snapshot.stateVersion,
  }),

  applyStatePatch: (patch) => set((s) => {
    if (!s.character) return s;
    // RFC 6902 JSON Patch 风格的增量应用
    let char = { ...s.character };
    for (const op of patch.patches || []) {
      if (op.op === 'replace' && op.path === '/hp/current') {
        char = { ...char, hp: { ...char.hp, current: op.value } };
      }
      if (op.op === 'replace' && op.path === '/san/current') {
        char = { ...char, san: { ...char.san, current: op.value } };
      }
      // ... 其他路径
    }
    return {
      character: char,
      stateVersion: patch.nextStateVersion ?? s.stateVersion,
      inventory: patch.inventory ? patch.inventory : s.inventory,
      clues: patch.clues ? patch.clues : s.clues,
    };
  }),

  resetPlayerStore: () => set({
    character: null, inventory: [], clues: [],
    actionState: 'IDLE', pendingActionId: null,
    stateVersion: 0, lastPlayerSequence: -1,
  }),
}));
```

### 第二部分：意图提交 Hook (`usePlayerAction.ts`)

```typescript
// src/client/player/hooks/usePlayerAction.ts
import { useState, useEffect, useRef } from 'react';
import { v4 as uuidv4 } from 'uuid';
import { usePlayerStore, ActionState } from '../store/usePlayerStore';

export function usePlayerAction() {
  const actionState = usePlayerStore(s => s.actionState);
  const setActionState = usePlayerStore(s => s.setActionState);
  const setPendingAction = usePlayerStore(s => s.setPendingAction);
  const latestCompletedAction = usePlayerStore(s => s.latestCompletedAction);
  const pendingActionId = usePlayerStore(s => s.pendingActionId);

  const characterId = usePlayerStore(s => s.character?.characterId);
  const roomToken = usePlayerStore(s => s.roomToken);
  const stateVersion = usePlayerStore(s => s.stateVersion);
  const watchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 监听 WebSocket 解锁信令
  useEffect(() => {
    if (actionState === 'RESOLVING' && latestCompletedAction?.actionId === pendingActionId) {
      resetLocks();
    }
  }, [latestCompletedAction]);

  const resetLocks = () => {
    setActionState('IDLE');
    setPendingAction(null);
    if (watchdogRef.current) { clearTimeout(watchdogRef.current); watchdogRef.current = null; }
  };

  const submitIntent = async (intentType: string, declaredIntent: string, params: any = {}) => {
    if (actionState !== 'IDLE' || !characterId) return;

    const actionId = uuidv4();
    setPendingAction(actionId);
    setActionState('SUBMITTING');
    if (navigator.vibrate) navigator.vibrate(30);

    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL}/api/player/intent`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Room-Token': roomToken, // 唯一信任凭证，Engine 由此解密 characterId
        },
        body: JSON.stringify({ actionId, intentType, declaredIntent, baseStateVersion: stateVersion, params }),
      });

      if (res.status === 202 || res.status === 200) {
        setActionState('RESOLVING');
        // 15 秒 Watchdog 兜底：真实发起快照重拉 + 强制解锁 UI
        watchdogRef.current = setTimeout(() => {
          console.error(`[Watchdog] 动作 ${actionId} 结算超时！`);
          setActionState('REJECTED');
          if (navigator.vibrate) navigator.vibrate([50, 50, 50]);

          // 发起兜底同步请求，拿回最新状态
          fetch(`${import.meta.env.VITE_API_URL}/api/player/sync`, {
            headers: { 'X-Room-Token': roomToken }
          }).then(async (res) => {
            const snapshot = await res.json();
            usePlayerStore.getState().applyFullSnapshot(snapshot);
          }).finally(() => {
            // 无论同步成败，必须解锁 UI 让玩家可以重试
            resetLocks();
          });
        }, 15000);
      } else {
        handleRejection();
      }
    } catch {
      handleRejection();
    }
  };

  const handleRejection = () => {
    if (navigator.vibrate) navigator.vibrate([50, 50, 50]);
    resetLocks();
  };

  return { actionState, submitIntent };
}
```

### 第三部分：触控技能按钮 (`SkillButton.tsx`)

```typescript
// src/client/player/components/SkillButton.tsx
import React from 'react';
import { usePlayerAction } from '../hooks/usePlayerAction';

export function SkillButton({ skillName, skillValue }: { skillName: string; skillValue: number }) {
  const { actionState, submitIntent } = usePlayerAction();

  return (
    <button
      className={`skill-btn ${actionState !== 'IDLE' ? 'locked' : ''}`}
      disabled={actionState !== 'IDLE'}
      onClick={() => submitIntent('skill_check', `我使用【${skillName}】技能`, { skillName })}
    >
      <span className="skill-name">{skillName}</span>
      <span className="skill-value">{skillValue}</span>
    </button>
  );
}
```

### 模块 3 小结

技能按钮不再直接"命令系统掷骰"，而是"提交使用该技能的意图"（`submitIntent('skill_check', ...)`）。锁机制从 `boolean + setTimeout(2000)` 升级为完整的 `IDLE → SUBMITTING → RESOLVING` 状态机，由 `s2c_action_completed` 事件驱动解锁。
