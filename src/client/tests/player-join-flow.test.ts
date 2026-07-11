import { describe, expect, test } from 'vitest';

import {
  buildPlayerJoinReturnPath,
  PLAYER_JOIN_SOURCE_ORDER,
  playerRoomEntryPath,
} from '../src/shared/player-join-flow';

describe('player join flow', () => {
  test('keeps the required character source order', () => {
    expect(PLAYER_JOIN_SOURCE_ORDER).toEqual(['account', 'preset', 'builder', 'upload']);
  });

  test('preserves the invitation room across login or registration', () => {
    expect(buildPlayerJoinReturnPath(' room-1 ')).toBe('/player/join?room=room-1');
  });

  test('active rooms enter the approval-aware lobby', () => {
    expect(playerRoomEntryPath('room-1', 'active')).toBe('/player/room-1/lobby');
  });
});
