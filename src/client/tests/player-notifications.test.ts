import { describe, expect, test } from 'vitest';
import {
  countUnreadPlayerNotifications,
  notificationReadStorageKey,
  readNotificationReadSequence,
  writeNotificationReadSequence,
} from '../src/shared/player-notifications';

describe('player notification counters', () => {
  test('counts only unread private results and party clues without reading payload text', () => {
    expect(countUnreadPlayerNotifications([
      { sequence: 8, event_type: 's2c_private_notice' },
      { sequence: 11, event_type: 's2c_private_notice' },
      { roomSequence: 12, type: 's2c_clue_discovered' },
      { sequence: 13, event_type: 's2c_clue_shared' },
      { sequence: 14, event_type: 's2c_public_observation' },
      { sequence: 15, event_type: 's2c_host_snapshot' },
      { roomSequence: 11, type: 's2c_private_notice' },
    ], 10)).toEqual({
      privateResults: 2,
      publicClues: 1,
    });
  });

  test('persists only a numeric notification read watermark', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };

    writeNotificationReadSequence(storage, 'room-42', 24);

    expect(notificationReadStorageKey('room-42')).toBe('aikeeper_notification_read:room-42');
    expect(values.get('aikeeper_notification_read:room-42')).toBe('24');
    expect(readNotificationReadSequence(storage, 'room-42')).toBe(24);
  });
});
