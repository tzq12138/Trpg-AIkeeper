"""AI Gateway contracts — KpResponse schema, permission matrix, and mutation validation.

All AI providers (DeepSeek, Hermes MCP, Local) must return data conforming to KpResponse.
The permission matrix enforces what AI can and cannot write directly.
"""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


# ══════════════════════════════════════════════
#  Response Models
# ══════════════════════════════════════════════

class NarrativePayload(BaseModel):
    """Structured narrative — public text + per-character private text."""
    model_config = ConfigDict(populate_by_name=True)
    public: str = ""
    per_character: dict[str, str | None] = Field(default={}, alias="perCharacter")


class KpRollRequest(BaseModel):
    """Roll request from KP — RuleExecutor picks up and executes."""
    model_config = ConfigDict(populate_by_name=True)
    id: str = ""
    skill_name: str = Field(default="", alias="skillName")
    difficulty: Literal["regular", "hard", "extreme"] = "regular"
    bonus_dice: int = Field(default=0, alias="bonusDice")
    reason: str = ""
    target_character: str | None = Field(default=None, alias="targetCharacter")
    visibility: Literal["public", "private"] = "public"


class KpStateMutation(BaseModel):
    """State change from KP — Engine validates and applies."""
    model_config = ConfigDict(populate_by_name=True)
    type: str
    permission: Literal["direct", "validate"] = "validate"
    target: str = ""
    payload: dict[str, Any] = {}


class KpTacticalPrompt(BaseModel):
    """Tactical action prompts for player UI."""
    model_config = ConfigDict(populate_by_name=True)
    text: str = ""
    actions: list[dict[str, Any]] = []


class KpCitation(BaseModel):
    """Source citation for knowledge queries."""
    model_config = ConfigDict(populate_by_name=True)
    source: str = ""
    text: str = ""


class KpResponse(BaseModel):
    """Unified KP response — all providers must return this shape."""
    model_config = ConfigDict(populate_by_name=True)
    narrative: NarrativePayload = Field(default_factory=NarrativePayload)
    roll_requests: list[KpRollRequest] = Field(default=[], alias="rollRequests")
    state_mutations: list[KpStateMutation] = Field(default=[], alias="stateMutations")
    tactical_prompts: list[KpTacticalPrompt] = Field(default=[], alias="tacticalPrompts")
    citations: list[KpCitation] = []
    keeper_notes: str = Field(default="", alias="keeperNotes")
    error: dict[str, Any] | None = Field(default=None, alias="error")


# ══════════════════════════════════════════════
#  Permission Matrix
# ══════════════════════════════════════════════

# Level 2 — direct write (no validation needed)
DIRECT_MUTATIONS: set[str] = {
    "narrative",
    "tactical_prompts",
    "scene_transition",
    "npc_reaction",
    "add_status_tag",
}

# Level 1 — validate then write
VALIDATE_MUTATIONS: set[str] = {
    "san_loss",
    "hp_loss",
    "mp_loss",
    "luck_change",
    "gain_clue",
    "gain_item",
    "move_location",
    "combat_suggestion",
}

# Blocked — never write
BLOCKED_MUTATIONS: set[str] = {
    "attribute_change",
    "skill_value_change",
    "credit_rating_change",
}


def get_mutation_level(mutation_type: str) -> str:
    """Return 'direct', 'validate', or 'block' for a given mutation type."""
    if mutation_type in DIRECT_MUTATIONS:
        return "direct"
    if mutation_type in VALIDATE_MUTATIONS:
        return "validate"
    return "block"


def validate_mutation(mutation: KpStateMutation) -> bool:
    """Check if a mutation passes basic structural validation.
    Does NOT apply business rules (dice rolling, dedup, range checks).
    Returns False for blocked types.
    """
    if mutation.type in BLOCKED_MUTATIONS:
        return False
    if mutation.permission == "direct" and mutation.type not in DIRECT_MUTATIONS:
        return False  # can't claim direct for validate-level operations
    if mutation.type in ("san_loss", "hp_loss", "mp_loss"):
        # Must have formula in payload
        if "formula" not in mutation.payload and "value" not in mutation.payload:
            return False
    if mutation.type in ("gain_clue",):
        if "text" not in mutation.payload:
            return False
    if mutation.type == "move_location":
        if "location" not in mutation.payload:
            return False
    if mutation.type == "gain_item":
        if "name" not in mutation.payload:
            return False
    return True


# ══════════════════════════════════════════════
#  Knowledge Query Models
# ══════════════════════════════════════════════

class KnowledgeAnswer(BaseModel):
    """Response from knowledge query (Host database Q&A)."""
    model_config = ConfigDict(populate_by_name=True)
    answer: str = ""
    citations: list[KpCitation] = []
    confidence: Literal["high", "medium", "low"] = "medium"
