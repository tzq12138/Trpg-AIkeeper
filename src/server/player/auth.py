from collections.abc import Collection

from fastapi import HTTPException, Request

from ..rule_source_lifecycle import RuleSourceRetiredError, ensure_room_rule_source_available


_REVOKED_PLAYER_STATUSES = {"left", "protected_inactive", "restricted_npc"}


def find_player_character(
    conn,
    token: str,
    *,
    allowed_statuses: Collection[str] | None = None,
) -> dict | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s",
        (token,),
    ).fetchone()
    if not row:
        return None
    character = dict(row)
    status = str(character.get("status") or "")
    if status in _REVOKED_PLAYER_STATUSES:
        return None
    if allowed_statuses is not None and status not in allowed_statuses:
        return None
    ensure_room_rule_source_available(conn, str(character.get("room_id") or ""))
    return character


def require_player_character(
    request: Request,
    *,
    allowed_statuses: Collection[str] | None = None,
) -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    try:
        character = find_player_character(
            request.app.state.db,
            token,
            allowed_statuses=allowed_statuses,
        )
    except RuleSourceRetiredError as exc:
        raise HTTPException(409, detail=exc.detail) from exc
    if not character:
        raise HTTPException(403, "Invalid token")
    return character
