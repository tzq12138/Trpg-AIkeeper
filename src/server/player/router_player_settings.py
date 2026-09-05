from fastapi import APIRouter, Request
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, model_validator
from .auth import require_player_character


router = APIRouter(prefix="/api/player")


class PlayerSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_analysis_enabled: StrictBool | None = None
    absent_policy: Literal["idle", "maintain_existing"] | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one player setting is required")
        if (
            "draft_analysis_enabled" in self.model_fields_set
            and self.draft_analysis_enabled is None
        ):
            raise ValueError("draft_analysis_enabled must be a boolean")
        if "absent_policy" in self.model_fields_set and self.absent_policy is None:
            raise ValueError("absent_policy must be idle or maintain_existing")
        return self


def _require_character(request: Request) -> dict:
    return require_player_character(request)


def get_effective_draft_analysis_enabled(conn, character: dict) -> bool:
    row = conn.execute(
        "SELECT COALESCE(settings.draft_analysis_enabled, rooms.draft_analysis_enabled) "
        "AS draft_analysis_enabled FROM rooms "
        "LEFT JOIN room_player_settings AS settings "
        "ON settings.room_id = rooms.room_id AND settings.character_id = %s "
        "WHERE rooms.room_id = %s",
        (character["character_id"], character["room_id"]),
    ).fetchone()
    return bool(row["draft_analysis_enabled"])


def get_absent_policy(conn, character: dict) -> str:
    row = conn.execute(
        "SELECT absent_policy FROM room_player_settings "
        "WHERE room_id = %s AND character_id = %s",
        (character["room_id"], character["character_id"]),
    ).fetchone()
    return str(row["absent_policy"]) if row else "idle"


def get_speech_routing(conn, character: dict) -> str:
    row = conn.execute(
        "SELECT speech_routing FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    routing = str(row["speech_routing"]) if row else "party_message"
    return routing if routing in {"party_message", "npc_dialogue"} else "party_message"


def _settings_response(conn, character: dict) -> dict:
    return {
        "room_id": character["room_id"],
        "character_id": character["character_id"],
        "draft_analysis_enabled": get_effective_draft_analysis_enabled(
            conn, character
        ),
        "absent_policy": get_absent_policy(conn, character),
        "speech_routing": get_speech_routing(conn, character),
    }


@router.get("/settings")
async def get_player_settings(request: Request):
    character = _require_character(request)
    return _settings_response(request.app.state.db, character)


@router.patch("/settings")
async def update_player_settings(request: Request, body: PlayerSettingsUpdate):
    character = _require_character(request)
    conn = request.app.state.db
    draft_analysis_enabled = (
        body.draft_analysis_enabled
        if "draft_analysis_enabled" in body.model_fields_set
        else get_effective_draft_analysis_enabled(conn, character)
    )
    absent_policy = (
        body.absent_policy
        if "absent_policy" in body.model_fields_set
        else get_absent_policy(conn, character)
    )
    conn.execute(
        "INSERT INTO room_player_settings "
        "(room_id, character_id, draft_analysis_enabled, absent_policy) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (room_id, character_id) DO UPDATE SET "
        "draft_analysis_enabled = EXCLUDED.draft_analysis_enabled, "
        "absent_policy = EXCLUDED.absent_policy, updated_at = NOW()",
        (
            character["room_id"],
            character["character_id"],
            draft_analysis_enabled,
            absent_policy,
        ),
    )
    # Append-only absent-policy history: every later effective change is
    # independently versioned and traceable on top of the frozen initial value
    # (AIO-SZ-005). The freeze snapshot itself is written when the room starts.
    if "absent_policy" in body.model_fields_set:
        latest = conn.execute(
            "SELECT COALESCE(MAX(snapshot_version), 0) AS version "
            "FROM absent_policy_snapshots "
            "WHERE room_id = %s AND character_id = %s",
            (character["room_id"], character["character_id"]),
        ).fetchone()
        version = int(latest["version"] or 0) + 1
        conn.execute(
            "INSERT INTO absent_policy_snapshots "
            "(snapshot_id, room_id, character_id, absent_policy, snapshot_version, reason) "
            "VALUES (%s, %s, %s, %s, %s, 'player_settings_change')",
            (
                f"snap-{character['room_id']}-{character['character_id']}-{version}",
                character["room_id"],
                character["character_id"],
                absent_policy,
                version,
            ),
        )
    conn.commit()
    return _settings_response(conn, character)
