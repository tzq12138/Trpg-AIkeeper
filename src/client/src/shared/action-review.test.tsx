// @vitest-environment jsdom

/**
 * R7 front-end contract for the automatic action review flow (ai_only):
 * - the entry renders ONLY when the server says can_review;
 * - submissions carry a per-action idempotency key that never changes across
 *   repeat clicks / network retries (the server replays the same case);
 * - pending cases and the six D07 terminals all have stable player-facing
 *   copy; the resolution reason never leaks internal evidence;
 * - while the room is paused_system/recovering the receipt leads with the
 *   recovery copy (roll preserved) instead of a retryable-looking status;
 * - transport errors surface the structured detail code/reason — never a
 *   "[object Object]".
 */

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ReviewPanel from '../components/ReviewPanel';
import { getActionReview, submitActionReview } from './player-api';
import {
  buildReviewSubmission,
  isReviewPending,
  recoveryCopy,
  reviewErrorMessage,
  reviewIdempotencyKey,
  reviewResolutionLabel,
} from './review-controller';
import type { ActionReceiptDTO, ActionReviewRequestDTO } from './types';

const D07_TERMINALS = [
  'upheld',
  'explanation_corrected',
  'projection_repaired',
  'compensated',
  'review_rejected',
  'system_paused',
] as const;

function receipt(overrides: Partial<ActionReceiptDTO> = {}): ActionReceiptDTO {
  return {
    action_id: 'action-r7',
    transaction_id: 'tx-1',
    state_version: 3,
    draft_id: null,
    status: 'completed',
    declared_intent: '我原本想侦查门框',
    revision: 1,
    result: {},
    timeline: [],
    can_cancel: false,
    can_review: true,
    rule_explanation: null,
    room_runtime_status: 'running',
    resolution_outcome: 'success',
    recovery: null,
    ...overrides,
  } as ActionReceiptDTO;
}

function reviewResponse(overrides: Partial<ActionReviewRequestDTO> = {}): ActionReviewRequestDTO {
  return {
    review_request_id: 'review-r7',
    action_id: 'action-r7',
    status: 'resolved',
    original_intent: '我原本想侦查门框',
    objection: '难度参数录入错误',
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('review entry gating', () => {
  it('renders nothing when can_review is false (no submission entry)', () => {
    const markup = renderToStaticMarkup(
      <ReviewPanel
        actionId="action-r7"
        canReview={false}
        declaredIntent="我原本想侦查门框"
        runtime={receipt({ can_review: false })}
      />,
    );
    expect(markup).toBe('');
  });

  it('renders the recovery copy first when the room is paused with the roll preserved', () => {
    const markup = renderToStaticMarkup(
      <ReviewPanel
        actionId="action-r7"
        canReview
        declaredIntent="我原本想侦查门框"
        runtime={receipt({
          room_runtime_status: 'paused_system',
          recovery: {
            reason_code: 'narrator_timeout',
            retryable: true,
            original_roll_preserved: true,
          },
        })}
      />,
    );
    expect(markup).toContain('系统暂停');
    expect(markup).toContain('原骰已保留');
    expect(markup).toContain('narrator_timeout');
  });
});

describe('idempotent submission contract', () => {
  it('builds a stable per-action key reused on every retry', () => {
    const first = buildReviewSubmission('action-r7', ' 难度参数录入错误 ', '');
    const second = buildReviewSubmission('action-r7', ' 难度参数录入错误 ', '');
    expect(first.key).toBe(reviewIdempotencyKey('action-r7'));
    expect(first.key).toBe(second.key);
    expect(first.body.objection).toBe('难度参数录入错误');
    expect(first.body.original_intent).toBe('');
  });

  it('POSTs the objection with the Idempotency-Key header', async () => {
    // A fresh Response per call: a shared instance would exhaust its body.
    const fetchMock = vi.fn().mockImplementation(async () => new Response(
      JSON.stringify(reviewResponse({ status: 'pending' })),
      { status: 201, headers: { 'Content-Type': 'application/json' } },
    ));
    vi.stubGlobal('fetch', fetchMock);

    const accepted = await submitActionReview(
      'action-r7',
      { objection: '难度参数录入错误', original_intent: '我原本想侦查门框' },
      reviewIdempotencyKey('action-r7'),
    );
    // Replay with the SAME key (retry after a lost reply).
    const replay = await submitActionReview(
      'action-r7',
      { objection: '难度参数录入错误', original_intent: '我原本想侦查门框' },
      reviewIdempotencyKey('action-r7'),
    );

    expect(accepted.review_request_id).toBe('review-r7');
    expect(replay.review_request_id).toBe(accepted.review_request_id);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const call of fetchMock.mock.calls) {
      const [url, init] = call as [string, RequestInit];
      expect(String(url)).toContain('/api/player/actions/action-r7/review-requests');
      expect((init.headers as Record<string, string>)['Idempotency-Key'])
        .toBe('review:action-r7');
    }
  });

  it('GET refresh returns the pending case for the same review id', async () => {
    const body = reviewResponse({ status: 'pending' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ));
    const refreshed = await getActionReview('action-r7', 'review-r7');
    expect(refreshed.review_request_id).toBe('review-r7');
    expect(isReviewPending(refreshed)).toBe(true);
  });
});

describe('terminal copy for the six D07 outcomes', () => {
  it('labels every terminal without leaking internal evidence', () => {
    for (const status of D07_TERMINALS) {
      const label = reviewResolutionLabel({
        status,
        reason_code: 'some_reason_code',
        reason: '复核完成说明',
      });
      expect(label.length).toBeGreaterThan(0);
      expect(label).toContain('some_reason_code');
      expect(label).not.toContain('object Object');
    }
  });

  it('marks a resolved case with an automatic_resolution as not pending', () => {
    const resolved = reviewResponse({
      automatic_resolution: { status: 'compensated', reason_code: 'no_error' },
    });
    expect(isReviewPending(resolved)).toBe(false);
  });
});

describe('recovery copy on receipts', () => {
  it('is absent while the room runs', () => {
    expect(recoveryCopy(receipt())).toBeNull();
  });

  it('announces paused_system with the preserved roll and reason code', () => {
    const copy = recoveryCopy(receipt({
      room_runtime_status: 'paused_system',
      recovery: { reason_code: 'narrator_timeout', retryable: true, original_roll_preserved: true },
    }));
    expect(copy?.title).toBe('系统暂停');
    expect(copy?.detail).toContain('原骰已保留');
    expect(copy?.code).toBe('narrator_timeout');
  });

  it('announces recovering without pretending the action is retryable', () => {
    const copy = recoveryCopy(receipt({
      room_runtime_status: 'recovering',
      recovery: { reason_code: 'system_recovery_started', retryable: true, original_roll_preserved: false },
    }));
    expect(copy?.title).toBe('系统恢复中');
    expect(copy?.detail).not.toContain('重试');
  });
});

describe('structured error copy (no [object Object])', () => {
  it('formats a PlayerApiError-style structured detail', () => {
    const error = { status: 409, detail: { code: 'idempotency_key_conflict', reason: '同一幂等键不能绑定不同异议载荷' } };
    const text = reviewErrorMessage(error);
    expect(text).toContain('idempotency_key_conflict');
    expect(text).toContain('同一幂等键');
    expect(text).not.toContain('object Object');
  });

  it('formats an api.ts ApiRequestError-style error', () => {
    const text = reviewErrorMessage({
      status: 409,
      code: 'review_already_pending',
      detailMessage: '同一行动已有待复核 case',
    });
    expect(text).toContain('review_already_pending');
    expect(text).not.toContain('object Object');
  });

  it('never stringifies an unknown object payload into the message', () => {
    const text = reviewErrorMessage({ status: 500, detail: { nested: { a: 1 } } });
    expect(text).not.toContain('[object Object]');
    expect(text.length).toBeGreaterThan(0);
  });
});
