// Event types synced with src/server/events_registry.py
export type EngineEventType =
  // ── Narrative / reveal ──
  | 's2c_reveal_transaction' | 's2c_resume_transaction' | 's2c_cancel_transaction'
  | 's2c_chat_stream' | 's2c_public_observation' | 's2c_scene_sync'
  // ── Action lifecycle ──
  | 's2c_action_queued' | 's2c_action_batched' | 's2c_action_completed'
  | 's2c_action_review_requested' | 's2c_action_review_resolved'
  | 's2c_action_exception_requested'
  | 's2c_action_choice_requested'
  | 's2c_tactical_prompt' | 's2c_clarification_prompt' | 's2c_clarification_result'
  // ── State sync ──
  | 's2c_state_patch' | 's2c_full_snapshot' | 's2c_host_snapshot'
  | 's2c_engine_state' | 's2c_private_notice'
  // ── Room management ──
  | 's2c_room_lobby_snapshot' | 's2c_ready_toggled' | 's2c_campaign_ended'
  | 's2c_turn_resolved'
  | 's2c_clue_discovered' | 's2c_clue_shared'
  // ── System ──
  | 's2c_atmosphere' | 's2c_checkpoint_created' | 's2c_checkpoint_restored'
  | 's2c_ai_stage_changed' | 's2c_ai_recovery_required'
  | 's2c_director_plan_validated' | 's2c_narration_completed'
  // ── Map ──
  | 's2c_map_updated' | 's2c_player_moved' | 's2c_map_revealed'
  // ── Encounter ──
  | 's2c_encounter_suggested' | 's2c_encounter_started'
  | 's2c_encounter_updated' | 's2c_encounter_resolved'
  // ── Team Chat ──
  | 's2c_team_message';

export interface EngineEvent {
  eventId: string;
  roomId: string;
  type: EngineEventType;
  roomSequence: number;
  audience: 'host' | 'player' | 'party' | 'system';
  visibility: string;
  issuedAt: string;
  payload: Record<string, unknown>;
}

export interface RedactedCitation {
  label: string;
  page?: number | null;
  scene?: string | null;
  verified: boolean;
}

export type AiStageName =
  | 'retrieving'
  | 'directing'
  | 'validating_rules'
  | 'narrating'
  | 'recovering'
  | 'completed';

export interface AiStageProgress {
  stage: AiStageName;
  status: 'idle' | 'active' | 'completed' | 'failed';
  label?: string;
  detail?: string;
  updated_at?: string;
}

export interface SemanticMapProjectionDTO {
  roomId: string;
  mapStatus: string;
  mapType?: 'graph' | 'image' | 'hybrid' | 'text';
  baseAsset?: { assetId?: string | null };
  knownLocations: Array<{
    nodeId: string;
    label: string;
    description?: string;
    isCurrent?: boolean;
    position?: { x: number; y: number };
  }>;
  knownConnections: Array<{ fromNodeId: string; toNodeId: string; label?: string }>;
  partyPosition?: { nodeId: string; label: string } | null;
  fogOfWar: Array<{ regionId: string; polygon?: Array<[number, number]> }>;
  textScene?: { name: string; description: string; visibleExits: string[] } | null;
}

export interface HostDirectorSnapshotDTO {
  currentScene: string;
  confirmedFacts: string[];
  pendingTriggers: string[];
  aiEvidence: RedactedCitation[];
  stage: AiStageName;
  risks: string[];
  exceptionQueue: string[];
}

export type ActionStatus =
  | 'idle' | 'typing' | 'analyzing' | 'awaiting_confirmation'
  | 'queued' | 'batched' | 'resolving'
  | 'awaiting_player_choice' | 'awaiting_host_exception'
  | 'completed' | 'resolved' | 'rejected' | 'canceled' | 'timeout' | 'sync_required';

export interface ActionDraftDTO {
  draft_id: string | null;
  revision: number;
  base_state_version: number;
  status: 'analyzing' | 'awaiting_confirmation';
  intent_type: string;
  declared_intent: string;
  params: Record<string, unknown>;
  understanding_summary: string;
  risk: 'low' | 'medium' | 'high';
  suggested_skill: string | null;
  difficulty: string | null;
  resource_impacts: Array<Record<string, unknown>>;
  visibility: 'public' | 'party' | 'private';
  movement_target: string | null;
  confirmation_requirements: string[];
  requires_confirmation: boolean;
  confidence: number;
  citations: RedactedCitation[];
  analysis_source: 'configured_provider' | 'fallback_provider' | 'local_fallback';
  resolution_route: 'ai' | 'local' | 'host_exception';
  ephemeral: boolean;
}

export interface ActionTimelineEventDTO {
  status: ActionStatus;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface RuleExplanationDTO {
  authoritative_inputs: Record<string, unknown>;
  modifiers: Record<string, unknown>;
  hidden_sources: Array<{ source: 'hidden'; effect?: unknown }>;
  formula: string;
  state_before: Record<string, unknown>;
  state_after: Record<string, unknown>;
  rule_set_version: string;
  citations: RedactedCitation[];
  verification_receipt: Record<string, unknown> | null;
}

export interface ActionReceiptDTO {
  action_id: string;
  draft_id: string | null;
  status: ActionStatus;
  declared_intent: string;
  revision: number;
  result: unknown;
  timeline: ActionTimelineEventDTO[];
  can_cancel: boolean;
  can_review: boolean;
  rule_explanation: RuleExplanationDTO | null;
}

export interface NarrationResultDTO {
  action_id: string;
  context_version: number;
  director_plan_digest: string;
  narrative_text: string;
  environment_changes: string[];
  interactable_objects: string[];
  open_question: string;
  fact_refs: Record<string, string[]>;
  redacted_citations: RedactedCitation[];
  style_pack_version: string;
  provider_source: 'configured_provider' | 'fallback_provider' | 'local_fallback';
  status: 'completed' | 'invalid_response';
}

export interface PlayerReconnectDTO {
  character: CharacterSheet;
  recent_events: Array<Record<string, unknown>>;
  pending_actions: ActionReceiptDTO[];
  last_sequence: number;
  stateVersion: number;
  sceneState?: {
    currentScene: string;
    visitedScenes: string[];
    version: number;
  };
}

export interface PlayerDeviceSessionDTO {
  device_session_id?: string;
  device_id: string;
  status: 'active' | 'revoked' | 'expired';
  controller: boolean;
  last_seen_at?: string;
  expires_at?: string;
}

export interface CampaignSessionDTO {
  campaign_session_id: string;
  status: 'active' | 'ended' | 'scheduled';
  started_by_character_id: string | null;
  started_at: string;
  last_activity_at: string;
  scheduled_for: string | null;
  ended_at: string | null;
  attendance_status?: 'attending' | 'tentative' | 'absent';
}

export interface EvidenceCardDTO {
  evidence_card_id: string;
  title: string;
  body: string;
  card_type: 'clue' | 'person' | 'location' | 'item' | 'question';
  fact_status: 'hypothesis' | 'confirmed' | 'excluded';
  visibility: 'party' | 'private';
  source: 'player' | 'host' | 'system';
  confirmed_by: string | null;
  created_by_character_id: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface CampaignHomeDTO {
  room_id: string;
  current_scene: {
    node_id: string;
    title: string;
    text_preview: string;
    citation: RedactedCitation;
    choice_count: number;
    image_asset_id?: string | null;
  } | null;
  session: CampaignSessionDTO | null;
  team_objectives: Array<{ objective_id: string; text: string; status: string; assigned_at: string }>;
  personal_objectives: Array<{ objective_id: string; text: string; status: string; assigned_at: string }>;
  last_summary: {
    summary_text: string;
    source: string;
    confidence: number;
    published_at: string;
    citations: Array<{ event_sequence: number; citation_label: string }>;
  } | null;
  next_session: CampaignSessionDTO | null;
  recent_clues: Array<Record<string, unknown>>;
  unresolved_questions: Array<Pick<EvidenceCardDTO, 'evidence_card_id' | 'title' | 'fact_status'>>;
}

export interface PlayerNoteDTO {
  note_id: string;
  parent_note_id: string | null;
  title: string;
  body: string;
  visibility: 'private' | 'party';
  is_redacted_copy: boolean;
  created_at: string;
  updated_at: string;
}

export interface CharacterSheet {
  character_id: string;
  player_name?: string;
  investigator_name?: string;
  name: string;
  occupation?: string;
  hp: number;
  max_hp: number;
  san: number;
  max_san: number;
  mp: number;
  max_mp: number;
  luck: number;
  skills: Record<string, number>;
  background: string;
}

export interface InventoryItem {
  id: string;
  name: string;
  description: string;
  quantity: number;
  is_secret: number;
}

export interface Clue {
  id: string;
  text: string;
  source: string;
  is_private: boolean;
  is_owner: boolean;
  shared_with: Array<{ share_id: string; shared_by: string; public_version: string }>;
}

export interface Objective {
  id: string;
  text: string;
  type: 'team' | 'personal';
  status: 'active' | 'completed' | 'failed';
}

export interface TacticalAction {
  action_id: string;
  label: string;
  intent_type: string;
  params: Record<string, unknown>;
}

export interface TacticalPrompt {
  text: string;
  actions: TacticalAction[];
}

export interface PlayerChatMessage {
  id: string;
  sender: 'kp' | 'player' | 'system' | 'team';
  text: string;
  actions?: TacticalAction[];
  timestamp: number;
}

export interface CharacterAttributes {
  str: number; con: number; siz: number; dex: number;
  app: number; int: number; pow: number; edu: number; luck: number;
}

export interface DerivedStats {
  hp: number; mp: number; san: number; mov: number; db: string; build: number;
}

export interface BackgroundData {
  description: string; belief: string; importantPerson: string;
  valuableThing: string; trait: string; wound: string; phobia: string;
}

export interface BuilderCharacterData {
  name: string; occupation: string; age: number; gender: string;
  attributes: CharacterAttributes; derived_stats: DerivedStats;
  skills: Record<string, number>; background: string;
  backstory?: BackgroundData;
}

export interface SkillCheckResult {
  skill_name: string;
  skill_value: number;
  roll: number;
  difficulty: string;
  success_level: 'critical' | 'extreme' | 'hard' | 'regular' | 'failure' | 'fumble';
  detail: string;
}
