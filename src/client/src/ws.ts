import { EngineEvent } from './types';

type EventHandler = (event: EngineEvent) => void;

export class PlayerWS {
  private ws: WebSocket | null = null;
  private handlers: EventHandler[] = [];
  private roomId: string;
  private lastSequence = 0;
  private reconnectDelay = 1000;
  private maxDelay = 30000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(roomId: string) {
    this.roomId = roomId;
  }

  connect(token: string) {
    if (this.stopped) return;
    const url = `ws://${window.location.hostname}:3001/ws?room=${this.roomId}&role=player&token=${token}&lastSequence=${this.lastSequence}`;
    this.ws = new WebSocket(url);
    this.ws.onmessage = (msg) => {
      const event: EngineEvent = JSON.parse(msg.data);
      this.lastSequence = event.roomSequence;
      this.handlers.forEach((h) => h(event));
    };
    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
    };
    this.ws.onclose = () => {
      if (this.stopped) return;
      this.reconnectTimer = setTimeout(() => {
        this.connect(token);
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5 + Math.random() * 1000, this.maxDelay);
      }, this.reconnectDelay);
    };
  }

  onEvent(handler: EventHandler) {
    this.handlers.push(handler);
  }

  disconnect() {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }
}
