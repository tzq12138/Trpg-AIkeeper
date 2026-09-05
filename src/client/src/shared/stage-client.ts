const stageStorageKey = (roomId: string) => `aikeeper_stage_token_${roomId}`;

export function buildStageClientHeaders(stageToken: string): Record<string, string> {
  return { 'X-Stage-Token': stageToken };
}

export function buildStageClientUrl(roomId: string, stageToken: string): string {
  const path = `/host/${encodeURIComponent(roomId)}/stage`;
  return stageToken
    ? `${path}#stage_token=${encodeURIComponent(stageToken)}`
    : path;
}

export function getStageClientToken(roomId: string): string {
  if (typeof window === 'undefined') return '';
  const token = new URLSearchParams(window.location.hash.slice(1)).get('stage_token') || '';
  if (token) {
    window.sessionStorage.setItem(stageStorageKey(roomId), token);
    return token;
  }
  return window.sessionStorage.getItem(stageStorageKey(roomId)) || '';
}
