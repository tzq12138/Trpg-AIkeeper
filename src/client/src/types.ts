export type EngineEventType =
  | 's2c_reveal_transaction' | 's2c_resume_transaction' | 's2c_cancel_transaction'
  | 's2c_chat_stream' | 's2c_atmosphere' | 's2c_engine_state' | 's2c_scene_sync'
  | 's2c_host_snapshot' | 's2c_full_snapshot' | 's2c_state_patch'
  | 's2c_private_notice' | 's2c_public_observation' | 's2c_tactical_prompt'
  | 's2c_room_lobby_snapshot' | 's2c_campaign_ended'
  | 's2c_action_queued' | 's2c_action_batched' | 's2c_action_completed'
  | 's2c_clarification_prompt' | 's2c_clarification_result';

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

export type ActionStatus = 'idle' | 'submitting' | 'queued' | 'batched' | 'resolving' | 'resolved' | 'rejected' | 'timeout';

export interface CharacterSheet {
  character_id: string;
  name: string;
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
  sender: 'kp' | 'player' | 'system';
  text: string;
  actions?: TacticalAction[];
  timestamp: number;
}

export interface SkillCheckResult {
  skill_name: string;
  skill_value: number;
  roll: number;
  difficulty: string;
  success_level: 'critical' | 'extreme' | 'hard' | 'regular' | 'failure' | 'fumble';
  detail: string;
}
