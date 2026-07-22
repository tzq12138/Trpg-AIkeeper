# 模块 1 —— Host 端通信总线与路由分发层 (Communication & Dispatch) v2.0

## v2.0 修订说明：全面对齐《AI-Keeper 全局通信与状态契约》

本模块从"收到就分发"的 v1.x 原型，升级为与统一协议严格对齐的工业级通信层：

1. **统一信封**：废弃自创的 `ServerMessage`，全面采用 `EngineEvent<T>` 标准信封（`eventId`, `roomId`, `type`, `roomSequence`, `hostSequence`, `audience`, `visibility`, `issuedAt`, `payload`）。
2. **camelCase 强约束**：所有字段名统一使用 camelCase（`characterId` 而非 `character_id`），与协议契约完全一致。
3. **瞬时事件白名单**：Host 端仅处理大屏专属事件（`s2c_atmosphere`, `s2c_engine_state`, `s2c_scene_sync`, `s2c_host_snapshot`）。Player 专属的 `s2c_full_snapshot` / `s2c_state_patch` 不在 Host 白名单内，误收即丢弃。
4. **废弃独立掷骰事件**：`s2c_roll_event` 已从协议中移除，掷骰必须作为 `s2c_reveal_transaction` 的一个 step 下发。
5. **房间隔离**：切换房间时断开旧连接并调用 `resetRoomStore()` 清空状态。
6. **重连退避**：实现指数退避 + jitter，替代固定 5s 重试。

---

### 第一部分：工程目录结构

```
src/client/host/
  ├── network/
  │    ├── types.ts              // 从 shared/protocol.ts 重导出的强类型
  │    ├── HostWSClient.ts       // WebSocket 单例 + 指数退避重连
  │    └── EventRouter.ts        // 路由器：校验信封 → 白名单拦截 → 分发
  ├── store/
  │    └── useHostStore.ts       // 全局状态管理（单一真相源）
```

### 第二部分：强类型接口（对齐 shared/protocol.ts）

```typescript
// src/client/host/network/types.ts
// 本文件从 shared/protocol.ts 重导出，此处展示核心类型

export type EngineEventType =
  | 's2c_reveal_transaction'
  | 's2c_chat_stream'
  | 's2c_atmosphere'
  | 's2c_engine_state'
  | 's2c_scene_sync'
  | 's2c_full_snapshot'
  | 's2c_state_patch'
  | 's2c_private_notice'
  | 's2c_public_observation'
  | 's2c_action_completed'
  | 's2c_resume_transaction'
  | 's2c_cancel_transaction'
  | 's2c_tactical_prompt';

export type EventAudience = 'host' | 'player' | 'party' | 'system';

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

// 瞬时事件白名单：Host 端仅处理大屏专属事件，Player 事件（full_snapshot/state_patch）不得进入
export const INSTANT_EVENT_WHITELIST: EngineEventType[] = [
  's2c_atmosphere',
  's2c_engine_state',
  's2c_scene_sync',
  's2c_host_snapshot',
];
```

### 第三部分：带指数退避的 WebSocket 引擎 (`HostWSClient.ts`)

```typescript
// src/client/host/network/HostWSClient.ts
import { routeHostEvent } from './EventRouter';
import { useHostStore } from '../store/useHostStore';

export class HostWSClient {
  private static instance: HostWSClient;
  private ws: WebSocket | null = null;
  private roomId: string;
  private retryCount = 0;
  private maxRetries = 10;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  private constructor(roomId: string) {
    this.roomId = roomId;
  }

  public static getInstance(roomId: string): HostWSClient {
    if (!HostWSClient.instance || HostWSClient.instance.roomId !== roomId) {
      HostWSClient.instance?.disconnect();
      // 切换房间时清空 Store
      useHostStore.getState().resetRoomStore();
      HostWSClient.instance = new HostWSClient(roomId);
    }
    return HostWSClient.instance;
  }

  public connect() {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;

    const baseUrl = import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000/ws';
    const lastSequence = useHostStore.getState().lastHostSequence ?? 0;
    const wsUrl = `${baseUrl}?room=${this.roomId}&role=host&lastSequence=${lastSequence}`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log(`[Host] 🟢 已连接, 房间: ${this.roomId}`);
      this.retryCount = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const message: EngineEvent = JSON.parse(event.data);
        routeHostEvent(message);
      } catch (err) {
        console.error('[Host] 消息解析失败:', err);
      }
    };

    this.ws.onclose = () => {
      console.warn('[Host] 🔴 断开，准备重连...');
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[Host] WebSocket 错误:', err);
    };
  }

  private scheduleReconnect() {
    if (this.retryCount >= this.maxRetries) {
      console.error('[Host] 已达最大重试次数，停止重连');
      return;
    }
    // 指数退避：1s → 2s → 4s → ... 最大 30s，加 ±20% jitter
    const baseMs = Math.min(1000 * Math.pow(2, this.retryCount), 30000);
    const jitter = baseMs * (0.8 + Math.random() * 0.4);
    this.retryCount++;
    console.log(`[Host] ${Math.round(jitter)}ms 后第 ${this.retryCount} 次重连...`);
    this.reconnectTimer = setTimeout(() => this.connect(), jitter);
  }

  public disconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }
}
```

### 第四部分：核心路由器 (`EventRouter.ts`)

```typescript
// src/client/host/network/EventRouter.ts
import { EngineEvent, INSTANT_EVENT_WHITELIST } from './types';
import { useHostStore } from '../store/useHostStore';

export function routeHostEvent(msg: EngineEvent) {
  const store = useHostStore.getState();

  // 1. 房间校验
  if (msg.roomId !== store.roomId) return;

  // 2. 序列号去重与乱序校验（使用 hostSequence）
  const seq = msg.hostSequence ?? msg.roomSequence;
  if (seq <= store.lastHostSequence) return;
  store.markHostSequence(seq);

  // 3. 事务事件 → 压入多级队列（由 TransactionPlayer 接管）
  if (msg.type === 's2c_reveal_transaction') {
    if (msg.payload?.priority === 'urgent') {
      store.enqueueUrgent(msg);
    } else {
      store.enqueueNormal(msg);
    }
    return;
  }

  // 3b. 抢占控制信令 → 直达 Store
  if (msg.type === 's2c_resume_transaction') {
    store.resumeInterruptedTransaction(msg.payload.transactionId);
    return;
  }
  if (msg.type === 's2c_cancel_transaction') {
    store.cancelInterruptedTransaction(msg.payload.transactionId);
    store.completeActiveTransaction();
    return;
  }

  // 4. 瞬时事件白名单 → 立即消费
  if (INSTANT_EVENT_WHITELIST.includes(msg.type)) {
    consumeInstantEvent(msg);
    return;
  }

  // 5. 非白名单且非事务事件 → 拦截告警
  console.warn(`[Host] 收到未知/非法事件类型: ${msg.type}，已丢弃`);
}

function consumeInstantEvent(msg: EngineEvent) {
  const store = useHostStore.getState();

  switch (msg.type) {
    case 's2c_atmosphere':
      store.setAtmosphere(msg.payload);
      break;

    case 's2c_engine_state':
      store.setEngineState(msg.payload.state);
      break;

    case 's2c_scene_sync':
      store.setSceneImage(msg.payload.imageUrl);
      break;

    case 's2c_host_snapshot':
      store.applyFullSnapshot(msg.payload);
      break;
  }
}
```

### 第五部分：在 React 根节点挂载

```typescript
// src/client/host/HostApp.tsx
import React, { useEffect } from 'react';
import { HostWSClient } from './network/HostWSClient';
import { AtmosphereOverlay } from './components/AtmosphereOverlay';
import { GlobalHUD } from './components/GlobalHUD';
import { StageRenderer } from './components/Stage/StageRenderer';

export function HostApp({ roomId }: { roomId: string }) {
  useEffect(() => {
    const wsClient = HostWSClient.getInstance(roomId);
    wsClient.connect();
  }, [roomId]);

  return (
    <div className="host-screen-container">
      <AtmosphereOverlay />
      <GlobalHUD />
      <StageRenderer />
    </div>
  );
}
```

### 模块 1 小结

升级后的数据流向：**Python Engine → WebSocket 端口 → `HostWSClient` → `EventRouter` → 事务进队列 / 瞬时事件直接消费 → `useHostStore` → React UI**。序列号校验、白名单拦截、指数退避重连、房间切换清理——四项机制确保通信层不再有"收错房、重复收、断连死"的问题。
