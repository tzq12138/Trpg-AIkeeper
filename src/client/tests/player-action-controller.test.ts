import { describe, expect, test } from 'vitest';
import {
  canStartNewAction,
  AUTO_CONFIRM_GRACE_MS,
  createConfirmIdempotencyKey,
  isActionInFlight,
  hasPendingCocFollowUp,
  mergeAuthoritativeReceipt,
  shouldUsePlayerRuntime,
  shouldAutoConfirmDraft,
} from '../src/shared/player-action-controller';
import { actionStatusLabel } from '../src/components/PlayerActionComposer';
import type { ActionDraftDTO, ActionReceiptDTO } from '../src/shared/types';


const draft = {
  draft_id: 'draft-1',
  revision: 2,
  status: 'awaiting_confirmation',
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

  test('gives eligible low-risk drafts a two-second cancellation window', () => {
    expect(AUTO_CONFIRM_GRACE_MS).toBe(2000);
    expect(shouldAutoConfirmDraft({ ...draft, requires_confirmation: false })).toBe(true);
    expect(shouldAutoConfirmDraft(draft)).toBe(false);
  });

  test('does not auto-confirm a draft still awaiting clarification', () => {
    expect(shouldAutoConfirmDraft({
      ...draft,
      status: 'analyzing',
      requires_confirmation: false,
      confirmation_requirements: [],
    })).toBe(false);
  });

  test('treats server pending states as authoritative in-flight actions', () => {
    expect(isActionInFlight('queued')).toBe(true);
    expect(isActionInFlight('awaiting_host_exception')).toBe(true);
    expect(isActionInFlight('completed')).toBe(false);
  });

  test('keeps an armed prepared action visible without blocking a new declaration', () => {
    expect(isActionInFlight('armed' as never)).toBe(false);
    expect(canStartNewAction(null, { ...queuedReceipt, status: 'armed' as never })).toBe(true);
    expect(actionStatusLabel('armed' as never)).toBe('已布防，等待公开规则事件');
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

  test('derives a CoC follow-up only from an authoritative pending receipt', () => {
    expect(hasPendingCocFollowUp({
      ...queuedReceipt,
      status: 'awaiting_player_choice',
      result: {
        metadata: {
          follow_up: {
            status: 'pending',
            allowed_decisions: ['spend_luck', 'push', 'decline'],
          },
        },
      },
    })).toBe(true);
    expect(hasPendingCocFollowUp({ ...queuedReceipt, status: 'completed' })).toBe(false);
  });

  test('keeps a paused integrity room on the read-only player runtime', () => {
    expect(shouldUsePlayerRuntime('active', { status: 'healthy' })).toBe(true);
    expect(shouldUsePlayerRuntime('paused', { status: 'read_only_recovery' })).toBe(true);
    expect(shouldUsePlayerRuntime('lobby', { status: 'healthy' })).toBe(false);
    expect(shouldUsePlayerRuntime('completed', { status: 'healthy' })).toBe(false);
  });
});
