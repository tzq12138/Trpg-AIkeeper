import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, describe, expect, test } from 'vitest';

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key) { return store.get(key) ?? null; },
    key(index) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key) { store.delete(key); },
    setItem(key, value) { store.set(key, value); },
  };
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', { value: createStorageMock(), configurable: true });
  Object.defineProperty(globalThis, 'sessionStorage', { value: createStorageMock(), configurable: true });
});

async function loadAdminDashboard() {
  return import('./AdminDashboard');
}

describe('AdminDashboard room pagination helpers', () => {
  test('normalizes the paginated room response into the UI page state', async () => {
    const { normalizeRoomPageResponse } = await loadAdminDashboard();

    expect(normalizeRoomPageResponse({
      items: [{ room_id: 'room-11' }],
      page: 2,
      page_size: 30,
      total: 64,
      total_pages: 3,
    })).toEqual({
      items: [{ room_id: 'room-11' }],
      page: 2,
      pageSize: 30,
      total: 64,
      totalPages: 3,
    });
  });

  test('falls back to a first page when an older array response is returned', async () => {
    const { normalizeRoomPageResponse } = await loadAdminDashboard();

    expect(normalizeRoomPageResponse([{ room_id: 'legacy-room' }] as any)).toEqual({
      items: [],
      page: 1,
      pageSize: 10,
      total: 0,
      totalPages: 1,
    });
  });

  test('current-page select all never includes another page', async () => {
    const { toggleCurrentPageSelection } = await loadAdminDashboard();
    const selected = toggleCurrentPageSelection(['room-01'], ['room-11', 'room-12']);

    expect(selected).toEqual(['room-01', 'room-11', 'room-12']);
    expect(toggleCurrentPageSelection(selected, ['room-11', 'room-12'])).toEqual(['room-01']);
  });

  test('deleting the only item on the last page moves to the preceding page', async () => {
    const { nextRoomPageAfterDeletion } = await loadAdminDashboard();

    expect(nextRoomPageAfterDeletion({ page: 3, pageSize: 10, total: 21, deleted: 1 })).toBe(2);
  });

  test('marks a retired rule-source room as unavailable instead of rendering room entry links', async () => {
    const { RoomDetailPanel } = await loadAdminDashboard();
    const html = renderToStaticMarkup(
      <RoomDetailPanel
        selectedRoomId="room-retired"
        status="ready"
        detail={{
          room_id: 'room-retired',
          scenario_title: '旧版剧本',
          status: 'archived',
          rule_source_status: 'rule_source_retired',
          created_at: '2026-08-14T00:00:00Z',
          characters: [],
        }}
        error=""
        onRetry={() => {}}
        onPatch={() => {}}
      />,
    );

    expect(html).toContain('规则源已失效，无法打开');
    expect(html).not.toContain('/host/room-retired');
    expect(html).not.toContain('/player/room-retired');
  });
});
