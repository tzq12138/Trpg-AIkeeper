export const PLAYER_JOIN_SOURCE_ORDER = ['account', 'preset', 'builder', 'upload'] as const;

export type PlayerJoinSourceMode = typeof PLAYER_JOIN_SOURCE_ORDER[number];

export function getPrimaryJoinSource(hasRecoverableCharacter: boolean): PlayerJoinSourceMode {
  return hasRecoverableCharacter ? 'account' : 'preset';
}

export function buildPlayerJoinReturnPath(roomCode: string): string {
  const normalized = roomCode.trim();
  return normalized
    ? `/player/join?room=${encodeURIComponent(normalized)}`
    : '/player/join';
}

export function playerRoomEntryPath(roomId: string, roomStatus: string): string {
  return roomStatus === 'active'
    ? `/player/${encodeURIComponent(roomId)}/lobby`
    : `/player/${encodeURIComponent(roomId)}/lobby`;
}
