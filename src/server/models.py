import uuid
from datetime import datetime, timezone
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field

# Event type literals — canonical registry is at .events.events_registry.ALL_EVENTS
EngineEventType = Literal[
    "s2c_reveal_transaction", "s2c_resume_transaction", "s2c_cancel_transaction",
    "s2c_chat_stream", "s2c_atmosphere", "s2c_engine_state", "s2c_scene_sync",
    "s2c_host_snapshot", "s2c_full_snapshot", "s2c_state_patch",
    "s2c_private_notice", "s2c_public_observation", "s2c_tactical_prompt",
    "s2c_room_lobby_snapshot", "s2c_campaign_ended",
    "s2c_action_queued", "s2c_action_batched", "s2c_action_completed",
    "s2c_clarification_prompt", "s2c_clarification_result",
    "s2c_ready_toggled",
    "s2c_map_updated", "s2c_player_moved", "s2c_map_revealed",
    "s2c_encounter_suggested", "s2c_encounter_started",
    "s2c_encounter_updated", "s2c_encounter_resolved",
    "s2c_team_message",
]

Audience = Literal["host", "player", "party", "system"]


class EngineEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="eventId")
    room_id: str = Field(alias="roomId")
    type: EngineEventType
    room_sequence: int = Field(default=0, alias="roomSequence")
    audience: Audience
    visibility: str = "public"
    issued_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), alias="issuedAt")
    payload: dict[str, Any] = {}


class RoomCreate(BaseModel):
    scenario_id: str | None = None
    spoiler_level: str = "standard"


class Room(BaseModel):
    room_id: str
    scenario_id: str | None = None
    owner_token: str
    status: str = "lobby"
    spoiler_level: str = "standard"


class PlayerIntent(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    intent_type: Literal[
        "voice_command", "dialogue", "skill_check", "move",
        "use_item", "show_item", "ready_toggle", "character_import_confirm",
        "clarification_request", "retroactive_item_claim",
        "combat_action", "chase_action", "system_skip",
    ]
    declared_intent: str = ""
    base_state_version: int = 0
    params: dict[str, Any] = {}


class ActionReceipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    action_id: str = Field(alias="actionId")
    status: Literal[
        "idle", "submitting", "queued", "batched",
        "resolving", "resolved", "rejected", "timeout",
    ] = "idle"
    declared_intent: str = Field(default="", alias="declaredIntent")
    batch_id: str | None = Field(default=None, alias="batchId")
    result: str | None = None


class TransactionStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["roll", "status_delta", "scene_transition", "narrative_text"]
    payload: dict[str, Any] = {}
    timeout_ms: int = Field(default=15000, alias="timeoutMs")


class RevealTransaction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    transaction_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="transactionId")
    priority: Literal["normal", "urgent"] = "normal"
    steps: list[TransactionStep] = []
    summary_text: str | None = Field(default=None, alias="summaryText")
    audio_action: str | None = Field(default=None, alias="audioAction")  # 'suspendBGM' | 'duckBGM'


class PlayerPublicStatus(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    player_name: str = Field(default="", alias="playerName")
    investigator_name: str = Field(default="", alias="investigatorName")
    hp: int = 0
    hp_max: int = Field(default=0, alias="hpMax")
    san: int = 0
    san_max: int = Field(default=0, alias="sanMax")
    mp: int = 0
    mp_max: int = Field(default=0, alias="mpMax")
    luck: int = 0
    status_tags: list[str] = Field(default=[], alias="statusTags")


class HostHUD(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    room_id: str = Field(alias="roomId")
    players: list[PlayerPublicStatus] = []
    scene_image_url: str | None = Field(default=None, alias="sceneImageUrl")
    engine_state: str = Field(default="idle", alias="engineState")
    queue_status: dict[str, int] = Field(default={"normal": 0, "urgent": 0}, alias="queueStatus")
    audio_action: str | None = Field(default=None, alias="audioAction")


class AtmosphereCommand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    bgm: dict[str, Any] | None = None
    sfx: list[dict[str, Any]] = []
    visual: dict[str, Any] | None = None


class Clue(BaseModel):
    clue_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    room_id: str
    character_id: str
    text: str
    source: str = ""
    is_private: bool = True
    discovered_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ClueShare(BaseModel):
    share_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    clue_id: str
    shared_by: str
    shared_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    public_version: str


class Objective(BaseModel):
    objective_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    room_id: str
    character_id: str | None = None
    text: str
    type: Literal["team", "personal"] = "team"
    status: Literal["active", "completed", "failed", "expired"] = "active"
    assigned_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ClarificationRequest(BaseModel):
    clarification_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    room_id: str
    character_id: str
    target_action_id: str
    text: str
    evidence: str | None = None
    status: Literal["pending", "resolved", "expired", "rejected"] = "pending"
    window_expires_at: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: str | None = None


class ClarificationResult(BaseModel):
    request_id: str
    type: Literal["explain", "followup", "recalc"] = "explain"
    content: str


class CharacterSheet(BaseModel):
    character_id: str
    name: str = ""
    hp: int = 0
    max_hp: int = 0
    san: int = 0
    max_san: int = 0
    mp: int = 0
    max_mp: int = 0
    luck: int = 0
    skills: dict[str, int] = {}
    background: str = ""


class InventoryItem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    quantity: int = 1
    is_secret: bool = False


class SkillCheckRequest(BaseModel):
    skill_name: str
    skill_value: int = 0
    difficulty: Literal["regular", "hard", "extreme"] = "regular"
    bonus_dice: int = 0


class SkillCheckResult(BaseModel):
    skill_name: str
    skill_value: int
    roll: int
    difficulty: str
    success_level: Literal["critical", "extreme", "hard", "regular", "failure", "fumble"]
    detail: str = ""


class TacticalAction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="actionId")
    label: str
    intent_type: str = Field(alias="intentType")
    params: dict[str, Any] = {}


class TacticalPrompt(BaseModel):
    text: str
    actions: list[TacticalAction] = []


class ReconnectSnapshot(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    character: dict[str, Any]
    recent_events: list[dict[str, Any]] = Field(alias="recentEvents")
    pending_actions: list[dict[str, Any]] = Field(alias="pendingActions")
    last_sequence: int = Field(alias="lastSequence")


class ArchiveEntry(BaseModel):
    sequence: int
    type: str
    timestamp: str
    data: dict[str, Any]
    is_public: bool = False


class ReplayEvent(BaseModel):
    sequence: int
    type: str
    audience: str
    payload: dict[str, Any]
    timestamp: str


SpoilerLevel = Literal["strict", "standard", "cinematic"]


class StateSuggestion(BaseModel):
    type: Literal["hp", "san", "mp", "clue", "objective", "status_tag"]
    target: str
    value: Any
    reason: str = ""


class RollRequest(BaseModel):
    skill_name: str
    difficulty: Literal["regular", "hard", "extreme"] = "regular"
    bonus_dice: int = 0
    reason: str = ""
    visibility: Literal["public", "private"] = "public"
    target_character: str | None = None


class AIResponse(BaseModel):
    narrative: str
    state_suggestions: list[StateSuggestion] = []
    roll_requests: list[RollRequest] = []
    tactical_prompts: list[TacticalPrompt] = []
    clues_to_release: list[str] = []
    keeper_notes: str = ""
    encounter_suggestion: "EncounterSuggestion | None" = Field(default=None, alias="encounterSuggestion")


class ExposureLevel(BaseModel):
    character_id: str
    level: int = 0
    discovered_elements: list[str] = []


class Checkpoint(BaseModel):
    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    room_id: str
    state_snapshot: dict[str, Any]
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CampaignEnding(BaseModel):
    ending_type: Literal["victory", "defeat", "mixed", "abandoned"]
    summary: str
    highlights: list[str] = []
    character_arcs: list[dict[str, Any]] = []


class CampaignSummary(BaseModel):
    room_id: str
    duration_seconds: int = 0
    total_actions: int = 0
    clues_found: int = 0
    key_events: list[dict[str, Any]] = []
    ending: CampaignEnding | None = None


class EventLogEntry(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    sequence: int
    room_id: str = Field(alias="roomId")
    event_type: str = Field(alias="eventType")
    audience: str
    payload: dict[str, Any]
    issued_at: str = Field(alias="issuedAt")


class CampaignArchiveQuery(BaseModel):
    action_type: str | None = None
    character_id: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int = 50


class ScenarioKnowledgeGraph(BaseModel):
    scenes: list[dict[str, Any]] = []
    npcs: list[dict[str, Any]] = []
    clues: list[dict[str, Any]] = []
    truth: dict[str, Any] | None = None
    endings: list[dict[str, Any]] = []


class ScenarioAssets(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    items: dict[str, dict[str, Any]] = {}
    professions_matrix: dict[str, dict[str, Any]] = Field(default={}, alias="professionsMatrix")
    scenes: list[dict[str, Any]] = []


class MechanicCompileResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    triggered_mechanic: Literal[
        "skill_check", "sanity_check", "combat_damage", "luck_check",
        "auto_success", "auto_failure", "dialogue", "move",
        "combat_attack", "combat_dodge", "combat_defend",
        "combat_assist", "combat_flee", "combat_wait",
        "chase_pursue", "chase_escape", "chase_block",
        "chase_create_obstacle", "chase_detour", "chase_assist", "chase_wait",
    ] = Field(default="dialogue", alias="triggeredMechanic")
    skill_name: str | None = Field(default=None, alias="skillName")
    difficulty: Literal["regular", "hard", "extreme"] = "regular"
    item_consumed: bool = Field(default=False, alias="itemConsumed")
    consequence: dict[str, Any] = {}


class ResolutionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    action_id: str = Field(alias="actionId")
    room_id: str = Field(alias="roomId")
    character_id: str = Field(alias="characterId")
    mechanic: str = "dialogue"
    is_success: bool = Field(default=True, alias="isSuccess")
    metadata: dict[str, Any] = {}
    mutations: list[dict[str, Any]] = []
    reveal_steps: list[dict[str, Any]] = Field(default=[], alias="revealSteps")
    cascading_state_changes: list[str] = Field(default=[], alias="cascadingStateChanges")
    narrative: str = ""


class NarrativeProjection(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    narrative: str
    host_transaction: dict[str, Any] | None = Field(default=None, alias="hostTransaction")
    state_patch: dict[str, Any] | None = Field(default=None, alias="statePatch")
    public_observation: dict[str, Any] | None = Field(default=None, alias="publicObservation")


class CharacterCompatibilityReport(BaseModel):
    character_id: str
    scenario_id: str | None = None
    matched: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    score: float = 0.0


class PlayerOnboardingState(BaseModel):
    step: Literal['joined', 'named', 'imported', 'reviewed', 'ready'] = 'joined'
    player_name: str = ''
    has_character: bool = False
    has_reviewed_adaptation: bool = False
    is_ready: bool = False


# ── Map Models ──

class MapNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    node_id: str = Field(alias="nodeId")
    name: str
    description: str = ""
    npcs_present: list[str] = Field(default=[], alias="npcsPresent")
    clues_available: list[str] = Field(default=[], alias="cluesAvailable")
    position: dict[str, float] = Field(default={"x": 0.0, "y": 0.0})
    is_start: bool = Field(default=False, alias="isStart")


class MapEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_node: str = Field(alias="fromNode")
    to_node: str = Field(alias="toNode")
    is_one_way: bool = Field(default=False, alias="isOneWay")
    label: str = ""


class ScenarioMap(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    map_id: str = Field(alias="mapId")
    scenario_id: str = Field(alias="scenarioId")
    generated_by: str = Field(default="python", alias="generatedBy")
    status: Literal["draft", "confirmed"] = "draft"
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    created_at: str | None = Field(default=None, alias="createdAt")
    confirmed_at: str | None = Field(default=None, alias="confirmedAt")


class PlayerMapView(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    room_id: str = Field(alias="roomId")
    nodes: list[dict[str, Any]] = []
    current_node_id: str | None = Field(default=None, alias="currentNodeId")
    hidden_count: int = Field(default=0, alias="hiddenCount")
    map_status: str = "no_map"


class MapMoveIntent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    target_node_id: str = Field(alias="targetNodeId")
    from_node_id: str = Field(alias="fromNodeId")
    room_id: str = Field(alias="roomId")


class HostMapOperation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    operation: Literal["reveal", "hide", "force_move"] = Field(alias="operation")
    node_id: str | None = Field(default=None, alias="nodeId")
    character_id: str | None = Field(default=None, alias="characterId")


# ── Encounter Models ──

class EncounterParticipant(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    encounter_id: str = Field(alias="encounterId")
    character_id: str = Field(alias="characterId")
    side: Literal["player", "enemy", "neutral"] = "player"
    hp: int = 0
    hp_max: int = Field(default=0, alias="hpMax")
    san: int = 0
    san_max: int = Field(default=0, alias="sanMax")
    dex: int = 0
    mov: int = 7
    current_position: str = Field(default="", alias="currentPosition")
    distance_band: str = Field(default="medium", alias="distanceBand")
    status_tags: list[str] = Field(default=[], alias="statusTags")
    acted_this_round: bool = Field(default=False, alias="actedThisRound")
    weapon_name: str = Field(default="", alias="weaponName")
    damage_expression: str = Field(default="1d3", alias="damageExpression")
    main_skill: str = Field(default="", alias="mainSkill")
    notes: str = ""


class Encounter(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    encounter_id: str = Field(alias="encounterId")
    room_id: str = Field(alias="roomId")
    type: Literal["combat", "chase"] = "combat"
    status: Literal["suggested", "active", "resolved", "cancelled"] = "suggested"
    current_round: int = Field(default=0, alias="currentRound")
    summary: str = ""
    participants: list[EncounterParticipant] = []
    created_at: str | None = Field(default=None, alias="createdAt")
    resolved_at: str | None = Field(default=None, alias="resolvedAt")


class EncounterSuggestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    type: Literal["combat", "chase"] = "combat"
    reason: str = ""
    suggested_participants: list[dict[str, Any]] = Field(default=[], alias="suggestedParticipants")
    initial_distance: str = Field(default="medium", alias="initialDistance")


# ── SpoilerGuard Models ──

SpoilerCategory = Literal["truth", "ending", "hidden_clue", "hidden_npc", "hidden_asset"]
SpoilerAuditStatus = Literal["retry_ok", "blocked_fallback", "redacted_safety_net"]


class SpoilerSensitiveItem(BaseModel):
    """A single sensitive item extracted from knowledge_graph for spoiler checking."""
    model_config = ConfigDict(populate_by_name=True)
    item_id: str = Field(alias="itemId")
    scenario_id: str = Field(alias="scenarioId")
    category: SpoilerCategory
    label: str
    aliases: list[str] = []
    source_ref: str = Field(default="", alias="sourceRef")
    default_audience: Audience = Field(default="host", alias="defaultAudience")


class SpoilerReviewResult(BaseModel):
    """Result of a single spoiler review pass."""
    model_config = ConfigDict(populate_by_name=True)
    allowed: bool = True
    violations: list[dict[str, Any]] = []
    redacted_reason: str = Field(default="", alias="redactedReason")
    retry_prompt: str = Field(default="", alias="retryPrompt")
    safe_fallback_text: str = Field(default="", alias="safeFallbackText")


class SpoilerUnlockState(BaseModel):
    """What content has been unlocked through gameplay events for a given room."""
    model_config = ConfigDict(populate_by_name=True)
    room_id: str = Field(alias="roomId")
    discovered_clue_ids: list[str] = Field(default=[], alias="discoveredClueIds")
    revealed_npc_names: list[str] = Field(default=[], alias="revealedNpcNames")
    entered_scene_names: list[str] = Field(default=[], alias="enteredSceneNames")
    explored_node_ids: list[str] = Field(default=[], alias="exploredNodeIds")
    active_ending_phase: str = Field(default="", alias="activeEndingPhase")
    shared_clue_ids: list[str] = Field(default=[], alias="sharedClueIds")
    host_manual_reveals: list[str] = Field(default=[], alias="hostManualReveals")


class SpoilerAuditEntry(BaseModel):
    """Persistent log of a spoiler interception event."""
    model_config = ConfigDict(populate_by_name=True)
    audit_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12], alias="auditId")
    room_id: str = Field(alias="roomId")
    action_id: str = Field(default="", alias="actionId")
    original_text: str = Field(alias="originalText")
    violations: list[dict[str, Any]] = []
    retry_count: int = Field(default=0, alias="retryCount")
    final_status: SpoilerAuditStatus = Field(default="blocked_fallback", alias="finalStatus")
    final_text: str = Field(default="", alias="finalText")
    unlock_snapshot: dict[str, Any] = Field(default_factory=dict, alias="unlockSnapshot")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(), alias="createdAt")


# ── StateService Models ──

class CharacterMutationItem(BaseModel):
    """A set of mutations targeting a specific character."""
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    mutations: list[dict[str, Any]]
    permanent: bool = False


class SceneChange(BaseModel):
    """Changes to room scene state."""
    model_config = ConfigDict(populate_by_name=True)
    current_scene: str | None = Field(default=None, alias="currentScene")
    visited_scenes_add: list[str] | None = Field(default=None, alias="visitedScenesAdd")
    trigger_fired: str | None = Field(default=None, alias="triggerFired")
    public_facts_add: list[str] | None = Field(default=None, alias="publicFactsAdd")
    variable_set: dict[str, Any] | None = Field(default=None, alias="variableSet")
    bgm: str | None = None
    asset_url: str | None = Field(default=None, alias="assetUrl")


class MapChangeItem(BaseModel):
    """Changes to room map state."""
    model_config = ConfigDict(populate_by_name=True)
    node_explored: str | None = Field(default=None, alias="nodeExplored")
    node_hidden: str | None = Field(default=None, alias="nodeHidden")
    node_revealed: str | None = Field(default=None, alias="nodeRevealed")
    position_set: dict[str, str] | None = Field(default=None, alias="positionSet")


class ClueChangeItem(BaseModel):
    """Changes to clue state."""
    model_config = ConfigDict(populate_by_name=True)
    clue_id: str = Field(alias="clueId")
    discovered: bool | None = None
    shared: bool | None = None
    shared_by: str | None = Field(default=None, alias="sharedBy")


class StateChangeSet(BaseModel):
    """Unified state change payload for StateService.apply_change()."""
    model_config = ConfigDict(populate_by_name=True)
    character_mutations: list[CharacterMutationItem] = Field(default=[], alias="characterMutations")
    scene_changes: SceneChange | None = Field(default=None, alias="sceneChanges")
    map_changes: MapChangeItem | None = Field(default=None, alias="mapChanges")
    clue_changes: list[ClueChangeItem] | None = Field(default=None, alias="clueChanges")
    inventory_changes: list[dict[str, Any]] | None = Field(default=None, alias="inventoryChanges")
    encounter_changes: dict[str, Any] | None = Field(default=None, alias="encounterChanges")
    room_changes: dict[str, Any] | None = Field(default=None, alias="roomChanges")


class CharacterProfile(BaseModel):
    """Long-term character profile (cross-campaign)."""
    model_config = ConfigDict(populate_by_name=True)
    profile_id: str = Field(alias="profileId")
    account_id: str = Field(alias="accountId")
    name: str = ""
    occupation: str = ""
    attributes: dict[str, int] = {}
    skills: dict[str, int] = {}
    background: str = ""
    backstory: dict[str, Any] = {}
    permanent_injuries: list[dict[str, Any]] = Field(default=[], alias="permanentInjuries")
    permanent_insanities: list[dict[str, Any]] = Field(default=[], alias="permanentInsanities")
    experience_points: int = Field(default=0, alias="experiencePoints")
    inheritable_items: list[dict[str, Any]] = Field(default=[], alias="inheritableItems")
    version: int = 0


class CharacterRuntimeState(BaseModel):
    """Per-room mutable character state."""
    model_config = ConfigDict(populate_by_name=True)
    character_id: str = Field(alias="characterId")
    room_id: str = Field(alias="roomId")
    profile_id: str | None = Field(default=None, alias="profileId")
    hp: int = 0
    hp_max: int = Field(default=0, alias="hpMax")
    san: int = 0
    san_max: int = Field(default=0, alias="sanMax")
    mp: int = 0
    mp_max: int = Field(default=0, alias="mpMax")
    luck: int = 0
    status_tags: list[str] = Field(default=[], alias="statusTags")
    temp_modifiers: dict[str, Any] = Field(default={}, alias="tempModifiers")
    visibility: str = "visible"
    version: int = 0


class RoomSceneState(BaseModel):
    """Per-room scene tracking state."""
    model_config = ConfigDict(populate_by_name=True)
    room_id: str = Field(alias="roomId")
    current_scene: str = Field(default="", alias="currentScene")
    visited_scenes: list[str] = Field(default=[], alias="visitedScenes")
    triggered_triggers: list[str] = Field(default=[], alias="triggeredTriggers")
    public_facts: list[str] = Field(default=[], alias="publicFacts")
    scene_variables: dict[str, Any] = Field(default={}, alias="sceneVariables")
    current_bgm: str = Field(default="", alias="currentBgm")
    current_asset_url: str = Field(default="", alias="currentAssetUrl")
    version: int = 0
