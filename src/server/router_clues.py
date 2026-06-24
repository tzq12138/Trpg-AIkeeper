from fastapi import APIRouter, Request, HTTPException
from .models import Clue, ClueShare

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


@router.get("/clues")
async def list_clues(request: Request):
    char = _get_character(request)
    conn = request.app.state.db

    private_rows = conn.execute(
        "SELECT c.*, STRING_AGG(cs.shared_by, ',') as shared_by_list FROM clues c "
        "LEFT JOIN clue_shares cs ON c.clue_id = cs.clue_id "
        "WHERE c.room_id = %s AND c.character_id = %s "
        "GROUP BY c.clue_id",
        (char["room_id"], char["character_id"]),
    ).fetchall()

    shared_rows = conn.execute(
        "SELECT c.*, cs.public_version, cs.shared_by, cs.shared_at "
        "FROM clue_shares cs JOIN clues c ON cs.clue_id = c.clue_id "
        "WHERE c.room_id = %s AND c.character_id != %s",
        (char["room_id"], char["character_id"]),
    ).fetchall()

    clues = []
    for row in private_rows:
        clue = {
            "clue_id": row["clue_id"],
            "text": row["text"],
            "source": row["source"],
            "is_private": bool(row["is_private"]),
            "discovered_at": row["discovered_at"],
            "is_owner": True,
        }
        clues.append(clue)

    for row in shared_rows:
        clue = {
            "clue_id": row["clue_id"],
            "text": row["public_version"],
            "source": row["source"],
            "is_private": False,
            "discovered_at": row["discovered_at"],
            "shared_by": row["shared_by"],
            "shared_at": row["shared_at"],
            "is_owner": False,
        }
        clues.append(clue)

    return {"clues": clues}


@router.post("/clues/{clue_id}/share")
async def share_clue(request: Request, clue_id: str):
    char = _get_character(request)
    conn = request.app.state.db

    clue = conn.execute(
        "SELECT * FROM clues WHERE clue_id = %s AND character_id = %s",
        (clue_id, char["character_id"]),
    ).fetchone()
    if not clue:
        raise HTTPException(404, "Clue not found or not owned by you")

    existing = conn.execute(
        "SELECT * FROM clue_shares WHERE clue_id = %s", (clue_id,)
    ).fetchone()
    if existing:
        raise HTTPException(409, "Clue already shared")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    note = body.get("note", "")

    public_text = clue["text"]
    if note:
        public_text = f"{public_text}\n[分享者备注: {note}]"

    share = ClueShare(
        clue_id=clue_id,
        shared_by=char["character_id"],
        public_version=public_text,
    )
    conn.execute(
        "INSERT INTO clue_shares (share_id, clue_id, shared_by, shared_at, public_version) "
        "VALUES (%s, %s, %s, %s, %s)",
        (share.share_id, share.clue_id, share.shared_by, share.shared_at, share.public_version),
    )
    conn.execute(
        "UPDATE clues SET is_private = FALSE WHERE clue_id = %s", (clue_id,)
    )
    conn.commit()
    return {"share_id": share.share_id, "public_version": share.public_version}
