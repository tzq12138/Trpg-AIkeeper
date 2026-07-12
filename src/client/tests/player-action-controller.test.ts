import { describe, expect, test } from 'vitest';
import {
  canStartNewAction,
  createConfirmIdempotencyKey,
  isActionInFlight,
  mergeAuthoritativeReceipt,
  shouldAutoConfirmDraft,
} from '../src/shared/player-action-controller';
import type { ActionDraftDTO, ActionReceiptDTO } from '../src/shared/types';


const draft = {
  draft_id: 'draft-1',
  revision: 2,
  requires_confirmation: true,
} as ActionDraftDTO;

const queuedReceipt = {
  action_id: 'action-1',
  status: 'queued',
  timeline: [{ status: 'queued', created_at: '1', metadata: {} }],
} as ActionReceiptDTO;


describe('player action controller', () => {
  test('builds stable confirmation key from immutable draft revision', () => {
    expect(createConfirmIdempotencyKey(draft)).toBe('confirm:draft-1:2');
    expect(createConfirmIdempotencyKey(draft)).toBe('confirm:draft-1:2');
  });

  test('auto-confirms only drafts without confirmation requirements', () => {
    expect(shouldAutoConfirmDraft(draft)).toBe(false);
    expect(shouldAutoConfirmDraft({ ...draft, requires_confirmation: false })).toBe(true);
  });

  test('treats server pending states as authoritative in-flight actions', () => {
    expect(isActionInFlight('queued')).toBe(true);
    expect(isActionInFlight('awaiting_host_exception')).toBe(true);
    expect(isActionInFlight('completed')).toBe(false);
  });

  test('allows a new action after the previous receipt is completed', () => {
    expect(canStartNewAction(null, { ...queuedReceipt, status: 'completed' })).toBe(true);
    expect(canStartNewAction(draft, { ...queuedReceipt, status: 'completed' })).toBe(false);
    expect(canStartNewAction(null, queuedReceipt)).toBe(false);
  });

  test('merges duplicate timeline events without losing newer server status', () => {
    const updated = mergeAuthoritativeReceipt(queuedReceipt, {
      ...queuedReceipt,
      status: 'resolving',
      timeline: [
        { status: 'queued', created_at: '1', metadata: {} },
        { status: 'resolving', created_at: '2', metadata: {} },
      ],
    });

    expect(updated.status).toBe('resolving');
    expect(updated.timeline.map((event) => event.status)).toEqual(['queued', 'resolving']);
  });
});
