import { describe, expect, it } from 'vitest';
import {
  filterRoomWorkspaceItems,
  getRoomCreateBlocker,
  getRoomStatusCounts,
  isEligibleRoomOwner,
} from '../src/shared/admin-room-workspace';

const rooms = [
  { room_id: 'active-room', scenario_title: '雾港失物局', status: 'active', owner_display_name: 'Keeper', player_count: 3 },
  { room_id: 'lobby-room', scenario_title: '玻璃雨夜', status: 'lobby', owner_display_name: 'Host', player_count: 1 },
  { room_id: 'old-room', scenario_title: '旧日余烬', status: 'completed', owner_display_name: 'Keeper', player_count: 4 },
  { room_id: 'deleted-room', scenario_title: '已删剧本', status: 'archived', owner_display_name: 'Keeper', player_count: 0, deleted_at: '2026-07-18' },
];

describe('admin room workspace', () => {
  it('groups current rooms and filters search across owner details', () => {
    expect(getRoomStatusCounts(rooms)).toMatchObject({ active: 1, lobby: 1, completed: 1, archived: 1 });
    expect(filterRoomWorkspaceItems(rooms, { status: 'active', search: '', includeDeleted: false }))
      .toEqual([rooms[0]]);
    expect(filterRoomWorkspaceItems(rooms, { status: 'current', search: '', includeDeleted: false }))
      .toEqual([rooms[0], rooms[1]]);
    expect(filterRoomWorkspaceItems(rooms, { status: 'all', search: 'host', includeDeleted: false }))
      .toEqual([rooms[1]]);
    expect(filterRoomWorkspaceItems(rooms, { status: 'all', search: '', includeDeleted: true }))
      .toHaveLength(4);
  });

  it('only treats active host and admin accounts as eligible room owners', () => {
    expect(isEligibleRoomOwner({ role: 'admin' })).toBe(true);
    expect(isEligibleRoomOwner({ role: 'host' })).toBe(true);
    expect(isEligibleRoomOwner({ role: 'player' })).toBe(false);
    expect(isEligibleRoomOwner({ role: 'host', deleted_at: '2026-07-18' })).toBe(false);
  });

  it('blocks room creation until a published scenario and eligible owner are selected', () => {
    expect(getRoomCreateBlocker({ scenarioId: '', ownerId: '', eligibleOwnerIds: ['host-1'] }))
      .toBe('请选择已发布且可开团的剧本');
    expect(getRoomCreateBlocker({ scenarioId: 'scenario-1', ownerId: 'player-1', eligibleOwnerIds: ['host-1'] }))
      .toBe('请选择具备房主权限的账号');
    expect(getRoomCreateBlocker({ scenarioId: 'scenario-1', ownerId: 'host-1', eligibleOwnerIds: ['host-1'] }))
      .toBe('');
  });
});
