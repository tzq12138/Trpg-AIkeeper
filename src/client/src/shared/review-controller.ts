/**
 * R7 action-review controller: pure logic shared by the review UI and its
 * tests. Submission uses a per-action idempotency key so a repeated click or
 * a network retry replays the SAME case instead of opening a second one; the
 * server returns the identical review_request_id for a replay.
 */

import type {
  ActionReceiptDTO,
  ActionReviewRequestDTO,
  AutomaticReviewResolutionDTO,
} from './types';

export type ReviewResolutionKind = AutomaticReviewResolutionDTO['status'];

export const REVIEW_STATUS_LABELS: Record<ReviewResolutionKind | 'resolved', string> = {
  pending: '已受理，等待自动复核',
  awaiting_engine_review: '引擎复核中（复用原骰，不重新掷骰）',
  upheld: '复核完成：原结算维持',
  explanation_corrected: '复核完成：已补充更正说明',
  projection_repaired: '复核完成：已补发错过的通知',
  compensated: '复核完成：已补偿核实差量',
  review_rejected: '复核完成：异议不成立',
  system_paused: '复核无法证明：房间已进入系统暂停',
  resolved: '已结案',
};

/** Stable per-action idempotency key: retries and repeat clicks reuse it. */
export function reviewIdempotencyKey(actionId: string): string {
  return `review:${actionId}`;
}

export function buildReviewSubmission(
  actionId: string,
  objection: string,
  originalIntent: string,
): { body: { objection: string; original_intent: string }; key: string } {
  const trimmedObjection = objection.trim();
  const trimmedIntent = originalIntent.trim();
  return {
    body: {
      objection: trimmedObjection || '请重新检查这次规则解释',
      original_intent: trimmedIntent,
    },
    key: reviewIdempotencyKey(actionId),
  };
}

export function isReviewPending(
  review: ActionReviewRequestDTO | null | undefined,
): boolean {
  if (!review) return false;
  if (review.status === 'pending') return true;
  const resolution = review.automatic_resolution;
  return Boolean(resolution && resolution.status === 'pending');
}

export function reviewResolutionLabel(
  resolution: AutomaticReviewResolutionDTO | null | undefined,
): string {
  if (!resolution || !resolution.status) return '';
  const base = REVIEW_STATUS_LABELS[resolution.status] ?? resolution.status;
  if (resolution.reason_code) return `${base}（${resolution.reason_code}）`;
  return base;
}

export function reviewResolutionReason(
  resolution: AutomaticReviewResolutionDTO | null | undefined,
): string {
  if (!resolution || typeof resolution.reason !== 'string') return '';
  return resolution.reason;
}

export function reviewTransactionId(
  resolution: AutomaticReviewResolutionDTO | null | undefined,
): string | null {
  return resolution?.compensation_transaction_id ?? null;
}

/**
 * Recovery copy for a receipt whose room is paused_system/recovering: players
 * see the durable machine reason code and whether their original roll was
 * preserved — never an internal prompt or cursor.
 */
export function recoveryCopy(
  receipt: Pick<ActionReceiptDTO, 'room_runtime_status' | 'recovery'>,
): { title: string; detail: string; code?: string } | null {
  const runtime = receipt.room_runtime_status;
  if (runtime !== 'paused_system' && runtime !== 'recovering') return null;
  const recovery = receipt.recovery;
  const preserved = recovery?.original_roll_preserved;
  if (runtime === 'recovering') {
    return {
      title: '系统恢复中',
      detail: preserved
        ? '原骰已保留；恢复完成后你会收到同一行动的最终回执。'
        : '系统正在恢复房间状态；恢复完成后即可继续。',
    };
  }
  return {
    title: '系统暂停',
    detail: preserved
      ? '房间因系统完整性暂停。原骰已保留，恢复后会用同一骰子继续同一行动。'
      : '房间因系统完整性暂停，不会写入新的世界状态。',
    code: recovery?.reason_code,
  };
}

interface NormalizedError { code: string | null; reason: string | null }

function normalizeErrorDetail(detail: unknown): NormalizedError {
  if (detail && typeof detail === 'object') {
    const structured = detail as { code?: unknown; reason?: unknown };
    if (typeof structured.code === 'string') {
      return {
        code: structured.code,
        reason: typeof structured.reason === 'string' ? structured.reason : null,
      };
    }
  }
  if (typeof detail === 'string') return { code: null, reason: detail };
  return { code: null, reason: null };
}

/**
 * Format any transport error into stable player-facing text. Handles both
 * error carriers (api.ts ApiRequestError and player-api PlayerApiError) by
 * duck-typing their fields; a structured FastAPI detail is surfaced as
 * code + reason and an object detail NEVER stringifies into "[object Object]".
 */
export function reviewErrorMessage(error: unknown): string {
  if (!error) return '操作失败，请重试';
  if (typeof error === 'string') return error;
  const candidate = error as {
    code?: unknown;
    detailMessage?: unknown;
    detail?: unknown;
    message?: unknown;
  };
  const code = typeof candidate.code === 'string' ? candidate.code : null;
  const detailMessage = typeof candidate.detailMessage === 'string'
    ? candidate.detailMessage
    : null;
  if (code || detailMessage) {
    if (code) return detailMessage ? `${code}（${detailMessage}）` : code;
    return `请求失败：${detailMessage}`;
  }
  if ('detail' in candidate) {
    const { code: detailCode, reason } = normalizeErrorDetail(candidate.detail);
    if (detailCode || reason) {
      return detailCode ? (reason ? `${detailCode}（${reason}）` : detailCode) : reason as string;
    }
  }
  const message = candidate.message;
  return typeof message === 'string' && message ? message : '操作失败，请重试';
}
