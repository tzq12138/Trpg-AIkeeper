from fastapi import APIRouter, Request, HTTPException

router = APIRouter(prefix="/api/player")


def _get_character(request: Request):
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    conn = request.app.state.db
    char = conn.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not char:
        raise HTTPException(403, "Invalid token")
    return char


@router.get("/objectives")
async def list_objectives(request: Request):
    char = _get_character(request)
    conn = request.app.state.db

    team_rows = conn.execute(
        "SELECT * FROM objectives WHERE room_id = %s AND type = 'team'",
        (char["room_id"],),
    ).fetchall()

    personal_rows = conn.execute(
        "SELECT * FROM objectives WHERE room_id = %s AND type = 'personal' AND character_id = %s",
        (char["room_id"], char["character_id"]),
    ).fetchall()

    objectives = []
    for row in team_rows:
        objectives.append({
            "objective_id": row["objective_id"],
            "text": row["text"],
            "type": row["type"],
            "status": row["status"],
            "assigned_at": row["assigned_at"],
        })
    for row in personal_rows:
        objectives.append({
            "objective_id": row["objective_id"],
            "text": row["text"],
            "type": row["type"],
            "status": row["status"],
            "assigned_at": row["assigned_at"],
        })

    return {"objectives": objectives}
