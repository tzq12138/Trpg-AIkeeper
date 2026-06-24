import uuid
from datetime import datetime, timezone
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field

EngineEventType = Literal[
    "s2c_reveal_transaction", "s2c_resume_transaction", "s2c_cancel_transaction",
    "s2c_chat_stream", "s2c_atmosphere", "s2c_engine_state", "s2c_scene_sync",
    "s2c_host_snapshot", "s2c_full_snapshot", "s2c_state_patch",
    "s2c_private_notice", "s2c_public_observation", "s2c_tactical_prompt",
    "s2c_room_lobby_snapshot", "s2c_campaign_ended",
    "s2c_action_queued", "s2c_action_batched", "s2c_action_completed",
    "s2c_clarification_prompt", "s2c_clarification_result",
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
        "clarification_request",
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
