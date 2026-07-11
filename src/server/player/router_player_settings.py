from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool


router = APIRouter(prefix="/api/player")


class PlayerSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_analysis_enabled: StrictBool


def _require_character(request: Request) -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    character = request.app.state.db.execute(
        "SELECT character_id, room_id FROM characters WHERE player_token = %s",
        (token,),
    ).fetchone()
    if not character:
        raise HTTPException(403, "Invalid token")
    return dict(character)


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


def _settings_response(conn, character: dict) -> dict:
    return {
        "room_id": character["room_id"],
        "character_id": character["character_id"],
        "draft_analysis_enabled": get_effective_draft_analysis_enabled(
            conn, character
        ),
    }


@router.get("/settings")
async def get_player_settings(request: Request):
    character = _require_character(request)
    return _settings_response(request.app.state.db, character)


@router.patch("/settings")
async def update_player_settings(request: Request, body: PlayerSettingsUpdate):
    character = _require_character(request)
    conn = request.app.state.db
    conn.execute(
        "INSERT INTO room_player_settings "
        "(room_id, character_id, draft_analysis_enabled) VALUES (%s, %s, %s) "
        "ON CONFLICT (room_id, character_id) DO UPDATE SET "
        "draft_analysis_enabled = EXCLUDED.draft_analysis_enabled, updated_at = NOW()",
        (
            character["room_id"],
            character["character_id"],
            body.draft_analysis_enabled,
        ),
    )
    conn.commit()
    return _settings_response(conn, character)
