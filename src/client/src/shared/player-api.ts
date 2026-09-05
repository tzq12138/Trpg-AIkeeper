import { authHeaders } from './api';
import type {
  ActionDraftDTO,
  ActionConsentDTO,
  ActionConsentOutcomeDTO,
  ActionReceiptDTO,
  CampaignHomeDTO,
  EvidenceCardDTO,
  EvidenceDetailDTO,
  PlayerDeviceSessionDTO,
  PlayerCombatRoundDTO,
  PlayerNoteDTO,
  PlayerReconnectDTO,
  SoloCombatReactionDTO,
  SoloCombatReactionResolutionDTO,
  SessionZeroDTO,
} from './types';
import type { PlayerInputMode } from './player-input-modes';


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
  submission_action_id?: string;
}

export interface ReceiveActionSubmissionInput {
  actionId: string;
  rawText: string;
  inputMode: PlayerInputMode;
  clientSequence: number;
  baseStateVersion: number;
  requestedVisibility?: 'public' | 'party' | 'private';
}

export interface PlayerActionSubmissionReceipt {
  actionId: string;
  inputMode: PlayerInputMode;
  status:
    | 'received'
    | 'recorded'
    | 'analyzing'
    | 'awaiting_confirmation'
    | 'safety_paused'
    | 'safety_resumed';
  requiresAnalysis: boolean;
  receivedAt: string;
}

export interface PlayerSafetyStateDTO {
  status: 'active' | 'safety_paused';
  activePauseCount: number;
  canResume: boolean;
  ownRequestIds: string[];
}

export interface PlayerRuleQuestionDTO {
  actionId: string;
  text: string;
  createdAt: string;
}

export interface PlayerSettingsDTO {
  room_id: string;
  character_id: string;
  draft_analysis_enabled: boolean;
  absent_policy: 'idle' | 'maintain_existing';
  speech_routing: 'party_message' | 'npc_dialogue';
}

export interface CollaborationParticipantDTO {
  characterId: string;
  playerName: string;
}

export interface CollaborationLinkedDraftDTO {
  characterId: string;
  draftId: string;
  status: string;
}

export interface CollaborationContractDTO {
  contractId: string;
  roomId: string;
  initiatorCharacterId: string;
  sharedIntent: string;
  status: 'pending' | 'accepted' | 'completed' | 'canceled' | 'expired';
  participantCharacterIds: string[];
  pendingCharacterIds: string[];
  linkedDrafts: CollaborationLinkedDraftDTO[];
  expiresAt: string;
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

export async function receiveActionSubmission(
  input: ReceiveActionSubmissionInput,
): Promise<PlayerActionSubmissionReceipt> {
  return requestJson('/api/player/action-submissions', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function getSafetyState(): Promise<PlayerSafetyStateDTO> {
  return requestJson('/api/player/safety-state');
}

export async function resumeSafetyPause(
  requestId: string,
): Promise<PlayerSafetyStateDTO> {
  return requestJson(
    `/api/player/safety-pauses/${encodeURIComponent(requestId)}/resume`,
    { method: 'POST' },
  );
}

export async function getRuleQuestions(): Promise<{ questions: PlayerRuleQuestionDTO[] }> {
  return requestJson('/api/player/rule-questions');
}

export function nextPlayerActionSequence(): number {
  const key = 'aikeeper_player_action_sequence';
  const current = Number(localStorage.getItem(key) || '0');
  const next = Number.isFinite(current) && current >= 0 ? current + 1 : 1;
  localStorage.setItem(key, String(next));
  return next;
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
  selectedSkill?: string,
  compositeStepOrder?: string[],
): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/action-drafts/${encodeURIComponent(draftId)}/confirm`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      confirmations,
      ...(selectedSkill ? { selected_skill: selectedSkill } : {}),
      ...(compositeStepOrder?.length ? { composite_step_order: compositeStepOrder } : {}),
    }),
  });
}

export async function cancelAction(actionId: string): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/actions/${encodeURIComponent(actionId)}/cancel`, {
    method: 'POST',
  });
}

export async function resolveCompositeActionChoice(
  actionId: string,
  proceed: boolean,
): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/actions/${encodeURIComponent(actionId)}/composite-choice`, {
    method: 'POST',
    body: JSON.stringify({ proceed }),
  });
}

export async function getActionReceipt(actionId: string): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/actions/${encodeURIComponent(actionId)}`);
}

export async function getPendingActionConsents(): Promise<{ items: ActionConsentDTO[] }> {
  return requestJson('/api/player/action-consents');
}

export async function respondToActionConsent(
  consentId: string,
  accepted: boolean,
): Promise<ActionConsentOutcomeDTO> {
  const response = await requestJson<ActionConsentOutcomeDTO>(`/api/player/action-consents/${encodeURIComponent(consentId)}`, {
    method: 'POST',
    body: JSON.stringify({ accepted }),
  });
  return {
    ...response,
    accepted: response.decision ? response.decision === 'accepted' : Boolean(response.accepted),
  };
}

export async function submitCocFollowUp(
  actionId: string,
  decision: 'spend_luck' | 'push' | 'decline',
  idempotencyKey: string,
): Promise<ActionReceiptDTO> {
  return requestJson(`/api/player/actions/${encodeURIComponent(actionId)}/follow-up`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ decision }),
  });
}

export async function getPendingEncounterReaction(): Promise<{
  reaction: SoloCombatReactionDTO | null;
}> {
  return requestJson('/api/player/encounter-reactions/pending');
}

export async function getPlayerCombatRound(): Promise<PlayerCombatRoundDTO> {
  return requestJson('/api/player/combat-round');
}

export async function declareCombatRoundIdle(): Promise<{
  status: 'declared_idle';
  turnId: string;
  actionId: string;
}> {
  return requestJson('/api/player/combat-round/idle', { method: 'POST' });
}

export async function getPlayerSettings(): Promise<PlayerSettingsDTO> {
  return requestJson('/api/player/settings');
}

export async function getCollaborationContracts(): Promise<{ items: CollaborationContractDTO[] }> {
  return requestJson('/api/player/collaboration-contracts');
}

export async function getCollaborationParticipants(): Promise<{ items: CollaborationParticipantDTO[] }> {
  return requestJson('/api/player/collaboration-contracts/participants');
}

export async function createCollaborationContract(
  sharedIntent: string,
  inviteeCharacterIds: string[],
): Promise<CollaborationContractDTO> {
  return requestJson('/api/player/collaboration-contracts', {
    method: 'POST',
    body: JSON.stringify({ sharedIntent, inviteeCharacterIds }),
  });
}

export async function respondToCollaborationContract(
  contractId: string,
  decision: 'accept' | 'decline',
): Promise<CollaborationContractDTO> {
  return requestJson(`/api/player/collaboration-contracts/${encodeURIComponent(contractId)}/responses`, {
    method: 'POST',
    body: JSON.stringify({ decision }),
  });
}

export async function cancelCollaborationContract(contractId: string): Promise<CollaborationContractDTO> {
  return requestJson(`/api/player/collaboration-contracts/${encodeURIComponent(contractId)}/cancel`, {
    method: 'POST',
  });
}

export async function updatePlayerSettings(
  input: Partial<Pick<PlayerSettingsDTO, 'draft_analysis_enabled' | 'absent_policy'>>,
): Promise<PlayerSettingsDTO> {
  return requestJson('/api/player/settings', {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
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

export async function getSessionZero(): Promise<SessionZeroDTO> {
  return requestJson('/api/player/session-zero');
}

export interface SessionZeroProbeDTO {
  probe_id: string | null;
  probe_type: 'private_projection' | 'party_projection' | 'device_recovery';
  status: string;
  audience: string;
  issued_watermark: number;
  confirmed_at: string | null;
  valid: boolean;
  reason: string | null;
}

export interface SessionZeroProbesDTO {
  probes: SessionZeroProbeDTO[];
  controller: { device_session_id: string; device_id: string } | null;
}

export async function getSessionZeroProbes(): Promise<SessionZeroProbesDTO> {
  return requestJson('/api/player/session-zero/probes');
}

export async function confirmSessionZeroProbe(
  probeId: string,
  probeType: SessionZeroProbeDTO['probe_type'],
  watermark?: number,
): Promise<{ status: string }> {
  return requestJson('/api/player/session-zero/probes/confirm', {
    method: 'POST',
    body: JSON.stringify({
      probe_id: probeId,
      probe_type: probeType,
      ...(watermark !== undefined ? { watermark } : {}),
    }),
  });
}

export async function confirmSessionZero(
  step: string,
  contractHash?: string,
): Promise<void> {
  await requestJson(`/api/player/session-zero/${encodeURIComponent(step)}`, {
    method: 'POST',
    body: JSON.stringify({
      confirmed: true,
      ...(contractHash ? { contract_hash: contractHash } : {}),
    }),
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

export async function updatePlayerNote(noteId: string, title: string, body: string): Promise<PlayerNoteDTO> {
  return requestJson(`/api/player/notes/${encodeURIComponent(noteId)}`, {
    method: 'PATCH',
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
  comments: EvidenceCommentDTO[];
}> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence`);
}

export async function getEvidenceDetail(
  roomId: string,
  evidenceCardId: string,
): Promise<EvidenceDetailDTO> {
  return requestJson(
    `/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/detail`,
  );
}

export async function createEvidenceNote(
  roomId: string,
  evidenceCardId: string,
  title: string,
  body: string,
): Promise<PlayerNoteDTO> {
  return requestJson(
    `/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/notes`,
    { method: 'POST', body: JSON.stringify({ title, body }) },
  );
}

export interface EvidenceCommentDTO {
  evidence_card_id: string;
  body: string;
  author_name: string;
}

export interface SharedHypothesisStatusTransition {
  card: EvidenceCardDTO;
  undo_available: boolean;
  changed: boolean;
}

export interface HypothesisDisproofSuggestion {
  suggestedStatus: 'possible_disproved';
  reason: string;
  factIds: string[];
  confidence: 'low' | 'medium' | 'high';
  requiresPlayerConfirmation: true;
}

export interface HypothesisDisproofSuggestionResponse {
  suggestion: HypothesisDisproofSuggestion | null;
  reason: 'no_confirmed_linked_facts' | 'ai_unavailable' | 'no_supported_disproof' | null;
}

export async function createEvidence(
  roomId: string,
  input: Pick<EvidenceCardDTO, 'title' | 'body' | 'card_type'>
    & Pick<Partial<EvidenceCardDTO>, 'visibility'>
    & { related_evidence_card_ids?: string[] },
): Promise<EvidenceCardDTO> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence`, {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

export async function shareEvidence(
  roomId: string,
  evidenceCardId: string,
  title: string,
  body: string,
): Promise<EvidenceCardDTO> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/share`, {
    method: 'POST',
    body: JSON.stringify({ title, body }),
  });
}

export async function createEvidenceComment(
  roomId: string,
  evidenceCardId: string,
  body: string,
): Promise<EvidenceCommentDTO> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/comments`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });
}

export async function updateSharedHypothesisStatus(
  roomId: string,
  evidenceCardId: string,
  hypothesisStatus: 'discussing' | 'disproved' | 'shelved',
): Promise<SharedHypothesisStatusTransition> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/hypothesis-status`, {
    method: 'POST',
    body: JSON.stringify({ hypothesis_status: hypothesisStatus }),
  });
}

export async function revertSharedHypothesisStatus(
  roomId: string,
  evidenceCardId: string,
): Promise<SharedHypothesisStatusTransition> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/hypothesis-status/revert`, {
    method: 'POST',
  });
}

export async function suggestSharedHypothesisDisproof(
  roomId: string,
  evidenceCardId: string,
): Promise<HypothesisDisproofSuggestionResponse> {
  return requestJson(`/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/hypothesis-disproof-suggestion`, {
    method: 'POST',
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

export interface PartyQuestionClosePreview {
  question: EvidenceCardDTO;
  related_hypotheses: Array<Pick<EvidenceCardDTO, 'evidence_card_id' | 'title' | 'card_type' | 'fact_status'>>;
  disputed_cards: Array<Pick<EvidenceCardDTO, 'evidence_card_id' | 'title' | 'card_type' | 'fact_status'>>;
}

export interface PartyQuestionTransition {
  card: EvidenceCardDTO;
  undo_available: boolean;
  undid_close: boolean;
}

export async function previewPartyQuestionClose(
  roomId: string,
  evidenceCardId: string,
): Promise<PartyQuestionClosePreview> {
  return requestJson(
    `/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/question-close-preview`,
  );
}

export async function closePartyQuestion(
  roomId: string,
  evidenceCardId: string,
): Promise<PartyQuestionTransition> {
  return requestJson(
    `/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/question-close`,
    { method: 'POST', body: JSON.stringify({ confirmed: true }) },
  );
}

export async function reopenPartyQuestion(
  roomId: string,
  evidenceCardId: string,
): Promise<PartyQuestionTransition> {
  return requestJson(
    `/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/question-reopen`,
    { method: 'POST' },
  );
}

export async function markPartyQuestionExplained(
  roomId: string,
  evidenceCardId: string,
): Promise<PartyQuestionTransition> {
  return requestJson(
    `/api/rooms/${encodeURIComponent(roomId)}/evidence/${encodeURIComponent(evidenceCardId)}/question-explanation`,
    { method: 'POST' },
  );
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
