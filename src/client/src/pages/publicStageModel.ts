export interface PublicStagePlayer {
  character_id: string;
  player_name: string;
  investigator_name: string;
  condition: string;
  condition_tone: 'stable' | 'warning' | 'danger';
}

export interface PublicStageEvent {
  text: string;
  issued_at: string;
}

export interface PublicStageCombatRound {
  round_number: number;
  phase: 'declaration' | 'resolution' | 'summary' | 'blocked';
  submitted_count: number;
  total_players: number;
  current_conflict?: string;
  public_units?: PublicStageCombatUnit[];
}

export interface PublicStageCombatUnit {
  label: string;
  kind: 'investigator' | 'observed_enemy';
  health_segments?: number;
  condition: string;
  distance_band?: 'engaged' | 'near' | 'short' | 'medium' | 'long';
  last_observed_at?: string;
}

export interface PublicStageData {
  room_id: string;
  scene_image_url: string | null;
  status_text: string;
  team_objectives: string[];
  scene_time: string;
  players: PublicStagePlayer[];
  recent_events: PublicStageEvent[];
  combat_round?: PublicStageCombatRound;
}

export interface PublicStagePresentation {
  available: boolean;
  version: number;
  kind: 'narrative_text' | null;
  narrative_text: string | null;
}

const PUBLIC_STAGE_PLAYER_LIMIT = 6;

export function normalizePublicStage(raw: Record<string, unknown>): PublicStageData {
  const players: PublicStagePlayer[] = (raw.players as Array<Record<string, unknown>> | undefined || []).slice(0, PUBLIC_STAGE_PLAYER_LIMIT).map((player) => {
    const conditionTone: PublicStagePlayer['condition_tone'] = player.conditionTone === 'danger' || player.condition_tone === 'danger'
      ? 'danger'
      : player.conditionTone === 'warning' || player.condition_tone === 'warning'
        ? 'warning'
        : 'stable';
    return {
      character_id: String(player.characterId || player.character_id || ''),
      player_name: String(player.playerName || player.player_name || '未命名玩家'),
      investigator_name: String(player.investigatorName || player.investigator_name || ''),
      condition: String(player.condition || '情况稳定'),
      condition_tone: conditionTone,
    };
  });
  const recentEvents = (raw.recentEvents as Array<Record<string, unknown>> | undefined || []).map((event) => ({
    text: String(event.text || ''),
    issued_at: String(event.issuedAt || event.issued_at || ''),
  })).filter((event) => event.text);
  const combatRound = normalizePublicCombatRound(raw.combatRound ?? raw.combat_round);

  return {
    room_id: String(raw.roomId || raw.room_id || ''),
    scene_image_url: (raw.sceneImageUrl ?? raw.scene_image_url ?? null) as string | null,
    status_text: String(raw.statusText || raw.status_text || '等待调查员行动'),
    team_objectives: (raw.teamObjectives as unknown[] | undefined || raw.team_objectives as unknown[] | undefined || [])
      .filter((objective): objective is string => typeof objective === 'string' && objective.trim().length > 0),
    scene_time: String(raw.sceneTime || raw.scene_time || '时间未定'),
    players,
    recent_events: recentEvents,
    ...(combatRound ? { combat_round: combatRound } : {}),
  };
}

function normalizePublicCombatRound(value: unknown): PublicStageCombatRound | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const raw = value as Record<string, unknown>;
  const phase = raw.phase;
  if (phase !== 'declaration' && phase !== 'resolution' && phase !== 'summary' && phase !== 'blocked') {
    return undefined;
  }
  const roundNumber = normalizeNonNegativeInteger(raw.roundNumber ?? raw.round_number, 1);
  const totalPlayers = normalizeNonNegativeInteger(raw.totalPlayers ?? raw.total_players, 0);
  const submittedCount = Math.min(
    normalizeNonNegativeInteger(raw.submittedCount ?? raw.submitted_count, 0),
    totalPlayers,
  );
  const conflict = typeof (raw.currentConflict ?? raw.current_conflict) === 'string'
    ? String(raw.currentConflict ?? raw.current_conflict).trim().slice(0, 80)
    : '';
  const publicUnits = normalizePublicCombatUnits(raw.publicUnits ?? raw.public_units);
  return {
    round_number: Math.max(1, roundNumber),
    phase,
    submitted_count: submittedCount,
    total_players: totalPlayers,
    ...(conflict && (phase === 'resolution' || phase === 'blocked') ? { current_conflict: conflict } : {}),
    ...(publicUnits.length
      ? { public_units: publicUnits }
      : {}),
  };
}

function normalizePublicCombatUnits(value: unknown): PublicStageCombatUnit[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return [];
    const raw = item as Record<string, unknown>;
    const kind = raw.kind;
    const label = typeof raw.label === 'string' ? raw.label.trim().slice(0, 80) : '';
    const condition = typeof raw.condition === 'string' ? raw.condition.trim().slice(0, 40) : '';
    if (!label || !condition || (kind !== 'investigator' && kind !== 'observed_enemy')) return [];
    const distance = raw.distanceBand ?? raw.distance_band;
    const lastObservedAt = raw.lastObservedAt ?? raw.last_observed_at;
    const healthSegments = normalizeNonNegativeInteger(raw.healthSegments ?? raw.health_segments, -1);
    const unit: PublicStageCombatUnit = { label, kind, condition };
    if (healthSegments >= 0 && healthSegments <= 8 && condition !== '失去踪迹') {
      unit.health_segments = healthSegments;
    }
    if (distance === 'engaged' || distance === 'near' || distance === 'short' || distance === 'medium' || distance === 'long') {
      unit.distance_band = distance;
    }
    if (condition === '失去踪迹' && typeof lastObservedAt === 'string' && lastObservedAt.trim()) {
      unit.last_observed_at = lastObservedAt.trim().slice(0, 80);
    }
    return [unit];
  }).slice(0, 12);
}

function normalizeNonNegativeInteger(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.max(0, Math.floor(value))
    : fallback;
}

export function normalizePublicStagePresentation(raw: Record<string, unknown>): PublicStagePresentation {
  const kind = raw.kind === 'narrative_text' ? 'narrative_text' : null;
  const narrative = typeof raw.narrativeText === 'string'
    ? raw.narrativeText.trim()
    : typeof raw.narrative_text === 'string'
      ? raw.narrative_text.trim()
      : '';
  const version = typeof raw.version === 'number' && Number.isFinite(raw.version)
    ? Math.max(0, Math.floor(raw.version))
    : 0;
  const available = raw.available === true && kind === 'narrative_text' && Boolean(narrative);
  return {
    available,
    version,
    kind: available ? kind : null,
    narrative_text: available ? narrative : null,
  };
}
