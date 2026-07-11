from __future__ import annotations

from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class Channel(str, Enum):
    PARTY = "party"
    PRIVATE = "private"
    OOC = "ooc"


class DiscourseAct(str, Enum):
    ACTION = "action"
    PROPOSAL = "proposal"
    RULE_QUERY = "rule_query"
    PRIVATE_NOTE = "private_note"
    OOC = "ooc"
    CORRECTION = "correction"
    CANCEL = "cancel"


class Commitment(str, Enum):
    NONE = "none"
    HYPOTHETICAL = "hypothetical"
    PROPOSAL = "proposal"
    INTENDED = "intended"
    CONFIRMED_CANDIDATE = "confirmed_candidate"
    PREPARED = "prepared"


class FrameType(str, Enum):
    WAIT = "Wait"
    MOVE = "Move"
    OBSERVE = "Observe"
    SEARCH = "Search"
    TRANSFER_ITEM = "TransferItem"
    REQUEST_ACTION = "RequestAction"
    USE_ITEM = "UseItem"
    SPEAK = "Speak"
    CREATIVE_ACTION = "CreativeAction"


class EntityKind(str, Enum):
    CHARACTER = "character"
    NPC = "npc"
    ITEM = "item"
    LOCATION = "location"
    OBJECT = "object"


class VisibleEntity(BaseModel):
    """Only viewer-safe entities are allowed into semantic grounding."""

    entity_id: str
    kind: EntityKind
    label: str
    aliases: list[str] = Field(default_factory=list)
    pronouns: list[str] = Field(default_factory=list)

    @property
    def all_names(self) -> set[str]:
        return {self.label, *self.aliases}


class SemanticContextSchema(BaseModel):
    room_id: str
    viewer_character_id: str
    visible_entities: list[VisibleEntity]
    available_frames: list[FrameType] = Field(default_factory=lambda: list(FrameType))
    schema_version: str = "1.0.0"


class UtteranceEnvelope(BaseModel):
    utterance_id: str = Field(default_factory=lambda: f"utt_{uuid4().hex[:12]}")
    room_id: str
    speaker_character_id: str
    channel: Channel
    raw_text: str = Field(min_length=1, max_length=4000)
    language: str = "zh-CN"


class EntityMention(BaseModel):
    surface: str
    role: str
    expected_kinds: list[EntityKind]
    bound_entity_id: str | None = None
    candidate_entity_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ConditionCandidate(BaseModel):
    kind: Literal["entity_action", "entity_state", "time", "custom"]
    subject: EntityMention | None = None
    predicate: str
    value: str | None = None


class ConstraintCandidate(BaseModel):
    kind: Literal[
        "exclude_action",
        "exclude_interaction",
        "do_not_reveal",
        "resource_limit",
        "custom",
    ]
    target: EntityMention | None = None
    value: str | None = None


class SemanticStep(BaseModel):
    step_id: str = Field(default_factory=lambda: f"step_{uuid4().hex[:8]}")
    frame: FrameType
    actor_entity_id: str
    target: EntityMention | None = None
    destination: EntityMention | None = None
    item: EntityMention | None = None
    receiver: EntityMention | None = None
    condition: ConditionCandidate | None = None
    temporal_relation: str | None = None
    constraints: list[ConstraintCandidate] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SemanticCandidate(BaseModel):
    discourse_act: DiscourseAct
    commitment: Commitment
    macro_goal: str | None = None
    steps: list[SemanticStep] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    parser_confidence: float = Field(ge=0.0, le=1.0)


class Ambiguity(BaseModel):
    field_path: str
    surface: str
    candidate_entity_ids: list[str]
    question: str


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Handling(str, Enum):
    DISCUSSION_ONLY = "discussion_only"
    NEEDS_CLARIFICATION = "needs_clarification"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    SAFE_AUTO_EXECUTE = "safe_auto_execute"
    REJECTED = "rejected"


class SemanticRecord(BaseModel):
    semantic_record_id: str = Field(default_factory=lambda: f"sem_{uuid4().hex[:12]}")
    utterance: UtteranceEnvelope
    candidate: SemanticCandidate
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    risk_level: RiskLevel
    handling: Handling
    player_summary: str
    parser_version: str = "demo-parser-1.0.0"
    semantic_schema_version: str = "1.0.0"


class ClarificationAnswer(BaseModel):
    field_path: str
    selected_entity_id: str


class ConfirmSemanticRequest(BaseModel):
    record: SemanticRecord
    clarification_answers: list[ClarificationAnswer] = Field(default_factory=list)
    confirmed: bool = True


class ActionStep(BaseModel):
    frame: FrameType
    actor_entity_id: str
    target_entity_id: str | None = None
    destination_entity_id: str | None = None
    item_entity_id: str | None = None
    receiver_entity_id: str | None = None
    condition: dict[str, Any] | None = None
    temporal_relation: str | None = None
    constraints: list[dict[str, Any]] = Field(default_factory=list)


class ActionCommand(BaseModel):
    """Validated command for Transaction; it is not a RuleResult or State mutation."""

    action_id: str = Field(default_factory=lambda: f"act_{uuid4().hex[:12]}")
    idempotency_key: str
    room_id: str
    character_id: str
    source_utterance_id: str
    source_semantic_record_id: str
    action_type: Literal["semantic_action"] = "semantic_action"
    macro_goal: str | None = None
    steps: list[ActionStep]
    status: Literal["confirmed"] = "confirmed"

    @model_validator(mode="after")
    def require_steps(self) -> "ActionCommand":
        if not self.steps:
            raise ValueError("confirmed action must contain at least one step")
        return self


class CompileRequest(BaseModel):
    utterance: UtteranceEnvelope
    context: SemanticContextSchema


class CompileResponse(BaseModel):
    record: SemanticRecord
    action: ActionCommand | None = None
