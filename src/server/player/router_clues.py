import logging
from fastapi import APIRouter, Request, HTTPException
from ..models import Clue, ClueShare
from .auth import require_player_character

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/player")


def _get_character(request: Request):
    return require_player_character(request)


@router.get("/clues")
async def list_clues(request: Request):
    char = _get_character(request)
    conn = request.app.state.db

    private_rows = conn.execute(
        "SELECT c.*, STRING_AGG(cs.shared_by, ',') as shared_by_list, "
        "MAX(cs.share_id) AS shared_copy_id FROM clues c "
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
            "id": row["clue_id"],
            "clue_id": row["clue_id"],
            "text": row["text"],
            "source": row["source"],
            "is_private": bool(row["is_private"]),
            "is_shared": bool(row.get("shared_copy_id")),
            "discovered_at": row["discovered_at"],
            "is_owner": True,
        }
        clues.append(clue)

    for row in shared_rows:
        clue = {
            "id": row["clue_id"],
            "clue_id": row["clue_id"],
            "text": row["public_version"],
            "source": row["source"],
            "is_private": False,
            "is_shared": True,
            "discovered_at": row["discovered_at"],
            "shared_by": row["shared_by"],
            "shared_at": row["shared_at"],
            "is_owner": False,
        }
        clues.append(clue)

    return {"clues": clues}


SAFE_SHARE_DEFAULT = "玩家分享了一条线索，但未公开完整内容。"


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
        "SELECT * FROM clue_shares WHERE clue_id = %s AND room_id = %s",
        (clue_id, char["room_id"]),
    ).fetchone()
    if existing:
        raise HTTPException(409, "Clue already shared")

    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    share_full_text = body.get("share_full_text", False)
    confirm_share_full_text = body.get("confirm_share_full_text", False)
    note = body.get("note", "")
    provided_public_version = body.get("public_version", "").strip()

    # Determine public_version
    if share_full_text:
        # Explicit full-text share: requires hard confirmation
        if confirm_share_full_text is not True:
            raise HTTPException(400, "全文分享线索需显式确认 (confirm_share_full_text: true)")
        # Still run through SpoilerGuard
        public_text = clue["text"]
        try:
            from ..engine.spoiler_guard import SpoilerGuard
            sg = SpoilerGuard(conn)
            # Check the text against spoiler index for party audience
            result = sg.review(public_text, "party", char["character_id"],
                              sg.compute_unlock_state(char["room_id"]),
                              sg.build_sensitive_index(
                                  conn.execute("SELECT scenario_id FROM rooms WHERE room_id = %s",
                                              (char["room_id"],)).fetchone() or {}))
            if result.violations:
                logger.warning("Share full-text blocked by SpoilerGuard for clue %s: %s",
                              clue_id, [v.get("label") for v in result.violations])
                raise HTTPException(400, "全文分享被防剧透系统拦截，请使用摘要分享 (public_version)")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning("SpoilerGuard check failed for clue share: %s", e)
    elif provided_public_version:
        # Player-provided summary
        public_text = provided_public_version
        # Also check through SpoilerGuard
        try:
            from ..engine.spoiler_guard import SpoilerGuard
            sg = SpoilerGuard(conn)
            room_scenario = conn.execute(
                "SELECT scenario_id FROM rooms WHERE room_id = %s", (char["room_id"],)
            ).fetchone()
            kg = {}
            if room_scenario and room_scenario.get("scenario_id"):
                sc = conn.execute(
                    "SELECT knowledge_graph FROM scenarios WHERE scenario_id = %s",
                    (room_scenario["scenario_id"],),
                ).fetchone()
                if sc:
                    kg_raw = sc.get("knowledge_graph") or {}
                    if isinstance(kg_raw, str):
                        import json as _json
                        try: kg = _json.loads(kg_raw)
                        except Exception: kg = {}
            result = sg.review(public_text, "party", char["character_id"],
                              sg.compute_unlock_state(char["room_id"]),
                              sg.build_sensitive_index(room_scenario["scenario_id"] if room_scenario else "", kg))
            if result.violations:
                raise HTTPException(400, "分享摘要包含敏感内容，请修改后重试")
        except HTTPException:
            raise
        except Exception:
            pass  # If SpoilerGuard unavailable, proceed
    else:
        # Safe default — no text exposure
        public_text = SAFE_SHARE_DEFAULT

    if note:
        public_text = f"{public_text}\n[分享者备注: {note}]"

    share = ClueShare(
        clue_id=clue_id,
        shared_by=char["character_id"],
        public_version=public_text,
    )
    conn.execute(
        "INSERT INTO clue_shares (share_id, clue_id, shared_by, shared_at, public_version, room_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (share.share_id, share.clue_id, share.shared_by, share.shared_at, share.public_version, char["room_id"]),
    )
    conn.commit()

    # Write share event
    try:
        from ..events.event_log import EventLog
        el = EventLog(conn)
        el.log_event(char["room_id"], "s2c_clue_shared", "party", {
            "clueId": clue_id,
            "shareId": share.share_id,
            "sharedBy": char["character_id"],
            "publicVersion": public_text,
            "visibility": "party",
            "sharedAt": share.shared_at,
        })
    except Exception as e:
        logger.warning("Failed to write clue_shared event: %s", e)

    return {
        "share_id": share.share_id,
        "public_version": public_text,
        "share_full_text": share_full_text,
    }
