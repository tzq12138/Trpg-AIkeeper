import json
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import Response

from .private_data import PrivateDataDecryptionError, private_data_cipher_from_env
from ..events.events_registry import event_type


router = APIRouter(prefix="/api/player")
host_router = APIRouter(prefix="/api/host")
evidence_router = APIRouter(prefix="/api")
library_router = APIRouter(prefix="/api")


class DeviceSessionClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    takeover: bool = False


class PlayerNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class PlayerNoteShare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)


class EmergencyNoteAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)
    password: str = Field(min_length=1, max_length=256)


class EvidenceCardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=5000)
    card_type: Literal["clue", "person", "location", "item", "question"] = "clue"
    visibility: Literal["party", "private"] = "party"


class EvidenceFactStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_status: Literal["confirmed", "excluded"]


class EvidenceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_evidence_card_id: str = Field(min_length=1, max_length=64)
    to_evidence_card_id: str = Field(min_length=1, max_length=64)
    relation_type: str = Field(min_length=1, max_length=50, pattern=r"^[a-z_]+$")


class CampaignSessionSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheduled_for: datetime


class CampaignAttendanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attendance_status: Literal["attending", "tentative", "absent"]


class TeamObjectiveCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)


class SessionZeroConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool


_NOTE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
_MAX_NOTE_ATTACHMENT_BYTES = 5 * 1024 * 1024
_SESSION_ZERO_STEPS = (
    "character_rules",
    "safety",
    "ai_host",
    "private_data",
    "connection",
)


def _require_character(request: Request) -> dict:
    token = request.headers.get("X-Room-Token", "")
    if not token:
        raise HTTPException(401, "Missing X-Room-Token")
    character = request.app.state.db.execute(
        "SELECT * FROM characters WHERE player_token = %s", (token,)
    ).fetchone()
    if not character:
        raise HTTPException(403, "Invalid token")
    return dict(character)


def _device_session_payload(row: dict) -> dict:
    return {
        "device_session_id": row["device_session_id"],
        "device_id": row["device_id"],
        "status": row["status"],
        "controller": bool(row["is_controller"]),
        "last_seen_at": row["last_seen_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat(),
    }


def claim_controller_device(conn, character: dict, device_id: str, takeover: bool = False) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", device_id):
        raise HTTPException(422, detail={"code": "invalid_device_id"})
    with conn.transaction() as transaction:
        transaction.execute(
            "SELECT character_id FROM characters WHERE character_id = %s FOR UPDATE",
            (character["character_id"],),
        )
        transaction.execute(
            "UPDATE player_device_sessions SET status = 'expired', is_controller = FALSE, "
            "updated_at = NOW() WHERE character_id = %s AND status = 'active' "
            "AND expires_at <= NOW()",
            (character["character_id"],),
        )
        current_controller = transaction.execute(
            "SELECT * FROM player_device_sessions WHERE character_id = %s "
            "AND status = 'active' AND is_controller = TRUE FOR UPDATE",
            (character["character_id"],),
        ).fetchone()
        if current_controller and current_controller["device_id"] != device_id:
            if not takeover:
                raise HTTPException(
                    409,
                    detail={
                        "code": "controller_held",
                        "controller_device_id": current_controller["device_id"],
                    },
                )
            transaction.execute(
                "UPDATE player_device_sessions SET status = 'revoked', is_controller = FALSE, "
                "updated_at = NOW() WHERE device_session_id = %s",
                (current_controller["device_session_id"],),
            )

        row = transaction.execute(
            "SELECT * FROM player_device_sessions WHERE character_id = %s AND device_id = %s FOR UPDATE",
            (character["character_id"], device_id),
        ).fetchone()
        if row:
            transaction.execute(
                "UPDATE player_device_sessions SET status = 'active', is_controller = TRUE, "
                "last_seen_at = NOW(), expires_at = NOW() + INTERVAL '30 minutes', updated_at = NOW() "
                "WHERE device_session_id = %s",
                (row["device_session_id"],),
            )
            device_session_id = row["device_session_id"]
        else:
            device_session_id = str(uuid.uuid4())
            transaction.execute(
                "INSERT INTO player_device_sessions "
                "(device_session_id, room_id, character_id, device_id, is_controller, expires_at) "
                "VALUES (%s, %s, %s, %s, TRUE, NOW() + INTERVAL '30 minutes')",
                (
                    device_session_id,
                    character["room_id"],
                    character["character_id"],
                    device_id,
                ),
            )
        transaction.execute(
            "INSERT INTO room_player_settings (room_id, character_id, controller_device_id) "
            "VALUES (%s, %s, %s) ON CONFLICT (room_id, character_id) DO UPDATE "
            "SET controller_device_id = EXCLUDED.controller_device_id, updated_at = NOW()",
            (character["room_id"], character["character_id"], device_id),
        )
        claimed = transaction.execute(
            "SELECT * FROM player_device_sessions WHERE device_session_id = %s",
            (device_session_id,),
        ).fetchone()
    return dict(claimed)


def record_campaign_activity(conn, character: dict) -> dict:
    with conn.transaction() as transaction:
        transaction.execute(
            "SELECT room_id FROM rooms WHERE room_id = %s FOR UPDATE",
            (character["room_id"],),
        )
        session = transaction.execute(
            "SELECT * FROM campaign_sessions WHERE room_id = %s AND status = 'active' FOR UPDATE",
            (character["room_id"],),
        ).fetchone()
        if session:
            transaction.execute(
                "UPDATE campaign_sessions SET last_activity_at = NOW() WHERE campaign_session_id = %s",
                (session["campaign_session_id"],),
            )
            session_id = session["campaign_session_id"]
        else:
            session_id = str(uuid.uuid4())
            transaction.execute(
                "INSERT INTO campaign_sessions "
                "(campaign_session_id, room_id, started_by_character_id) VALUES (%s, %s, %s)",
                (session_id, character["room_id"], character["character_id"]),
            )
        transaction.execute(
            "INSERT INTO session_attendance (campaign_session_id, character_id, attendance_status) "
            "VALUES (%s, %s, 'present') ON CONFLICT (campaign_session_id, character_id) "
            "DO UPDATE SET attendance_status = 'present', updated_at = NOW()",
            (session_id, character["character_id"]),
        )
        result = transaction.execute(
            "SELECT * FROM campaign_sessions WHERE campaign_session_id = %s", (session_id,)
        ).fetchone()
    return dict(result)


def _end_inactive_session(conn, room_id: str) -> None:
    with conn.transaction() as transaction:
        session = transaction.execute(
            "SELECT * FROM campaign_sessions WHERE room_id = %s AND status = 'active' FOR UPDATE",
            (room_id,),
        ).fetchone()
        if not session:
            return
        recently_active = transaction.execute(
            "SELECT 1 FROM player_device_sessions WHERE room_id = %s AND status = 'active' "
            "AND last_seen_at > NOW() - INTERVAL '30 minutes' LIMIT 1",
            (room_id,),
        ).fetchone()
        quiet = transaction.execute(
            "SELECT 1 FROM events WHERE room_id = %s AND issued_at > NOW() - INTERVAL '90 minutes' LIMIT 1",
            (room_id,),
        ).fetchone()
        recently_active_session = transaction.execute(
            "SELECT 1 FROM campaign_sessions WHERE campaign_session_id = %s "
            "AND last_activity_at > NOW() - INTERVAL '90 minutes'",
            (session["campaign_session_id"],),
        ).fetchone()
        if recently_active or quiet or recently_active_session:
            return
        transaction.execute(
            "UPDATE campaign_sessions SET status = 'ended', ended_at = NOW(), end_reason = 'inactive' "
            "WHERE campaign_session_id = %s",
            (session["campaign_session_id"],),
        )
        visible_events = transaction.execute(
            "SELECT sequence, event_type FROM events WHERE room_id = %s AND audience = 'party' "
            "AND issued_at >= %s AND issued_at <= NOW() ORDER BY sequence ASC",
            (room_id, session["started_at"]),
        ).fetchall()
        summary_id = str(uuid.uuid4())
        transaction.execute(
            "INSERT INTO session_summaries "
            "(session_summary_id, campaign_session_id, room_id, summary_text, source, confidence) "
            "VALUES (%s, %s, %s, %s, 'local_fallback', 1.0)",
            (
                summary_id,
                session["campaign_session_id"],
                room_id,
                f"本次 Session 因长时间无活动自动结束；已保留 {len(visible_events)} 条玩家可见事件作为续接依据。",
            ),
        )
        for event in visible_events:
            transaction.execute(
                "INSERT INTO session_summary_citations "
                "(session_summary_citation_id, session_summary_id, event_sequence, citation_label) "
                "VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), summary_id, event["sequence"], event["event_type"]),
            )


def _serialize_session(session: dict | None) -> dict | None:
    if not session:
        return None
    result = {
        "campaign_session_id": session["campaign_session_id"],
        "status": session["status"],
        "started_by_character_id": session.get("started_by_character_id"),
        "started_at": session["started_at"].isoformat(),
        "last_activity_at": session["last_activity_at"].isoformat(),
        "scheduled_for": session["scheduled_for"].isoformat() if session.get("scheduled_for") else None,
        "ended_at": session["ended_at"].isoformat() if session.get("ended_at") else None,
    }
    if session.get("attendance_status"):
        result["attendance_status"] = session["attendance_status"]
    return result


def _note_payload(note: dict, include_body: bool = True) -> dict:
    cipher = private_data_cipher_from_env()
    try:
        title = cipher.decrypt(note["title_ciphertext"])
        body = cipher.decrypt(note["body_ciphertext"]) if include_body else ""
    except PrivateDataDecryptionError as exc:
        raise HTTPException(503, detail={"code": "private_data_unavailable"}) from exc
    return {
        "note_id": note["note_id"],
        "parent_note_id": note.get("parent_note_id"),
        "title": title,
        "body": body,
        "visibility": note["visibility"],
        "is_redacted_copy": bool(note["is_redacted_copy"]),
        "created_at": note["created_at"].isoformat(),
        "updated_at": note["updated_at"].isoformat(),
    }


def _evidence_card_payload(card: dict) -> dict:
    return {
        "evidence_card_id": card["evidence_card_id"],
        "title": card["title"],
        "body": card["body"],
        "card_type": card["card_type"],
        "fact_status": card["fact_status"],
        "visibility": card["visibility"],
        "source": card["source"],
        "confirmed_by": card.get("confirmed_by"),
        "created_by_character_id": card.get("created_by_character_id"),
        "version": card["version"],
        "created_at": card["created_at"].isoformat(),
        "updated_at": card["updated_at"].isoformat(),
    }


def _json_object(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@router.post("/device-sessions/claim")
async def claim_device_session(request: Request, body: DeviceSessionClaim):
    character = _require_character(request)
    claimed = claim_controller_device(
        request.app.state.db, character, body.device_id, body.takeover
    )
    return _device_session_payload(claimed)


@router.get("/device-sessions")
async def list_device_sessions(request: Request):
    character = _require_character(request)
    rows = request.app.state.db.execute(
        "SELECT * FROM player_device_sessions WHERE character_id = %s "
        "ORDER BY is_controller DESC, last_seen_at DESC",
        (character["character_id"],),
    ).fetchall()
    return {"sessions": [_device_session_payload(dict(row)) for row in rows]}


@router.get("/campaign-home")
async def campaign_home(request: Request):
    character = _require_character(request)
    conn = request.app.state.db
    _end_inactive_session(conn, character["room_id"])
    session = conn.execute(
        "SELECT * FROM campaign_sessions WHERE room_id = %s "
        "ORDER BY (status = 'active') DESC, started_at DESC LIMIT 1",
        (character["room_id"],),
    ).fetchone()
    team_objectives = conn.execute(
        "SELECT objective_id, text, status, assigned_at FROM objectives "
        "WHERE room_id = %s AND type = 'team' ORDER BY assigned_at ASC",
        (character["room_id"],),
    ).fetchall()
    personal_objectives = conn.execute(
        "SELECT objective_id, text, status, assigned_at FROM objectives "
        "WHERE room_id = %s AND type = 'personal' AND character_id = %s ORDER BY assigned_at ASC",
        (character["room_id"], character["character_id"]),
    ).fetchall()
    summary = conn.execute(
        "SELECT session_summary_id, summary_text, source, confidence, published_at FROM session_summaries "
        "WHERE room_id = %s ORDER BY published_at DESC LIMIT 1",
        (character["room_id"],),
    ).fetchone()
    summary_citations = []
    if summary:
        summary_citations = conn.execute(
            "SELECT event_sequence, citation_label FROM session_summary_citations "
            "WHERE session_summary_id = %s ORDER BY created_at ASC",
            (summary["session_summary_id"],),
        ).fetchall()
    next_session = conn.execute(
        "SELECT cs.*, sa.attendance_status FROM campaign_sessions cs "
        "LEFT JOIN session_attendance sa ON sa.campaign_session_id = cs.campaign_session_id "
        "AND sa.character_id = %s WHERE cs.room_id = %s AND cs.status = 'scheduled' "
        "AND cs.scheduled_for >= NOW() ORDER BY cs.scheduled_for ASC LIMIT 1",
        (character["character_id"], character["room_id"]),
    ).fetchone()
    unresolved_questions = conn.execute(
        "SELECT evidence_card_id, title, fact_status FROM evidence_cards "
        "WHERE room_id = %s AND card_type = 'question' AND visibility = 'party' "
        "AND fact_status = 'hypothesis' ORDER BY updated_at DESC",
        (character["room_id"],),
    ).fetchall()
    return {
        "room_id": character["room_id"],
        "session": _serialize_session(dict(session)) if session else None,
        "team_objectives": [dict(row) for row in team_objectives],
        "personal_objectives": [dict(row) for row in personal_objectives],
        "last_summary": {
            "summary_text": summary["summary_text"],
            "source": summary["source"],
            "confidence": float(summary["confidence"]),
            "published_at": summary["published_at"].isoformat(),
            "citations": [dict(citation) for citation in summary_citations],
        } if summary else None,
        "next_session": _serialize_session(dict(next_session)) if next_session else None,
        "recent_clues": [],
        "unresolved_questions": [dict(row) for row in unresolved_questions],
    }


@router.post("/notes", status_code=201)
async def create_note(request: Request, body: PlayerNoteCreate):
    character = _require_character(request)
    cipher = private_data_cipher_from_env()
    note_id = str(uuid.uuid4())
    conn = request.app.state.db
    conn.execute(
        "INSERT INTO player_notes "
        "(note_id, room_id, character_id, title_ciphertext, body_ciphertext) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            note_id,
            character["room_id"],
            character["character_id"],
            cipher.encrypt(body.title.strip()),
            cipher.encrypt(body.body.strip()),
        ),
    )
    conn.commit()
    note = conn.execute("SELECT * FROM player_notes WHERE note_id = %s", (note_id,)).fetchone()
    return _note_payload(dict(note))


@router.get("/notes")
async def list_notes(request: Request):
    character = _require_character(request)
    rows = request.app.state.db.execute(
        "SELECT * FROM player_notes WHERE room_id = %s "
        "AND (character_id = %s OR visibility = 'party') ORDER BY updated_at DESC",
        (character["room_id"], character["character_id"]),
    ).fetchall()
    return {"notes": [_note_payload(dict(row)) for row in rows]}


@router.post("/notes/{note_id}/share", status_code=201)
async def share_note(request: Request, note_id: str, body: PlayerNoteShare):
    character = _require_character(request)
    conn = request.app.state.db
    original = conn.execute(
        "SELECT * FROM player_notes WHERE note_id = %s AND character_id = %s AND room_id = %s",
        (note_id, character["character_id"], character["room_id"]),
    ).fetchone()
    if not original:
        raise HTTPException(404, detail={"code": "note_not_found"})
    cipher = private_data_cipher_from_env()
    shared_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO player_notes "
        "(note_id, room_id, character_id, parent_note_id, title_ciphertext, body_ciphertext, visibility, is_redacted_copy) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'party', TRUE)",
        (
            shared_id,
            character["room_id"],
            character["character_id"],
            note_id,
            cipher.encrypt(body.title.strip()),
            cipher.encrypt(body.body.strip()),
        ),
    )
    conn.commit()
    shared = conn.execute("SELECT * FROM player_notes WHERE note_id = %s", (shared_id,)).fetchone()
    return _note_payload(dict(shared))


@router.post("/notes/{note_id}/attachment", status_code=201)
async def add_note_attachment(request: Request, note_id: str, file: UploadFile = File(...)):
    character = _require_character(request)
    if file.content_type not in _NOTE_IMAGE_TYPES:
        raise HTTPException(415, detail={"code": "image_attachment_required"})
    content = await file.read()
    if not content or len(content) > _MAX_NOTE_ATTACHMENT_BYTES:
        raise HTTPException(413, detail={"code": "attachment_too_large"})
    conn = request.app.state.db
    note = conn.execute(
        "SELECT note_id FROM player_notes WHERE note_id = %s AND room_id = %s AND character_id = %s",
        (note_id, character["room_id"], character["character_id"]),
    ).fetchone()
    if not note:
        raise HTTPException(404, detail={"code": "note_not_found"})
    existing = conn.execute(
        "SELECT note_attachment_id FROM note_attachments WHERE note_id = %s", (note_id,)
    ).fetchone()
    if existing:
        raise HTTPException(409, detail={"code": "note_attachment_exists"})
    cipher = private_data_cipher_from_env()
    attachment_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO note_attachments "
        "(note_attachment_id, note_id, filename_ciphertext, content_type, content_ciphertext) "
        "VALUES (%s, %s, %s, %s, %s)",
        (
            attachment_id,
            note_id,
            cipher.encrypt(file.filename or "image"),
            file.content_type,
            cipher.encrypt_bytes(content),
        ),
    )
    conn.commit()
    return {"note_attachment_id": attachment_id, "content_type": file.content_type}


@router.get("/notes/{note_id}/attachment")
async def get_note_attachment(request: Request, note_id: str):
    character = _require_character(request)
    row = request.app.state.db.execute(
        "SELECT a.* FROM note_attachments a JOIN player_notes n ON n.note_id = a.note_id "
        "WHERE a.note_id = %s AND n.room_id = %s AND n.character_id = %s",
        (note_id, character["room_id"], character["character_id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "note_attachment_not_found"})
    cipher = private_data_cipher_from_env()
    try:
        content = cipher.decrypt_bytes(row["content_ciphertext"])
    except PrivateDataDecryptionError as exc:
        raise HTTPException(503, detail={"code": "private_data_unavailable"}) from exc
    return Response(
        content=content,
        media_type=row["content_type"],
        headers={"X-Content-Type-Options": "nosniff"},
    )


@host_router.post("/{room_id}/player-notes/{note_id}/emergency-decrypt")
async def emergency_decrypt_note(
    request: Request,
    room_id: str,
    note_id: str,
    body: EmergencyNoteAccess,
):
    from ..host.router_host import _verify_owner
    from ..router_auth import _verify_password, get_account_from_token

    _verify_owner(request, room_id)
    account = get_account_from_token(request)
    if not account:
        raise HTTPException(401, detail={"code": "reauthentication_required"})
    conn = request.app.state.db
    credentials = conn.execute(
        "SELECT password_hash FROM accounts WHERE account_id = %s", (account["account_id"],)
    ).fetchone()
    if not credentials or not _verify_password(body.password, credentials["password_hash"]):
        raise HTTPException(401, detail={"code": "reauthentication_failed"})
    note = conn.execute(
        "SELECT * FROM player_notes WHERE note_id = %s AND room_id = %s",
        (note_id, room_id),
    ).fetchone()
    if not note:
        raise HTTPException(404, detail={"code": "note_not_found"})
    note_data = dict(note)
    result = _note_payload(note_data)
    with conn.transaction() as transaction:
        transaction.execute(
            "INSERT INTO private_data_access_audits "
            "(private_data_access_audit_id, room_id, note_id, owner_character_id, host_account_id, reason) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                str(uuid.uuid4()),
                room_id,
                note_id,
                note_data["character_id"],
                account["account_id"],
                body.reason.strip(),
            ),
        )
        transaction.execute(
            "INSERT INTO events (room_id, event_type, audience, payload) VALUES (%s, %s, 'player', %s)",
            (
                room_id,
                event_type("s2c_private_note_emergency_access"),
                json.dumps(
                    {
                        "character_id": note_data["character_id"],
                        "note_id": note_id,
                        "reason": "Host 以紧急流程访问了一条私人笔记。",
                    },
                    ensure_ascii=False,
                ),
            ),
        )
    return result


@host_router.post("/{room_id}/campaign-sessions/schedule", status_code=201)
async def schedule_campaign_session(
    request: Request,
    room_id: str,
    body: CampaignSessionSchedule,
):
    from ..host.router_host import _verify_owner

    _verify_owner(request, room_id)
    scheduled_for = body.scheduled_for
    if scheduled_for.tzinfo is None:
        raise HTTPException(422, detail={"code": "scheduled_time_timezone_required"})
    if scheduled_for <= datetime.now(timezone.utc):
        raise HTTPException(422, detail={"code": "scheduled_time_must_be_future"})
    session_id = str(uuid.uuid4())
    conn = request.app.state.db
    conn.execute(
        "INSERT INTO campaign_sessions (campaign_session_id, room_id, status, scheduled_for) "
        "VALUES (%s, %s, 'scheduled', %s)",
        (session_id, room_id, scheduled_for),
    )
    conn.commit()
    scheduled = conn.execute(
        "SELECT * FROM campaign_sessions WHERE campaign_session_id = %s", (session_id,)
    ).fetchone()
    return _serialize_session(dict(scheduled))


@host_router.post("/{room_id}/objectives", status_code=201)
async def create_team_objective(request: Request, room_id: str, body: TeamObjectiveCreate):
    from ..host.router_host import _verify_owner

    _verify_owner(request, room_id)
    objective_id = str(uuid.uuid4())
    conn = request.app.state.db
    conn.execute(
        "INSERT INTO objectives (objective_id, room_id, text, type) VALUES (%s, %s, %s, 'team')",
        (objective_id, room_id, body.text.strip()),
    )
    conn.commit()
    objective = conn.execute(
        "SELECT objective_id, text, type, status, assigned_at FROM objectives WHERE objective_id = %s",
        (objective_id,),
    ).fetchone()
    return dict(objective)


@router.post("/campaign-sessions/{campaign_session_id}/attendance")
async def update_campaign_attendance(
    request: Request,
    campaign_session_id: str,
    body: CampaignAttendanceUpdate,
):
    character = _require_character(request)
    conn = request.app.state.db
    session = conn.execute(
        "SELECT campaign_session_id FROM campaign_sessions WHERE campaign_session_id = %s "
        "AND room_id = %s AND status IN ('scheduled', 'active')",
        (campaign_session_id, character["room_id"]),
    ).fetchone()
    if not session:
        raise HTTPException(404, detail={"code": "campaign_session_not_found"})
    conn.execute(
        "INSERT INTO session_attendance (campaign_session_id, character_id, attendance_status) "
        "VALUES (%s, %s, %s) ON CONFLICT (campaign_session_id, character_id) "
        "DO UPDATE SET attendance_status = EXCLUDED.attendance_status, updated_at = NOW()",
        (campaign_session_id, character["character_id"], body.attendance_status),
    )
    conn.commit()
    return {
        "campaign_session_id": campaign_session_id,
        "character_id": character["character_id"],
        "attendance_status": body.attendance_status,
    }


@router.get("/session-zero")
async def get_session_zero(request: Request):
    character = _require_character(request)
    rows = request.app.state.db.execute(
        "SELECT step, confirmed_at FROM session_zero_confirmations "
        "WHERE room_id = %s AND character_id = %s",
        (character["room_id"], character["character_id"]),
    ).fetchall()
    confirmed = {row["step"]: row["confirmed_at"].isoformat() for row in rows}
    steps = [
        {"step": step, "confirmed": step in confirmed, "confirmed_at": confirmed.get(step)}
        for step in _SESSION_ZERO_STEPS
    ]
    return {"steps": steps, "complete": all(item["confirmed"] for item in steps)}


@router.post("/session-zero/{step}")
async def confirm_session_zero(request: Request, step: str, body: SessionZeroConfirmation):
    character = _require_character(request)
    if step not in _SESSION_ZERO_STEPS:
        raise HTTPException(404, detail={"code": "session_zero_step_not_found"})
    if not body.confirmed:
        raise HTTPException(422, detail={"code": "session_zero_confirmation_required"})
    step_index = _SESSION_ZERO_STEPS.index(step)
    conn = request.app.state.db
    if step_index:
        prior_steps = _SESSION_ZERO_STEPS[:step_index]
        rows = conn.execute(
            "SELECT step FROM session_zero_confirmations WHERE room_id = %s AND character_id = %s "
            "AND step = ANY(%s)",
            (character["room_id"], character["character_id"], list(prior_steps)),
        ).fetchall()
        if {row["step"] for row in rows} != set(prior_steps):
            raise HTTPException(409, detail={"code": "session_zero_step_order"})
    conn.execute(
        "INSERT INTO session_zero_confirmations (room_id, character_id, step) VALUES (%s, %s, %s) "
        "ON CONFLICT (room_id, character_id, step) DO NOTHING",
        (character["room_id"], character["character_id"], step),
    )
    conn.commit()
    return {"step": step, "confirmed": True}


@evidence_router.post("/rooms/{room_id}/evidence", status_code=201)
async def create_evidence_card(request: Request, room_id: str, body: EvidenceCardCreate):
    character = _require_character(request)
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    evidence_card_id = str(uuid.uuid4())
    conn = request.app.state.db
    conn.execute(
        "INSERT INTO evidence_cards "
        "(evidence_card_id, room_id, created_by_character_id, title, body, card_type, fact_status, visibility, source) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'hypothesis', %s, 'player')",
        (
            evidence_card_id,
            room_id,
            character["character_id"],
            body.title.strip(),
            body.body.strip(),
            body.card_type,
            body.visibility,
        ),
    )
    conn.commit()
    card = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (evidence_card_id,)
    ).fetchone()
    return _evidence_card_payload(dict(card))


@library_router.get("/library")
async def list_ready_to_play_library(request: Request):
    conn = request.app.state.db
    scenarios = conn.execute(
        "SELECT scenario_id, title, published_version_id, knowledge_graph, quality_report "
        "FROM scenarios WHERE publish_status = 'published' AND published_version_id IS NOT NULL "
        "ORDER BY title, scenario_id"
    ).fetchall()
    items = []
    for scenario in scenarios:
        scenario_id = scenario["scenario_id"]
        version_id = scenario["published_version_id"]
        version = conn.execute(
            "SELECT scenario_version_id FROM scenario_versions WHERE scenario_version_id = %s AND status = 'published'",
            (version_id,),
        ).fetchone()
        if not version:
            continue
        rule_binding = conn.execute(
            "SELECT 1 FROM scenario_rule_bindings WHERE scenario_version_id = %s LIMIT 1",
            (version_id,),
        ).fetchone()
        template = conn.execute(
            "SELECT 1 FROM character_templates WHERE scenario_id = %s LIMIT 1", (scenario_id,)
        ).fetchone()
        graph = _json_object(scenario.get("knowledge_graph"))
        has_world = all(bool(graph.get(key)) for key in ("scenes", "npcs", "clues"))
        quality = _json_object(scenario.get("quality_report"))
        if quality.get("level") in {"blocked", "highRisk"} or not (rule_binding and template and has_world):
            continue
        items.append({
            "scenario_id": scenario_id,
            "scenario_version_id": version_id,
            "title": scenario.get("title") or "未命名剧本",
            "ready_to_play": True,
        })
    return {"items": items}


@evidence_router.post("/rooms/{room_id}/evidence/links", status_code=201)
async def create_evidence_link(request: Request, room_id: str, body: EvidenceLinkCreate):
    character = _require_character(request)
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    if body.from_evidence_card_id == body.to_evidence_card_id:
        raise HTTPException(422, detail={"code": "evidence_link_requires_two_cards"})
    conn = request.app.state.db
    visible_cards = conn.execute(
        "SELECT evidence_card_id FROM evidence_cards WHERE room_id = %s "
        "AND evidence_card_id = ANY(%s) AND (visibility = 'party' OR created_by_character_id = %s)",
        (
            room_id,
            [body.from_evidence_card_id, body.to_evidence_card_id],
            character["character_id"],
        ),
    ).fetchall()
    if len(visible_cards) != 2:
        raise HTTPException(404, detail={"code": "evidence_card_not_visible"})
    link_id = str(uuid.uuid4())
    with conn.transaction() as transaction:
        created = transaction.execute(
            "INSERT INTO evidence_links "
            "(evidence_link_id, room_id, from_evidence_card_id, to_evidence_card_id, relation_type, created_by_character_id) "
            "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING "
            "RETURNING evidence_link_id",
            (
                link_id,
                room_id,
                body.from_evidence_card_id,
                body.to_evidence_card_id,
                body.relation_type,
                character["character_id"],
            ),
        ).fetchone()
        if not created:
            raise HTTPException(409, detail={"code": "evidence_link_exists"})
    return {
        "evidence_link_id": link_id,
        "from_evidence_card_id": body.from_evidence_card_id,
        "to_evidence_card_id": body.to_evidence_card_id,
        "relation_type": body.relation_type,
    }


@evidence_router.get("/rooms/{room_id}/evidence")
async def list_evidence_cards(request: Request, room_id: str):
    character = _require_character(request)
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    conn = request.app.state.db
    cards = conn.execute(
        "SELECT * FROM evidence_cards WHERE room_id = %s "
        "AND (visibility = 'party' OR created_by_character_id = %s) ORDER BY updated_at DESC",
        (room_id, character["character_id"]),
    ).fetchall()
    card_ids = [card["evidence_card_id"] for card in cards]
    links = []
    if card_ids:
        links = conn.execute(
            "SELECT evidence_link_id, from_evidence_card_id, to_evidence_card_id, relation_type "
            "FROM evidence_links WHERE room_id = %s AND from_evidence_card_id = ANY(%s) "
            "AND to_evidence_card_id = ANY(%s) ORDER BY created_at ASC",
            (room_id, card_ids, card_ids),
        ).fetchall()
    return {
        "cards": [_evidence_card_payload(dict(card)) for card in cards],
        "links": [dict(link) for link in links],
    }


@host_router.patch("/{room_id}/evidence/{evidence_card_id}/fact-status")
async def update_evidence_fact_status(
    request: Request,
    room_id: str,
    evidence_card_id: str,
    body: EvidenceFactStatusUpdate,
):
    from ..host.router_host import _verify_owner

    _verify_owner(request, room_id)
    conn = request.app.state.db
    card = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s AND room_id = %s",
        (evidence_card_id, room_id),
    ).fetchone()
    if not card:
        raise HTTPException(404, detail={"code": "evidence_not_found"})
    conn.execute(
        "UPDATE evidence_cards SET fact_status = %s, confirmed_by = 'host', source = 'host', "
        "version = version + 1, updated_at = NOW() WHERE evidence_card_id = %s",
        (body.fact_status, evidence_card_id),
    )
    conn.commit()
    updated = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (evidence_card_id,)
    ).fetchone()
    return _evidence_card_payload(dict(updated))
