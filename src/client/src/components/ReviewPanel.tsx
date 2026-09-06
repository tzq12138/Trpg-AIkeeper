import { useEffect, useRef, useState } from 'react';
import type {
  ActionReceiptDTO,
  ActionReviewRequestDTO,
} from '../shared/types';
import { getActionReview, submitActionReview } from '../shared/player-api';
import {
  buildReviewSubmission,
  isReviewPending,
  recoveryCopy,
  reviewErrorMessage,
  reviewResolutionLabel,
  reviewResolutionReason,
  reviewTransactionId,
  REVIEW_STATUS_LABELS,
} from '../shared/review-controller';

export interface ReviewPanelProps {
  actionId: string;
  canReview: boolean;
  declaredIntent: string;
  runtime: Pick<ActionReceiptDTO, 'room_runtime_status' | 'recovery'>;
}

const POLL_INTERVAL_MS = 3000;

/**
 * R7 review entry + case viewer for ai_only rooms. Appears only when the
 * server says can_review; the objection is a review STATEMENT (the server's
 * frozen original is the authoritative intent), and the engine reuses the
 * original die — no re-roll. Submissions carry a per-action idempotency key
 * so repeat clicks and network retries replay the same case. While the room
 * is paused_system/recovering the panel leads with the recovery copy
 * (roll-preserved notice) instead of pretending the action can be retried.
 */
export default function ReviewPanel({
  actionId,
  canReview,
  declaredIntent,
  runtime,
}: ReviewPanelProps) {
  const [objection, setObjection] = useState('');
  const [originalIntent, setOriginalIntent] = useState(declaredIntent);
  const [review, setReview] = useState<ActionReviewRequestDTO | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  const recovery = recoveryCopy(runtime);
  const reviewPending = isReviewPending(review);

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, []);

  useEffect(() => {
    if (!reviewPending || !review) return;
    pollTimer.current = setInterval(() => {
      getActionReview(review.action_id, review.review_request_id)
        .then((fresh) => {
          setReview(fresh);
          if (!isReviewPending(fresh) && pollTimer.current) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
          }
        })
        .catch(() => {
          // Transient refresh failure: the durable GET stays authoritative;
          // the next poll (or manual refresh) retries.
        });
    }, POLL_INTERVAL_MS);
    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
  }, [review?.review_request_id, reviewPending]);

  if (!canReview) return null;

  const submit = async () => {
    setErrorMessage(null);
    setSubmitting(true);
    const submission = buildReviewSubmission(actionId, objection, originalIntent);
    try {
      const accepted = await submitActionReview(
        actionId,
        submission.body,
        submission.key,
      );
      setReview(accepted);
      setObjection('');
    } catch (error) {
      setErrorMessage(reviewErrorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const refresh = () => {
    if (!review) return;
    setErrorMessage(null);
    getActionReview(review.action_id, review.review_request_id)
      .then((fresh) => {
        setReview(fresh);
        if (pollTimer.current) clearInterval(pollTimer.current);
      })
      .catch((error) => setErrorMessage(reviewErrorMessage(error)));
  };

  const resolution = review?.automatic_resolution ?? null;
  const resolvedLabel = resolution && resolution.status !== 'pending'
    ? reviewResolutionLabel(resolution)
    : (review?.status === 'resolved' && !resolution
      ? REVIEW_STATUS_LABELS.resolved
      : null);

  return (
    <section className="bh-review-panel" aria-label="行动复核">
      {recovery && (
        <article className="bh-muted-box" role="status">
          <strong>{recovery.title}</strong>
          <p>{recovery.detail}</p>
          {recovery.code && <code>{recovery.code}</code>}
        </article>
      )}

      {!review && !recovery && (
        <div className="bh-muted-box">
          <strong>对这次结算有异议？</strong>
          <p>复核只基于服务器冻结的原意与原骰重新解释——不会重新掷骰，也不会改写原结果。复核由引擎自动进行，不经过 Host 人工裁决。</p>
          <label className="bh-field-label" htmlFor="review-objection">异议内容</label>
          <textarea
            id="review-objection"
            className="bh-input"
            rows={3}
            value={objection}
            onChange={(event) => setObjection(event.target.value)}
            placeholder="例如：难度参数录入错误、结算对象理解错了"
          />
          <label className="bh-field-label" htmlFor="review-original-intent">原意陈述（可选，服务器冻结原文为权威）</label>
          <input
            id="review-original-intent"
            className="bh-input"
            type="text"
            value={originalIntent}
            onChange={(event) => setOriginalIntent(event.target.value)}
          />
          <div className="bh-action-row">
            <button
              className="bh-button bh-button--yellow"
              type="button"
              disabled={submitting}
              onClick={submit}
            >
              {submitting ? '提交中…' : '提交异议'}
            </button>
          </div>
        </div>
      )}

      {review && reviewPending && (
        <article className="bh-muted-box" role="status">
          <strong>{REVIEW_STATUS_LABELS.pending}</strong>
          <p>原结果保持原样；结论到达后这里会自动更新。重复点击不会产生第二个复核。</p>
          <button className="bh-button" type="button" onClick={refresh}>刷新复核状态</button>
        </article>
      )}

      {review && !reviewPending && resolvedLabel && (
        <article className="bh-muted-box" role="status">
          <strong>{resolvedLabel}</strong>
          {reviewResolutionReason(resolution) && <p>{reviewResolutionReason(resolution)}</p>}
          {reviewTransactionId(resolution) && (
            <p className="bh-muted">补偿事务：{reviewTransactionId(resolution)}</p>
          )}
        </article>
      )}

      {errorMessage && <p className="bh-error" role="alert">{errorMessage}</p>}
    </section>
  );
}
