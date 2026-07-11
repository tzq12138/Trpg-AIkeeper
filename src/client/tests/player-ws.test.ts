import { beforeAll, beforeEach, describe, expect, test, vi } from 'vitest';

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key: string) { return store.get(key) ?? null; },
    key(index: number) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key: string) { store.delete(key); },
    setItem(key: string, value: string) { store.set(key, value); },
  };
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onmessage: ((event: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {}
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: createStorageMock(),
    configurable: true,
  });
  Object.defineProperty(globalThis, 'window', {
    value: { location: new URL('http://127.0.0.1:5173/player/room-1') },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'WebSocket', {
    value: FakeWebSocket,
    configurable: true,
  });
});

beforeEach(() => {
  localStorage.clear();
  FakeWebSocket.instances = [];
  vi.useFakeTimers();
});

describe('PlayerWS reconnect authority', () => {
  test('persists last sequence and ignores duplicate or out-of-order events', async () => {
    const { PlayerWS } = await import('../src/shared/ws');
    const received: number[] = [];
    const ws = new PlayerWS('room-1');
    ws.onEvent((event) => received.push(event.roomSequence));
    ws.connect('player-token');
    const socket = FakeWebSocket.instances[0];

    socket.onmessage?.({ data: JSON.stringify({
      eventId: 'e2', roomId: 'room-1', roomSequence: 2,
      type: 's2c_public_observation', audience: 'party', visibility: 'public', issuedAt: '', payload: {},
    }) });
    socket.onmessage?.({ data: JSON.stringify({
      eventId: 'e1', roomId: 'room-1', roomSequence: 1,
      type: 's2c_public_observation', audience: 'party', visibility: 'public', issuedAt: '', payload: {},
    }) });

    expect(received).toEqual([2]);
    expect(localStorage.getItem('aikeeper_ws_sequence:room-1')).toBe('2');

    const restored = new PlayerWS('room-1');
    restored.connect('player-token');
    expect(FakeWebSocket.instances[1].url).toContain('lastSequence=2');
  });

  test('REST reconnect can seed the next websocket sequence', async () => {
    const { PlayerWS } = await import('../src/shared/ws');
    const ws = new PlayerWS('room-1');

    ws.setLastSequence(77);
    ws.connect('player-token');

    expect(FakeWebSocket.instances[0].url).toContain('lastSequence=77');
    expect(localStorage.getItem('aikeeper_ws_sequence:room-1')).toBe('77');
  });

  test('invalid player token closes permanently instead of reconnecting forever', async () => {
    const { PlayerWS } = await import('../src/shared/ws');
    const statuses: string[] = [];
    const ws = new PlayerWS('room-1');
    ws.onStatus((status) => statuses.push(status));
    ws.connect('bad-token');
    const socket = FakeWebSocket.instances[0];

    socket.onclose?.({ code: 4003 });
    await vi.runAllTimersAsync();

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(statuses.at(-1)).toBe('unauthorized');
  });
});
