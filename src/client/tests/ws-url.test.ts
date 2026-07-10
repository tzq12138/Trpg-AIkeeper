import { describe, expect, test } from 'vitest';
import { buildRoomWsUrl } from '../src/shared/ws-url';

describe('room websocket URL', () => {
  test('uses the current frontend host so Vite can proxy websocket traffic', () => {
    const url = buildRoomWsUrl(
      { protocol: 'http:', host: '127.0.0.1:5173' },
      { roomId: 'room-1', role: 'player', token: 'player-token', lastSequence: 3 },
    );

    expect(url).toBe('ws://127.0.0.1:5173/ws?room=room-1&role=player&token=player-token&lastSequence=3');
  });

  test('switches to wss on HTTPS origins', () => {
    const url = buildRoomWsUrl(
      { protocol: 'https:', host: 'game.example.test' },
      { roomId: 'room-1', role: 'host', ownerToken: 'owner-token' },
    );

    expect(url).toBe('wss://game.example.test/ws?room=room-1&role=host&ownerToken=owner-token');
  });
});
