import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse, Response

from .private_data import PrivateDataDecryptionError, private_data_cipher_from_env
from ..events.events_registry import event_type
from ..models import CampaignHomeDTO, EvidenceDetailDTO, redact_citation


router = APIRouter(prefix="/api/player")
host_router = APIRouter(prefix="/api/host")
evidence_router = APIRouter(prefix="/api")
library_router = APIRouter(prefix="/api")


_SOLO_NAVIGATION_INSTRUCTION = re.compile(
    r"\s*(?:请|再|然后)?(?:转|翻|跳|前往|进入|见)\s*(?:到|至|去|向|往)?"
    r"(?:条目|段落)?\s*(?:第)?\s*\d+\s*[。．.!！?？]*",
    re.IGNORECASE,
)
_PLAYER_SOURCE_MARKER_RE = re.compile(
    r"(?:七宫涟(?:个人)?汉化?|七宫(?:涟)?个人汉化?|七宫(?=\s+)|火独行|向火|宫涟(?:个人)?汉化|宫涟|人汉化|个人汉|汉化)"
)
_PLAYER_SOURCE_LINE_RE = re.compile(r"(?m)^\s*七宫\s*(?:\n|$)")
_PLAYER_VISIBLE_ASSET_VISIBILITIES = {"party", "player", "public"}


def _player_safe_solo_preview(text: object) -> str:
    preview = _SOLO_NAVIGATION_INSTRUCTION.sub("", str(text or ""))
    preview = _PLAYER_SOURCE_LINE_RE.sub("", preview)
    preview = _PLAYER_SOURCE_MARKER_RE.sub("", preview)
    preview = re.sub(r"\s+", " ", preview)
    preview = preview.replace("看出 了", "看出了").replace("沮个丧", "沮丧")
    preview = preview.strip()
    return preview[:400] or "请根据当前场景的叙事继续行动。"


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
    visibility: Literal["party", "private"] | None = None
    related_evidence_card_ids: list[str] = Field(default_factory=list, max_length=8)


class EvidenceCardShare(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=300)
    body: str = Field(default="", max_length=5000)


class EvidenceFactStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_status: Literal["confirmed", "excluded"]


class QuestionCloseConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed: bool


class EvidenceLinkCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_evidence_card_id: str = Field(min_length=1, max_length=64)
    to_evidence_card_id: str = Field(min_length=1, max_length=64)
    relation_type: str = Field(min_length=1, max_length=50, pattern=r"^[a-z_]+$")


class EvidenceCommentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=2000)


class HypothesisStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_status: Literal["discussing", "disproved", "shelved"]


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
    contract_hash: str | None = Field(default=None, min_length=64, max_length=64)


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
    payload = {
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
    if card["card_type"] == "question":
        payload.update({
            "question_status": card.get("question_status") or "investigating",
            "question_closed_by_character_id": card.get("question_closed_by_character_id"),
            "question_closed_at": (
                card["question_closed_at"].isoformat()
                if card.get("question_closed_at") else None
            ),
            "question_undo_until": (
                card["question_undo_until"].isoformat()
                if card.get("question_undo_until") else None
            ),
        })
    elif (
        card.get("visibility") == "party"
        and card.get("source") == "player"
        and card.get("fact_status") == "hypothesis"
    ):
        payload.update({
            "hypothesis_status": card.get("hypothesis_status") or "discussing",
            "hypothesis_status_changed_by_character_id": card.get(
                "hypothesis_status_changed_by_character_id"
            ),
            "hypothesis_status_changed_at": (
                card["hypothesis_status_changed_at"].isoformat()
                if card.get("hypothesis_status_changed_at") else None
            ),
            "hypothesis_status_undo_until": (
                card["hypothesis_status_undo_until"].isoformat()
                if card.get("hypothesis_status_undo_until") else None
            ),
        })
    return payload


def _visible_evidence_card(conn, character: dict, room_id: str, evidence_card_id: str) -> dict:
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    row = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s AND room_id = %s "
        "AND (visibility = 'party' OR created_by_character_id = %s)",
        (evidence_card_id, room_id, character["character_id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "evidence_card_not_visible"})
    return dict(row)


def _evidence_cognitive_tag(card: dict) -> str:
    if card["fact_status"] == "confirmed":
        return "已确认"
    if card["fact_status"] == "excluded":
        return "已证伪"
    if card["source"] == "player":
        return "玩家推测"
    return "存在争议"


def _evidence_detail_known_item(card: dict) -> dict:
    return {
        "evidence_card_id": card["evidence_card_id"],
        "title": card["title"],
        "body": card["body"],
        "cognitive_tag": _evidence_cognitive_tag(card),
    }


def _load_shared_hypothesis(
    conn,
    character: dict,
    room_id: str,
    evidence_card_id: str,
    *,
    for_update: bool = False,
) -> dict:
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    lock_clause = " FOR UPDATE" if for_update else ""
    card = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s AND room_id = %s" + lock_clause,
        (evidence_card_id, room_id),
    ).fetchone()
    if not card or (
        card["visibility"] != "party"
        or card["card_type"] == "question"
        or card["source"] != "player"
        or card["fact_status"] != "hypothesis"
    ):
        raise HTTPException(404, detail={"code": "shared_hypothesis_not_found"})
    return dict(card)


def _hypothesis_transition_payload(card: dict, *, undo_available: bool = False, changed: bool = False) -> dict:
    return {
        "card": _evidence_card_payload(card),
        "undo_available": undo_available,
        "changed": changed,
    }


def _confirmed_facts_for_shared_hypothesis(
    conn,
    room_id: str,
    evidence_card_id: str,
) -> list[dict]:
    rows = conn.execute(
        "SELECT DISTINCT card.evidence_card_id, card.title, card.body "
        "FROM evidence_links link "
        "JOIN evidence_cards card ON card.evidence_card_id = CASE "
        "WHEN link.from_evidence_card_id = %s THEN link.to_evidence_card_id "
        "ELSE link.from_evidence_card_id END "
        "WHERE link.room_id = %s "
        "AND (link.from_evidence_card_id = %s OR link.to_evidence_card_id = %s) "
        "AND card.visibility = 'party' AND card.fact_status = 'confirmed' "
        "ORDER BY card.evidence_card_id ASC",
        (evidence_card_id, room_id, evidence_card_id, evidence_card_id),
    ).fetchall()
    return [dict(row) for row in rows]


async def _emit_public_hypothesis_status(
    request: Request,
    room_id: str,
    card: dict,
    previous_status: str,
) -> None:
    from ..engine.projection import ProjectionDispatcher

    status = card.get("hypothesis_status") or "discussing"
    labels = {
        "discussing": "讨论中",
        "disproved": "已证伪",
        "shelved": "已搁置",
    }
    dispatcher = getattr(request.app.state, "dispatcher", None) or ProjectionDispatcher(request.app.state.db)
    await dispatcher.emit(
        room_id,
        "s2c_public_observation",
        "party",
        {
            "text": f"队伍假说状态更新：{card['title']} · {labels[status]}",
            "kind": "hypothesis_status",
            "hypothesisStatus": status,
            "previousHypothesisStatus": previous_status,
        },
    )


def _load_party_question(
    conn,
    character: dict,
    room_id: str,
    evidence_card_id: str,
    *,
    for_update: bool = False,
) -> dict:
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    lock_clause = " FOR UPDATE" if for_update else ""
    card = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s AND room_id = %s" + lock_clause,
        (evidence_card_id, room_id),
    ).fetchone()
    if not card or card["card_type"] != "question" or card["visibility"] != "party":
        raise HTTPException(404, detail={"code": "party_question_not_found"})
    return dict(card)


def _question_related_cards(conn, room_id: str, evidence_card_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT DISTINCT card.evidence_card_id, card.title, card.card_type, card.fact_status, card.updated_at "
        "FROM evidence_links link "
        "JOIN evidence_cards card ON card.evidence_card_id = CASE "
        "WHEN link.from_evidence_card_id = %s THEN link.to_evidence_card_id "
        "ELSE link.from_evidence_card_id END "
        "WHERE link.room_id = %s "
        "AND (link.from_evidence_card_id = %s OR link.to_evidence_card_id = %s) "
        "AND card.visibility = 'party' "
        "ORDER BY card.updated_at DESC",
        (evidence_card_id, room_id, evidence_card_id, evidence_card_id),
    ).fetchall()
    return [
        {
            key: value
            for key, value in dict(row).items()
            if key != "updated_at"
        }
        for row in rows
    ]


def _question_close_preview(card: dict, related_cards: list[dict]) -> dict:
    hypotheses = [item for item in related_cards if item["fact_status"] == "hypothesis"]
    return {
        "question": _evidence_card_payload(card),
        "related_hypotheses": hypotheses,
        "disputed_cards": hypotheses,
    }


def _question_transition_payload(
    card: dict,
    *,
    undo_available: bool = False,
    undid_close: bool = False,
) -> dict:
    return {
        "card": _evidence_card_payload(card),
        "undo_available": undo_available,
        "undid_close": undid_close,
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


@router.get("/campaign-home", response_model=CampaignHomeDTO)
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
        "AND fact_status = 'hypothesis' "
        "AND COALESCE(question_status, 'investigating') <> 'closed' "
        "ORDER BY updated_at DESC LIMIT 3",
        (character["room_id"],),
    ).fetchall()
    recent_clues = conn.execute(
        """
        SELECT clue_id, text, discovered_at, is_owner, is_shared
        FROM (
            SELECT c.clue_id, c.text, c.discovered_at,
                   TRUE AS is_owner,
                   EXISTS(
                       SELECT 1 FROM clue_shares own_share
                       WHERE own_share.clue_id = c.clue_id
                   ) AS is_shared
            FROM clues c
            WHERE c.room_id = %s AND c.character_id = %s

            UNION ALL

            SELECT shared.clue_id, shared.public_version AS text, shared.shared_at AS discovered_at,
                   FALSE AS is_owner, TRUE AS is_shared
            FROM (
                SELECT DISTINCT ON (c.clue_id)
                       c.clue_id, cs.public_version, cs.shared_at
                FROM clue_shares cs
                JOIN clues c ON c.clue_id = cs.clue_id
                WHERE c.room_id = %s AND c.character_id <> %s
                ORDER BY c.clue_id, cs.shared_at DESC
            ) AS shared
        ) AS visible_clues
        ORDER BY discovered_at DESC
        LIMIT 5
        """,
        (
            character["room_id"],
            character["character_id"],
            character["room_id"],
            character["character_id"],
        ),
    ).fetchall()
    current_scene = None
    try:
        from ..scenario.solo_runtime import SoloAdventureRuntime

        solo_scene = SoloAdventureRuntime(conn).current(character["room_id"])
        if solo_scene:
            from ..scenario.asset_binding import ScenarioAssetBindingService

            image_binding = ScenarioAssetBindingService(conn).confirmed_asset_for_target(
                solo_scene["scenario_version_id"],
                "branch_node",
                solo_scene["node_id"],
            )
            current_scene = {
                "title": "当前场景",
                "text_preview": _player_safe_solo_preview(solo_scene.get("text")),
                "citation": redact_citation(solo_scene.get("citation") or {}),
                "choice_count": len(solo_scene.get("target_node_ids") or []),
                "image_asset_id": (
                    image_binding["asset_id"]
                    if image_binding
                    and image_binding.get("asset_visibility") in _PLAYER_VISIBLE_ASSET_VISIBILITIES
                    else None
                ),
            }
    except Exception:
        current_scene = None
    return {
        "room_id": character["room_id"],
        "current_scene": current_scene,
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
        "recent_clues": [
            {
                "clue_id": row["clue_id"],
                "text": row["text"],
                "discovered_at": row["discovered_at"].isoformat(),
                "is_owner": bool(row["is_owner"]),
                "is_shared": bool(row["is_shared"]),
            }
            for row in recent_clues
        ],
        "unresolved_questions": [dict(row) for row in unresolved_questions],
    }


@router.get("/assets/{asset_id}")
async def get_current_scene_asset(request: Request, asset_id: str):
    character = _require_character(request)
    conn = request.app.state.db
    from ..scenario.solo_runtime import SoloAdventureRuntime

    current = SoloAdventureRuntime(conn).current(character["room_id"])
    if not current:
        raise HTTPException(404, detail={"code": "asset_not_visible"})
    row = conn.execute(
        "SELECT sa.scenario_id, sa.filename, sa.mime_type "
        "FROM scenario_asset_bindings sab "
        "JOIN scenario_assets sa ON sa.asset_id = sab.asset_id "
        "WHERE sab.scenario_version_id = %s AND sab.asset_id = %s "
        "AND sab.target_type = 'branch_node' AND sab.target_key = %s "
        "AND sab.status = 'confirmed' AND sa.visibility IN ('party', 'player', 'public')",
        (current["scenario_version_id"], asset_id, current["node_id"]),
    ).fetchone()
    if not row:
        raise HTTPException(404, detail={"code": "asset_not_visible"})
    configured_root = getattr(request.app.state, "scenario_asset_root", None)
    asset_root = Path(configured_root) if configured_root else (
        Path(__file__).resolve().parents[3] / "data" / "scenario_assets"
    )
    asset_path = (asset_root / row["scenario_id"] / row["filename"]).resolve()
    if not asset_path.is_relative_to(asset_root.resolve()) or not asset_path.is_file():
        raise HTTPException(404, detail={"code": "asset_file_unavailable"})
    return FileResponse(asset_path, media_type=row["mime_type"])


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


@router.patch("/notes/{note_id}")
async def update_note(request: Request, note_id: str, body: PlayerNoteCreate):
    character = _require_character(request)
    conn = request.app.state.db
    note = conn.execute(
        "SELECT * FROM player_notes WHERE note_id = %s AND room_id = %s "
        "AND character_id = %s AND visibility = 'private' AND is_redacted_copy = FALSE",
        (note_id, character["room_id"], character["character_id"]),
    ).fetchone()
    if not note:
        raise HTTPException(404, detail={"code": "note_not_found"})
    cipher = private_data_cipher_from_env()
    conn.execute(
        "UPDATE player_notes SET title_ciphertext = %s, body_ciphertext = %s, updated_at = NOW() "
        "WHERE note_id = %s",
        (cipher.encrypt(body.title.strip()), cipher.encrypt(body.body.strip()), note_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM player_notes WHERE note_id = %s", (note_id,)).fetchone()
    return _note_payload(dict(updated))


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


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/notes", status_code=201)
async def create_evidence_note(
    request: Request,
    room_id: str,
    evidence_card_id: str,
    body: PlayerNoteCreate,
):
    character = _require_character(request)
    conn = request.app.state.db
    _visible_evidence_card(conn, character, room_id, evidence_card_id)
    cipher = private_data_cipher_from_env()
    note_id = str(uuid.uuid4())
    with conn.transaction() as transaction:
        transaction.execute(
            "INSERT INTO player_notes "
            "(note_id, room_id, character_id, title_ciphertext, body_ciphertext) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                note_id,
                room_id,
                character["character_id"],
                cipher.encrypt(body.title.strip()),
                cipher.encrypt(body.body.strip()),
            ),
        )
        transaction.execute(
            "INSERT INTO evidence_references "
            "(evidence_reference_id, evidence_card_id, reference_type, reference_id) "
            "VALUES (%s, %s, 'player_note', %s)",
            (str(uuid.uuid4()), evidence_card_id, note_id),
        )
    note = conn.execute("SELECT * FROM player_notes WHERE note_id = %s", (note_id,)).fetchone()
    return _note_payload(dict(note))


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
    conn = request.app.state.db
    room = conn.execute(
        "SELECT risk_contract, risk_contract_version, risk_contract_hash "
        "FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    rows = conn.execute(
        "SELECT step, confirmed_at, contract_version, contract_hash "
        "FROM session_zero_confirmations "
        "WHERE room_id = %s AND character_id = %s",
        (character["room_id"], character["character_id"]),
    ).fetchall()
    confirmed = {
        row["step"]: row["confirmed_at"].isoformat()
        for row in rows
        if row["step"] != "safety"
        or not room
        or not room.get("risk_contract_hash")
        or (
            row.get("contract_version") == room.get("risk_contract_version")
            and row.get("contract_hash") == room.get("risk_contract_hash")
        )
    }
    steps = [
        {"step": step, "confirmed": step in confirmed, "confirmed_at": confirmed.get(step)}
        for step in _SESSION_ZERO_STEPS
    ]
    from ..engine.risk_contract import public_risk_contract

    return {
        "steps": steps,
        "complete": all(item["confirmed"] for item in steps),
        "risk_contract": public_risk_contract(room.get("risk_contract") if room else None),
    }


@router.post("/session-zero/{step}")
async def confirm_session_zero(request: Request, step: str, body: SessionZeroConfirmation):
    character = _require_character(request)
    if step not in _SESSION_ZERO_STEPS:
        raise HTTPException(404, detail={"code": "session_zero_step_not_found"})
    if not body.confirmed:
        raise HTTPException(422, detail={"code": "session_zero_confirmation_required"})
    step_index = _SESSION_ZERO_STEPS.index(step)
    conn = request.app.state.db
    room = conn.execute(
        "SELECT risk_contract_version, risk_contract_hash FROM rooms WHERE room_id = %s",
        (character["room_id"],),
    ).fetchone()
    contract_version = None
    contract_hash = None
    if step == "safety" and room and room.get("risk_contract_hash"):
        contract_version = room.get("risk_contract_version")
        contract_hash = room.get("risk_contract_hash")
        if body.contract_hash != contract_hash:
            raise HTTPException(
                409,
                detail={
                    "code": "risk_contract_hash_mismatch",
                    "contract_version": contract_version,
                    "contract_hash": contract_hash,
                },
            )
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
        "INSERT INTO session_zero_confirmations "
        "(room_id, character_id, step, contract_version, contract_hash) "
        "VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (room_id, character_id, step) DO UPDATE SET "
        "contract_version = EXCLUDED.contract_version, "
        "contract_hash = EXCLUDED.contract_hash, confirmed_at = NOW()",
        (
            character["room_id"],
            character["character_id"],
            step,
            contract_version,
            contract_hash,
        ),
    )
    conn.commit()
    return {
        "step": step,
        "confirmed": True,
        "contract_version": contract_version,
        "contract_hash": contract_hash,
    }


@evidence_router.post("/rooms/{room_id}/evidence", status_code=201)
async def create_evidence_card(request: Request, room_id: str, body: EvidenceCardCreate):
    character = _require_character(request)
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    visibility = body.visibility or ("party" if body.card_type == "question" else "private")
    if visibility == "party" and body.card_type != "question":
        raise HTTPException(422, detail={"code": "evidence_share_required"})
    evidence_card_id = str(uuid.uuid4())
    conn = request.app.state.db
    related_ids = list(dict.fromkeys(body.related_evidence_card_ids))
    if len(related_ids) != len(body.related_evidence_card_ids):
        raise HTTPException(422, detail={"code": "duplicate_related_evidence"})
    with conn.transaction() as transaction:
        if related_ids:
            visible_cards = transaction.execute(
                "SELECT evidence_card_id FROM evidence_cards WHERE room_id = %s "
                "AND evidence_card_id = ANY(%s) AND (visibility = 'party' OR created_by_character_id = %s)",
                (room_id, related_ids, character["character_id"]),
            ).fetchall()
            if len(visible_cards) != len(related_ids):
                raise HTTPException(404, detail={"code": "evidence_card_not_visible"})
        transaction.execute(
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
                visibility,
            ),
        )
        for related_id in related_ids:
            transaction.execute(
                "INSERT INTO evidence_links "
                "(evidence_link_id, room_id, from_evidence_card_id, to_evidence_card_id, relation_type, created_by_character_id) "
                "VALUES (%s, %s, %s, %s, 'related', %s)",
                (
                    str(uuid.uuid4()),
                    room_id,
                    evidence_card_id,
                    related_id,
                    character["character_id"],
                ),
            )
    card = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (evidence_card_id,)
    ).fetchone()
    return _evidence_card_payload(dict(card))


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/share", status_code=201)
async def share_evidence_card(
    request: Request,
    room_id: str,
    evidence_card_id: str,
    body: EvidenceCardShare,
):
    character = _require_character(request)
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    conn = request.app.state.db
    original = conn.execute(
        "SELECT card_type FROM evidence_cards WHERE evidence_card_id = %s AND room_id = %s "
        "AND created_by_character_id = %s AND visibility = 'private'",
        (evidence_card_id, room_id, character["character_id"]),
    ).fetchone()
    if not original:
        raise HTTPException(404, detail={"code": "private_evidence_not_found"})
    shared_id = str(uuid.uuid4())
    with conn.transaction() as transaction:
        transaction.execute(
            "INSERT INTO evidence_cards "
            "(evidence_card_id, room_id, created_by_character_id, title, body, card_type, fact_status, visibility, source, hypothesis_status) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'hypothesis', 'party', 'player', 'discussing')",
            (
                shared_id,
                room_id,
                character["character_id"],
                body.title.strip(),
                body.body.strip(),
                original["card_type"],
            ),
        )
    shared = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (shared_id,)
    ).fetchone()
    return _evidence_card_payload(dict(shared))


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
        "SELECT evidence_card_id, card_type, fact_status, visibility, source FROM evidence_cards WHERE room_id = %s "
        "AND evidence_card_id = ANY(%s) AND (visibility = 'party' OR created_by_character_id = %s)",
        (
            room_id,
            [body.from_evidence_card_id, body.to_evidence_card_id],
            character["character_id"],
        ),
    ).fetchall()
    if len(visible_cards) != 2:
        raise HTTPException(404, detail={"code": "evidence_card_not_visible"})
    includes_shared_hypothesis = any(
        card["visibility"] == "party"
        and card["card_type"] != "question"
        and card["source"] == "player"
        and card["fact_status"] == "hypothesis"
        for card in visible_cards
    )
    if includes_shared_hypothesis and body.relation_type not in {"support", "contradict", "related"}:
        raise HTTPException(422, detail={"code": "evidence_relation_invalid"})
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


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/comments", status_code=201)
async def create_evidence_comment(
    request: Request,
    room_id: str,
    evidence_card_id: str,
    body: EvidenceCommentCreate,
):
    character = _require_character(request)
    if character["room_id"] != room_id:
        raise HTTPException(403, detail={"code": "room_mismatch"})
    conn = request.app.state.db
    card = conn.execute(
        "SELECT evidence_card_id FROM evidence_cards WHERE evidence_card_id = %s AND room_id = %s "
        "AND visibility = 'party' AND card_type != 'question' AND source = 'player' "
        "AND fact_status = 'hypothesis'",
        (evidence_card_id, room_id),
    ).fetchone()
    if not card:
        raise HTTPException(404, detail={"code": "shared_hypothesis_not_found"})
    comment_id = str(uuid.uuid4())
    with conn.transaction() as transaction:
        transaction.execute(
            "INSERT INTO evidence_comments "
            "(evidence_comment_id, room_id, evidence_card_id, character_id, body) "
            "VALUES (%s, %s, %s, %s, %s)",
            (comment_id, room_id, evidence_card_id, character["character_id"], body.body.strip()),
        )
    comment = conn.execute(
        "SELECT comment.evidence_card_id, comment.body, character.player_name AS author_name "
        "FROM evidence_comments comment JOIN characters character ON character.character_id = comment.character_id "
        "WHERE comment.evidence_comment_id = %s",
        (comment_id,),
    ).fetchone()
    return dict(comment)


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/hypothesis-status")
async def update_shared_hypothesis_status(
    request: Request,
    room_id: str,
    evidence_card_id: str,
    body: HypothesisStatusUpdate,
):
    character = _require_character(request)
    conn = request.app.state.db
    changed = False
    previous_status = "discussing"
    with conn.transaction() as transaction:
        card = _load_shared_hypothesis(
            transaction, character, room_id, evidence_card_id, for_update=True,
        )
        previous_status = card.get("hypothesis_status") or "discussing"
        if previous_status != body.hypothesis_status:
            transaction.execute(
                "UPDATE evidence_cards SET hypothesis_status = %s, hypothesis_previous_status = %s, "
                "hypothesis_status_changed_by_character_id = %s, hypothesis_status_changed_at = NOW(), "
                "hypothesis_status_undo_until = NOW() + INTERVAL '10 seconds', version = version + 1, "
                "updated_at = NOW() WHERE evidence_card_id = %s",
                (
                    body.hypothesis_status,
                    previous_status,
                    character["character_id"],
                    evidence_card_id,
                ),
            )
            changed = True
    updated = conn.execute(
        "SELECT *, hypothesis_status_changed_by_character_id = %s "
        "AND hypothesis_status_undo_until >= NOW() AS undo_available "
        "FROM evidence_cards WHERE evidence_card_id = %s",
        (character["character_id"], evidence_card_id),
    ).fetchone()
    updated_card = dict(updated)
    if changed:
        await _emit_public_hypothesis_status(request, room_id, updated_card, previous_status)
    return _hypothesis_transition_payload(
        updated_card,
        undo_available=bool(updated_card["undo_available"]),
        changed=changed,
    )


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/hypothesis-status/revert")
async def revert_shared_hypothesis_status(
    request: Request,
    room_id: str,
    evidence_card_id: str,
):
    character = _require_character(request)
    conn = request.app.state.db
    previous_status = "discussing"
    with conn.transaction() as transaction:
        card = _load_shared_hypothesis(
            transaction, character, room_id, evidence_card_id, for_update=True,
        )
        undo = transaction.execute(
            "SELECT hypothesis_status_changed_by_character_id = %s "
            "AND hypothesis_status_undo_until >= NOW() AS undo_available "
            "FROM evidence_cards WHERE evidence_card_id = %s",
            (character["character_id"], evidence_card_id),
        ).fetchone()
        if not undo or not undo["undo_available"]:
            raise HTTPException(409, detail={"code": "hypothesis_status_undo_not_available"})
        previous_status = card.get("hypothesis_status") or "discussing"
        restored_status = card.get("hypothesis_previous_status") or "discussing"
        transaction.execute(
            "UPDATE evidence_cards SET hypothesis_status = %s, hypothesis_previous_status = NULL, "
            "hypothesis_status_changed_by_character_id = %s, hypothesis_status_changed_at = NOW(), "
            "hypothesis_status_undo_until = NULL, version = version + 1, updated_at = NOW() "
            "WHERE evidence_card_id = %s",
            (restored_status, character["character_id"], evidence_card_id),
        )
    updated = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (evidence_card_id,)
    ).fetchone()
    updated_card = dict(updated)
    await _emit_public_hypothesis_status(request, room_id, updated_card, previous_status)
    return _hypothesis_transition_payload(updated_card, changed=True)


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/hypothesis-disproof-suggestion")
async def suggest_shared_hypothesis_disproof(
    request: Request,
    room_id: str,
    evidence_card_id: str,
):
    character = _require_character(request)
    conn = request.app.state.db
    card = _load_shared_hypothesis(conn, character, room_id, evidence_card_id)
    confirmed_facts = _confirmed_facts_for_shared_hypothesis(conn, room_id, evidence_card_id)
    if not confirmed_facts:
        return {"suggestion": None, "reason": "no_confirmed_linked_facts"}
    gateway = getattr(request.app.state, "gateway", None)
    suggest = getattr(gateway, "suggest_hypothesis_disproof", None)
    if not callable(suggest):
        return {"suggestion": None, "reason": "ai_unavailable"}
    suggestion = await suggest(
        {
            "hypothesis": {
                "evidence_card_id": card["evidence_card_id"],
                "title": card["title"],
                "body": card["body"],
            },
            "confirmed_facts": confirmed_facts,
        },
        room_id,
    )
    if not isinstance(suggestion, dict):
        return {"suggestion": None, "reason": "ai_unavailable"}
    allowed_fact_ids = {fact["evidence_card_id"] for fact in confirmed_facts}
    fact_ids = [
        str(fact_id)
        for fact_id in suggestion.get("factIds", suggestion.get("fact_ids", []))
        if str(fact_id) in allowed_fact_ids
    ]
    if suggestion.get("suggestedStatus", suggestion.get("suggested_status")) != "possible_disproved" or not fact_ids:
        return {"suggestion": None, "reason": "no_supported_disproof"}
    return {
        "suggestion": {
            "suggestedStatus": "possible_disproved",
            "reason": str(suggestion.get("reason") or "")[:500],
            "factIds": fact_ids,
            "confidence": str(suggestion.get("confidence") or "low"),
            "requiresPlayerConfirmation": True,
        },
        "reason": None,
    }


@evidence_router.get("/rooms/{room_id}/evidence/{evidence_card_id}/question-close-preview")
async def preview_party_question_close(request: Request, room_id: str, evidence_card_id: str):
    character = _require_character(request)
    conn = request.app.state.db
    card = _load_party_question(conn, character, room_id, evidence_card_id)
    return _question_close_preview(card, _question_related_cards(conn, room_id, evidence_card_id))


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/question-close")
async def close_party_question(
    request: Request,
    room_id: str,
    evidence_card_id: str,
    body: QuestionCloseConfirmation,
):
    character = _require_character(request)
    conn = request.app.state.db
    with conn.transaction() as transaction:
        card = _load_party_question(transaction, character, room_id, evidence_card_id, for_update=True)
        related_cards = _question_related_cards(transaction, room_id, evidence_card_id)
        if not body.confirmed:
            preview = _question_close_preview(card, related_cards)
            raise HTTPException(
                409,
                detail={"code": "question_close_confirmation_required", **preview},
            )
        if (card.get("question_status") or "investigating") != "closed":
            transaction.execute(
                "UPDATE evidence_cards SET question_status = 'closed', "
                "question_closed_by_character_id = %s, question_closed_at = NOW(), "
                "question_undo_until = NOW() + INTERVAL '10 seconds', version = version + 1, "
                "updated_at = NOW() WHERE evidence_card_id = %s",
                (character["character_id"], evidence_card_id),
            )
    updated = conn.execute(
        "SELECT *, question_closed_by_character_id = %s AND question_undo_until >= NOW() AS undo_available "
        "FROM evidence_cards WHERE evidence_card_id = %s",
        (character["character_id"], evidence_card_id),
    ).fetchone()
    return _question_transition_payload(dict(updated), undo_available=bool(updated["undo_available"]))


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/question-reopen")
async def reopen_party_question(request: Request, room_id: str, evidence_card_id: str):
    character = _require_character(request)
    conn = request.app.state.db
    with conn.transaction() as transaction:
        card = _load_party_question(transaction, character, room_id, evidence_card_id, for_update=True)
        undo_row = transaction.execute(
            "SELECT question_closed_by_character_id = %s AND question_undo_until >= NOW() AS undo_available "
            "FROM evidence_cards WHERE evidence_card_id = %s",
            (character["character_id"], evidence_card_id),
        ).fetchone()
        undid_close = bool((undo_row or {}).get("undo_available"))
        if (card.get("question_status") or "investigating") != "investigating":
            transaction.execute(
                "UPDATE evidence_cards SET question_status = 'investigating', "
                "question_closed_by_character_id = NULL, question_closed_at = NULL, question_undo_until = NULL, "
                "version = version + 1, updated_at = NOW() WHERE evidence_card_id = %s",
                (evidence_card_id,),
            )
    updated = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (evidence_card_id,)
    ).fetchone()
    return _question_transition_payload(dict(updated), undid_close=undid_close)


@evidence_router.post("/rooms/{room_id}/evidence/{evidence_card_id}/question-explanation")
async def mark_party_question_explained(request: Request, room_id: str, evidence_card_id: str):
    character = _require_character(request)
    conn = request.app.state.db
    with conn.transaction() as transaction:
        card = _load_party_question(transaction, character, room_id, evidence_card_id, for_update=True)
        if (card.get("question_status") or "investigating") == "closed":
            raise HTTPException(409, detail={"code": "question_closed"})
        related_cards = _question_related_cards(transaction, room_id, evidence_card_id)
        if not any(item["fact_status"] == "hypothesis" for item in related_cards):
            raise HTTPException(409, detail={"code": "question_explanation_requires_hypothesis"})
        transaction.execute(
            "UPDATE evidence_cards SET question_status = 'explained', version = version + 1, "
            "updated_at = NOW() WHERE evidence_card_id = %s",
            (evidence_card_id,),
        )
    updated = conn.execute(
        "SELECT * FROM evidence_cards WHERE evidence_card_id = %s", (evidence_card_id,)
    ).fetchone()
    return _question_transition_payload(dict(updated))


@evidence_router.get("/rooms/{room_id}/evidence/{evidence_card_id}/detail", response_model=EvidenceDetailDTO)
async def get_evidence_detail(request: Request, room_id: str, evidence_card_id: str):
    character = _require_character(request)
    conn = request.app.state.db
    card = _visible_evidence_card(conn, character, room_id, evidence_card_id)
    related_rows = conn.execute(
        "SELECT DISTINCT related.* FROM evidence_links link "
        "JOIN evidence_cards related ON related.evidence_card_id = CASE "
        "WHEN link.from_evidence_card_id = %s THEN link.to_evidence_card_id "
        "ELSE link.from_evidence_card_id END "
        "WHERE link.room_id = %s "
        "AND (link.from_evidence_card_id = %s OR link.to_evidence_card_id = %s) "
        "AND (related.visibility = 'party' OR related.created_by_character_id = %s) "
        "ORDER BY related.updated_at DESC",
        (
            evidence_card_id,
            room_id,
            evidence_card_id,
            evidence_card_id,
            character["character_id"],
        ),
    ).fetchall()
    note_rows = conn.execute(
        "SELECT note.* FROM evidence_references reference "
        "JOIN player_notes note ON note.note_id = reference.reference_id "
        "WHERE reference.evidence_card_id = %s AND reference.reference_type = 'player_note' "
        "AND note.room_id = %s AND note.character_id = %s "
        "ORDER BY note.updated_at DESC",
        (evidence_card_id, room_id, character["character_id"]),
    ).fetchall()
    notes = [_note_payload(dict(row)) for row in note_rows]
    return {
        "summary": _evidence_card_payload(card),
        "current_known": [_evidence_detail_known_item(card)],
        "related_materials": [_evidence_detail_known_item(dict(row)) for row in related_rows],
        "player_notes": [
            {"note_id": note["note_id"], "title": note["title"], "body": note["body"]}
            for note in notes
        ],
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
    comments = []
    if card_ids:
        links = conn.execute(
            "SELECT evidence_link_id, from_evidence_card_id, to_evidence_card_id, relation_type "
            "FROM evidence_links WHERE room_id = %s AND from_evidence_card_id = ANY(%s) "
            "AND to_evidence_card_id = ANY(%s) ORDER BY created_at ASC",
            (room_id, card_ids, card_ids),
        ).fetchall()
        comments = conn.execute(
            "SELECT comment.evidence_card_id, comment.body, character.player_name AS author_name "
            "FROM evidence_comments comment "
            "JOIN evidence_cards card ON card.evidence_card_id = comment.evidence_card_id "
            "JOIN characters character ON character.character_id = comment.character_id "
            "WHERE comment.room_id = %s AND comment.evidence_card_id = ANY(%s) "
            "AND card.visibility = 'party' ORDER BY comment.created_at ASC",
            (room_id, card_ids),
        ).fetchall()
    return {
        "cards": [_evidence_card_payload(dict(card)) for card in cards],
        "links": [dict(link) for link in links],
        "comments": [dict(comment) for comment in comments],
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
