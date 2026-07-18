import { authHeaders } from './api';
import type {
  ActionDraftDTO,
  ActionReceiptDTO,
  CampaignHomeDTO,
  EvidenceCardDTO,
  PlayerDeviceSessionDTO,
  PlayerNoteDTO,
  PlayerReconnectDTO,
  SoloCombatReactionDTO,
  SoloCombatReactionResolutionDTO,
} from './types';


const PLAYER_DEVICE_ID_KEY = 'aikeeper_player_device_id';

export function getPlayerDeviceId(): string {
  const existing = localStorage.getItem(PLAYER_DEVICE_ID_KEY);
  if (existing && /^[A-Za-z0-9._:-]{1,128}$/.test(existing)) return existing;
  const deviceId = typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID()
    : `device-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  localStorage.setItem(PLAYER_DEVICE_ID_KEY, deviceId);
  return deviceId;
}


export interface AnalyzeActionDraftInput {
  declared_intent: string;
  intent_type?: string;
  params?: Record<string, unknown>;
  base_state_version?: number;
  ephemeral?: boolean;
}

export class PlayerApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(`Player API error: ${status}`);
    this.name = 'PlayerApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function analyzeActionDraft(input: AnalyzeActionDraftInput): Promise<ActionDraftDTO> {
  return requestJson('/api/player/action-drafts/analyze', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function getCurrentActionDraft(): Promise<ActionDraftDTO | null> {
  return requestJson('/api/player/action-drafts/current');
}

export async function reviseActionDraft(
  draftId: string,
  input: AnalyzeActionDraftInput,
): Promise<ActionDraftDTO> {
  return requestJson(`/api/player/action-drafts/${encodeURIComponent(draftId)}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

export async function deleteActionDraft(draftId: string): Promise<void> {
  await requestJson(`/api/player/action-drafts/${encodeURIComponent(draftId)}`, {
    method: 'DELETE',
  });
}

export async function confirmActionDraft(
  draftId: string,
  confirmations: string[],
  idempotencyKey: string,
): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/action-drafts/${encodeURIComponent(draftId)}/confirm`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ confirmations }),
  });
}

export async function cancelAction(actionId: string): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/actions/${encodeURIComponent(actionId)}/cancel`, {
    method: 'POST',
  });
}

export async function getActionReceipt(actionId: string): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/actions/${encodeURIComponent(actionId)}`);
}

export async function getPendingEncounterReaction(): Promise<{
  reaction: SoloCombatReactionDTO | null;
}> {
  return requestJson('/api/player/encounter-reactions/pending');
}

export async function resolveEncounterReaction(
  reactionId: string,
  choice: 'dodge' | 'counterattack',
): Promise<SoloCombatReactionResolutionDTO> {
  return requestJson(`/api/player/encounter-reactions/${encodeURIComponent(reactionId)}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ choice }),
  });
}

export async function getActionHints(): Promise<{ hints: string[] }> {
  const payload = await requestJson<{ hints?: string[]; examples?: string[] }>('/api/player/action-hints', {
    method: 'POST',
  });
  return { hints: (payload.hints || payload.examples || []).slice(0, 5) };
}

export async function reconnectPlayer(): Promise<PlayerReconnectDTO> {
  return requestJson('/api/player/reconnect');
}

export async function claimPlayerDevice(takeover = false): Promise<PlayerDeviceSessionDTO> {
  return requestJson('/api/player/device-sessions/claim', {
    method: 'POST',
    body: JSON.stringify({ device_id: getPlayerDeviceId(), takeover }),
  });
}

export async function getCampaignHome(): Promise<CampaignHomeDTO> {
  return requestJson('/api/player/campaign-home');
}

export async function createPersonalObjective(text: string): Promise<{ objective_id: string }> {
  return requestJson('/api/player/objectives', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
}

export interface SessionZeroDTO {
  steps: Array<{ step: string; confirmed: boolean; confirmed_at: string | null }>;
  complete: boolean;
}

export async function getSessionZero(): Promise<SessionZeroDTO> {
  return requestJson('/api/player/session-zero');
}

export async function confirmSessionZero(step: string): Promise<void> {
  await requestJson(`/api/player/session-zero/${encodeURIComponent(step)}`, {
    method: 'POST',
    body: JSON.stringify({ confirmed: true }),
  });
}

export async function listPlayerNotes(): Promise<{ notes: PlayerNoteDTO[] }> {
  return requestJson('/api/player/notes');
}

export async function createPlayerNote(title: string, body: string): Promise<PlayerNoteDTO> {
  return requestJson('/api/player/notes', {
    method: 'POST',
    body: JSON.stringify({ title, body }),
  });
}

export async function sharePlayerNote(noteId: string, title: string, body: string): Promise<PlayerNoteDTO> {
  return requestJson(`/api/player/notes/${encodeURIComponent(noteId)}/share`, {
    method: 'POST',
    body: JSON.stringify({ title, body }),
  });
}

export async function uploadPlayerNoteAttachment(noteId: string, file: File): Promise<void> {
  const form = new FormData();
  form.append('file', file);
  await requestJson(`/api/player/notes/${encodeURIComponent(noteId)}/attachment`, {
    method: 'POST',
    body: form,
  });
}

export async function listEvidence(roomId: string): Promise<{
  cards: EvidenceCardDTO[];
  links: Array<{
    evidence_link_id: string;
    from_evidence_card_id: string;
    to_evidence_card_id: string;
    relation_type: string;
  }>;
}> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence`);
}

export async function createEvidence(
  roomId: string,
  input: Pick<EvidenceCardDTO, 'title' | 'body' | 'card_type'>,
): Promise<EvidenceCardDTO> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function createEvidenceLink(
  roomId: string,
  fromEvidenceCardId: string,
  toEvidenceCardId: string,
  relationType: string,
): Promise<void> {
  await requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence/links`, {
    method: 'POST',
    body: JSON.stringify({
      from_evidence_card_id: fromEvidenceCardId,
      to_evidence_card_id: toEvidenceCardId,
      relation_type: relationType,
    }),
  });
}

async function requestJson<T = void>(path: string, init: RequestInit = {}): Promise<T> {
  const isMultipart = typeof FormData !== 'undefined' && init.body instanceof FormData;
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(isMultipart ? {} : { 'Content-Type': 'application/json' }),
      ...authHeaders(),
      'X-Device-Id': getPlayerDeviceId(),
      ...init.headers,
    },
  });
  const payload = response.status === 204
    ? undefined
    : await response.json().catch(() => undefined);
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload
      ? (payload as { detail: unknown }).detail
      : payload;
    throw new PlayerApiError(response.status, detail);
  }
  return payload as T;
}
