import type {
  ActionDraftDTO,
  ActionReceiptDTO,
  ActionStatus,
  RuntimeIntegrityDTO,
} from './types';


const IN_FLIGHT_STATUSES = new Set<ActionStatus>([
  'queued',
  'batched',
  'resolving',
  'awaiting_player_choice',
  'awaiting_player_consent',
  'awaiting_host_exception',
  'sync_required',
]);

export const AUTO_CONFIRM_GRACE_MS = 2000;


export function shouldUsePlayerRuntime(
  roomStatus: string | null | undefined,
  integrity?: Pick<RuntimeIntegrityDTO, 'status'> | null,
): boolean {
  if (roomStatus === 'active') return true;
  return roomStatus === 'paused' && Boolean(integrity && integrity.status !== 'healthy');
}


export function createConfirmIdempotencyKey(draft: ActionDraftDTO): string {
  return `confirm:${draft.draft_id}:${draft.revision}`;
}


export function shouldAutoConfirmDraft(draft: ActionDraftDTO): boolean {
  return draft.status === 'awaiting_confirmation'
    && !draft.requires_confirmation
    && (draft.confirmation_requirements?.length || 0) === 0;
}


export function isActionInFlight(status: ActionStatus): boolean {
  return IN_FLIGHT_STATUSES.has(status);
}


export function hasPendingCocFollowUp(receipt: ActionReceiptDTO | null): boolean {
  if (!receipt || receipt.status !== 'awaiting_player_choice') return false;
  if (!receipt.result || typeof receipt.result !== 'object') return false;
  const metadata = (receipt.result as { metadata?: unknown }).metadata;
  if (!metadata || typeof metadata !== 'object') return false;
  const followUp = (metadata as { follow_up?: unknown }).follow_up;
  return Boolean(
    followUp
    && typeof followUp === 'object'
    && (followUp as { status?: unknown }).status === 'pending'
    && Array.isArray((followUp as { allowed_decisions?: unknown }).allowed_decisions),
  );
}


export function canStartNewAction(
  draft: ActionDraftDTO | null,
  receipt: ActionReceiptDTO | null,
): boolean {
  return !draft && !(receipt && isActionInFlight(receipt.status));
}


export function mergeAuthoritativeReceipt(
  current: ActionReceiptDTO | null,
  incoming: ActionReceiptDTO,
): ActionReceiptDTO {
  if (!current || current.action_id !== incoming.action_id) return incoming;
  const seen = new Set<string>();
  const timeline = [...current.timeline, ...incoming.timeline].filter((event) => {
    const key = `${event.status}:${event.created_at}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  return { ...current, ...incoming, timeline };
}
