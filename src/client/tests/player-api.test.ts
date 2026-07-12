import { beforeAll, beforeEach, describe, expect, test, vi } from 'vitest';

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key: string) { return store.get(key) ?? null; },
    key(index: number) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key: string) { store.delete(key); },
    setItem(key: string, value: string) { store.set(key, value); },
  };
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: createStorageMock(),
    configurable: true,
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: createStorageMock(),
    configurable: true,
  });
});

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem('player_token', 'player-token');
  vi.restoreAllMocks();
});

describe('player V2 API', () => {
  test('analyzes an ephemeral draft without changing the payload', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      draft_id: null,
      status: 'awaiting_confirmation',
      declared_intent: '我查看门框',
      risk: 'low',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { analyzeActionDraft } = await import('../src/shared/player-api');

    await analyzeActionDraft({
      declared_intent: '我查看门框',
      intent_type: 'dialogue',
      params: {},
      ephemeral: true,
      base_state_version: 7,
    });

    expect(fetchMock).toHaveBeenCalledWith('/api/player/action-drafts/analyze', expect.objectContaining({
      method: 'POST',
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
        'X-Room-Token': 'player-token',
      }),
      body: JSON.stringify({
        declared_intent: '我查看门框',
        intent_type: 'dialogue',
        params: {},
        ephemeral: true,
        base_state_version: 7,
      }),
    }));
  });

  test('confirms a draft with a stable idempotency key', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      action_id: 'action-1',
      draft_id: 'draft-1',
      status: 'queued',
      timeline: [],
      can_cancel: true,
      can_review: false,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { confirmActionDraft } = await import('../src/shared/player-api');

    await confirmActionDraft('draft-1', ['movement'], 'confirm-draft-1');

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/player/action-drafts/draft-1/confirm',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          'Idempotency-Key': 'confirm-draft-1',
          'X-Device-Id': expect.stringMatching(/^[A-Za-z0-9._:-]+$/),
        }),
        body: JSON.stringify({ confirmations: ['movement'] }),
      }),
    );
  });

  test('claims a stable browser device before it submits actions', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      device_id: 'device-test',
      controller: true,
      status: 'active',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { claimPlayerDevice, getPlayerDeviceId } = await import('../src/shared/player-api');

    const deviceId = getPlayerDeviceId();
    await claimPlayerDevice();

    expect(deviceId).toMatch(/^[A-Za-z0-9._:-]+$/);
    expect(fetchMock).toHaveBeenCalledWith('/api/player/device-sessions/claim', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, takeover: false }),
    }));
  });

  test('preserves structured API error details', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      detail: { code: 'sync_required', current_state_version: 9 },
    }), { status: 409, headers: { 'Content-Type': 'application/json' } }));
    const { analyzeActionDraft, PlayerApiError } = await import('../src/shared/player-api');

    await expect(analyzeActionDraft({
      declared_intent: '过时行动',
      ephemeral: false,
      base_state_version: 3,
    })).rejects.toEqual(expect.objectContaining({
      name: PlayerApiError.name,
      status: 409,
      detail: { code: 'sync_required', current_state_version: 9 },
    }));
  });

  test('normalizes action hint examples to the shared hints contract', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      examples: ['检查窗台', '询问售票员', '整理线索'],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const { getActionHints } = await import('../src/shared/player-api');

    await expect(getActionHints()).resolves.toEqual({
      hints: ['检查窗台', '询问售票员', '整理线索'],
    });
    expect(fetchSpy).toHaveBeenCalledWith('/api/player/action-hints', expect.objectContaining({
      method: 'POST',
    }));
  });
});
