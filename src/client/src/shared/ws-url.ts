type LocationLike = Pick<Location, 'protocol' | 'host'>;

export interface RoomWsParams {
  roomId: string;
  role: 'host' | 'player';
  token?: string;
  ownerToken?: string;
  lastSequence?: number;
}

export function buildRoomWsUrl(location: LocationLike, params: RoomWsParams): string {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const search = new URLSearchParams({
    room: params.roomId,
    role: params.role,
  });
  if (params.token) {
    search.set('token', params.token);
  }
  if (params.ownerToken) {
    search.set('ownerToken', params.ownerToken);
  }
  if (params.lastSequence !== undefined) {
    search.set('lastSequence', String(params.lastSequence));
  }
  return `${protocol}//${location.host}/ws?${search.toString()}`;
}
