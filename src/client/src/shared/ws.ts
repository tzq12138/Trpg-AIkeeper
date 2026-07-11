import { EngineEvent } from './types';
import { buildRoomWsUrl } from './ws-url';

type EventHandler = (event: EngineEvent) => void;
export type PlayerWSStatus = 'connecting' | 'open' | 'reconnecting' | 'closed' | 'unauthorized';
type StatusHandler = (status: PlayerWSStatus) => void;

export class PlayerWS {
  private ws: WebSocket | null = null;
  private handlers: EventHandler[] = [];
  private statusHandlers: StatusHandler[] = [];
  private roomId: string;
  private lastSequence = 0;
  private reconnectDelay = 1000;
  private maxDelay = 30000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(roomId: string) {
    this.roomId = roomId;
    this.lastSequence = this.readStoredSequence();
  }

  connect(token: string) {
    if (this.stopped) return;
    this.emitStatus(this.ws ? 'reconnecting' : 'connecting');
    const url = buildRoomWsUrl(window.location, {
      roomId: this.roomId,
      role: 'player',
      token,
      lastSequence: this.lastSequence,
    });
    this.ws = new WebSocket(url);
    this.ws.onmessage = (msg) => {
      try {
        const event: EngineEvent = JSON.parse(msg.data);
        if (typeof event.roomSequence === 'number' && event.roomSequence > 0) {
          if (event.roomSequence <= this.lastSequence) return;
          this.setLastSequence(event.roomSequence);
        }
        this.handlers.forEach((h) => h(event));
      } catch { /* ignore malformed frames — don't crash the event pipe */ }
    };
    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.emitStatus('open');
    };
    this.ws.onclose = (event) => {
      this.ws = null;
      if (event.code === 4003) {
        this.stopped = true;
        this.emitStatus('unauthorized');
        return;
      }
      if (this.stopped) return;
      this.emitStatus('reconnecting');
      this.reconnectTimer = setTimeout(() => {
        this.connect(token);
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5 + Math.random() * 1000, this.maxDelay);
      }, this.reconnectDelay);
    };
  }

  onEvent(handler: EventHandler) {
    this.handlers.push(handler);
  }

  onStatus(handler: StatusHandler) {
    this.statusHandlers.push(handler);
  }

  setLastSequence(sequence: number) {
    if (!Number.isInteger(sequence) || sequence < 0) return;
    this.lastSequence = Math.max(this.lastSequence, sequence);
    try {
      localStorage.setItem(this.sequenceStorageKey(), String(this.lastSequence));
    } catch { /* storage can be unavailable in private browsing */ }
  }

  disconnect() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
    this.emitStatus('closed');
  }

  private sequenceStorageKey() {
    return `aikeeper_ws_sequence:${this.roomId}`;
  }

  private readStoredSequence() {
    try {
      const stored = Number.parseInt(localStorage.getItem(this.sequenceStorageKey()) ?? '0', 10);
      return Number.isInteger(stored) && stored >= 0 ? stored : 0;
    } catch {
      return 0;
    }
  }

  private emitStatus(status: PlayerWSStatus) {
    this.statusHandlers.forEach((handler) => handler(status));
  }
}
