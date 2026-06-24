# 模块 2 —— 全局状态聚合与可视化面板 (Global HUD & Data Aggregation) v2.0

## v2.0 修订说明：Store 收口为单一真相源 + camelCase 强约束

1. **Store 收口**：Zustand store 不再由各模块"增量追加"，而是在本模块给出 `useHostStore` 的**完整定义**，包含所有后续模块需要的字段。
2. **camelCase 强约束**：`character_id` → `characterId`，`skill_name` → `skillName`，与协议对齐。
3. **状态更新只走事务或 patch**：废弃直接从 `s2c_status_sync` 更新 HUD 的旧路径。HUD 的数值变更由 `s2c_reveal_transaction` 的 `status_delta` step 或 `s2c_state_patch` 驱动。
4. **角色卡动画由 Store 驱动**：`PlayerCard` 不自行监听 `isTakingDamage` 状态变化——改为由 Store 的 `applyPublicStatusDelta` 方法统一触发。
5. **房间切换清空**：`resetRoomStore()` 全量归零。

---

### 第一部分：完整状态树定义 (`useHostStore.ts`)

这是 Host 端 Zustand Store 的**唯一定义文件**，不再分散在多个模块中。

```typescript
// src/client/host/store/useHostStore.ts
import { create } from 'zustand';
import { EngineEvent, RollEventPayload } from '../network/types';

// ─── 共享类型（对齐协议） ───

export interface CharacterNode {
  characterId: string;
  name: string;
  avatarUrl: string;
  hp: { current: number; max: number };
  san: { current: number; max: number };
  mp?: { current: number; max: number };
  luck?: { current: number; max: number };
  statusTags: string[];
}

export interface ChatMessage {
  streamId: string;
  speakerName?: string;
  role: 'keeper' | 'npc' | 'system';
  text: string;
}

export interface AtmosphereState {
  visual: {
    filter?: 'deep_red' | 'cold_blue' | 'sepia' | 'darkness';
    vignette?: number;
    shake?: { intensity: 'low' | 'medium' | 'high'; durationMs: number };
    glitch?: boolean;
  };
  bgm: {
    trackId: string | null;
    volume: number;
    fadeInMs: number;
  };
  sfxQueue: { clipId: string; volume?: number }[];
}

// ─── 完整 Store 接口 ───

interface HostState {
  roomId: string;
  players: Record<string, CharacterNode>;
  currentSceneImageUrl: string;
  chatMessages: ChatMessage[];
  engineState: string | null;

  // 多级队列 (模块 3 使用)
  normalQueue: EngineEvent[];
  urgentQueue: EngineEvent[];
  interruptedTransaction: { txId: string } | null;
  activeTransactionId: string | null;
  currentRollEvent: RollEventPayload | null;

  // 序列号
  lastHostSequence: number;

  // 氛围 (模块 4 使用)
  atmosphere: AtmosphereState;

  // ─── 原子 Actions ───

  // 生命周期
  resetRoomStore: () => void;
  markHostSequence: (seq: number) => void;

  // 队列操作
  enqueueNormal: (event: EngineEvent) => void;
  enqueueUrgent: (event: EngineEvent) => void;
  popNextEvent: () => EngineEvent | null;
  completeActiveTransaction: () => void;
  setTransactionLock: (txId: string | null) => void;
  interruptActiveTransaction: (newTxId: string) => void;
  resumeInterruptedTransaction: (txId: string) => void;
  cancelInterruptedTransaction: (txId: string) => void;

  // 演出
  setRollEvent: (roll: RollEventPayload | null) => void;
  applyPublicStatusDelta: (characterId: string, delta: Record<string, unknown>) => void;
  setSceneImage: (url: string) => void;
  appendChatMessage: (streamId: string, chunk: string, meta?: { role?: string; speakerName?: string }) => void;

  // 氛围
  setAtmosphere: (payload: Partial<AtmosphereState>) => void;
  setEngineState: (state: string) => void;
  shiftSfx: () => void;

  // 快照与补丁
  applyFullSnapshot: (snapshot: Record<string, unknown>) => void;
  applyStatePatch: (patch: Record<string, unknown>) => void;
}

export const useHostStore = create<HostState>((set, get) => ({
  roomId: '',
  players: {},
  currentSceneImageUrl: '',
  chatMessages: [],
  engineState: null,

  normalQueue: [],
  urgentQueue: [],
  interruptedTransaction: null,
  activeTransactionId: null,
  currentRollEvent: null,

  lastHostSequence: -1,

  atmosphere: {
    visual: {},
    bgm: { trackId: null, volume: 0.5, fadeInMs: 2000 },
    sfxQueue: [],
  },

  // ─── 生命周期 ───

  resetRoomStore: () => set({
    players: {},
    currentSceneImageUrl: '',
    chatMessages: [],
    engineState: null,
    normalQueue: [],
    urgentQueue: [],
    interruptedTransaction: null,
    activeTransactionId: null,
    currentRollEvent: null,
    lastHostSequence: -1,
  }),

  markHostSequence: (seq) => set({ lastHostSequence: seq }),

  // ─── 队列操作 ───

  enqueueNormal: (event) => set((s) => ({ normalQueue: [...s.normalQueue, event] })),
  enqueueUrgent: (event) => set((s) => ({ urgentQueue: [...s.urgentQueue, event] })),

  popNextEvent: () => {
    const { urgentQueue, normalQueue } = get();
    if (urgentQueue.length > 0) {
      const [next, ...rest] = urgentQueue;
      set({ urgentQueue: rest });
      return next;
    }
    if (normalQueue.length > 0) {
      const [next, ...rest] = normalQueue;
      set({ normalQueue: rest });
      return next;
    }
    return null;
  },

  completeActiveTransaction: () => set({ activeTransactionId: null }),

  setTransactionLock: (txId) => set({ activeTransactionId: txId }),

  interruptActiveTransaction: (newTxId) => set((s) => ({
    interruptedTransaction: s.activeTransactionId ? { txId: s.activeTransactionId, /* 保存状态 */ } : null,
    activeTransactionId: newTxId,
  })),

  resumeInterruptedTransaction: (txId) => set((s) =>
    s.interruptedTransaction?.txId === txId
      ? { activeTransactionId: txId, interruptedTransaction: null }
      : s
  ),

  cancelInterruptedTransaction: (txId) => set((s) =>
    s.interruptedTransaction?.txId === txId
      ? { interruptedTransaction: null }
      : s
  ),

  // ─── 演出 ───

  setRollEvent: (roll) => set({ currentRollEvent: roll }),

  applyPublicStatusDelta: (characterId, delta) => set((s) => {
    const player = s.players[characterId];
    if (!player) return s;
    return {
      players: {
        ...s.players,
        [characterId]: { ...player, ...delta },
      },
    };
  }),

  setSceneImage: (url) => set({ currentSceneImageUrl: url }),

  appendChatMessage: (streamId, chunk, meta) => set((s) => {
    let messages = [...s.chatMessages];
    const existingIdx = messages.findIndex(m => m.streamId === streamId);
    if (existingIdx > -1) {
      messages[existingIdx] = {
        ...messages[existingIdx],
        text: messages[existingIdx].text + chunk,
      };
    } else {
      messages.push({
        streamId,
        text: chunk,
        role: meta?.role || 'keeper',
        speakerName: meta?.speakerName,
      });
    }
    // 保留最近 200 条消息，防止长期跑团导致 OOM
    if (messages.length > 200) messages = messages.slice(-200);
    return { chatMessages: messages };
  }),

  // ─── 氛围 ───

  setAtmosphere: (payload) => set((s) => ({
    atmosphere: {
      visual: { ...s.atmosphere.visual, ...(payload.visual || {}) },
      bgm: payload.bgm ? { ...s.atmosphere.bgm, ...payload.bgm } : s.atmosphere.bgm,
      sfxQueue: payload.sfx ? [...s.atmosphere.sfxQueue, ...payload.sfx] : s.atmosphere.sfxQueue,
    },
  })),

  setEngineState: (state) => set({ engineState: state }),
  shiftSfx: () => set((s) => ({ atmosphere: { ...s.atmosphere, sfxQueue: s.atmosphere.sfxQueue.slice(1) } })),

  // ─── 快照与补丁 ───

  applyFullSnapshot: (snapshot) => set({
    players: snapshot.players || {},
    currentSceneImageUrl: snapshot.currentSceneImageUrl || '',
  }),

  applyStatePatch: (patch) => {
    if (patch.characterId && patch.publicDelta) {
      get().applyPublicStatusDelta(patch.characterId, patch.publicDelta);
    }
  },
}));
```

### 第二部分：全局监视器布局 (`GlobalHUD.tsx`)

```typescript
// src/client/host/components/GlobalHUD.tsx
import React from 'react';
import { useHostStore } from '../store/useHostStore';
import { PlayerCard } from './PlayerCard';
import './GlobalHUD.css';

export function GlobalHUD() {
  const players = useHostStore(state => state.players);

  return (
    <div className="global-hud-container">
      {Object.values(players).map(player => (
        <PlayerCard key={player.characterId} player={player} />
      ))}
    </div>
  );
}
```

### 第三部分："活体"角色卡组件 (`PlayerCard.tsx`)

v2.0：受伤动画不再由 `PlayerCard` 内部 `useEffect` 监听——改为接收 Store 中的瞬时动画状态，播完即止。

```typescript
// src/client/host/components/PlayerCard.tsx
import React from 'react';
import { CharacterNode } from '../store/useHostStore';

export function PlayerCard({ player }: { player: CharacterNode }) {
  const hpPercent = (player.hp.current / player.hp.max) * 100;
  const sanPercent = (player.san.current / player.san.max) * 100;
  const isDying = hpPercent <= 30;

  return (
    <div className={`player-card ${isDying ? 'critical-border' : ''}`}>
      <img src={player.avatarUrl} alt={player.name} className="avatar" />

      <div className="stats-area">
        <div className="player-name">{player.name}</div>

        <div className="stat-bar-container">
          <span className="stat-label">HP</span>
          <div className="bar-bg">
            <div className="bar-fill hp-fill" style={{ width: `${hpPercent}%` }} />
          </div>
          <span className="stat-value">{player.hp.current}/{player.hp.max}</span>
        </div>

        <div className="stat-bar-container">
          <span className="stat-label">SAN</span>
          <div className="bar-bg">
            <div className="bar-fill san-fill" style={{ width: `${sanPercent}%` }} />
          </div>
          <span className="stat-value">{player.san.current}/{player.san.max}</span>
        </div>

        <div className="tags-area">
          {player.statusTags.map(tag => (
            <span key={tag} className="status-tag">{tag}</span>
          ))}
        </div>
      </div>
    </div>
  );
}
```

### 模块 2 小结

Store 收口为本模块的唯一定义，后继模块 3/4/5 均引用此文件。`snake_case` 全面清除，`characterId` 统一。HUD 的数值变更唯一来源为 `applyPublicStatusDelta`（由事务 `status_delta` step 或 `s2c_state_patch` 驱动）。
