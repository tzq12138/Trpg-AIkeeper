import { describe, expect, test } from 'vitest';
import { lockCombatRoundReceipt } from '../src/shared/combat-round-lock';

describe('combat round lock receipt', () => {
  test('only removes cancellation while preserving the authoritative receipt', () => {
    const receipt = {
      action_id: 'action-1',
      status: 'queued' as const,
      can_cancel: true,
      timeline: [{ status: 'queued' }],
    };

    expect(lockCombatRoundReceipt(receipt)).toEqual({
      ...receipt,
      can_cancel: false,
    });
    expect(lockCombatRoundReceipt(null)).toBeNull();
  });
});
