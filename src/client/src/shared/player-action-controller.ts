import type { ActionDraftDTO, ActionReceiptDTO, ActionStatus } from './types';


const IN_FLIGHT_STATUSES = new Set<ActionStatus>([
  'queued',
  'batched',
  'resolving',
  'awaiting_player_choice',
  'awaiting_host_exception',
  'sync_required',
]);


export function createConfirmIdempotencyKey(draft: ActionDraftDTO): string {
  return `confirm:${draft.draft_id}:${draft.revision}`;
}


export function shouldAutoConfirmDraft(draft: ActionDraftDTO): boolean {
  return !draft.requires_confirmation && (draft.confirmation_requirements?.length || 0) === 0;
}


export function isActionInFlight(status: ActionStatus): boolean {
  return IN_FLIGHT_STATUSES.has(status);
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
