from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException
from .models import ClarificationRequest, ClarificationResult

router = APIRouter(prefix="/api/player")

CLARIFICATION_WINDOW_MINUTES = 5
RATE_LIMIT_COOLDOWN_SECONDS = 60


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


@router.post("/clarification")
async def submit_clarification(request: Request):
    char = _get_character(request)
    conn = request.app.state.db
    body = await request.json()

    target_action_id = body.get("targetActionId")
    text = body.get("text", "")
    evidence = body.get("evidence")

    if not target_action_id or not text:
        raise HTTPException(400, "targetActionId and text are required")

    action = conn.execute(
        "SELECT * FROM actions WHERE action_id = %s AND room_id = %s",
        (target_action_id, char["room_id"]),
    ).fetchone()
    if not action:
        raise HTTPException(404, "Target action not found")

    now = datetime.now(timezone.utc)
    window_expires = now + timedelta(minutes=CLARIFICATION_WINDOW_MINUTES)

    recent = conn.execute(
        "SELECT * FROM clarifications WHERE character_id = %s AND room_id = %s "
        "ORDER BY created_at DESC LIMIT 1",
        (char["character_id"], char["room_id"]),
    ).fetchone()
    if recent:
        last_time = recent["created_at"] if isinstance(recent["created_at"], datetime) else datetime.fromisoformat(recent["created_at"])
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=timezone.utc)
        if (now - last_time).total_seconds() < RATE_LIMIT_COOLDOWN_SECONDS:
            raise HTTPException(429, "Rate limited. Please wait before submitting another clarification.")

    clarification = ClarificationRequest(
        room_id=char["room_id"],
        character_id=char["character_id"],
        target_action_id=target_action_id,
        text=text,
        evidence=evidence,
        window_expires_at=window_expires.isoformat(),
    )

    conn.execute(
        "INSERT INTO clarifications "
        "(clarification_id, room_id, character_id, target_action_id, text, evidence, "
        "status, window_expires_at, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            clarification.clarification_id, clarification.room_id, clarification.character_id,
            clarification.target_action_id, clarification.text, clarification.evidence,
            clarification.status, clarification.window_expires_at, clarification.created_at,
        ),
    )
    conn.commit()

    return {"clarification_id": clarification.clarification_id, "status": "pending"}


@router.get("/clarification/{clarification_id}")
async def get_clarification(request: Request, clarification_id: str):
    char = _get_character(request)
    conn = request.app.state.db

    row = conn.execute(
        "SELECT * FROM clarifications WHERE clarification_id = %s AND room_id = %s",
        (clarification_id, char["room_id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Clarification not found")

    result = None
    if row["result"]:
        import json
        result = row["result"] if isinstance(row["result"], (dict, list)) else json.loads(row["result"])

    return {
        "clarification_id": row["clarification_id"],
        "target_action_id": row["target_action_id"],
        "text": row["text"],
        "evidence": row["evidence"],
        "status": row["status"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "result": result,
    }
