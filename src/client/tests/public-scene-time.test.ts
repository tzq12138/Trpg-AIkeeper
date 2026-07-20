import { describe, expect, test, vi } from 'vitest';
import { updatePublicSceneTime } from '../src/shared/public-scene-time';

describe('updatePublicSceneTime', () => {
  test('sends only the public time with the room owner credential', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sceneTime: '1924-10-14 23:40', version: 5 }),
    });

    await expect(updatePublicSceneTime(
      'room-1',
      'owner-token',
      '1924-10-14 23:40',
      fetcher as typeof fetch,
    )).resolves.toEqual({ sceneTime: '1924-10-14 23:40', version: 5 });

    expect(fetcher).toHaveBeenCalledWith('/api/host/room-1/public-scene-time', {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-Owner-Token': 'owner-token',
      },
      body: JSON.stringify({ sceneTime: '1924-10-14 23:40' }),
    });
  });

  test('reports a failed update instead of accepting stale UI state', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false });

    await expect(updatePublicSceneTime(
      'room-1',
      'owner-token',
      '1924-10-14 23:40',
      fetcher as typeof fetch,
    )).rejects.toThrow('public_scene_time_update_failed');
  });
});
