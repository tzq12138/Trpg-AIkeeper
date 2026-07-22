# 方向 1 —— 玩家级通信网关与单播路由 (Player Network & Unicast Routing) v2.0

## v2.0 修订说明：从 WebSocket 双向指令到 REST 意图 + WebSocket 单播下行

本模块是 Player 端改动最大的部分，彻底废弃 v1.x 的 `sendCommand(type, payload)` 模式：

1. **上行全走 REST**：所有玩家操作（检定、使用物品、语音指令）统一走 `POST /api/player/intent`。废弃 `c2s_manual_roll`、`c2s_interact_item`、`c2s_tool_invoke`。
2. **下行用 EngineEvent 标准信封**：与 Host 端共用 `EngineEvent<T>`，通过 `audience` 和 `playerSequence` 区分。
3. **单播由服务端物理隔离**：前端不再依赖 `msg.target === myCharacterId` 过滤——该角色不该收到的包根本不会到达其 WebSocket 连接。
4. **认证用 `X-Room-Token`**：基于 localStorage UUID 的轻量鉴权，对齐项目"无认证"现状。
5. **序列号校验 + 重连**：`playerSequence` 去重/乱序拦截，指数退避重连。

---

### 第一部分：升级的消息信封（与 Host 共用）

本模块从 `shared/protocol.ts` 引入 `EngineEvent`，不再自创 `ServerMessage`。

```typescript
// 下行信封（与 Host 共用 shared/protocol.ts）
export interface EngineEvent<T = unknown> {
  eventId: string;
  roomId: string;
  type: EngineEventType;
  roomSequence: number;
  hostSequence?: number;
  playerSequence?: number;
  audience: EventAudience;
  visibility: 'public' | 'private' | 'party' | 'hostOnly';
  transactionId?: string;
  sourceActionId?: string;
  issuedAt: number;
  payload: T;
}
```

### 第二部分：带身份标识的 WebSocket 客户端 (`PlayerWSClient.ts`)

```typescript
// src/client/player/network/PlayerWSClient.ts
import { routePlayerEvent } from './PlayerRouter';
import { usePlayerStore } from '../store/usePlayerStore';

export class PlayerWSClient {
  private static instance: PlayerWSClient;
  private ws: WebSocket | null = null;
  private roomId: string;
  public characterId: string;
  private retryCount = 0;
  private maxRetries = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private constructor(roomId: string, characterId: string) {
    this.roomId = roomId;
    this.characterId = characterId;
  }

  public static getInstance(roomId?: string, characterId?: string): PlayerWSClient {
    if (!PlayerWSClient.instance && roomId && characterId) {
      PlayerWSClient.instance = new PlayerWSClient(roomId, characterId);
    }
    return PlayerWSClient.instance;
  }

  public connect() {
    const lastSeq = usePlayerStore.getState().lastPlayerSequence ?? 0;
    const roomToken = usePlayerStore.getState().roomToken;
    const wsUrl = `${import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws'}?room=${this.roomId}&role=player&characterId=${this.characterId}&lastSequence=${lastSeq}&token=${roomToken}`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log(`[Player] 🟢 ${this.characterId} 已接入`);
      this.retryCount = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: EngineEvent = JSON.parse(event.data);
        routePlayerEvent(msg);
      } catch (err) {
        console.error('[Player] 消息解析失败:', err);
      }
    };

    this.ws.onclose = () => {
      console.warn('[Player] 🔴 断开，准备重连...');
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect() {
    if (this.retryCount >= this.maxRetries) return;
    const baseMs = Math.min(1000 * Math.pow(2, this.retryCount), 30000);
    const jitter = baseMs * (0.8 + Math.random() * 0.4);
    this.retryCount++;
    this.reconnectTimer = setTimeout(() => this.connect(), jitter);
  }

  public disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}
```

### 第三部分：静默拦截路由器 (`PlayerRouter.ts`)

v2.0：单播已由服务端物理隔离，路由器不再做 `target` 过滤。转而做序列号校验和事件分发。

```typescript
// src/client/player/network/PlayerRouter.ts
import { EngineEvent, INSTANT_EVENT_WHITELIST } from 'shared/protocol';
import { usePlayerStore } from '../store/usePlayerStore';

export function routePlayerEvent(msg: EngineEvent) {
  const store = usePlayerStore.getState();

  // 1. 房间校验
  if (msg.roomId !== store.roomId) return;

  // 2. 序列号去重
  const seq = msg.playerSequence ?? msg.roomSequence;
  if (seq <= store.lastPlayerSequence) return;
  store.markPlayerSequence(seq);

  // 3. 动作生命周期事件 → 更新锁状态
  if (msg.type === 's2c_action_completed') {
    store.setLatestCompletedAction(msg.payload);
    return;
  }

  // 4. 私密通知
  if (msg.type === 's2c_private_notice') {
    store.addPrivateNotification(msg.payload);
    return;
  }

  // 5. 战术面板
  if (msg.type === 's2c_tactical_prompt') {
    store.receiveTacticalPrompt(msg.payload);
    return;
  }

  // 6. 状态快照 / 补丁 —— 全量覆写或增量应用
  if (msg.type === 's2c_full_snapshot') {
    store.applyFullSnapshot(msg.payload);
    return;
  }

  if (msg.type === 's2c_state_patch') {
    store.applyStatePatch(msg.payload);
    return;
  }

  // 7. 公共观察（旁观视角）
  if (msg.type === 's2c_public_observation') {
    store.addPublicObservation(msg.payload);
    return;
  }

  // 8. 事务中的状态变更也会以 s2c_state_patch 到达，
  //    不需单独处理 s2c_reveal_transaction（Player 不渲染演出）
}
```

### 第四部分：体验闭环

1. **Engine 判定玩家 A 获得私密线索** → 仅向 A 的 socket 发送 `s2c_private_notice` + `s2c_state_patch`。
2. **Player A 的路由器**收到后 → 背包更新、手机震动、弹出暗红色通知。
3. **Player B 的 socket**根本没有收到这个包，零开销、零泄漏。

上行则是另一条路径：
1. 玩家点击"🎲 侦查" → `usePlayerAction().submitIntent('skill_check', '我仔细检查门锁', { skillName: '侦查' })`
2. `POST /api/player/intent` → Engine 校验 → 返回 202
3. Engine 处理后通过 WebSocket 单独下发 `s2c_action_completed{ actionId, status: 'resolved' }`
4. 前端解锁 UI，玩家可进行下一次操作。

### 模块 1 小结

Player 端的通信模型从"WebSocket 双向指令"重写为"REST 上行意图 + WebSocket 下行事件"。单播由 Engine 物理隔离，前端不再持有 `target` 过滤逻辑。序列号校验和指数退避重连补齐了断线恢复能力。
