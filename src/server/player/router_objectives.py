import uuid

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/player")


class PersonalObjectiveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)


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


@router.post("/objectives", status_code=201)
async def create_personal_objective(request: Request, body: PersonalObjectiveCreate):
    char = _get_character(request)
    conn = request.app.state.db
    objective_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO objectives (objective_id, room_id, character_id, text, type) "
        "VALUES (%s, %s, %s, %s, 'personal')",
        (objective_id, char["room_id"], char["character_id"], body.text.strip()),
    )
    conn.commit()
    objective = conn.execute(
        "SELECT objective_id, text, type, status, assigned_at FROM objectives WHERE objective_id = %s",
        (objective_id,),
    ).fetchone()
    return dict(objective)


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
