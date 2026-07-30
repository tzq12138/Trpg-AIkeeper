import uuid
from datetime import datetime, timezone
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Event type literals — canonical registry is at .events.events_registry.ALL_EVENTS
EngineEventType = Literal[
    "s2c_reveal_transaction", "s2c_resume_transaction", "s2c_cancel_transaction",
    "s2c_chat_stream", "s2c_atmosphere", "s2c_engine_state", "s2c_scene_sync",
    "s2c_host_snapshot", "s2c_full_snapshot", "s2c_state_patch",
    "s2c_private_notice", "s2c_public_observation", "s2c_tactical_prompt",
    "s2c_room_lobby_snapshot", "s2c_campaign_ended",
    "s2c_action_queued", "s2c_action_batched", "s2c_action_completed", "s2c_action_deferred",
    "s2c_action_review_requested", "s2c_action_review_resolved",
    "s2c_action_exception_requested",
    "s2c_action_choice_requested",
    "s2c_safety_request", "s2c_safety_state_changed",
    "s2c_clarification_prompt", "s2c_clarification_result",
    "s2c_ready_toggled",
    "s2c_map_updated", "s2c_player_moved", "s2c_map_revealed",
    "s2c_encounter_suggested", "s2c_encounter_started",
    "s2c_encounter_updated", "s2c_encounter_resolved",
    "s2c_solo_combat_reaction_requested",
    "s2c_team_message",
    "s2c_turn_resolved",
    "s2c_combat_round_locked",
    "s2c_clue_discovered", "s2c_clue_shared",
    "s2c_checkpoint_created", "s2c_checkpoint_restored",
    "s2c_private_note_emergency_access",
    "s2c_ai_stage_changed", "s2c_player_clarification_required",
    "s2c_director_plan_validated", "s2c_narration_completed", "s2c_ai_recovery_required",
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
        "combat_action", "chase_action", "prepared_action", "system_skip",
    ]
    declared_intent: str = ""
    base_state_version: int = 0
    params: dict[str, Any] = {}


class InventoryTransferCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    to_character_id: str = Field(alias="toCharacterId", min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=999)


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


PlayerInputMode = Literal[
    "action", "speech", "party_chat", "ooc", "rule_question", "private_note",
    "clue_share", "item_action", "map_move", "combat_action", "safety",
]


class PlayerActionSubmissionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="actionId", min_length=1, max_length=128)
    raw_text: str = Field(alias="rawText", min_length=1, max_length=2000)
    input_mode: PlayerInputMode = Field(default="action", alias="inputMode")
    client_sequence: int | None = Field(default=None, alias="clientSequence", ge=0)
    base_state_version: int = Field(default=0, alias="baseStateVersion", ge=0)
    requested_visibility: Literal["public", "party", "private"] | None = Field(
        default=None,
        alias="requestedVisibility",
    )


class PlayerActionSubmissionReceipt(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    action_id: str = Field(alias="actionId")
    input_mode: PlayerInputMode = Field(alias="inputMode")
    status: Literal[
        "received",
        "recorded",
        "analyzing",
        "awaiting_confirmation",
        "safety_paused",
        "safety_resumed",
    ]
    requires_analysis: bool = Field(alias="requiresAnalysis")
    received_at: str = Field(alias="receivedAt")


class ActionDraftAnalyzeRequest(BaseModel):
    declared_intent: str = Field(min_length=1, max_length=2000)
    intent_type: str | None = None
    base_state_version: int = 0
    params: dict[str, Any] = Field(default_factory=dict)
    ephemeral: bool = False
    submission_action_id: str | None = None


class RedactedCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = "已校验依据"
    page: int | None = None
    scene: str | None = None
    verified: bool = True


def _redact_citation(value: Any) -> dict[str, Any]:
    if isinstance(value, RedactedCitation):
        return value.model_dump()
    if not isinstance(value, dict):
        return {"label": "已校验依据"}
    label = value.get("label") or value.get("citation_label") or value.get("source") or value.get("source_part_id")
    page = value.get("page", value.get("page_number"))
    scene = value.get("scene") or value.get("location")
    redacted: dict[str, Any] = {"label": str(label or "已校验依据")}
    if isinstance(page, int):
        redacted["page"] = page
    if isinstance(scene, str) and scene:
        redacted["scene"] = scene
    redacted["verified"] = bool(value.get("verified", True))
    return redacted


def redact_citation(value: Any) -> dict[str, Any]:
    return _redact_citation(value)


def _redact_citations(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [_redact_citation(value) for value in values]


AiStageName = Literal[
    "retrieving",
    "directing",
    "validating_rules",
    "narrating",
    "recovering",
    "completed",
]


class AiStageProgress(BaseModel):
    stage: AiStageName
    status: Literal["idle", "active", "completed", "failed"] = "active"
    label: str | None = None
    detail: str | None = None
    updated_at: str | None = None


class SemanticMapProjectionDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    room_id: str = Field(alias="roomId")
    map_status: str = Field(default="active", alias="mapStatus")
    map_type: Literal["graph", "image", "hybrid", "text"] = Field(default="graph", alias="mapType")
    base_asset: dict[str, Any] = Field(default_factory=dict, alias="baseAsset")
    known_locations: list[dict[str, Any]] = Field(default_factory=list, alias="knownLocations")
    known_connections: list[dict[str, Any]] = Field(default_factory=list, alias="knownConnections")
    party_position: dict[str, Any] | None = Field(default=None, alias="partyPosition")
    fog_of_war: list[dict[str, Any]] = Field(default_factory=list, alias="fogOfWar")
    text_scene: dict[str, Any] | None = Field(default=None, alias="textScene")


class HostDirectorSnapshotDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    current_scene: str = Field(default="", alias="currentScene")
    confirmed_facts: list[str] = Field(default_factory=list, alias="confirmedFacts")
    pending_triggers: list[str] = Field(default_factory=list, alias="pendingTriggers")
    ai_evidence: list[RedactedCitation] = Field(default_factory=list, alias="aiEvidence")
    stage: AiStageName = "completed"
    risks: list[str] = Field(default_factory=list)
    exception_queue: list[str] = Field(default_factory=list, alias="exceptionQueue")


class IntentContractDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str | None = Field(default=None, max_length=200)
    method: str | None = Field(default=None, max_length=200)
    object: str | None = Field(default=None, max_length=200)
    constraints: list[str] = Field(default_factory=list, max_length=8)
    resources: list[str] = Field(default_factory=list, max_length=8)
    conditions: list[str] = Field(default_factory=list, max_length=8)
    visibility: Literal["public", "party", "private"] = "public"
    ambiguities: list[str] = Field(default_factory=list, max_length=8)


class ActionDraftDTO(BaseModel):
    draft_id: str | None = None
    revision: int = 1
    base_state_version: int = 0
    status: Literal["analyzing", "awaiting_confirmation"] = "awaiting_confirmation"
    intent_type: str
    declared_intent: str
    params: dict[str, Any] = Field(default_factory=dict)
    understanding_summary: str
    risk: Literal["low", "medium", "high"]
    intent_contract: IntentContractDTO = Field(default_factory=IntentContractDTO)
    suggested_skill: str | None = None
    alternative_skills: list[str] = Field(default_factory=list)
    composite_steps: list["ActionDraftStepDTO"] = Field(default_factory=list)
    difficulty: str | None = None
    resource_impacts: list[dict[str, Any]] = Field(default_factory=list)
    visibility: Literal["public", "party", "private"] = "public"
    movement_target: str | None = None
    confirmation_requirements: list[str] = Field(default_factory=list)
    requires_confirmation: bool = False
    confidence: float = 0.0
    citations: list[RedactedCitation] = Field(default_factory=list)
    analysis_source: Literal["configured_provider", "fallback_provider", "local_fallback"]
    resolution_route: Literal["ai", "local", "host_exception"] = "local"
    ephemeral: bool = False
    context_version: int = 0
    candidate_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    semantic_progression: dict[str, Any] = Field(default_factory=dict)
    adjudication_stage: str = "local_analysis"
    npc_reactions: list[dict[str, Any]] = Field(default_factory=list)
    time_impact: dict[str, Any] = Field(default_factory=dict)

    @field_validator("citations", mode="before")
    @classmethod
    def _citations_are_redacted(cls, values):
        return _redact_citations(values)


class DirectorCitationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str | None = None
    source_part_id: str | None = None
    content_item_id: str | None = None
    page_number: int | None = None
    location: str | None = None


_DIRECTOR_NESTED_DENIED_KEYS = {
    "absolutepath",
    "accountid",
    "actionid",
    "apikey",
    "authorization",
    "characterid",
    "fulltext",
    "ownertoken",
    "passwordhash",
    "playerid",
    "playername",
    "playertoken",
    "rawboundarytext",
    "rawsafetytext",
    "roomid",
    "safetyreason",
    "scenarioversionid",
    "sourcepartid",
    "storagepath",
}


def _validate_director_nested_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        raise ValueError("director nested payload exceeds maximum depth")
    if isinstance(value, dict):
        if len(value) > 40:
            raise ValueError("director nested object is too large")
        result = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if len(key) > 80:
                raise ValueError("director nested key is too long")
            normalized = "".join(
                character
                for character in key.lower()
                if character.isalnum()
            )
            if (
                normalized in _DIRECTOR_NESTED_DENIED_KEYS
                or normalized.endswith("token")
                or normalized.endswith("secret")
                or normalized.endswith("ciphertext")
            ):
                raise ValueError("director nested payload contains sensitive key")
            result[key] = _validate_director_nested_value(
                item,
                depth=depth + 1,
            )
        return result
    if isinstance(value, list):
        if len(value) > 40:
            raise ValueError("director nested list is too large")
        return [
            _validate_director_nested_value(item, depth=depth + 1)
            for item in value
        ]
    if isinstance(value, str):
        if len(value) > 4000:
            raise ValueError("director nested string is too long")
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("director nested payload must be JSON-compatible")


class DirectorBasisRefDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    citation: DirectorCitationDTO | None = None


class DirectorPreconditionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["room_status", "state_version", "position", "resource", "visibility", "permission"]
    expected: Any = None
    path: str | None = None
    scope: str | None = None

    @field_validator("expected")
    @classmethod
    def _expected_is_safe_json(cls, value):
        return _validate_director_nested_value(value)


class DirectorPermissionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str
    allowed: bool
    reason: str | None = None


class DirectorMechanicPlanDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    mechanic: str = "dialogue"
    skill_name: str | None = Field(default=None, alias="skillName")
    difficulty: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def _parameters_are_safe_json(cls, value):
        return _validate_director_nested_value(value)


class DirectorStatePatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["add", "replace", "remove", "test"]
    path: str = Field(min_length=1)
    value: Any = None

    @field_validator("value")
    @classmethod
    def _value_is_safe_json(cls, value):
        return _validate_director_nested_value(value)


class DirectorEventPlanDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: EngineEventType
    audience: Audience | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _payload_is_safe_json(cls, value):
        return _validate_director_nested_value(value)


class DirectorSemanticProgressionDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    target_node_id: str | None = Field(default=None, alias="targetNodeId")
    from_node_id: str | None = Field(default=None, alias="fromNodeId")
    citation: DirectorCitationDTO | None = None
    rationale: str | None = None


class DirectorActionStepDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=500)
    declared_intent: str = Field(min_length=1, max_length=2000)
    intent_type: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    execution_condition: Literal[
        "always", "previous_step_success", "previous_step_failure"
    ] = "previous_step_success"
    on_previous_failure: Literal["cancel", "continue"] = "cancel"

    @field_validator("params")
    @classmethod
    def _params_are_safe_json(cls, value):
        return _validate_director_nested_value(value)


class DirectorPlanDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    context_version: int = 0
    actor_display_name: str = ""
    declared_intent: str = ""
    interpreted_intent: str = ""
    intent_type: str = "dialogue"
    intent_contract: IntentContractDTO = Field(default_factory=IntentContractDTO)
    preconditions: list[DirectorPreconditionDTO] = Field(default_factory=list)
    permissions: list[DirectorPermissionDTO] = Field(default_factory=list)
    mechanic_plan: DirectorMechanicPlanDTO = Field(default_factory=DirectorMechanicPlanDTO)
    state_patch: list[DirectorStatePatchDTO] = Field(default_factory=list)
    event_plan: list[DirectorEventPlanDTO] = Field(default_factory=list)
    semantic_progression: DirectorSemanticProgressionDTO = Field(default_factory=DirectorSemanticProgressionDTO)
    action_steps: list[DirectorActionStepDTO] = Field(default_factory=list, max_length=2)
    npc_reactions: list[dict[str, Any]] = Field(default_factory=list)
    time_impact: dict[str, Any] = Field(default_factory=dict)
    visibility: Literal["public", "party", "private"] = "public"
    basis_refs: list[DirectorBasisRefDTO] = Field(default_factory=list)
    citations: list[DirectorCitationDTO] = Field(default_factory=list)
    confidence: float = 0.0
    requires_player_clarification: bool = False
    clarification_options: list[dict[str, Any]] = Field(default_factory=list)
    requires_host_exception: bool = False
    exception_reason: str | None = None
    narration_mode: str = "summarize"
    analysis_source: Literal["configured_provider", "fallback_provider", "local_fallback"] = "fallback_provider"

    @field_validator(
        "npc_reactions",
        "time_impact",
        "clarification_options",
    )
    @classmethod
    def _nested_output_is_safe_json(cls, value):
        return _validate_director_nested_value(value)


class NarrationResultDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    context_version: int
    director_plan_digest: str
    narrative_text: str = Field(min_length=1)
    environment_changes: list[str] = Field(min_length=1)
    interactable_objects: list[str] = Field(min_length=1)
    open_question: str = Field(min_length=1)
    fact_refs: dict[str, list[str]]
    redacted_citations: list[RedactedCitation] = Field(default_factory=list)
    style_pack_version: str
    provider_source: Literal["configured_provider", "fallback_provider", "local_fallback"]
    status: Literal["completed", "invalid_response"] = "completed"

    @field_validator("redacted_citations", mode="before")
    @classmethod
    def _narration_citations_are_redacted(cls, values):
        return _redact_citations(values)

    @model_validator(mode="after")
    def _requires_visible_fact_refs(self):
        required = {
            "narrative_text",
            "environment_changes",
            "interactable_objects",
            "open_question",
        }
        if set(self.fact_refs) != required:
            raise ValueError("fact_refs must cover all player-visible fields")
        for key in required:
            refs = self.fact_refs.get(key)
            if not isinstance(refs, list) or not refs or any(not str(item).strip() for item in refs):
                raise ValueError("fact_refs values must be non-empty string lists")
        return self


class ActionDraftUpdateRequest(BaseModel):
    declared_intent: str = Field(min_length=1, max_length=2000)
    intent_type: str | None = None
    base_state_version: int = 0
    params: dict[str, Any] | None = None


class ActionDraftConfirmRequest(BaseModel):
    confirmations: list[str] = Field(default_factory=list)
    selected_skill: str | None = Field(default=None, max_length=100)
    composite_step_order: list[str] = Field(default_factory=list, max_length=2)


class CollaborationContractCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    shared_intent: str = Field(alias="sharedIntent", min_length=1, max_length=1000)
    invitee_character_ids: list[str] = Field(alias="inviteeCharacterIds", min_length=1, max_length=3)
    expires_in_seconds: int = Field(default=120, alias="expiresInSeconds", ge=30, le=600)


class CollaborationContractResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accept", "decline"]


class CollaborationLinkedDraftDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    character_id: str = Field(alias="characterId")
    draft_id: str = Field(alias="draftId")
    status: str


class CollaborationContractDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    contract_id: str = Field(alias="contractId")
    room_id: str = Field(alias="roomId")
    initiator_character_id: str = Field(alias="initiatorCharacterId")
    shared_intent: str = Field(alias="sharedIntent")
    status: Literal["pending", "accepted", "completed", "canceled", "expired"]
    participant_character_ids: list[str] = Field(default_factory=list, alias="participantCharacterIds")
    pending_character_ids: list[str] = Field(default_factory=list, alias="pendingCharacterIds")
    linked_drafts: list[CollaborationLinkedDraftDTO] = Field(default_factory=list, alias="linkedDrafts")
    expires_at: datetime = Field(alias="expiresAt")


class CompositeActionChoiceRequest(BaseModel):
    proceed: bool


class ActionDraftStepDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=500)
    declared_intent: str = Field(min_length=1, max_length=2000)
    intent_type: str = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)
    execution_condition: Literal["always", "previous_step_success", "previous_step_failure"] = "previous_step_success"
    on_previous_failure: Literal["cancel", "continue"] = "cancel"


class ActionStatusEventDTO(BaseModel):
    status: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionReceiptV2(BaseModel):
    action_id: str
    transaction_id: str | None = None
    state_version: int | None = None
    draft_id: str | None = None
    status: str
    declared_intent: str = ""
    revision: int = 1
    result: Any = None
    timeline: list[ActionStatusEventDTO] = Field(default_factory=list)
    can_cancel: bool = False
    can_review: bool = False
    rule_explanation: dict[str, Any] | None = None


class RuleExplanationDTO(BaseModel):
    authoritative_inputs: dict[str, Any] = Field(default_factory=dict)
    modifiers: dict[str, Any] = Field(default_factory=dict)
    hidden_sources: list[dict[str, Any]] = Field(default_factory=list)
    formula: str = ""
    state_before: dict[str, Any] = Field(default_factory=dict)
    state_after: dict[str, Any] = Field(default_factory=dict)
    rule_set_version: str
    citations: list[RedactedCitation] = Field(default_factory=list)
    verification_receipt: dict[str, Any] | None = None

    @field_validator("citations", mode="before")
    @classmethod
    def _rule_citations_are_redacted(cls, values):
        return _redact_citations(values)


class PlayerDeviceSessionDTO(BaseModel):
    device_session_id: str | None = None
    device_id: str
    status: Literal["active", "revoked", "expired"]
    controller: bool
    last_seen_at: str | None = None
    expires_at: str | None = None


class CampaignSessionDTO(BaseModel):
    campaign_session_id: str
    status: Literal["active", "ended", "scheduled"]
    started_by_character_id: str | None = None
    started_at: str
    last_activity_at: str
    scheduled_for: str | None = None
    ended_at: str | None = None
    attendance_status: Literal["attending", "tentative", "absent"] | None = None


class EvidenceCardDTO(BaseModel):
    evidence_card_id: str
    title: str
    body: str
    card_type: Literal["clue", "person", "location", "item", "question"]
    fact_status: Literal["hypothesis", "confirmed", "excluded"]
    visibility: Literal["party", "private"]
    source: Literal["player", "host", "system"]
    confirmed_by: str | None = None
    created_by_character_id: str | None = None
    version: int = 1
    question_status: Literal["investigating", "explained", "closed"] | None = None
    question_closed_by_character_id: str | None = None
    question_closed_at: str | None = None
    question_undo_until: str | None = None
    hypothesis_status: Literal["discussing", "disproved", "shelved"] | None = None
    hypothesis_status_changed_by_character_id: str | None = None
    hypothesis_status_changed_at: str | None = None
    hypothesis_status_undo_until: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class EvidenceDetailKnownItemDTO(BaseModel):
    evidence_card_id: str
    title: str
    body: str
    cognitive_tag: Literal["亲眼观察", "NPC 证词", "玩家推测", "存在争议", "已确认", "已证伪"]


class EvidenceDetailNoteDTO(BaseModel):
    note_id: str
    title: str
    body: str


class EvidenceDetailDTO(BaseModel):
    summary: EvidenceCardDTO
    current_known: list[EvidenceDetailKnownItemDTO] = Field(default_factory=list)
    related_materials: list[EvidenceDetailKnownItemDTO] = Field(default_factory=list)
    player_notes: list[EvidenceDetailNoteDTO] = Field(default_factory=list)


class CampaignCurrentSceneDTO(BaseModel):
    title: str
    text_preview: str
    citation: RedactedCitation = Field(default_factory=RedactedCitation)
    choice_count: int = Field(default=0, ge=0)
    image_asset_id: str | None = None


class CampaignQuestionDTO(BaseModel):
    evidence_card_id: str
    title: str
    fact_status: Literal["hypothesis", "confirmed", "excluded"]


class CampaignRecentClueDTO(BaseModel):
    clue_id: str
    text: str
    discovered_at: str
    is_owner: bool
    is_shared: bool


class CampaignHomeDTO(BaseModel):
    room_id: str
    current_scene: CampaignCurrentSceneDTO | None = None
    session: CampaignSessionDTO | None = None
    team_objectives: list[dict[str, Any]] = Field(default_factory=list)
    personal_objectives: list[dict[str, Any]] = Field(default_factory=list)
    last_summary: dict[str, Any] | None = None
    next_session: CampaignSessionDTO | None = None
    recent_clues: list[CampaignRecentClueDTO] = Field(default_factory=list)
    unresolved_questions: list[CampaignQuestionDTO] = Field(default_factory=list)


class ActionHintsDTO(BaseModel):
    hints: list[str] = Field(default_factory=list)


class TransactionStep(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="stepId")
    kind: Literal["roll", "status_delta", "scene_transition", "narrative_text"]
    payload: dict[str, Any] = {}
    timeout_ms: int = Field(default=15000, alias="timeoutMs")


class RevealTransaction(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    transaction_id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="transactionId")
    action_id: str | None = Field(default=None, alias="actionId")
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
    team_objectives: list[str] = Field(default_factory=list, alias="teamObjectives")
    scene_time: str = Field(default="时间未定", alias="sceneTime")


class HostPublicSceneTimeUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    scene_time: str = Field(alias="sceneTime", min_length=1, max_length=120)

    @field_validator("scene_time")
    @classmethod
    def _scene_time_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("sceneTime 不能为空")
        return value


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
    branches: list[dict[str, Any]] = []
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
        "skill_check", "sanity_check", "sanity_advance", "combat_damage", "luck_check",
        "opposed_check", "healing", "status_change",
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
    unlock_clue_ids: list[str] = Field(default=[], alias="unlockClueIds")


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
    revealed_npc_ids: list[str] = Field(default=[], alias="revealedNpcIds")
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
