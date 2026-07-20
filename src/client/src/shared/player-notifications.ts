export interface PlayerNotificationEvent {
  type?: string;
  event_type?: string;
  roomSequence?: number;
  sequence?: number;
}

export interface PlayerUnreadNotificationCounts {
  privateResults: number;
  publicClues: number;
}

export interface NotificationReadStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const PRIVATE_RESULT_EVENT_TYPES = new Set([
  's2c_private_notice',
  's2c_clue_discovered',
]);

const PUBLIC_CLUE_EVENT_TYPES = new Set([
  's2c_clue_shared',
]);

function eventSequence(event: PlayerNotificationEvent): number {
  const value = event.roomSequence ?? event.sequence ?? 0;
  return Number.isSafeInteger(value) && value > 0 ? value : 0;
}

export function notificationReadStorageKey(roomId: string): string {
  return `aikeeper_notification_read:${roomId}`;
}

export function readNotificationReadSequence(
  storage: NotificationReadStorage,
  roomId: string,
): number | null {
  const value = Number.parseInt(storage.getItem(notificationReadStorageKey(roomId)) ?? '', 10);
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

export function writeNotificationReadSequence(
  storage: NotificationReadStorage,
  roomId: string,
  sequence: number,
): void {
  if (!Number.isSafeInteger(sequence) || sequence < 0) return;
  storage.setItem(notificationReadStorageKey(roomId), String(sequence));
}

export function countUnreadPlayerNotifications(
  events: PlayerNotificationEvent[],
  lastReadSequence: number,
): PlayerUnreadNotificationCounts {
  const seenSequences = new Set<number>();
  const counts: PlayerUnreadNotificationCounts = { privateResults: 0, publicClues: 0 };

  for (const event of events) {
    const sequence = eventSequence(event);
    const eventType = event.type || event.event_type || '';
    if (sequence <= lastReadSequence || seenSequences.has(sequence)) continue;
    seenSequences.add(sequence);

    if (PRIVATE_RESULT_EVENT_TYPES.has(eventType)) counts.privateResults += 1;
    if (PUBLIC_CLUE_EVENT_TYPES.has(eventType)) counts.publicClues += 1;
  }

  return counts;
}
