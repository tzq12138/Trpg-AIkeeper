import { describe, expect, test, vi } from 'vitest';
import { requestInventoryTransfer, resolveInventoryTransfer } from '../src/shared/inventory-transfer-api';

describe('inventory transfer API', () => {
  test('creates a pending recipient-confirmed transfer', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ transferId: 'transfer-1', status: 'pending' }),
    });

    await expect(requestInventoryTransfer(
      'item-1',
      'character-2',
      1,
      { 'X-Room-Token': 'player-token' },
      fetcher as typeof fetch,
    )).resolves.toMatchObject({ transferId: 'transfer-1', status: 'pending' });

    expect(fetcher).toHaveBeenCalledWith('/api/player/inventory/item-1/transfers', {
      method: 'POST',
      headers: { 'X-Room-Token': 'player-token', 'Content-Type': 'application/json' },
      body: JSON.stringify({ toCharacterId: 'character-2', quantity: 1 }),
    });
  });

  test('submits an explicit recipient decision', async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ transferId: 'transfer-1', status: 'completed' }),
    });

    await resolveInventoryTransfer(
      'transfer-1',
      'accept',
      { 'X-Room-Token': 'player-token' },
      fetcher as typeof fetch,
    );

    expect(fetcher).toHaveBeenCalledWith('/api/player/inventory-transfers/transfer-1/accept', {
      method: 'POST',
      headers: { 'X-Room-Token': 'player-token' },
    });
  });
});
