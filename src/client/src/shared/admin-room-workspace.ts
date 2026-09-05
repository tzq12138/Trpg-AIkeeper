export type RoomWorkspaceItem = {
  room_id: string;
  scenario_title?: string;
  status?: string;
  owner_display_name?: string;
  player_count?: number;
  created_at?: string;
  last_activity_at?: string;
  deleted_at?: string | null;
};

export type RoomOwnerOption = {
  account_id?: string;
  role?: string;
  deleted_at?: string | null;
};

export type RoomWorkspaceFilter = {
  status: string;
  search: string;
  includeDeleted: boolean;
};

export function isEligibleRoomOwner(account: RoomOwnerOption) {
  return !account.deleted_at && (account.role === 'admin' || account.role === 'host');
}

export function getRoomCreateBlocker({
  scenarioId,
  ownerId,
  eligibleOwnerIds,
}: {
  scenarioId: string;
  ownerId: string;
  eligibleOwnerIds: string[];
}) {
  if (!scenarioId) return '请选择已发布且可开团的剧本';
  if (ownerId && !eligibleOwnerIds.includes(ownerId)) return '请选择具备房主权限的账号';
  return '';
}

export function getRoomStatusCounts(rooms: RoomWorkspaceItem[]) {
  return rooms.reduce<Record<string, number>>((counts, room) => {
    const status = room.deleted_at ? 'archived' : room.status || 'draft';
    counts[status] = (counts[status] || 0) + 1;
    return counts;
  }, {});
}

export function filterRoomWorkspaceItems(
  rooms: RoomWorkspaceItem[],
  { status, search, includeDeleted }: RoomWorkspaceFilter,
) {
  const query = search.trim().toLowerCase();
  return rooms.filter((room) => {
    if (!includeDeleted && room.deleted_at) return false;
    const roomStatus = room.deleted_at ? 'archived' : room.status || 'draft';
    if (status === 'current' && !['draft', 'lobby', 'active', 'paused'].includes(roomStatus)) return false;
    if (status !== 'all' && status !== 'current' && roomStatus !== status) return false;
    if (!query) return true;
    return [room.room_id, room.scenario_title, roomStatus, room.owner_display_name]
      .some((value) => String(value || '').toLowerCase().includes(query));
  });
}
