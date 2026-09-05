import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..engine.automatic_action_review import (
    AUTOMATIC_REVIEW_TERMINAL_STATUSES,
    automatic_review_summary,
    build_review_evidence_snapshot,
    review_evidence_hash,
    run_automatic_action_review,
)
from ..engine.host_autonomy import AiOnlyResolutionPolicy, room_session_mode
from ..events.event_log import EventLog
from .router_actions_v2 import _require_character


router = APIRouter(prefix="/api/player")
logger = logging.getLogger(__name__)


def _schedule_automatic_review_background(app, review_request_id: str) -> None:
    """Dispatch one accepted case through the unified background machinery.

    Requires the production pg_db pool; tests exercise
    run_automatic_action_review() directly, and cases without a pool stay
    pending until the scheduler/real-runner picks them up (R7/V3 scenario).
    """
    pg_db = getattr(app.state, "pg_db", None)
    if pg_db is None:
        return

    async def _run() -> None:
        conn = pg_db.get_connection()
        try:
            await run_automatic_action_review(app, conn, review_request_id)
        except Exception as exc:
            logger.error(
                "Automatic action review failed review=%s error_type=%s",
                review_request_id,
                type(exc).__name__,
            )
        finally:
            conn.close()

    asyncio.create_task(_run())


class ActionReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_intent: str = Field(default="", max_length=2000)
    objection: str = Field(min_length=1, max_length=2000)


def _is_ai_only(conn, room_id: str) -> bool:
    return AiOnlyResolutionPolicy(
        session_mode=room_session_mode(conn, room_id),
    ).enabled


def _load_own_review(conn, action_id: str, character_id: str, review_request_id: str):
    return conn.execute(
        "SELECT * FROM action_review_requests "
        "WHERE review_request_id = %s AND action_id = %s AND character_id = %s",
        (review_request_id, action_id, character_id),
    ).fetchone()


def _redacted_review_response(row: dict) -> dict:
    summary = automatic_review_summary(row)
    return {
        "review_request_id": summary["review_request_id"],
        "action_id": summary["action_id"],
        "status": summary["status"],
        "original_intent": summary["original_intent"] or "",
        "objection": summary["objection"],
        "created_at": summary["created_at"],
        "resolved_at": summary["resolved_at"],
        "evidence_hash": summary["evidence_hash"],
        "evidence_summary": summary["evidence_summary"],
        "automatic_resolution": summary["automatic_resolution"] or {},
        "ai_suggestion": row.get("ai_suggestion") or {},
    }


def _accept_automatic_review(
    conn,
    action: dict,
    character: dict,
    body: ActionReviewCreate,
    idempotency_key: str,
) -> dict:
    """Accept one player dispute as a pending automatic review case (R4).

    The case is accepted only for already-settled actions whose evidence is
    sealed: a still-resolving action gets an explicit inadmissible reason and
    is never raced against the original transaction. The server's action row
    is the authoritative original intent; the submitter's `original_intent`
    is only recorded as a review statement.
    """
    original_intent = body.original_intent.strip() or action.get("declared_intent") or ""
    if action["status"] not in AUTOMATIC_REVIEW_TERMINAL_STATUSES:
        raise HTTPException(
            409,
            detail={
                "code": "review_not_available",
                "reason": "action_still_running_evidence_not_sealed",
            },
        )
    if idempotency_key:
        existing = conn.execute(
            "SELECT * FROM action_review_requests "
            "WHERE character_id = %s AND action_id = %s AND idempotency_key = %s",
            (character["character_id"], action["action_id"], idempotency_key),
        ).fetchone()
        if existing:
            same_payload = (
                (existing.get("original_intent") or "") == original_intent
                and (existing.get("objection") or "") == body.objection.strip()
            )
            if not same_payload:
                raise HTTPException(
                    409,
                    detail={
                        "code": "idempotency_key_conflict",
                        "reason": "同一幂等键不能绑定不同异议载荷",
                    },
                )
            return _redacted_review_response(dict(existing))
    pending = conn.execute(
        "SELECT review_request_id FROM action_review_requests "
        "WHERE action_id = %s AND character_id = %s AND status = 'pending'",
        (action["action_id"], character["character_id"]),
    ).fetchone()
    if pending:
        raise HTTPException(
            409,
            detail={
                "code": "review_already_pending",
                "review_request_id": pending["review_request_id"],
            },
        )

    review_request_id = str(uuid.uuid4())
    snapshot = build_review_evidence_snapshot(conn, dict(action))
    snapshot["evidence_hash"] = review_evidence_hash(snapshot)
    suggestion = {
        "source": "engine_frozen",
        "review_mode": "automatic",
        "requires_host_review": False,
        "summary": "自动复核案件已受理：证据已按服务器冻结记录封存。",
        "mutations": [],
    }
    try:
        conn.execute(
            "INSERT INTO action_review_requests "
            "(review_request_id, action_id, character_id, original_intent, objection, "
            "status, ai_suggestion, evidence_snapshot, evidence_hash, idempotency_key) "
            "VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)",
            (
                review_request_id,
                action["action_id"],
                character["character_id"],
                original_intent,
                body.objection.strip(),
                json.dumps(suggestion, ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
                snapshot["evidence_hash"],
                idempotency_key,
            ),
        )
    except Exception as exc:
        # Concurrent duplicate under the same idempotency key: replay the
        # winner instead of failing the second caller.
        conn.rollback()
        from psycopg2.errors import UniqueViolation

        if not isinstance(exc, UniqueViolation):
            raise
        existing = conn.execute(
            "SELECT * FROM action_review_requests "
            "WHERE character_id = %s AND action_id = %s AND idempotency_key = %s",
            (character["character_id"], action["action_id"], idempotency_key),
        ).fetchone()
        if not existing:
            raise HTTPException(
                409,
                detail={"code": "review_already_pending"},
            ) from exc
        return _redacted_review_response(dict(existing))
    conn.commit()
    # Automatic acceptance never creates a Host queue entry or Host event.
    return _redacted_review_response(
        dict(
            conn.execute(
                "SELECT * FROM action_review_requests WHERE review_request_id = %s",
                (review_request_id,),
            ).fetchone()
        )
    )


@router.post("/actions/{action_id}/review-requests", status_code=201)
async def create_action_review(
    request: Request,
    action_id: str,
    body: ActionReviewCreate,
    idempotency_key: str = Header(alias="Idempotency-Key", default="", max_length=200),
):
    character = _require_character(request)
    conn = request.app.state.db
    action = conn.execute(
        "SELECT action_id, room_id, character_id, declared_intent, status, result, "
        "params, draft_id, idempotency_key "
        "FROM actions WHERE action_id = %s AND character_id = %s",
        (action_id, character["character_id"]),
    ).fetchone()
    if not action:
        raise HTTPException(404, detail={"code": "action_not_found"})
    if _is_ai_only(conn, str(action["room_id"])):
        accepted = _accept_automatic_review(
            conn,
            dict(action),
            character,
            body,
            idempotency_key.strip(),
        )
        _schedule_automatic_review_background(
            request.app,
            accepted["review_request_id"],
        )
        return accepted
    if action["status"] not in (
        "resolving",
        "awaiting_player_choice",
        "awaiting_host_exception",
        "completed",
        "resolved",
        "rejected",
        "timeout",
        "sync_required",
    ):
        raise HTTPException(409, detail={"code": "review_not_available"})
    pending = conn.execute(
        "SELECT review_request_id FROM action_review_requests "
        "WHERE action_id = %s AND character_id = %s AND status = 'pending'",
        (action_id, character["character_id"]),
    ).fetchone()
    if pending:
        raise HTTPException(
            409,
            detail={"code": "review_already_pending", "review_request_id": pending["review_request_id"]},
        )

    review_request_id = str(uuid.uuid4())
    suggestion = {
        "source": "local_fallback",
        "requires_host_review": True,
        "summary": "对照玩家原意与权威结算，并决定是否需要补偿。",
        "mutations": [],
    }
    original_intent = body.original_intent.strip() or action.get("declared_intent") or ""
    conn.execute(
        "INSERT INTO action_review_requests "
        "(review_request_id, action_id, character_id, original_intent, objection, status, ai_suggestion) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', %s)",
        (
            review_request_id,
            action_id,
            character["character_id"],
            original_intent,
            body.objection.strip(),
            json.dumps(suggestion, ensure_ascii=False),
        ),
    )
    EventLog(conn).log_event(
        action["room_id"],
        "s2c_action_review_requested",
        "host",
        {
            "reviewRequestId": review_request_id,
            "actionId": action_id,
            "characterId": character["character_id"],
        },
    )
    return {
        "review_request_id": review_request_id,
        "action_id": action_id,
        "status": "pending",
        "original_intent": original_intent,
        "objection": body.objection.strip(),
        "ai_suggestion": suggestion,
    }


@router.get("/actions/{action_id}/review-requests/{review_request_id}")
async def get_action_review(
    request: Request,
    action_id: str,
    review_request_id: str,
):
    """Read one own review case (automatic or host mode); redacted summary."""
    character = _require_character(request)
    conn = request.app.state.db
    row = _load_own_review(conn, action_id, character["character_id"], review_request_id)
    if not row:
        raise HTTPException(404, detail={"code": "review_request_not_found"})
    return _redacted_review_response(dict(row))
